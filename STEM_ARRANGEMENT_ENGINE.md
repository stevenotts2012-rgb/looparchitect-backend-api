# STEM Arrangement Engine

## Primary Mode Behavior
Stem arrangement is now the primary render mode when stem metadata is available and successful.

Decision rule:
- If `stems_exist`: use stem arrangement
- Else: use loop variation/stereo fallback

## Section Layer Activation
`_apply_stem_primary_section_states()` assigns `active_stem_roles` per section type:

- Intro: `melody + harmony/pads + fx`
- Verse: `drums + bass` (later verse can add harmony)
- Hook/Chorus/Drop: progressively fuller stem layers
- Bridge/Breakdown: `harmony + fx + melody`
- Outro: `melody + harmony + fx`

Each section is annotated with:
- `instruments`
- `active_stem_roles`
- `stem_primary=true`

## Render Plan Impact
`_build_pre_render_plan()` now:
1. applies stem section-state assignment first
2. then applies loop-variant assignment
3. sets `render_profile.stem_primary_mode=true` when stems are active

This ensures section-level stem activation drives audible differences across the arrangement.