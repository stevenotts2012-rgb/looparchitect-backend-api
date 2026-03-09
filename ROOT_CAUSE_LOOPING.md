# Root Cause Analysis: Why Output Sounds Like A Repeated Loop

**Date:** 2026-03-08  
**Status:** 🔴 **CRITICAL - PRIMARY ROOT CAUSE IDENTIFIED**  
**Impact:** High - User-reported production issue

---

## The Problem

**User Report:**
> "The output sounds like the same loop repeating over and over, with only louder/quieter sections in some places."

**Actual Behavior:**
That description is 100% accurate - the system IS literally repeating the same stereo loop with volume/EQ changes.

---

## Failure Mode Analysis

### P0 - Primary Cause: Stems Never Loaded During Rendering

**Location:** `app/services/arrangement_jobs.py::run_arrangement_job()` lines 1065-1164

**What Happens:**
1. Loop audio is downloaded from S3 as a **full stereo mix WAV**
2. Stem metadata is extracted from `loop.analysis_json` (file paths only)
3. Stem metadata is passed to `_build_pre_render_plan()` 
4. Render plan is built WITH stem information in metadata
5. BUT: `render_from_plan()` only receives the **full stereo loop audio**
6. Renderer processes the **full stereo loop** with DSP effects
7. No stem audio files are ever loaded from storage

**Evidence:**
```python
# Line 1065: Load loop audio (FULL STEREO MIX)
loop_audio = _load_audio_segment_from_wav_bytes(input_bytes)

# Line 1147: Extract stem metadata (FILE PATHS ONLY)
stem_metadata = _parse_stem_metadata_from_loop(loop)

# Line 1148: Build plan with stem metadata
render_plan = _build_pre_render_plan(
    ...,
    stem_metadata=stem_metadata,  # ← Only metadata, not audio
)

# Line 1161: Render with FULL STEREO LOOP only
render_result = render_from_plan(
    render_plan_json=arrangement.render_plan_json,
    audio_source=loop_audio,  # ← This is the full mix, not stems
    output_path=temp_wav_path,
)
```

**Impact:**
- Intro cannot actually mute drums - no drums stem loaded
- Verse cannot actually remove melody - no melody stem loaded  
- Bridge cannot actually remove bass - no bass stem loaded
- Hook cannot actually add/boost layers - no stems available to mix
- Producer moves that target specific instruments become DSP filters on full mix

**Severity:** P0 - This is the PRIMARY reason output sounds like a repeated loop.

---

### P1 - Important Contributors

#### P1-A: No Stem Audio Loading Infrastructure

**Location:** Missing from codebase

**What's Missing:**
- No function to load stem audio from S3/local storage
- No parallel download of multiple stem files
- No stem audio caching or management
- No stem audio validation after load

**Current Workaround:**
Code falls back to "stem-aware DSP" which means slightly different filter cutoffs based on whether stems EXIST (not whether they're loaded).

**Example:**
```python
def _apply_producer_move_effect(...):
    if move_type == "verse_melody_reduction":
        if stem_available:  # ← This just checks metadata
            return segment.high_pass_filter(220)
        return segment.high_pass_filter(140) - 1
```

This applies a slightly stronger high-pass filter if stems "exist", but doesn't actually load or mute the melody stem.

---

#### P1-B: Renderer Signature Doesn't Support Stems

**Location:** `app/services/arrangement_jobs.py::_render_producer_arrangement()` line 324

**Current Signature:**
```python
def _render_producer_arrangement(
    loop_audio: AudioSegment,  # ← Single stereo file
    producer_arrangement: dict,
    bpm: float,
) -> tuple[AudioSegment, str]:
```

**Problem:**
- Function expects ONE AudioSegment (the full loop)
- No parameter for stem audio dict  
- No logic to switch between stems per section
- All processing operates on `loop_audio` variable

**Impact:**
Even if stems were loaded, this function couldn't use them without signature change.

---

#### P1-C: Section Instrument Lists Are Metadata Only

**Location:** `app/services/arrangement_jobs.py::_build_pre_render_plan()` lines 720-735

**Example Section:**
```python
{
    "name": "Intro",
    "type": "intro",
    "bar_start": 0,
    "bars": 4,
    "energy": 0.35,
    "instruments": ["kick", "bass"],  # ← Metadata only
}
```

**Problem:**
The `instruments` list says "only kick and bass should play in intro", but:
- This is never enforced during rendering
- No code checks this list to decide what stems to enable
- It's purely documentation for the timeline JSON

**Impact:**
Render plan looks correct on paper, but has no runtime effect on audio.

---

#### P1-D: Producer Moves Are DSP-Only

**Location:** `app/services/arrangement_jobs.py::_apply_producer_move_effect()` line 254

**Current Implementation:**
All producer moves are implemented as DSP effects on the full stereo loop:

| Move Type | Current Effect | What It Should Do |
|-----------|---------------|-------------------|
| `verse_melody_reduction` | High-pass filter | Mute or reduce melody stem gain |
| `bridge_bass_removal` | High-pass filter | Mute bass stem |
| `pre_hook_drum_mute` | Low-pass + gain reduce | Mute drums stem |
| `final_hook_expansion` | Multi-band boost | Add extra stem layers or boost all |
| `outro_strip_down` | Low-pass + fade | Progressively mute stems |

**Impact:**
Moves alter the tone but don't create real layer changes.

---

### P2 - Polish Issues

#### P2-A: No Stem-to-Instrument Mapping

**Problem:** Even if stems were loaded, there's no mapping between:
- `stem files`: `drums.wav`, `bass.wav`, `melody.wav`, `vocal.wav`
- `section instruments`: `["kick", "snare", "bass", "melody"]`

Need intelligent mapping like:
- `kick` + `snare` → use `drums.wav`
- `bass` → use `bass.wav`
- `melody` → use `melody.wav`
- `vocal` → use `vocal.wav`

---

#### P2-B: No Fallback Validation

**Location:** Missing

**Problem:**
If stem separation fails or stems are corrupt:
- System should detect this and use stereo fallback
- Should log clear warning to user
- Should still produce output (not crash)

Currently: System assumes stems work if metadata says they exist.

---

#### P2-C: Per-Bar Variation Is Weak

**Location:** `app/services/arrangement_jobs.py::_build_varied_section_audio()` line 162

**Current Approach:**
Rotate loop start offset per bar:
```python
offset = ((section_idx * 3) + bar_idx) * quarter % loop_len
bar_source = loop_audio[offset:] + loop_audio[:offset]
```

**Problem:**
- This creates slight timing shifts but doesn't change musical content
- Still sounds like same loop just starting at different points
- Doesn't create real rhythmic or melodic variation

**Better Approach:**
If no stems available, at least:
- Add more dramatic gaps/stutters
- Apply more rhythmic chopping
- Add filter sweeps between bars
- Create call-response patterns with silence

---

## Why It Feels Like "The Same Loop"

**Perceptual Analysis:**

1. **No Layer Changes**
   - User expects: Intro has fewer layers, Hook has full band
   - Reality: Same stereo mix plays throughout

2. **Only Volume/Tone Changes**
   - User hears: Intro is quieter and filtered, Hook is louder
   - But: It's the SAME audio playing, just processed
   - Perception: "Just volume changes, not real arrangement"

3. **No Missing Instruments**
   - User expects: Verse has no melody, Bridge has no bass
   - Reality: All instruments always present (can't remove from stereo)
   - Perception: "Nothing is actually being removed"

4. **Weak Musical Contrast**
   - Hook + 8dB vs Verse -8dB = 16dB difference
   - This SHOULD feel dramatic, but:
   - Since it's same audio, feels like "louder/quieter versions of same thing"
   - Perception: "No real musical change happening"

---

## Technical Proof

**Test: Check what audio is actually rendered**

```python
# In run_arrangement_job():
logger.info(f"loop_audio channels: {loop_audio.channels}")  # → 2 (stereo)
logger.info(f"loop_audio duration: {len(loop_audio)}ms")    # → ~2000ms

# After render:
logger.info(f"output duration: {len(output_audio)}ms")      # → 180000ms (3 min)
# It's literally loop_audio repeated 90 times with DSP overlays per section
```

**Audio Analysis:**
If user runs spectral analysis on output:
- Every 2 seconds, same frequency content repeats
- Only amplitude and filter cutoff changes per section
- No note/rhythm variation

---

## Why Stem Metadata Exists But Isn't Used

**Historical Analysis:**

Looking at the code, stems were clearly planned but not fully implemented:

1. ✅ Stem separation service exists
2. ✅ Stem files are created and uploaded to S3
3. ✅ Stem metadata is stored in `loop.analysis_json`
4. ✅ Render plan includes stem information
5. ❌ **No code loads stem audio files**
6. ❌ **No code mixes stems per section**

**Likely Development Path:**
1. Phase 1: Basic arrangement with full loop ✅
2. Phase 2: Add section-specific DSP ✅
3. Phase 3: Add stem separation service ✅
4. Phase 4: Add stem metadata to render plan ✅
5. **Phase 5: Use stems in rendering** ← ❌ NEVER COMPLETED

---

## Comparison: What Should Happen vs What Actually Happens

### INTRO Section

**Expected Behavior:**
- Load drums stem, bass stem, melody stem, vocal stem
- Enable: bass stem (low volume)
- Disable: drums, melody, vocal
- Apply: fade in on bass
- Result: User hears only bass line fading in

**Actual Behavior:**
- Load: full stereo loop (all instruments mixed together)
- Apply: -12dB gain + 800Hz lowpass + fade in
- Result: User hears muffled version of full loop

**Perceptual Difference:**
- Expected: Sparse, focused, clear bass intro
- Actual: Quiet muffled version of full beat

---

### VERSE Section

**Expected Behavior:**
- Enable: drums, bass
- Disable or reduce: melody by -10dB
- Apply: slight EQ shaping
- Result: Beat with prominent drums/bass, subdued melody

**Actual Behavior:**
- Use full stereo loop
- Apply: -8dB to +1dB gain + 7kHz lowpass
- Result: Always has ALL instruments, just slightly darker tone

**Perceptual Difference:**
- Expected: Drums and bass clearly lead, space for vocals
- Actual: Full beat playing a bit quieter

---

### HOOK/DROP Section

**Expected Behavior:**
- Pre-hook: 0.5 second silence
- Enable: ALL stems at full volume
- Boost: melody +3dB, drums +2dB
- Apply: brightness, punch
- Result: Dramatic silence → HUGE full-band impact

**Actual Behavior:**
- Trim 0.25 bars from previous section
- Add 0.5 second silence
- Use full stereo loop + 8dB + high-pass overlay
- Result: Silence → loud version of same loop

**Perceptual Difference:**
- Expected: Massive contrast, wall of sound
- Actual: "Louder version after pause"

---

### BRIDGE/BREAKDOWN Section

**Expected Behavior:**
- Enable: melody, vocal (soft)
- Disable: drums, bass
- Apply: reverb, space
- Result: Ambient, sparse, contrasting section

**Actual Behavior:**
- Use full stereo loop -10dB
- Apply: 1200Hz lowpass + rhythmic gaps
- Result: Muffled loop with gaps

**Perceptual Difference:**
- Expected: Totally different vibe, ambient breakdown
- Actual: "Quiet filtered version with stutters"

---

### FINAL HOOK Section

**Expected Behavior:**
- Enable: ALL stems
- Add: extra layered stems or doubled instruments
- Boost: everything +4dB
- Apply: maximum width, brightness
- Result: BIGGEST section, more layers than first hook

**Actual Behavior:**
- Use full stereo loop +11dB
- Apply: multi-band boost
- Result: Very loud version of same loop

**Perceptual Difference:**
- Expected: Climax with added elements
- Actual: "Just louder than before"

---

## Symptom vs Reality Comparison

| User Perception | Technical Reality | Root Cause |
|----------------|-------------------|------------|
| "Same loop repeating" | Loop audio IS literally repeated | No stems loaded |
| "Only volume changes" | Gain changes -12dB to +12dB range | No layer muting/enabling |
| "No real arrangement" | Structure exists in metadata only | Instruments list not enforced |
| "Sounds like demo/preview" | It IS just DSP on stereo file | Missing stem rendering layer |
| "Not producer-quality" | Producer moves are filters only | No stem-targeted effects |

---

## Why This Passed Testing

**Hypothesis:**

1. **Short loops sound okay**
   - 8-16 bar loop with DSP changes sounds "reasonably arranged"
   - Problem becomes obvious at 3+ minutes

2. **Spectral differences mask repetition**
   - Lowpass filter in intro LOOKS different on waveform
   - Hook boost LOOKS different
   - But underlying audio is identical

3. **Tests checked metadata, not audio**
   - Tests verify render_plan_json is generated ✅
   - Tests verify producer moves are injected ✅
   - Tests verify output file exists ✅
   - Tests DON'T verify stems are actually used ❌

4. **Development used short loops**
   - 2-4 second test loops
   - 20-30 second outputs
   - Repetition less obvious

5. **No A/B comparison with real production**
   - No side-by-side with actual producer-arranged beat
   - No stem-based rendering comparison

---

## Priority Classification

### P0 - Critical (Breaks Core Value Proposition)

**Issue:** Stems are never loaded or used in rendering

**Impact:**
- Output is fundamentally a looped audio file
- No real layer separation per section
- No real producer-style arrangement
- Product does not deliver on promise

**Fix Required:**
1. Load stem audio files from storage
2. Pass stems to renderer
3. Enable/disable stems per section based on instruments list
4. Mix enabled stems to create section audio

---

### P1 - Important (Limits Musical Quality)

**Issue A:** Producer moves are DSP-only, not stem-targeted

**Impact:**
- Moves don't create real instrument-level changes
- Falls back to tone/volume changes only

**Fix Required:**
- Rewrite move effects to operate on stems when available
- Keep DSP fallback for when stems not available

**Issue B:** Renderer signature doesn't support stems

**Impact:**
- Even if stems loaded, can't be passed to renderer

**Fix Required:**
- Change `_render_producer_arrangement()` signature
- Add `stems: dict[str, AudioSegment] | None` parameter

**Issue C:** No stereo fallback validation

**Impact:**
- If stems fail, system may crash or produce corrupt output

**Fix Required:**
- Add stem loading error handling
- Detect when stems unavailable and use stereo with warning

---

### P2 - Polish (Improves Edge Cases)

- Weak per-bar variation in stereo fallback mode
- No stem-to-instrument intelligent mapping
- No quality validation before returning output

---

## Recommended Fix Order

1. **Load stem audio files** (P0)
2. **Pass stems to renderer** (P0) 
3. **Implement stem-based section rendering** (P0)
4. **Rewrit producer move effects for stem mode** (P1)
5. **Add stereo fallback validation** (P1)
6. **Improve stereo fallback variation** (P2)
7. **Add output quality guards** (P2)

---

## Next Steps

See implementation plan in:
- Phase 3: Fix Implementation
- Phase 4: Producer Moves Engine Completion
- Phase 5: Render Plan Upgrade
