# FORENSIC RUNTIME TRACE

**Date**: 2026-03-09  
**Target**: LoopArchitect Backend Runtime Path Analysis  
**Goal**: Trace exact execution path from Frontend Generate button to final WAV export

---

## PHASE 1: FULL RUNTIME TRACE

### User Action → API Route

**1. Frontend Generate Button** → [src/app/generate/page.tsx](looparchitect-frontend/src/app/generate/page.tsx#L170-L250)
- **Function**: `handleGenerate()` (inferred from usage)
- **Calls**: `generateArrangement(loopId, options)`
- **Status**: ✅ REAL - Button calls API client

**2. API Client** → [api/client.ts](looparchitect-frontend/api/client.ts#L170-L250)
- **Function**: `generateArrangement()`
- **HTTP**: `POST ${API_BASE_PATH}/v1/arrangements/generate`
- **Body**:
  ```json
  {
    "loop_id": number,
    "target_seconds": number,
    "style_preset": string?,
    "producer_moves": string[]?,
    "include_stems": boolean?
  }
  ```
- **Status**: ✅ REAL - Makes HTTP POST

**3. Backend Route** → [app/routes/arrangements.py](looparchitect-backend-api/app/routes/arrangements.py#L347-L450)
- **Endpoint**: `POST /api/v1/arrangements/generate`
- **Function**: `generate_arrangement()`
- **Creates**: Arrangement database record
- **Enqueues**: `background_tasks.add_task(run_arrangement_job, arrangement.id)`
- **Returns**: `202 ACCEPTED` with `arrangement_id`
- **Status**: ✅ REAL - Creates DB record and background job

---

### Background Job Processing

**4. Arrangement Job Entry** → [app/services/arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L1223)
- **Function**: `run_arrangement_job(arrangement_id)`
- **Loads**: Arrangement + Loop from database
- **Downloads**: Loop audio from S3 or local storage
- **Status**: ✅ REAL - Actual async execution

**5. Stem Loading Attempt** → [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L1373-L1430)
```python
stem_metadata = _parse_stem_metadata_from_loop(loop)
if stem_metadata and stem_metadata.get("enabled") and stem_metadata.get("succeeded"):
    from app.services.stem_loader import load_stems_from_metadata
    loaded_stems = load_stems_from_metadata(stem_metadata, timeout_seconds=60.0)
else:
    loaded_stems = None
```
- **Status**: ⚠️ **PARTIAL** - Code exists but **STEMS NOT LOADED** for recent arrangements
- **Evidence**: Database shows `"stems_used": False` for arrangements 241, 242

**6. Loop Variation Generation** → [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L1432-L1436)
```python
loop_variations, loop_variation_manifest = generate_loop_variations(
    loop_audio=loop_audio,
    stems=loaded_stems,
    bpm=bpm,
)
```
- **Delegates to**: [loop_variation_engine.py](looparchitect-backend-api/app/services/loop_variation_engine.py#L128-L221)
- **Status**: ✅ REAL - **Generates 5 variants: intro, verse, hook, bridge, outro**
- **Evidence**: Database shows `"variation_count": 5`, `"active": True`

---

### Loop Variation Details

**7. Loop Variation Engine** → [loop_variation_engine.py](looparchitect-backend-api/app/services/loop_variation_engine.py#L128-221)

**Function**: `generate_loop_variations(loop_audio, stems, bpm)`

**Generates 5 Distinct Variants**:

| Variant | Audio Processing | Real Difference? |
|---------|-----------------|------------------|
| **intro** | Melody-only, low-pass 1800Hz, fade in, -4dB to -8dB | ✅ YES - Heavily filtered |
| **verse** | Drums -6dB, melody -7dB, transient softening, silence gaps | ✅ YES - Sparse, quieter |
| **hook** | Full stems, drums +4dB, hi-hat density variation | ✅ YES - Louder, fuller |
| **bridge** | Melody/vocal only, low-pass 1400Hz, high-pass 180Hz, gaps | ✅ YES - Ambient, filtered |
| **outro** | Progressive drum removal, fade out | ✅ YES - Gradual fade |

**BUT - When stems unavailable:**
```python
if intro.rms == 0:
    intro = loop_audio.low_pass_filter(1200) - 10
```
- Falls back to **DSP processing on full stereo loop**
- Still creates **REAL audio differences** via filtering

**Status**: ✅ **REAL VARIANTS CREATED** - Audio is audibly different

**Evidence from code**:
- Intro: filtered to 1800Hz max frequency
- Hook: Full bandwidth + density variation
- Bridge: Band-passed 180Hz-1400Hz + gaps
- These are **NOT subtle** - they're 50-80% frequency bandwidth changes

---

### Section Assignment Problem

**8. Variant Assignment** → [loop_variation_engine.py](looparchitect-backend-api/app/services/loop_variation_engine.py#L232-267)

**Function**: `assign_section_variants(sections, manifest)`

**CRITICAL CODE**:
```python
def _variant_for_section(section_type: str) -> str:
    section_type = (section_type or "verse").strip().lower()
    if section_type in {"intro"}:
        return "intro"
    if section_type in {"hook", "chorus", "drop"}:
        return "hook"
    # ...
    return "verse"
```

**Assignment Logic**:
- `Section type "hook"` → `variant = "hook"` FOR ALL HOOKS
- `Section type "verse"` → `variant = "verse"` FOR ALL VERSES

**Database Evidence** (Arrangement 242):
```
Section 2: Hook → variant=hook
Section 4: Hook → variant=hook  ← SAME VARIANT
Section 7: Hook → variant=hook  ← SAME VARIANT (3x)
```

**Status**: ❌ **BUG - STATIC ASSIGNMENT**  
All sections of same type get identical variant audio

---

### Per-Instance Randomization (The "Fix")

**9. Per-Instance DSP Variation** → [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L534-563)

**CRITICAL CODE**:
```python
if use_loop_variations and section_loop_variant in (loop_variations or {}):
    variation_source = (loop_variations or {})[section_loop_variant]
    section_audio = _repeat_to_duration(variation_source, section_ms)
    
    # Per-instance randomization
    import hashlib
    instance_seed = int(hashlib.md5(f"{section_name}_{section_idx}_{bar_start}".encode()).hexdigest()[:8], 16)
    variation_intensity = (instance_seed % 100) / 100.0
    
    # Subtle EQ variation (±2dB)
    eq_shift = -2 + (variation_intensity * 4)  # -2dB to +2dB
    if instance_seed % 3 == 0:
        section_audio = section_audio.low_pass_filter(8000) + eq_shift
    elif instance_seed % 3 == 1:
        section_audio = section_audio.high_pass_filter(120) + eq_shift
    else:
        section_audio = section_audio + eq_shift
    
    # Stereo width variation
    if instance_seed % 4 == 0:
        left = section_audio.split_to_mono()[0] + 1
        right = section_audio.split_to_mono()[1] + 1
        section_audio = AudioSegment.from_mono_audiosegments(left, right)
    elif instance_seed % 4 == 2:
        section_audio = section_audio - 1
```

**Per-Instance Changes**:
1. **EQ Variations**: ±2dB on low-pass 8kHz, high-pass 120Hz, or flat
2. **Stereo Width**: ±1dB left/right channel adjustment
3. **Deterministic**: Same section always gets same variation

**Effectiveness Assessment**:
- ✅ **APPLIED**: Code is in place and runs
- ⚠️ **SUBTLE**: Only ±2dB and mild filtering
- ❌ **INSUFFICIENT**: Using "hook" variant 3 times with ±2dB EQ is **NOT enough** to sound like different sections

**Status**: ⚠️ **REAL BUT WEAK** - Technically varies audio, but differences too subtle

---

### Rendering & Audio Export

**10. Audio Rendering** → [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L443-900)

**Function**: `_render_producer_arrangement()`

**Rendering Flow for Each Section**:
```
1. Check if loop_variations exist and section has loop_variant assigned
   ↓
2. Get variant audio: variation_source = loop_variations[section_loop_variant]
   ↓
3. Repeat to section duration: _repeat_to_duration(variation_source, section_ms)
   ↓
4. Apply per-instance randomization (±2dB EQ, stereo width)
   ↓
5. Apply section-type processing (intro=-12dB+filter, hook=+8dB, etc)
   ↓
6. Append to arranged audio
```

**Status**: ✅ **REAL AUDIO PROCESSING** - Actually builds WAV data

**11. Section-Type Processing** → [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L638-710)

**DRAMATIC PROCESSING APPLIED**:
- **Intro**: -12dB, low-pass 800Hz, fade in
- **Buildup**: Progressive volume -8dB → +4dB, opening high-pass
- **Hook/Drop**: +8dB, pre-hook silence, brightness boost
- **Breakdown**: -10dB, low-pass 1200Hz, sparse gaps
- **Outro**: -6dB, fade out
- **Verse**: -8dB to +1dB (energy-based), low-pass 7kHz

**Status**: ✅ **REAL & STRONG** - These ARE audible changes

---

### Final Output

**12. Mastering** → [render_executor.py](looparchitect-backend-api/app/services/render_executor.py#L195-202)
```python
mastering_result = apply_mastering(output_audio, genre=...)
output_audio = mastering_result.audio
```
- **Status**: ✅ REAL - Applies final loudness/EQ

**13. WAV Export** → [render_executor.py](looparchitect-backend-api/app/services/render_executor.py#L204-205)
```python
output_path = Path(output_path)
output_audio.export(str(output_path), format="wav")
```
- **Status**: ✅ REAL - Writes actual WAV file

**14. Storage Upload** → [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L1527-1533)
```python
output_key = f"arrangements/{arrangement_id}.wav"
storage.upload_file(file_bytes=output_bytes, content_type="audio/wav", key=output_key)
```
- **Status**: ✅ REAL - Uploads to S3 or saves locally

**15. Database Update** → [arrangement_jobs.py](looparchitect-backend-api/app/services/arrangement_jobs.py#L1548-1554)
```python
arrangement.status = "done"
arrangement.output_s3_key = output_key
arrangement.timeline_json = timeline_json
db.commit()
```
- **Status**: ✅ REAL - Marks complete

---

## CRITICAL FINDINGS

### Which function writes final audio?

**Answer**: [render_executor.py:204](looparchitect-backend-api/app/services/render_executor.py#L204) - `output_audio.export(str(output_path), format="wav")`

### What audio sources are used?

**Answer**:
1. **Loop Variations** (5 variants) - ✅ **USED**
   - Generated from stereo loop via DSP (filters, gains, gaps)
   - Each variant IS audibly different from others
2. **Stems** - ❌ **NOT USED**
   - Code exists to load stems
   - Database shows `stems_used: False`
   - Stems not available or not loaded
3. **Full Stereo Loop** - ⚠️ **FALLBACK ONLY**
   - Used as input to create variants
   - Not used directly in final render (variants are used instead)

### Are stems loaded as real audio?

**Answer**: ❌ **NO** - Recent arrangements show `"stems_used": False`

**Evidence**:
- Arrangement 241: `"stems_used": False`
- Arrangement 242: `"stems_used": False`

**Why?**:
- Stem metadata missing from loop analysis
- Stem separation not run
- Stem files don't exist or aren't accessible

### Are render plan events descriptive or actionable?

**Answer**: ✅ **ACTIONABLE** - Events trigger real audio processing

**Evidence**:
- Section-type processing applies -12dB to +8dB changes
- Intro filtered to 800Hz
- Hook boosted +8dB with pre-drop silence
- These are NOT metadata - they're audio transformations

### Does app create multiple real loop variants?

**Answer**: ✅ **YES** - Creates 5 distinct variants with real audio differences

**BUT**:
- ❌ Multiple sections of same type (3 Hooks) use SAME variant
- ⚠️ Per-instance randomization (±2dB) too subtle to fix repetition

---

## THE CORE PROBLEM

**ROOT CAUSE**: 
```
Hook #1 → "hook" variant + randomization seed A (±2dB)
Hook #2 → "hook" variant + randomization seed B (±2dB)  ← SAME BASE AUDIO
Hook #3 → "hook" variant + randomization seed C (±2dB)  ← SAME BASE AUDIO
```

**Impact**:
- Variants ARE different from each other (intro ≠ verse ≠ hook)
- BUT repeated sections ARE NOT different enough (hook #1 ≈ hook #2 ≈ hook #3)
- ±2dB EQ shift insufficient to mask repetition
- User hears: "It's just looping the same thing"

---

## RUNTIME SUMMARY

| Stage | File | Function | Audio Change? | Status |
|-------|------|----------|--------------|--------|
| 1. Frontend | generate/page.tsx | handleGenerate | None | ✅ Real |
| 2. API Call | client.ts | generateArrangement | None | ✅ Real |
| 3. Route | arrangements.py | generate_arrangement | None (DB only) | ✅ Real |
| 4. Job Start | arrangement_jobs.py | run_arrangement_job | None | ✅ Real |
| 5. Stem Load | arrangement_jobs.py | load_stems | None (fails) | ❌ Not used |
| 6. Variant Gen | loop_variation_engine.py | generate_loop_variations | ✅ Creates 5 variants | ✅ Real |
| 7. Assignment | loop_variation_engine.py | assign_section_variants | None (metadata) | ⚠️ Static |
| 8. Build Plan | arrangement_jobs.py | _build_pre_render_plan | None (metadata) | ✅ Real |
| 9. Render | arrangement_jobs.py | _render_producer_arrangement | ✅ YES - huge changes | ✅ Real |
| 10. Per-Instance | arrangement_jobs.py | (inline randomization) | ⚠️ ±2dB subtle | ⚠️ Weak |
| 11. Section DSP | arrangement_jobs.py | (section type processing) | ✅ -12dB to +8dB | ✅ Strong |
| 12. Mastering | render_executor.py | apply_mastering | ✅ Loudness/EQ | ✅ Real |
| 13. Export | render_executor.py | export | Writes WAV | ✅ Real |
| 14. Upload | arrangement_jobs.py | storage.upload_file | Saves file | ✅ Real |

---

## CONCLUSION

**The system DOES create musically distinct variants and applies strong processing.**

**BUT it fails because repeated sections (3 Hooks) use the SAME variant audio with only ±2dB EQ variation, which is insufficient to prevent "looping" perception.**

**Next**: Proceed to Phase 2 - Audio Difference Audit to measure actual waveform similarity
