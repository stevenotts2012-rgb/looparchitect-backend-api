# Arrangement Logic

## Section-Level Stem Activation
Stem-primary mode assigns active roles by **energy level** (0.0 to 1.0):

| Section | Energy | Stems |
|---------|--------|-------|
| Intro | 0.3 | harmony, melody |
| Verse 1 | 0.5 | drums, bass |
| Hook 1 | 0.8 | drums, bass, melody |
| Verse 2 | 0.6 | drums, bass, melody |
| Hook 2 | 0.9 | drums, bass, melody, harmony |
| Bridge | 0.6 | harmony, fx, drums |
| Hook 3 | 1.0 | drums, bass, melody, harmony, fx |
| Outro | 0.2 | melody, harmony |

Each section config includes:
- `active_stem_roles`: Set of StemRole enums
- `energy_level`: 0.0-1.0 progression
- `stem_states`: Per-stem gain, pan, filter settings
- `producer_moves`: Musical events (drum_fill, riser, etc.)
- `section_type`: Intro, Verse, Hook, Bridge, Outro

## Hook Evolution Rules
**Progressive layer accumulation with each hook:**

- **Hook 1** (energy 0.8): drums + bass + melody → drum_fill, pre_hook_silence
- **Hook 2** (energy 0.9): ↑ + harmony (+2 layers) → snare_roll, riser_fx  
- **Hook 3** (energy 1.0): ↑ + fx (all stems active) → crash_hit, pre_drop_buildout

Each hook's energy calculated as: `min(1.0, 0.7 + (0.1 × hook_number))`
- Hook 1: 0.7 + 0.1 = **0.80**
- Hook 2: 0.7 + 0.2 = **0.90**
- Hook 3: 0.7 + 0.3 = **1.00**

## Producer Move Injection
Producer moves are **automatically injected** for musical interest:

| Move | Applied At | Effect |
|------|-----------|--------|
| `drum_fill` | Hook 1 | Expand previous section's last drum bar |
| `pre_hook_silence` | Hook 1 | 0.5-bar silence before hook impact |
| `snare_roll` | Hook 2 | Snare density increase → tension |
| `riser_fx` | Hook 2 | High-pass sweep into Hook 2 |
| `crash_hit` | Hook 3 | Cymbal peak for maximum impact |
| `pre_drop_buildout` | Hook 3 | Drum build (velocity ramp) |
| `bass_pause` | Bridge | Bass drops out for 2 bars |
| `call_response_variation` | Verse 2+ | Repeat melody with variation |

## Loop Fallback
**Dual-Path Architecture:**

✅ **Stem Path** (NEW): If stems detected, valid, and classified → use `StemArrangementEngine`
❌ **Loop Fallback** (EXISTING): If stems missing/invalid → use existing `LoopVariationEngine`

This preserves **100% backward compatibility** while enabling stem-first behavior.

## Implementation Reference

See these files for complete implementation:
- `app/services/stem_arrangement_engine.py` - Section planning, energy calculation, stem activation
- `app/services/stem_render_executor.py` - Audio mixing, producer move application
- `app/services/render_path_router.py` - Path decision logic and orchestration
- `tests/services/test_stem_engine.py` - Comprehensive test coverage
