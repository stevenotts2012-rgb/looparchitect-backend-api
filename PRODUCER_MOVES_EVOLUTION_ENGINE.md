# Producer Moves Evolution Engine

## Purpose
The Producer Moves Evolution Engine upgrades arrangement behavior from loop-level repetition to section-to-section producer-style evolution.

## Runtime Producer Behaviors Implemented
1. Intro tease: melody/pad entry, drum/bass suppression, filtered entry.
2. Verse vocal space: melody gain reduction, reduced active layer targets, periodic pocket gaps.
3. Pre-hook tension: pre-hook mute + silence drop + riser/fill event.
4. Hook impact: layer enable events, brightness lift, transient texture lift.
5. Hook evolution: hook-specific expansion levels increase per hook occurrence.
6. End-of-section fills: fill events at section boundaries.
7. Bridge breakdown: bridge strip events + atmospheric band-limited filter.
8. Outro strip-down: progressive stem disable steps + outro strip event.
9. 4–8 bar movement rule: movement events emitted every 4 bars (or 2 for short sections).
10. Call-and-response: alternating events every 4 bars offset by 2 bars.

## Event Model
The engine now emits both legacy-compatible and evolution-native events:
- `enable_stem`, `disable_stem`, `stem_gain_change`, `stem_filter`
- `silence_drop`, `pre_hook_mute`, `fill_event`, `texture_lift`
- `hook_expansion`, `bridge_strip`, `outro_strip`
- plus existing compatibility events for older tests/pipelines.

## Stem-Aware + DSP Fallback
- Stem-aware intent is encoded via event `params` (target stems/filter/gain directives).
- DSP fallback behaviors are applied in render execution for all move types, including:
  - chop/gap drops
  - transient emphasis
  - brightness/width shaping
  - atmospheric bridge filtering
  - progressive outro strip-down.

## Section Evolution Rules
- Repeated section types get `evolution_index`.
- Hooks receive increasing energy targets and expansion intensity by occurrence.
- Verses remain intentionally thinner than hooks.
- Bridge is constrained to lower energy for ear reset before final payoff.
