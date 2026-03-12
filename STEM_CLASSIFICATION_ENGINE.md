# STEM CLASSIFICATION ENGINE

**Date**: 2026-03-12  
**Scope**: Phases 1–9 of the Stem Role Detection Upgrade  
**Status**: ✅ Complete — 62 new tests passing, 0 regressions in stem test modules

---

## Files Changed

| File | Change |
|------|--------|
| `app/services/stem_classifier.py` | **Full rewrite** — expanded taxonomy, ranked keyword table, 4-band audio heuristics, rich StemClassification dataclass |
| `app/services/stem_role_classifier.py` | Updated re-exports to include `ARRANGEMENT_GROUPS` |
| `app/services/stem_arrangement_engine.py` | New `StemRole` enum values, `STEM_GROUPS` dict, group-based `_determine_active_stems`, expanded `_create_stem_states` |
| `app/services/stem_pack_service.py` | Stores per-filename `StemClassification`; exposes `stem_classifications`, `arrangement_groups_detected`, `friendly_labels` in metadata |
| `tests/services/test_stem_classifier.py` | **Full rewrite** — 56 new tests across 8 classes |
| `tests/services/test_stem_engine.py` | Fixed 2 assertions broken by taxonomy expansion (`_FILENAME_HINTS` removal, `pad_harmony` disambiguation) |
| `tests/services/test_stem_pack_service.py` | Updated expected `roles_detected` for `pad.wav` → `"pads"` |

---

## Role Taxonomy (Phase 1)

### Primary Roles

| Role | Arrangement Group | Description |
|------|------------------|-------------|
| `drums` | `rhythm` | Full kit loops, kick, snare, clap, hat, rim, tom |
| `percussion` | `rhythm` | Shaker, conga, bongo, tambourine, perc loops |
| `bass` | `low_end` | Sub bass, 808, bass lines |
| `melody` | `lead` | Lead synths, bell, piano, guitar lead, arp, riff |
| `vocals` | `lead` | Vocal chops, vox, adlib, rap lines |
| `harmony` | `harmonic` | Chord stabs, strings, organ, rhodes, harmony pads |
| `pads` | `harmonic` | Pad layers, texture pads, sustained chords |
| `fx` | `texture` | Risers, downlifters, sweeps, impacts, reverses, atmospheres |
| `accent` | `transition` | One-shots, stabs, accent hits |
| `full_mix` | `fallback_mix` | Full mix / bounce / master — fallback when nothing classifies |

### Arrangement Group → Roles Mapping

```
rhythm       → drums, percussion
low_end      → bass
lead         → melody, vocals
harmonic     → harmony, pads
texture      → fx
transition   → accent
fallback_mix → full_mix
```

---

## Keyword Classification Engine (Phase 2)

### Architecture

The classifier uses a ranked, ordered keyword table (`_KEYWORD_TABLE`) with two passes:

1. **Compound token pass** — multi-word patterns matched first (highest specificity):
   - `"synth key"` → `harmony`, `"bell melody"` → `melody`, `"kick drum"` → `drums`, `"full mix"` → `full_mix`, etc.

2. **Single token pass** — individual normalised tokens:
   - `"bell"` → `melody`, `"pad"` → `pads`, `"accent"` → `accent`, etc.

3. **Substring pass** — for tokens buried inside compound words (e.g. `"808"` inside `808bass_loop`)

### Scoring

| Match type | Base confidence |
|-----------|----------------|
| Token match | 0.88 |
| Substring match | 0.78 |
| Each additional keyword on same role | +0.04 bonus (capped at 0.98) |

### Keyword Coverage

**Drums**: drum, drums, kick, snare, clap, hat, hihat, hh, rim, tom, loop drums, kick drum, snare drum, hi hat  
**Percussion**: shaker, perc, percussion, conga, bongo, tambourine, perc loop  
**Bass**: bass, 808, sub, low, lowend, bass line, bass loop, sub bass  
**Melody**: melody, lead, bell, pluck, arp, riff, hook, piano, epiano, guitar, marimba, vibes, flute, sax, trumpet, synth lead, bell melody, guitar lead  
**Harmony**: pad, pads, chord, chords, harmony, texture, organ, strings, rhodes, keys, key, stabs, synth key, guitar rhythm  
**FX**: fx, sfx, riser, downlifter, sweep, impact, crash, reverse, transition, noise, ambience, atmosphere, riser fx, sweep fx  
**Accent**: accent, stab, hit, oneshot, one shot, accent hit  
**Vocals**: vocal, vox, voice, chop, adlib, rap, vox chop  
**Full Mix**: full, mix, stereo, master, bounce, mixdown, full mix  

---

## Audio Heuristics (Phase 3)

Activated when filename confidence < **0.70** (the `AUDIO_HEURISTIC_THRESHOLD`).

### 4-Band Analysis

| Band | Range | Variable |
|------|-------|----------|
| Sub | 0–80 Hz | `sub_r` |
| Low | 80–300 Hz | `low_r` |
| Mid | 300–3000 Hz | `mid_r` |
| Hi | 3000+ Hz | `hi_r` |

Combined: `low_energy = sub_r + low_r`

### Transient Density Proxy

```
peak_ratio = max_amplitude / total_rms
```
High peak_ratio (> 6.0) indicates many sharp transients → drums/percussion.

### Decision Tree

```
low_energy > 0.80 and hi_r < 0.40   → bass      (0.72)
peak_ratio > 6.0 and low_energy < 0.65 → drums   (0.68)
mid_r > 0.82 and hi_r < 0.45         → pads      (0.65)
hi_r > 0.75 and mid_r > 0.60         → melody    (0.62)
hi_r > 0.80 and low_energy < 0.35    → fx        (0.60)
fallback                              → full_mix  (0.50)
```

---

## Confidence Model (Phase 4)

| Threshold | Meaning |
|-----------|---------|
| ≥ 0.88 | Strong filename token match — high confidence |
| 0.70–0.87 | Moderate — audio heuristics may supplement |
| < 0.70 | Weak filename match — audio heuristics **always** run |
| < 0.55 | `uncertain = True` — classification is a best-guess |

### Blending Logic

When both filename and audio sources run:

- **They agree** → confidence boosted by +0.06, `sources_used = ["filename", "audio"]`
- **Audio strongly disagrees** (by > 0.08) → audio wins with small penalty, `sources_used = ["audio"]`
- **Audio weakly disagrees** → filename result kept, audio not decisive enough

### Conservative Fallback

When confidence < `UNCERTAIN_THRESHOLD` (0.55):
- `uncertain = True` is set on the result
- Role is preserved (not silently swapped to `full_mix`)
- Caller can inspect `uncertain` and `sources_used` to decide how to handle it

---

## Metadata Exposure (Phase 5)

Each stem in an uploaded pack now returns full classification details via `to_metadata()`:

```json
{
  "stem_classifications": [
    {
      "filename": "Catch_Fire_Bell_Dmin_142BPM_9.wav",
      "role": "melody",
      "group": "lead",
      "confidence": 0.88,
      "matched_keywords": ["bell"],
      "sources_used": ["filename"],
      "uncertain": false,
      "friendly_label": "Melody"
    }
  ],
  "arrangement_groups_detected": ["lead", "low_end", "rhythm", "transition"],
  "friendly_labels": ["Accent", "Bass", "Drums", "Melody"]
}
```

---

## Arrangement Engine Integration (Phase 6)

`StemArrangementEngine._determine_active_stems()` now uses **arrangement groups** rather than enumerating individual roles. This means adding a new role (e.g. `percussion`) automatically participates in the correct section without any engine changes.

### Group → Section Mapping

| Section | Active Groups |
|---------|--------------|
| Intro | lead + harmonic + texture (no rhythm or low_end) |
| Verse | rhythm + low_end + (lead if energy > 0.5) |
| Hook | rhythm + low_end + lead + (harmonic if E > 0.70) + (texture if E > 0.82) + (transition if E > 0.88) |
| Bridge | harmonic + texture + (rhythm if E > 0.60), no low_end |
| Outro | lead + harmonic (rhythm stripped) |

New `StemRole` enum values: `PADS`, `PERCUSSION`, `ACCENT`, `VOCALS`

New `STEM_GROUPS` constant maps every group to its member roles, enabling O(1) group-based lookup with `_roles_in_group()`.

---

## Frontend Friendly Labels (Phase 7)

Each role maps to a capitalised display label:

| Role | Friendly Label |
|------|---------------|
| `drums` | Drums |
| `percussion` | Percussion |
| `bass` | Bass |
| `melody` | Melody |
| `vocals` | Vocals |
| `harmony` | Harmony |
| `pads` | Pads |
| `fx` | FX |
| `accent` | Accent |
| `full_mix` | Full Mix |

Exposed as `friendly_labels: ["Bass", "Drums", "Melody", "Pads"]` in the loop metadata API response.

---

## Classified Examples (Phase 8)

| Filename | Role | Group | Confidence | Matched Keywords |
|---------|------|-------|-----------|-----------------|
| `Catch_Fire_Bass_Dmin_142BPM_8.wav` | bass | low_end | 0.88 | ["bass"] |
| `Catch_Fire_Bell_Dmin_142BPM_9.wav` | melody | lead | 0.88 | ["bell"] |
| `Catch_Fire_Synth_Key_Dmin_142BPM_11.wav` | harmony | harmonic | 0.88 | ["synth key"] |
| `Catch_Fire_Accent_3_Dmin_142BPM_6.wav` | accent | transition | 0.88 | ["accent"] |
| `perc_loop.wav` | percussion | rhythm | 0.88 | ["perc"] |
| `full_mix.wav` | full_mix | fallback_mix | 0.88 | ["full", "mix"] |
| `kick_drum_loop.wav` | drums | rhythm | 0.92 | ["kick drum", "drum"] |
| `808_sub_bass.wav` | bass | low_end | 0.96 | ["808", "sub", "bass"] |
| `mystery_layer_xyz.wav` | full_mix | fallback_mix | 0.50 | [] — audio fallback |

---

## Tests Run (Phase 8)

**File**: `tests/services/test_stem_classifier.py` — **56 tests**

| Test Class | Coverage |
|-----------|---------|
| `TestCatchFireFilenames` | 6 tests — exact product-spec filenames |
| `TestRoleTaxonomy` | 24 parametrised tests — all 10 roles reachable |
| `TestArrangementGroups` | 11 tests — group mapping accuracy |
| `TestSourcesUsed` | 2 tests — sources_used field |
| `TestCompoundFilenames` | 3 tests — synth_lead, perc_loop, kick_drum |
| `TestLowConfidenceFallback` | 3 tests — uncertain flag, fallback role, group presence |
| `TestAudioHeuristics` | 3 tests — bass-heavy, transient, no-filename |
| `TestStemRolesConstant` | 1 test — all 10 roles in STEM_ROLES |
| `TestMetadataShape` | 2 tests — backward compatibility of reason property |

**Also updated**: `tests/services/test_stem_pack_service.py` (6 tests — all pass)

**Grand total stem tests**: **62 passed, 0 failed**

---

## Backward Compatibility

- `classify_stem(filename, audio)` signature unchanged
- `StemClassification.reason` is a `@property` returning the same string format as before
- `STEM_ROLES` tuple extended (superset of old tuple)
- `stem_role_classifier.py` re-exports all previous symbols + new ones
- Existing `StemRole` enum values in `stem_arrangement_engine.py` unchanged (new values added only)
- `StemPackIngestResult` fields unchanged; `stem_classifications` added with `default=None` + `__post_init__`
