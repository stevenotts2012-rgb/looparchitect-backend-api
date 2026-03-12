# Stem Render Pipeline

## Render Decision Path
1. `run_arrangement_job` loads loop audio.
2. Stem metadata is parsed from loop analysis payload.
3. If stem metadata indicates success, role stems are loaded.
4. Loop variations are generated.
5. Render plan is built and producer moves are injected.
6. `render_from_plan(...)` renders from plan.

## Stem-Driven Rendering
When stems are available:
- `_render_producer_arrangement(...)` enables stem mode.
- per section, only selected stems are mixed.
- section variations and producer moves are applied.
- section transitions are applied.
- section audio is appended in timeline order.

## Fallback Rendering
When stems are unavailable:
- loop variations are used when available.
- otherwise stereo loop DSP fallback path is used.

## Producer Move Events
Supported events include:
- `drum_fill`
- `snare_roll`
- `pre_hook_silence`
- `riser_fx`
- `crash_hit`
- `reverse_cymbal`
- `drop_kick`
- `bass_pause`

Legacy events are still supported for compatibility.

## Output Artifacts
- final WAV uploaded to storage
- timeline JSON with section details and event metadata
- render plan JSON persisted for debug and replayability