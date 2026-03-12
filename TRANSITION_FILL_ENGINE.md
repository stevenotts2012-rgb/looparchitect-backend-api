# Transition & Fill Engine

## Files changed

- app/services/transition_engine.py
- app/services/arrangement_jobs.py
- app/services/render_executor.py
- tests/services/test_arrangement_jobs_variations.py
- tests/services/test_transition_engine.py

## Transition types added

- `pre_hook_silence_drop`
- `drum_fill`
- `snare_pickup`
- `riser_fx`
- `reverse_cymbal`
- `crash_hit`
- `bridge_strip`
- `outro_strip`

## How hooks now enter differently

- Verse-to-hook boundaries now inject a short drop before impact.
- Hook downbeats receive `crash_hit`.
- If FX stems exist, the engine adds `riser_fx` or `reverse_cymbal` before the hook.
- Final hook entries are stronger than early hooks and can stack riser, reverse cymbal, crash, and fill behavior.

## How bridge/outro transitions work

- Boundaries into bridge now add `bridge_strip` to reduce bass/drum weight before the rebuild.
- Boundaries into outro add `outro_strip`.
- Outro also gets an extra mid-section strip event so energy keeps falling instead of changing only once.

## Render-plan integration

- Transition boundaries are written into `render_plan_json` as `section_boundaries`.
- Each boundary carries grouped events under:
  - `before_section`
  - `on_downbeat`
  - `end_of_section`
- Flattened runtime events are also appended to `events` so the shared render path can apply them audibly.

## Runtime application

- In stem-aware mode, transition DSP is shaped more aggressively to simulate producer-style stem dropouts and returns.
- In stereo fallback mode, transitions still create audible cuts, pickups, strip-downs, crashes, and risers.
- Boundary events are applied inside the real producer renderer, not stored as metadata only.

## Tests run

- Command run:
  - `python -m pytest tests/services/test_transition_engine.py tests/services/test_arrangement_jobs_variations.py -q`
- Result:
  - `13 passed, 1 warning`
- Added focused transition generation tests.
- Added render-plan/runtime transition tests covering:
  - verse -> hook boundary events
  - stronger final hook transition
  - bridge strip behavior
  - outro strip behavior
  - runtime timeline exposure and audible application
