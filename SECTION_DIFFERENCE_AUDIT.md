# SECTION DIFFERENCE AUDIT

**Date**: 2026-03-09  
**Arrangement Analyzed**: ID 242 (most recent)  
**Goal**: Measure actual audio differences between repeated sections

---

## ARRANGEMENT 242 STRUCTURE

**Total Duration**: 114 bars @ 144 BPM = ~190 seconds  
**Loop Variations**: 5 variants (intro, verse, hook, bridge, outro)  
**Stems Used**: NO (`stems_used: False`)

### Section Breakdown

| # | Name | Type | Bars | Start Bar | Variant | Energy |
|---|------|------|------|-----------|---------|--------|
| 1 | Intro | intro | 8 | 0 | intro | 0.50 |
| 2 | Hook | hook | 8 | 8 | **hook** | 0.85 |
| 3 | Verse | verse | 16 | 16 | verse | 0.50 |
| 4 | Hook | hook | 8 | 32 | **hook** ← REPEAT | 0.85 |
| 5 | Verse | verse | 16 | 40 | verse ← REPEAT | 0.50 |
| 6 | Bridge | bridge | 8 | 56 | bridge | 0.50 |
| 7 | Hook | hook | 8 | 64 | **hook** ← REPEAT 2 | 0.90 |
| 8 | Outro | outro | 4 | 72 | outro | 0.50 |

**Repetition Pattern**:
- **3 Hook sections**: All use `"hook"` variant
- **2 Verse sections**: Both use `"verse"` variant

---

## VARIANT GENERATION ANALYSIS

### How Variants Are Created (No Stems)

**Source**: [loop_variation_engine.py:128-221](looparchitect-backend-api/app/services/loop_variation_engine.py#L128-L221)

When stems unavailable, variants fall back to DSP processing on full stereo loop:

```python
# Intro fallback
if intro.rms == 0:
    intro = loop_audio.low_pass_filter(1200) - 10

# Verse fallback
if verse.rms == 0:
    verse = (loop_audio - 5).low_pass_filter(5000)

# Hook fallback
if hook.rms == 0:
    hook = loop_audio + 4

# Bridge fallback
if bridge.rms == 0:
    bridge = loop_audio - 8
    bridge = bridge.low_pass_filter(1400).high_pass_filter(180)

# Outro fallback
if outro_base.rms == 0:
    outro_base = loop_audio - 4
    outro = _progressive_drum_removal(outro_base, drums=None, bar_duration_ms)
```

### Variant Differences (No Stems)

| Variant | Frequency Range | Gain Shift | Other Processing |
|---------|----------------|------------|------------------|
| **intro** | 0 - 1200 Hz | -10 dB | None |
| **verse** | 0 - 5000 Hz | -5 dB | Transient softening, gaps |
| **hook** | Full (20-20kHz) | +4 dB | Density variation |
| **bridge** | 180 - 1400 Hz | -8 dB | Band-pass, gaps |
| **outro** | 0 - 5000 Hz | -4 dB | Progressive fade, drum removal |

**Assessment**: ✅ **VARIANTS ARE SIGNIFICANTLY DIFFERENT**
- Intro vs Hook: 18 dB level difference + massive filtering
- Bridge vs Hook: Band-passed vs full-range = very different sound

---

## SECTION-TO-SECTION COMPARISON

### Hook #1 vs Hook #2 vs Hook #3

**Base Audio**:
- All 3 use `loop_variations["hook"]` - **IDENTICAL SOURCE**

**Per-Instance Randomization**:

**Source**: [arrangement_jobs.py:534-563](looparchitect-backend-api/app/services/arrangement_jobs.py#L534-L563)

```python
instance_seed = int(hashlib.md5(f"{section_name}_{section_idx}_{bar_start}".encode()).hexdigest()[:8], 16)

# Hook #1: section_name="Hook", section_idx=1, bar_start=8
# Hook #2: section_name="Hook", section_idx=3, bar_start=32
# Hook #3: section_name="Final Hook", section_idx=6, bar_start=64
```

**Variations Applied**:

| Hook | Seed Input | EQ Type | EQ Shift | Stereo Width |
|------|------------|---------|----------|--------------|
| #1 | "Hook_1_8" | seed%3 = ? | -2 to +2 dB | seed%4 = ? |
| #2 | "Hook_3_32" | seed%3 = ? | -2 to +2 dB | seed%4 = ? |
| #3 | "Final Hook_6_64" | seed%3 = ? | -2 to +2 dB | seed%4 = ? |

**EQ Options**:
- `seed % 3 == 0`: Low-pass 8kHz + shift
- `seed % 3 == 1`: High-pass 120Hz + shift
- `seed % 3 == 2`: Flat + shift only

**Stereo Options**:
- `seed % 4 == 0`: Wider (+1dB L/R)
- `seed % 4 == 2`: Narrower (-1dB)
- Otherwise: Unchanged

### Section-Type Processing (Post-Randomization)

**Hook sections also get**:
```python
section_audio = section_audio + 8  # +8dB boost for all hooks
# Add brightness
bright = section_audio.high_pass_filter(100) + 2
section_audio = section_audio.overlay(bright, gain_during_overlay=-2)
```

**Analysis**:
- ✅ All Hooks get +8dB boost → **STRONG, SAME FOR ALL**
- ⚠️ Per-instance randomization (±2dB, mild filter) → **SUBTLE, DIFFERENT**

**Net Result**:
- Hook #1: `hook_variant + randomization_A + +8dB`
- Hook #2: `hook_variant + randomization_B + +8dB`
- Hook #3: `hook_variant + randomization_C + +8dB`

**Perceived Similarity**: ⚠️ **HIGH** - Base audio 95% identical, only ±2dB EQ difference

---

### Verse #1 vs Verse #2

**Base Audio**:
- Both use `loop_variations["verse"]` - **IDENTICAL SOURCE**
- Verse variant: loop @ -5dB, low-pass 5kHz, transient softening, gaps

**Per-Instance Randomization**:
```python
# Verse #1: section_name="Verse", section_idx=2, bar_start=16
# Verse #2: section_name="Verse", section_idx=4, bar_start=40
```

**Variations Applied**: ±2dB + mild EQ, same as Hooks

**Section-Type Processing**:
```python
# Verses get energy-based volume
energy_db = -8 + (section_energy * 9)  # energy=0.50 → -3.5 dB
section_audio = section_audio.low_pass_filter(7000)  # Slight HF reduction
section_audio = section_audio + energy_db
```

**Analysis**:
- ✅ Both Verses get -3.5dB, low-pass 7kHz → **SAME FOR ALL**
- ⚠️ Per-instance randomization → **SUBTLE DIFFERENCE**

**Perceived Similarity**: ⚠️ **VERY HIGH** - Even more similar than Hooks

---

## WAVEFORM SIMILARITY ESTIMATE

**Cannot measure actual RMS without audio files, but can estimate from code:**

### Variant-Level Differences

**Intro vs Hook** (different variants):
- Frequency: 1200 Hz vs 20 kHz = **95% different spectral content**
- Gain: -10 dB vs +4 dB = **14 dB difference**
- **Estimated Similarity**: <20% - **VERY DIFFERENT**

**Verse vs Hook** (different variants):
- Frequency: 5000 Hz vs 20 kHz = **50% different spectral content**
- Gain: -5 dB vs +4 dB = **9 dB difference**
- **Estimated Similarity**: 40% - **MODERATELY DIFFERENT**

### Same-Variant Differences

**Hook #1 vs Hook #2** (same variant):
- Base Audio: **100% IDENTICAL**
- EQ Variation: ±2 dB on 8kHz LP or 120Hz HP = **~5-10% energy change**
- Stereo Width: ±1 dB L/R = **~3% change**
- **Estimated Similarity**: **85-90%** - **TOO SIMILAR**

**Verse #1 vs Verse #2** (same variant):
- Base Audio: **100% IDENTICAL**
- Variations: Same as Hooks
- **Estimated Similarity**: **85-90%** - **TOO SIMILAR**

---

## SECTION DIFFERENCE MEASURES

### Expected Differences (Producer Arrangement)

**Professional arrangement should have**:
1. **Intro quieter than verse**: ✅ YES - intro at -10dB, verse at -5dB
2. **Verse quieter than hook**: ✅ YES - verse at -5dB, hook at +4dB = 9dB difference
3. **Hook #1 different from Hook #2**: ❌ **NO** - Only ±2dB EQ difference
4. **Bridge distinctly different**: ✅ YES - band-passed 180-1400Hz vs full-range
5. **Final hook bigger than first**: ⚠️ **BARELY** - Same variant, same +8dB boost, only randomization differs

### Energy Curve Analysis

**From Database** (energy values):
```
Intro:  0.50 → Processed at -10dB
Hook:   0.85 → Processed at +8dB   ✅ BIG JUMP
Verse:  0.50 → Processed at -3.5dB
Hook:   0.85 → Processed at +8dB   ⚠️ SAME AS FIRST HOOK
Verse:  0.50 → Processed at -3.5dB ⚠️ SAME AS FIRST VERSE
Bridge: 0.50 → Processed at -8dB
Hook:   0.90 → Processed at +8dB   ⚠️ BARELY HIGHER (energy value different but processing same)
Outro:  0.50 → Processed at -4dB
```

**Issue**: Energy values differ (0.85 vs 0.90) but Hook processing is identical (+8dB for all)

---

## ACTIVE STEMS/LAYERS CHECK

**Question**: Are different stems enabled per section?

**Answer**: ❌ **NO STEMS USED** - Database confirms `"stems_used": False`

**Without Stems**:
- Cannot selectively enable/disable drums, bass, melody
- Cannot create "verse with no drums" vs "hook with full drums"
- Limited to DSP processing on full stereo mix

**With Stems** (if available):
```python
# Intro: melody only
active_stems = ("melody", "vocal")

# Verse: reduced drums
active_stems = ("drums", "bass", "melody")
gains = {"drums": -6, "melody": -7, "bass": -1}

# Hook: full stems, loud drums
active_stems = ("drums", "bass", "melody", "vocal")
gains = {"drums": 4, "bass": 1, "melody": 2, "vocal": 1}
```

**Impact**: With stems, variants would have **dramatically different layer compositions**, not just EQ/gain

---

## SILENCE REGIONS

**Intro**: None (fade in only)  
**Verse**: ✅ YES - `_apply_silence_gaps()` adds 90ms gaps every other bar  
**Hook**: None  
**Bridge**: ✅ YES - 140ms gaps for sparse feel  
**Outro**: None (fade out only)

**Status**: ⚠️ **PARTIAL** - Only Verse and Bridge have gaps

---

## SIMILARITY SCORES (Estimated)

Cannot compute actual cross-correlation without audio files, but estimated from code:

| Comparison | Base Audio | Processing | Total Similarity | Assessment |
|------------|------------|------------|------------------|------------|
| Intro → Verse | Same loop | Different filters | **40%** | ✅ Different enough |
| Verse → Hook | Same loop | Different gains | **50%** | ⚠️ Borderline |
| Hook #1 → Hook #2 | **SAME VARIANT** | ±2dB only | **88%** | ❌ **TOO SIMILAR** |
| Verse #1 → Verse #2 | **SAME VARIANT** | ±2dB only | **88%** | ❌ **TOO SIMILAR** |
| Bridge → Hook | Same loop | Huge filter diff | **25%** | ✅ Very different |
| Hook #3 → Outro | Different variants | Different | **45%** | ✅ Different enough |

---

## FINDINGS SUMMARY

### ✅ What IS Different

1. **Variant Types** - intro/verse/hook/bridge/outro ARE audibly distinct
2. **Section Types** - intro vs hook get vastly different processing (-10dB vs +8dB)
3. **Frequency Content** - intro (1.2kHz) vs hook (20kHz) dramatically different
4. **Energy Curve** - quiet intro → loud hook → quiet verse structure works

### ❌ What IS NOT Different Enough

1. **Repeated Hooks** - Hook #1, #2, #3 use SAME "hook" variant
   - Only ±2dB EQ difference
   - ~88% waveform similarity
   - **User perception: "It's just repeating"**

2. **Repeated Verses** - Verse #1, #2 use SAME "verse" variant
   - Only ±2dB EQ difference
   - ~88% waveform similarity
   - **User perception: "Same thing again"**

3. **No Stem Variation** - Without stems, cannot vary layer composition
   - Hook #1 cannot have "less drums" than Hook #3
   - Cannot do "verse with no hi-hats" vs "verse with hi-hats"

4. **Per-Instance Randomization Too Weak**
   - ±2dB insufficient to mask repetition
   - Need ±6-8dB or melodic/rhythmic changes

---

## ROOT CAUSE CONFIRMATION

**The arrangement IS structured correctly** (intro/verse/hook/bridge/outro).  
**The variants ARE significantly different from each other**.  

**BUT**: Repeating the same variant 3 times (Hook #1, #2, #3) with only ±2dB EQ variation **DOES NOT CREATE THE ILLUSION OF A NEW SECTION**.

**Analogy**:
- Having 5 different ingredients (variants) = ✅ Good
- Using the same ingredient 3 times in a row = ❌ Repetitive
- Adding ±2dB salt to that ingredient = ⚠️ Not enough variation

**User hears**: "This is the same loop, just louder then quieter then louder again"

---

## RECOMMENDATIONS FOR PHASE 5

**Priority Issues**:
1. **P0**: Same variant repeated multiple times (3 Hooks use "hook")
2. **P1**: Per-instance randomization too subtle (±2dB insufficient)
3. **P1**: No stems means no layer variation (cannot disable drums/bass per section)
4. **P2**: Final hook not meaningfully bigger than first hook

**Next**: Phase 3 - Stem Usage Audit to confirm why stems aren't being used
