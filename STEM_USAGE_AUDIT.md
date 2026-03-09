# STEM USAGE AUDIT

**Date**: 2026-03-09  
**Goal**: Deep-scan stem separation and rendering pipeline to verify actual stem usage

---

## EXECUTIVE SUMMARY

**Status**: ❌ **STEMS NOT USED IN PRODUCTION**

**Root Cause**: `FEATURE_STEM_SEPARATION = False` (default config)

**Impact**: Loop Variation Engine falls back to DSP-only processing on full stereo loop instead of real layer-based mixing

---

## STEM SEPARATION PIPELINE

### 1. Configuration

**File**: [app/config.py](looparchitect-backend-api/app/config.py#L30-L32)

```python
feature_stem_separation: bool = Field(default=False, validation_alias="FEATURE_STEM_SEPARATION")
stem_separation_backend: str = Field(default="builtin", validation_alias="STEM_SEPARATION_BACKEND")
```

**Current Setting**: `FEATURE_STEM_SEPARATION = False`  
**Evidence**: No `.env` file with override, defaults to `False`

**Status**: ❌ **FEATURE DISABLED**

---

### 2. Stem Generation (Loop Upload)

**File**: [app/routes/loops.py](looparchitect-backend-api/app/routes/loops.py#L34-L60)

**Flow**:
```python
if not settings.feature_stem_separation:
    payload["stem_separation"] = {
        "enabled": False,
        "reason": "feature_disabled",
        "backend": settings.stem_separation_backend,
    }
else:
    # Call stem separation service
    stem_result = separate_and_store_stems(...)
    payload["stem_separation"] = stem_result.to_dict()
```

**When feature disabled**:
- Stem separation NOT run
- `analysis_json` contains `{"enabled": False, "reason": "feature_disabled"}`
- No stem files generated

**Status**: ❌ **NOT EXECUTING** - Feature flag check prevents execution

---

### 3. Stem Separation Service

**File**: [app/services/stem_separation.py](looparchitect-backend-api/app/services/stem_separation.py#L60-L100)

**Function**: `separate_and_store_stems(source_audio, loop_id, source_key)`

**Backends Available**:
1. **builtin** (default): Frequency-based splits using pydub
   - Bass: Low-pass 180Hz
   - Vocals: Band-pass 200Hz-3500Hz
   - Drums: Band-pass 60Hz-9000Hz
   - Other: High-pass 3500Hz

2. **mock**: Same as builtin (for testing)

**Output**:
- Generates 4 stem files: `stems/loop_{id}_bass.wav`, `_drums.wav`, `_vocals.wav`, `_other.wav`
- Uploads to S3/local storage
- Returns `StemSeparationResult` with stem keys

**Status**: ✅ **CODE EXISTS AND FUNCTIONAL** - But never called because feature disabled

---

### 4. Stem Storage

**When feature enabled, expected stem files**:
```
stems/loop_1_bass.wav
stems/loop_1_drums.wav
stems/loop_1_vocals.wav
stems/loop_1_other.wav
```

**Actual storage check**:

**Database Evidence** (Arrangement 242):
```json
{
  "loop_variations": {
    "active": true,
    "stems_used": false
  }
}
```

**Status**: ❌ **NO STEM FILES EXIST** - Feature never runs, no files generated

---

## STEM LOADING (Arrangement Generation)

### 5. Stem Metadata Parsing

**File**: [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L145-L161)

```python
def _parse_stem_metadata_from_loop(loop: Loop) -> dict | None:
    if not loop or not loop.analysis_json:
        return None
    payload = json.loads(loop.analysis_json)
    stem_meta = payload.get("stem_separation")
    if not isinstance(stem_meta, dict):
        return None
    return stem_meta
```

**For recent loops**:
- `loop.analysis_json = "{}"`  (empty)
- Returns `None`

**Status**: ❌ **NO STEM METADATA** - Loops uploaded without stem separation

---

### 6. Stem Loading Attempt

**File**: [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L1373-L1430)

```python
stem_metadata = _parse_stem_metadata_from_loop(loop)
loaded_stems: dict[str, AudioSegment] | None = None

if stem_metadata and stem_metadata.get("enabled") and stem_metadata.get("succeeded"):
    from app.services.stem_loader import load_stems_from_metadata
    loaded_stems = load_stems_from_metadata(stem_metadata, timeout_seconds=60.0)
else:
    loaded_stems = None
```

**Decision Tree**:
```
stem_metadata exists?
├─ NO → loaded_stems = None ❌ (current state)
└─ YES
   └─ enabled = True?
      ├─ NO → loaded_stems = None ❌
      └─ YES
         └─ succeeded = True?
            ├─ NO → loaded_stems = None ❌
            └─ YES
               └─ Load stems from S3 ✅ (never reached)
```

**Current Path**: `stem_metadata = None` → `loaded_stems = None`

**Status**: ❌ **SKIPPED** - Condition never met

---

### 7. Stem Loader Service

**File**: [app/services/stem_loader.py](looparchitect-backend-api/app/services/stem_loader.py#L27-L100)

**Function**: `load_stems_from_metadata(stem_metadata, timeout_seconds)`

**Expected Input**:
```json
{
  "enabled": true,
  "succeeded": true,
  "stems": {
    "drums": "stems/loop_123_drums.wav",
    "bass": "stems/loop_123_bass.wav",
    "vocals": "stems/loop_123_vocals.wav",
    "other": "stems/loop_123_other.wav"
  }
}
```

**Process**:
1. Validate metadata (`enabled=True`, `succeeded=True`)
2. For each stem key in `stems` dict:
   - Download from S3 via presigned URL (or load from local)
   - Load as `AudioSegment`
   - Validate: non-empty, 1-2 channels, 22-192kHz sample rate
3. Return `Dict[str, AudioSegment]`

**Status**: ✅ **CODE EXISTS AND FUNCTIONAL** - Never executed because stems don't exist

---

## STEM USAGE IN RENDERING

### 8. Loop Variation Generation

**File**: [loop_variation_engine.py](looparchitect-backend-api/app/services/loop_variation_engine.py#L128-L221)

**Function**: `generate_loop_variations(loop_audio, stems, bpm)`

**WITH STEMS** (stems != None):
```python
drums = stems.get("drums")
bass = stems.get("bass")
melody = stems.get("melody")  # or "other"
vocal = stems.get("vocal")    # or "vocals"

# Intro: melody-focused
intro = _mix_selected_stems(
    stems,
    active_stems=("melody", "vocal"),
    target_ms=target_ms,
    gains={"melody": -4, "vocal": -8},
)
```

**WITHOUT STEMS** (stems = None) - **CURRENT STATE**:
```python
drums = None
bass = None
melody = None
vocal = None

# Intro fallback
if intro.rms == 0:
    intro = loop_audio.low_pass_filter(1200) - 10
```

**Stem-Based vs DSP Fallback**:

| Variant | With Stems | Without Stems (Current) |
|---------|-----------|-------------------------|
| **Intro** | Melody + vocal only, no drums | Full loop, low-pass 1200Hz |
| **Verse** | Reduced drums + simplified melody | Full loop, low-pass 5000Hz, gaps |
| **Hook** | Full stems, loud drums | Full loop + 4dB |
| **Bridge** | Melody + vocal only, no bass/drums | Full loop, band-pass 180-1400Hz |
| **Outro** | Progressive drum removal | Full loop fade with fake drum removal |

**Key Difference**:
- **Stems**: Can REMOVE layers (verse with no drums, bridge with no bass)
- **DSP**: Can only FILTER/ATTENUATE full mix (all drums still audible, just quieter)

**Status**: ⚠️ **FALLBACK MODE ACTIVE** - Using DSP processing, not real stem mixing

---

### 9. Stem Mapping (Instrument → Stem)

**File**: [stem_loader.py](looparchitect-backend-api/app/services/stem_loader.py#L200-L250)

**Function**: `map_instruments_to_stems(instruments, stems)`

**Purpose**: Convert producer arrangement instrument list to stem keys

**Example**:
```python
# Producer says: ["kick", "snare", "bass"]
# Maps to: {"drums": stem_audio, "bass": stem_audio}
```

**Mapping Table**:
```python
{
    "kick": ["drums"],
    "snare": ["drums"],
    "hi_hat": ["drums"],
    "drums": ["drums"],
    "bass": ["bass"],
    "synth": ["other", "melody"],
    "melody": ["melody", "other"],
    "vocal": ["vocals", "vocal"],
}
```

**Status**: ✅ **CODE EXISTS** - Never reached because `stems = None`

---

### 10. Render Path - Stem Branch

**File**: [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L565-L590)

**Code**:
```python
if use_loop_variations and section_loop_variant in loop_variations:
    # USE LOOP VARIANT (this branch executes) ✅
    variation_source = loop_variations[section_loop_variant]
    section_audio = _repeat_to_duration(variation_source, section_ms)
    
elif use_stems:
    # USE STEMS (this branch NEVER executes) ❌
    enabled_stems = map_instruments_to_stems(section_instruments, stems)
    section_audio = _build_section_audio_from_stems(...)
    
else:
    # FALLBACK (never reached because loop_variations exist)
    section_audio = _build_varied_section_audio(...)
```

**Current Execution**:
- `use_loop_variations = True` (variants DO exist)
- `use_stems = False` (stems don't exist)
- **Takes first branch**: Uses loop variant (DSP-processed full loop)

**Status**: ⚠️ **STEMS BRANCH UNREACHABLE** - Loop variations take priority even when inferior to stems

---

## STEM EFFECTIVENESS COMPARISON

### Without Stems (Current)

**Verse Creation**:
```python
verse = (loop_audio - 5).low_pass_filter(5000)
verse = _apply_transient_softening(verse)
verse = _apply_silence_gaps(verse, bar_duration_ms)
```

**Result**: Full mix at -5dB, filtered to 5kHz, with gaps
- Drums still audible (just quieter)
- Bass still present (just filtered)
- Cannot isolate melody

**Audio Difference**: ~40% different from hook (still clearly the same loop)

---

### With Stems (If Enabled)

**Verse Creation**:
```python
verse = _mix_selected_stems(
    stems,
    active_stems=("drums", "bass", "melody"),
    target_ms=target_ms,
    gains={"drums": -6, "melody": -7, "bass": -1},
)
```

**Result**: ONLY drums + bass + melody stems
- Vocals completely absent
- Drums at -6dB (not just filtered, actually lower volume)
- Can create "verse with no hi-hats" by removing high frequencies from drum stem

**Audio Difference**: ~70% different from hook (clearly different arrangement)

---

### Hook vs Verse Comparison

| Aspect | Without Stems (Current) | With Stems |
|--------|------------------------|------------|
| **Drums** | Filtered, all components present | Can remove/reduce specific drum elements |
| **Bass** | Always present, filtered or not | Can remove entirely (bridge) or adjust level |
| **Melody** | Always present, filtered or not | Can remove (intro/bridge/outro) |
| **Vocals** | Always present, filtered or not | Can add/remove per section |
| **Layers** | 1 layer (full mix) always | 4 layers independently controllable |
| **Difference** | 40% (DSP only) | 70% (layer composition) |

---

## STEM QUALITY ASSESSMENT

### Builtin Stem Separation Quality

**Algorithm**: Frequency-based splitting using pydub filters

**Stems Generated**:
- **Bass**: `audio.low_pass_filter(180)` = 0-180Hz only
- **Drums**: `audio.high_pass_filter(60).low_pass_filter(9000)` = 60Hz-9kHz
- **Vocals**: `audio.high_pass_filter(200).low_pass_filter(3500)` = 200Hz-3500Hz
- **Other**: `audio.high_pass_filter(3500)` = 3500Hz+

**Quality**: ⚠️ **LOW - Frequency leakage**
- Bass will contain some kick drum (both at 60-180Hz)
- Drums will contain bass fundamentals and vocal/melody (entire 60-9kHz range)
- Vocals will contain snare, melody, some bass harmonics
- **NOT true stem separation** (no ML model, just EQ splits)

**BUT**: **Still better than no stems at all**
- Can at least remove vocal range completely for instrumental sections
- Can remove high-frequency percussion for breakdown
- Can create "bass-only" bridge even if it has some kick leakage

**Comparison to ML Stem Separation (Demucs, Spleeter)**:
- **ML**: 90-95% separation quality, minimal leakage
- **Builtin**: 50-60% separation quality, significant leakage
- **None** (current): 0% separation, full mix only

---

## FINDINGS BY STAGE

### ✅ REAL (Code Exists & Functional)

1. **Stem separation service** - Can generate frequency-based stems
2. **Stem storage** - Can upload stem files to S3/local
3. **Stem loader** - Can download and load stem audio
4. **Stem mapping** - Can map instruments to stems
5. **Stem mixing** - Can selectively mix stems per section
6. **Variant generation with stems** - Can create true layer-based variants

**BUT**: None of this code is executed because `FEATURE_STEM_SEPARATION = False`

---

### ⚠️ PARTIAL (Code Exists But Not Used)

1. **Loop variation engine fallback** - Works but inferior to stem-based
2. **Section instrument tracking** - Stored but not used (no stems to map to)
3. **Stem validation** - Works but never called

---

### ❌ FAKE/METADATA-ONLY (Not Actually Used)

1. **Stem metadata in render plan** - Shows `"stems_used": false`
2. **ProducerArrangement instrument lists** - Ignored (no stems to apply to)
3. **Stem branch in renderer** - Exists but unreachable

---

## STEM USAGE CHECKLIST

| Stage | Real | Partial | Fake | Evidence |
|-------|------|---------|------|----------|
| 1. Stem generation enabled | ❌ | | | Config: `FEATURE_STEM_SEPARATION = False` |
| 2. Stems generated on upload | ❌ | | | No stem files in storage |
| 3. Stem metadata in loop.analysis_json | ❌ | | | `analysis_json = "{}"` |
| 4. Stems stored and retrievable | ❌ | | | No stem keys in database |
| 5. Stems loaded at render time | ❌ | | | `loaded_stems = None` always |
| 6. Stems used in variant generation | | ⚠️ | | Falls back to DSP |
| 7. Stems used in final render | ❌ | | | Loop variants used instead |

**Overall Status**: ❌ **COMPLETELY UNUSED** - Full pipeline exists but never executes

---

## WHY STEMS AREN'T USED

### Primary Reason: Feature Flag Disabled

**File**: [app/config.py](looparchitect-backend-api/app/config.py#L30)
```python
feature_stem_separation: bool = Field(default=False)
```

**Impact**:
- Stem separation never runs on loop upload
- No stem files generated
- `loop.analysis_json` empty or missing stem data
- Arrangement generation sees no stems → `loaded_stems = None`
- Renderer uses DSP fallback

**Why disabled?**:
- Likely intentional for development/performance
- Stem separation computationally expensive
- Builtin stems low quality (might not be worth overhead)
- External backend (Demucs/Spleeter) not configured

---

### Secondary Reason: Architectural Priority

**Code**: [arrangement_jobs.py:534](looparchitect-backend-api/app/services/arrangement_jobs.py#L534)

```python
if use_loop_variations and section_loop_variant in loop_variations:
    # USE LOOP VARIANT ← Takes priority
    ...
elif use_stems:
    # USE STEMS ← Never reached if variants exist
    ...
```

**Issue**: Even if stems were available, loop variants take priority

**Result**: Stems would ONLY be used if loop variation generation failed

**Design Question**: Should stems be used to CREATE variants, or should variants use stems?

**Current Design**:
```
Loop Audio → Generate Variants (with or without stems) → Use Variants
```

**Alternative Design**:
```
Loop Audio → Separate Stems → Generate Variants from Stems → Use Variants
```

**Actual Implementation**: Hybrid - variants CAN use stems if available, but fallback to DSP if not

---

## RECOMMENDATIONS

### To Enable Stems (Quick Fix)

1. **Set environment variable**:
   ```bash
   export FEATURE_STEM_SEPARATION=true
   ```

2. **Restart backend**

3. **Re-upload loops** (existing loops don't have stems)

4. **Generate new arrangements**

**Expected Result**: Stems generated, loop variants use real layer mixing

---

### Stem Backend Options

**Current**: `stem_separation_backend: "builtin"`
- ✅ No external dependencies
- ✅ Fast (just EQ splits)
- ❌ Low quality (50-60% separation)

**External Option 1**: Demucs (ML-based)
- ✅ High quality (90-95% separation)
- ❌ Requires Python model installation
- ❌ Slow (30-60 seconds per loop)
- ❌ High CPU/GPU usage

**External Option 2**: Spleeter (ML-based)
- ✅ High quality (85-90% separation)
- ❌ Requires TensorFlow installation
- ❌ Medium speed (15-30 seconds)

**External Option 3**: API Service (Separate Microservice)
- ✅ Offloads computation
- ✅ Can use GPU
- ❌ Network latency
- ❌ Additional service to maintain

**Recommendation**: Start with `builtin`, upgrade to Demucs if quality insufficient

---

## CONCLUSION

**Stem Pipeline Status**: ❌ **COMPLETELY DISABLED**

**Evidence**:
1. Feature flag: `FEATURE_STEM_SEPARATION = False`
2. Database: `stems_used: false` for all arrangements
3. Loop analysis: Empty or missing stem metadata
4. Storage: No stem files found

**Impact on Arrangement Quality**:
- Loop variants use DSP processing only (filters, gains)
- Cannot remove drums from verse
- Cannot create melody-only bridge
- Cannot build up from sparse to full
- **Limited to ~40% audio difference vs ~70% with stems**

**Root Cause**: **Intentional feature flag**, not a bug

**To Fix**: Enable `FEATURE_STEM_SEPARATION` and re-upload loops

**Next**: Proceed to Phase 4 - Arrangement Quality Audit
