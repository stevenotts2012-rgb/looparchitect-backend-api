# Root Cause: Loop Repeat Syndrome

**Issue**: Arrangements sound like "the same loop repeated with only volume/EQ changes"

---

## The P0 Critical Root Cause

**STEMS WERE NEVER LOADED AS AUDIO FILES DURING RENDERING.**

### What Was Happening

1. ✅ Stem separation worked (Demucs created 4 stems: drums, bass, melody, vocal)
2. ✅ Stem metadata stored in `loop.analysis_json`
3. ✅ PreSignedURLs generated for stem WAV files  
4. ✅ Producer arrangement system created sophisticated section plans
5. ❌ **Stems NEVER downloaded or loaded into memory**
6. ❌ **Renderer processed only full stereo loop**
7. ❌ **DSP effects applied to stereo loop (filters, gain)**
8. ❌ **Output = repeated loop with volume changes**

### Why It Happened

**Historical evolution**:
- System started with stereo-only rendering
- Stem separation added later as a feature
- Metadata integration complete (stems in database)
- **Audio integration never completed** (stems never loaded)

**Missing infrastructure**:
- No `stem_loader` module to download stem audio files
- No `stems` parameter in `render_from_plan()` signature
- No stem-based section mixer
- No stem loading logic in `run_arrangement_job()`

---

## The Evidence Trail

### 1. Forensic Runtime Audit

Traced execution from API → DB → background job → renderer:

```
POST /api/v1/arrangements/generate
    ↓
run_arrangement_job()
    ↓
render_from_plan(render_plan, loop_audio)  ← Only stereo loop passed
    ↓
_render_producer_arrangement(loop_audio)  ← Only stereo loop received
    ↓
_build_varied_section_audio(loop_audio)  ← DSP filters applied to full loop
    ↓
export to MP3 → upload to S3
```

**Critical finding**: `loop_audio` is an `AudioSegment` of the full stereo loop. No stems in sight.

### 2. Render Function Signatures

**render_from_plan()** (BEFORE):
```python
def render_from_plan(
    render_plan: dict,
    loop_audio: AudioSegment,  # ← Only stereo loop
    correlation_id: str | None = None,
) -> AudioSegment:
```

**No stems parameter. No way to pass stem audio even if loaded.**

### 3. Section Rendering Logic

**_build_varied_section_audio()** processes full stereo loop:
```python
def _build_varied_section_audio(
    loop_audio: AudioSegment,  # ← Full stereo loop
    section_bars: int,
    bar_duration_ms: int,
    section_idx: int,
    section_type: str,
) -> AudioSegment:
    # Applies DSP filters to loop_audio
    if section_type == "verse":
        segment = segment.high_pass_filter(200)  # Filter stereo loop
    elif section_type == "hook":
        segment = segment.high_pass_filter(100)  # Brighter stereo loop
```

**No stem mixing. No layer composition. Just DSP on full loop.**

### 4. Producer Moves Implementation

**_apply_producer_move_effect()** applies DSP filters:
```python
if move_type == "verse_melody_reduction":
    return segment.high_pass_filter(800)  # Reduce highs in FULL LOOP
elif move_type == "bridge_bass_removal":
    return segment.high_pass_filter(200)  # Filter bass from FULL LOOP
```

**Should have been**: Mute melody stem, keep drums + bass stems.

### 5. Stem Metadata Check

**loop.analysis_json** contains:
```json
{
  "stem_separation": {
    "enabled": true,
    "succeeded": true,
    "model": "htdemucs",
    "stems": {
      "drums": {
        "file_url": "https://s3.../drums.wav",
        "file_path": "stems/abc123/drums.wav"
      },
      "bass": { ... },
      "melody": { ... },
      "vocal": { ... }
    }
  }
}
```

**Stems exist in storage. Metadata exists in database. Audio files NEVER loaded.**

---

## The Fix

### Phase 1: Create Stem Loader

**app/services/stem_loader.py**:
- `load_stems_from_metadata()` - Download stem WAV files from S3/local
- `validate_stem_sync()` - Check stem durations align
- `normalize_stem_durations()` - Trim to shortest stem
- `map_instruments_to_stems()` - Map `["kick", "bass"]` → `{"drums": ..., "bass": ...}`

### Phase 2: Update Render Pipeline

**Updated signatures**:
```python
def render_from_plan(
    render_plan: dict,
    loop_audio: AudioSegment,
    correlation_id: str | None = None,
    stems: dict[str, AudioSegment] | None = None,  # ← NEW
) -> AudioSegment:

def _render_producer_arrangement(
    render_plan: dict,
    loop_audio: AudioSegment,
    bpm: int,
    correlation_id: str | None = None,
    stems: dict[str, AudioSegment] | None = None,  # ← NEW
) -> AudioSegment:
```

### Phase 3: Add Stem-Based Section Renderer

**_build_section_audio_from_stems()**:
```python
def _build_section_audio_from_stems(
    stems: dict[str, AudioSegment],
    section_instruments: list[str],  # e.g., ["kick", "snare", "bass"]
    section_bars: int,
    bar_duration_ms: int,
    section_type: str,
) -> AudioSegment:
    # Map instruments → stems
    stem_map = map_instruments_to_stems(section_instruments, stems)
    
    # Mix only active stems
    mixed_audio = AudioSegment.silent(duration=section_duration_ms)
    for stem_name, stem_audio in stem_map.items():
        looped_stem = _repeat_to_duration(stem_audio, section_duration_ms)
        mixed_audio = mixed_audio.overlay(looped_stem)
    
    return mixed_audio
```

**Result**: Verses with `["kick", "bass"]` → Only drums + bass stems. No melody/vocal.

### Phase 4: Load Stems Before Rendering

**run_arrangement_job()** (AFTER render plan built):
```python
# LOAD STEM AUDIO FILES
loaded_stems: dict[str, AudioSegment] | None = None

if stem_metadata and stem_metadata.get("enabled") and stem_metadata.get("succeeded"):
    try:
        loaded_stems = load_stems_from_metadata(stem_metadata, timeout_seconds=60.0)
        logger.info(f"✅ STEMS LOADED: {list(loaded_stems.keys())}")
    except StemLoadError as e:
        logger.warning(f"❌ STEM LOAD FAILED: {e} - Falling back to stereo")
        loaded_stems = None

# Pass stems to renderer
final_audio = render_from_plan(
    render_plan=render_plan,
    loop_audio=loop_audio,
    correlation_id=correlation_id,
    stems=loaded_stems,  # ← NEW
)
```

### Phase 5: Branch Rendering Logic

**_render_producer_arrangement()** (section loop):
```python
for section in sections:
    use_stems = stems is not None and section.get("instruments")
    
    if use_stems:
        # NEW: Real layer-based rendering
        section_audio = _build_section_audio_from_stems(
            stems=stems,
            section_instruments=section["instruments"],
            section_bars=section["bars"],
            bar_duration_ms=bar_duration_ms,
            section_type=section.get("type"),
        )
    else:
        # LEGACY: Stereo DSP fallback
        section_audio = _build_varied_section_audio(
            loop_audio=loop_audio,
            section_bars=section["bars"],
            bar_duration_ms=bar_duration_ms,
            section_idx=i,
            section_type=section.get("type"),
        )
```

### Phase 6: Add Validation Guards

**_validate_render_plan_quality()**:
- Check at least 3 sections
- Check at least 10 meaningful events
- Check section type variety
- Fail fast with clear errors

---

## Impact

### Before
- ❌ Stems in storage but never used
- ❌ Verses = Hooks = Breakdowns (all same full loop)
- ❌ Producer moves = DSP filters only
- ❌ Output = "repeated loop with volume changes"

### After
- ✅ Stems loaded from storage
- ✅ Verses have fewer layers (kick + bass only)
- ✅ Hooks have full layers (drums + bass + melody + vocal)
- ✅ Producer moves affect actual layers
- ✅ Output = real producer-grade beat arrangement

---

## Files Changed

### Created
- `app/services/stem_loader.py` (282 lines)

### Modified
- `app/services/arrangement_jobs.py`:
  - Added `_validate_render_plan_quality()`
  - Added stem loading in `run_arrangement_job()`
  - Updated `_render_producer_arrangement()` (+stems parameter)
  - Created `_build_section_audio_from_stems()`
  - Updated section rendering branch logic

- `app/services/render_executor.py`:
  - Updated `render_from_plan()` (+stems parameter)
  - Added stems logging
  - Passed stems to `_render_producer_arrangement()`

---

## Key Insight

**The problem wasn't in the architecture or algorithm design.** The producer arrangement system, stem separation, and section planning were all working correctly.

**The problem was a missing integration step**: Stems existed but were never loaded into the render process.

**One line was missing**:
```python
loaded_stems = load_stems_from_metadata(stem_metadata)
```

**Everything downstream was already designed to work with layers**, but the layers were never provided, so the system fell back to processing the full stereo loop with DSP.

---

**Root Cause Summary**: Stems analyzed and stored but never loaded as audio during rendering.

**Solution Summary**: Create stem loader, update render pipeline to accept stems, add stem-based section mixer, load stems before rendering.

**Status**: ✅ **RESOLVED**
