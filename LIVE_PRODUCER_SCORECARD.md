# Live Producer Scorecard

## Goal
Score each arrangement for live-producer musical behavior and flag weak outputs.

## Metrics
Each metric is scored 0–100:
- Hook impact
- Verse space
- Section contrast
- Final hook payoff
- 4–8 bar movement
- Repetition avoidance

## Verdict Thresholds
- `pass`: score >= 75
- `warn`: 55–74
- `reject`: < 55

## Runtime Integration
- Scorecard is generated during producer move injection.
- Stored on render plan as `producer_scorecard` and mirrored in `render_profile`.
- Quality validator behavior:
  - `reject` => raises and blocks rendering
  - `warn` => allows render with warning logs

## Why This Works
This prevents technically valid but musically static arrangements from passing through unchanged, and pushes outputs toward producer-style evolution across hooks, verses, bridge, and transitions.
