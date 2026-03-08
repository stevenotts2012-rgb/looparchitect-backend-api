# Producer Moves Engine

## Purpose

The Producer Moves Engine adds musically realistic producer-style gestures into `render_plan_json` so arrangements sound intentionally produced, not mechanically loop-arranged.

## Runtime Integration

The engine runs in the real arrangement runtime path:

1. `run_arrangement_job` builds `render_plan_json` via `_build_pre_render_plan`
2. `_build_pre_render_plan` calls `ProducerMovesEngine.inject(render_plan)`
3. The injected events are consumed by `render_executor.render_from_plan`
4. `render_executor` maps move events into section variations for `_render_producer_arrangement`
5. `_render_producer_arrangement` applies audible DSP per move

This path is shared by API and worker render execution through the unified render executor.

## Moves Implemented

- `pre_hook_drum_mute`
- `silence_drop_before_hook`
- `hat_density_variation`
- `end_section_fill`
- `verse_melody_reduction`
- `bridge_bass_removal`
- `final_hook_expansion`
- `outro_strip_down`
- `call_response_variation`

## Stem-Aware Behavior

`render_profile.stem_separation` metadata is propagated into the render payload.

- When stems are marked available (`enabled=true` and `succeeded=true`), move effects use stronger targeted processing (e.g., tighter bass/melody suppression).
- When stems are unavailable, the renderer falls back to deterministic DSP approximations.

## Event Model

Each move is represented as an event in `render_plan_json.events`:

```json
{
  "type": "final_hook_expansion",
  "bar": 28,
  "description": "Final hook expansion",
  "intensity": 1.0,
  "section_name": "Final Hook",
  "section_type": "hook"
}
```

These are merged with section-start and existing variation events, then sorted by bar.

## Verification

Tests are included in `tests/services/test_producer_moves_engine.py` to verify:

- all required producer move event types are injected
- hook sections are audibly bigger than verses
- final hook is audibly bigger than the first hook
