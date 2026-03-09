# DEBUG: Real Render Path - Forensic Runtime Audit

**Date:** 2026-03-08  
**Scope:** Complete trace of runtime execution from frontend Generate button to final WAV output  
**Status:** 🔴 CRITICAL ISSUE IDENTIFIED

---

## Executive Summary

**ROOT CAUSE IDENTIFIED:** The app generates arrangement plans with stems metadata, but **never actually loads or uses the stem audio files during rendering**. All rendering is done on the full stereo loop with DSP effects only.

This explains why output sounds like "the same loop repeating with volume changes" - because that's literally what it is.

---

## Complete Runtime Path Trace

### Stage 1: Frontend Generate Action
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Generate Page | `looparchitect-frontend/src/app/generate/page.tsx` | `handleGenerate()` | ✅ Active | User clicks Generate button |
| API Client | `looparchitect-frontend/api/client.ts` | `generateArrangement()` | ✅ Active | POST /api/v1/arrangements/generate |

**Flow:**
```typescript
handleGenerate() 
  → generateArrangement(loopId, params)
  → POST http://localhost:8000/api/v1/arrangements/generate
```

---

### Stage 2: API Route (Arrangement Creation)
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Arrangements Router | `app/routes/arrangements.py` | `create_arrangement()` | ✅ Active | Line 244 |
| Schema Validation | `app/routes/arrangements.py` | `_ensure_arrangements_schema()` | ✅ Active | Auto-creates missing columns |
| Producer Engine | `app/services/producer_engine.py` | `ProducerEngine.generate()` | ✅ Active | If style_text_input provided |
| Job Scheduler | `app/routes/arrangements.py` | `background_tasks.add_task()` | ✅ Active | Line 667 |

**Flow:**
```python
POST /api/v1/arrangements/generate
  → validate loop exists  
  → create Arrangement record (status=queued)
  → optionally call ProducerEngine.generate() if style_text_input
  → schedule background_tasks.add_task(run_arrangement_job, arrangement.id)
  → return 202 Accepted
```

**Arrangement Record Created With:**
- `producer_arrangement_json`: ProducerArrangement structure (sections, tracks, energy)
- `style_profile_json`: Style parameters
- `ai_parsing_used`: True if natural language style used
- `render_plan_json`: NULL at this stage (built in background job)

---

### Stage 3: Background Job Processing
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Job Executor | `app/services/arrangement_jobs.py` | `run_arrangement_job()` | ✅ Active | Line 987 |
| Audio Loader | `app/services/arrangement_jobs.py` | `_load_audio_segment_from_wav_bytes()` | ✅ Active | Downloads loop from S3 |

**Flow:**
```python
run_arrangement_job(arrangement_id)
  → load Arrangement and Loop records from DB
  → download loop audio from S3 via presigned URL
  → parse producer_arrangement_json
  → parse style_profile_json  
  → extract stem_metadata from loop.analysis_json
  → build render_plan_json via _build_pre_render_plan()
  → save render_plan_json to DB
  → call render_from_plan()
```

**Key Point:** Stem metadata is extracted from `loop.analysis_json` but only as **metadata**, not actual audio files.

---

### Stage 4: Render Plan Generation
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Plan Builder | `app/services/arrangement_jobs.py` | `_build_pre_render_plan()` | ✅ Active | Line 705 |
| Producer Moves | `app/services/producer_moves_engine.py` | `ProducerMovesEngine.inject()` | ✅ Active | Injects 9 move types |

**Flow:**
```python
_build_pre_render_plan(...)
  → if producer_arrangement exists: extract sections + variations
  → else if style_sections exist: use style plan
  → else: build default structured sections (Intro/Verse/Hook/Bridge/Outro)
  → inject producer moves via ProducerMovesEngine.inject()
  → return render_plan dict with:
      - sections: [name, type, bar_start, bars, energy, instruments]
      - events: [type, bar, description]  
      - render_profile: {genre, stem_separation}
```

**Producer Moves Injected:**
1. pre_hook_drum_mute
2. silence_drop_before_hook
3. hat_density_variation  
4. end_section_fill
5. verse_melody_reduction
6. bridge_bass_removal
7. final_hook_expansion
8. outro_strip_down
9. call_response_variation

**Output:** `render_plan_json` saved to DB with event list and section structure.

---

### Stage 5: Unified Render Executor
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Executor | `app/services/render_executor.py` | `render_from_plan()` | ✅ Active | Line 116 |
| Plan Converter | `app/services/render_executor.py` | `_build_producer_arrangement_from_render_plan()` | ✅ Active | Converts render_plan to producer format |

**Flow:**
```python
render_from_plan(render_plan_json, audio_source, output_path)
  → parse render_plan_json
  → convert to producer_arrangement format
  → call _render_producer_arrangement()
  → apply mastering
  → export WAV to output_path
  → return {timeline_json, summary, postprocess}
```

**Key Insight:** `render_from_plan()` receives `audio_source` as a single AudioSegment (the full stereo loop), not stems.

---

### Stage 6: Producer Arrangement Renderer
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Renderer | `app/services/arrangement_jobs.py` | `_render_producer_arrangement()` | ✅ Active | Line 324 |
| Section Builder | `app/services/arrangement_jobs.py` | `_build_varied_section_audio()` | ✅ Active | Line 162 |
| Move Effects | `app/services/arrangement_jobs.py` | `_apply_producer_move_effect()` | ✅ Active | Line 254 |

**Flow:**
```python
_render_producer_arrangement(loop_audio, producer_arrangement, bpm)
  → for each section:
      1. Build section audio via _build_varied_section_audio()
         - Repeats loop_audio to fill section duration
         - Applies per-bar offsets for variation
         - Applies section-type-specific DSP
      
      2. Apply DRAMATIC section processing:
         - Intro: -12dB + lowpass 800Hz + fade in
         - Buildup: Progressive volume -8dB → +4dB, opening high-pass
         - Drop/Hook: +8dB + silence gap before + brightness
         - Breakdown: -10dB + lowpass 1200Hz + sparse gaps
         - Outro: -6dB + fade out
         - Verse: -8dB to +1dB range + slight lowpass 7kHz
      
      3. Apply variations (fills, rolls, drops):
         - Hat rolls: +8dB
         - Snare fills: +10dB  
         - Bass drops: silence gap + +12dB
         - Producer moves via _apply_producer_move_effect()
      
      4. Apply transitions:
         - Sweeps, risers, builds
  
  → concatenate all sections
  → return (arranged_audio, timeline_json)
```

**🔴 CRITICAL FINDING:** All processing is done on `loop_audio` (full stereo loop). No stems are ever loaded or used.

---

### Stage 7: Stem Separation Check
| Component | File | Status | Notes |
|-----------|------|--------|-------|
| Stem Metadata | `loop.analysis_json` | ✅ Present | Contains stem file paths |
| Stem Audio Loading | **NOWHERE** | ❌ **MISSING** | No code loads stem WAV files |
| Stem-Based Rendering | **NOWHERE** | ❌ **MISSING** | No code mutes/unmutes individual stems |

**What stem_metadata contains:**
```json
{
  "enabled": true,
  "succeeded": true,
  "stems": {
    "drums": "loops/123_drums.wav",
    "bass": "loops/123_bass.wav",  
    "melody": "loops/123_melody.wav",
    "vocal": "loops/123_vocal.wav"
  }
}
```

**What the code does with stems:** NOTHING. It's only checked as `stem_available = bool(stem_meta)` and used to select slightly different DSP parameters in `_apply_producer_move_effect()`.

---

### Stage 8: Mastering
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Mastering | `app/services/mastering.py` | `apply_mastering()` | ✅ Active | Final polish |

**Flow:**
```python
apply_mastering(output_audio, genre)
  → apply genre-specific EQ and compression
  → normalize to -1dBFS
  → return mastered audio
```

---

### Stage 9: Storage Upload
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Storage Service | `app/services/storage.py` | `upload_file()` | ✅ Active | S3 or local |

**Flow:**
```python
storage.upload_file(output_bytes, "audio/wav", output_key)
  → if S3: boto3.put_object()
  → if local: write to uploads/ folder
  → create presigned GET URL for download
```

---

### Stage 10: Database Update & Frontend Polling
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| Status Update | `app/services/arrangement_jobs.py` | `run_arrangement_job()` | ✅ Active | Sets status=done |
| Frontend Polling | `looparchitect-frontend/src/app/generate/page.tsx` | `pollStatus()` | ✅ Active | Every 2 seconds |

**Flow:**
```python
arrangement.status = "done"
arrangement.output_url = presigned_url
db.commit()
```

```typescript
pollStatus()
  → GET /api/v1/arrangements/{id}
  → if status === "done": stop polling, show download button
  → user clicks download → GET output_url
```

---

### Stage 11: DAW ZIP Generation
| Component | File | Function | Status | Notes |
|-----------|------|----------|--------|-------|
| DAW Exporter | `app/services/daw_export.py` | `DAWExporter.create_daw_package()` | ✅ Active | Optional download |

**Flow:**
```python
DAWExporter.create_daw_package(arrangement)
  → extract sections from render_plan_json  
  → create README.md with import instructions
  → package: arrangement.wav + README.md + (no MIDI)
  → return ZIP bytes
```

---

## Function That Writes Final WAV

**Answer:** `app/services/render_executor.py::render_from_plan()` line 171

```python
output_path = Path(output_path)
output_audio.export(str(output_path), format="wav")
```

The `output_audio` is the result of `_render_producer_arrangement()` after mastering.

---

## Are Stems Actually Used?

**Answer:** ❌ **NO**

**Evidence:**
1. `render_from_plan()` receives `audio_source: AudioSegment` - a single stereo file
2. `_render_producer_arrangement()` processes `loop_audio: AudioSegment` - the full mix
3. `_build_varied_section_audio()` repeats and rotates `loop_audio` - the full mix
4. No code anywhere loads stem WAV files from S3 or local storage
5. `stem_available` flag only affects DSP parameters, not what audio is rendered

**What Actually Happens:**
- Producer moves inject events into render_plan → ✅ Yes, events exist in JSON
- Events are converted to variations → ✅ Yes, mapped correctly
- Variations are applied → ✅ Yes, `_apply_producer_move_effect()` is called
- **But all effects are DSP filters/gain on the full stereo loop** → 🔴 This is the problem

---

## Are Producer Moves Real Events or Just Metadata?

**Answer:** Both. They are:
1. ✅ **Real events** in `render_plan_json`
2. ✅ **Processed** by renderer as variations
3. ❌ **Limited to DSP effects** - they don't mute/unmute/swap stems

**Example:**
```python
def _apply_producer_move_effect(...):
    if move_type == "verse_melody_reduction":
        if stem_available:
            return segment.high_pass_filter(220)  # Slightly stronger filter
        return segment.high_pass_filter(140) - 1  # Weaker filter
```

This just applies a **high-pass filter to the full stereo loop**. It doesn't actually mute the melody stem.

---

## Is Output Just Stereo Loop with Section DSP Overlays?

**Answer:** ✅ **YES, EXACTLY**

**What the renderer actually does:**
1. Takes the full stereo loop (one AudioSegment)
2. Repeats it to fill section durations
3. Rotates loop start point per bar for "variation"
4. Applies section-specific DSP:
   - Intro: -12dB + lowpass
   - Hook: +8dB + brightness  
   - Breakdown: -10dB + gaps
5. Applies producer move DSP effects
6. Concatenates sections
7. Mast ers and exports

**What it DOESN'T do:**
- ❌ Load drum stem
- ❌ Load bass stem
- ❌ Load melody stem
- ❌ Mute drums in intro
- ❌ Remove melody in verse
- ❌ Mute bass in bridge
- ❌ Layer stems differently per section

---

## Worker Fallback Path

**Is there a separate worker path?**

**Answer:** No separate queue worker, but there IS a `dev_fallback_loop_only` path.

**Location:** `app/services/arrangement_jobs.py` line 1172

```python
except Exception as render_error:
    if settings.dev_fallback_loop_only and not settings.is_production:
        logger.warning("DEV_FALLBACK_LOOP_ONLY enabled - using fallback render plan")
        render_plan = _build_dev_fallback_plan(...)
        # Re-render with simpler plan
```

This fallback still uses the same `render_from_plan()` executor - just with a simpler plan.

---

## Validation

**Current Status:**

✅ **What Works:**
- render_plan_json is generated correctly
- Producer moves are injected correctly  
- Events are mapped to variations
- Section-specific DSP is applied dramatically
- Output is structurally correct (intro/verse/hook/outro)
- Mastering is applied

❌ **What's Broken:**
- **Stems are never loaded from storage**
- **Stems are never used in rendering**
- **All processing is DSP overlays on full stereo loop**
- **No real layer muting/enabling per section**
- **Output sounds like "the same loop with volume changes" because it IS**

---

## Root Cause Summary

**P0 - PRIMARY CAUSE:**
Stems are separated, analyzed, and stored with metadata, but **never loaded as audio files during rendering**. The renderer only receives and processes the full stereo loop.

**EXACT LOCATION OF FAILURE:**
`arrangement_jobs.py::run_arrangement_job()` line 1069

```python
# This loads the LOOP AUDIO (full stereo mix)
loop_audio = _load_audio_segment_from_wav_bytes(input_bytes)

# This extracts STEM METADATA (file paths only)
stem_metadata = _parse_stem_metadata_from_loop(loop)

# Render plan is built WITH stem metadata
render_plan = _build_pre_render_plan(..., stem_metadata=stem_metadata)

# But render executor only receives the FULL STEREO LOOP
render_result = render_from_plan(
    render_plan_json=arrangement.render_plan_json,
    audio_source=loop_audio,  # ← This is the full stereo mix, not stems
    output_path=temp_wav_path,
)
```

**Impact:**
- Intro cannot mute drums (because drums stem is not loaded)
- Verse cannot remove melody (because melody stem is not loaded)
- Bridge cannot remove bass (because bass stem is not loaded)
- Final hook cannot layer extra stems (because NO stems are loaded)

**Result:**
Output is LITERALLY the same stereo loop repeated with volume/filter changes per section.

---

## Next Steps

See [ROOT_CAUSE_LOOPING.md](ROOT_CAUSE_LOOPING.md) for detailed failure mode analysis and fix plan.
