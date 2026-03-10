# Arrangement Evolution Report

## Summary
LoopArchitect now applies a Producer Moves Evolution Engine that produces section-level musical evolution instead of loop-level repetition.

## What Changed
- Added evolution-native move events (stem state moves + section impact moves).
- Added section occurrence-based progression (`evolution_index`) and hook growth logic.
- Added scorecard with pass/warn/reject verdicts.
- Extended render-time move execution to apply audible DSP behaviors for all new move types.
- Preserved legacy move event compatibility.

## Hook Progression
- Hook 1: baseline impact
- Hook 2: increased hook expansion intensity and target layer count
- Hook 3: highest expansion/energy target and final payoff emphasis

## Verse Vocal Space
- Verse sections apply melody-focused gain reduction and fewer active target layers.
- Pocket-gap/silence-drop events create breathing room.

## Bridge Reset
- Bridge sections trigger `bridge_strip` and atmospheric filtering.
- Bridge energy is constrained lower than hook energy to reset listener perception before final hook.

## Movement + Repetition Controls
- Movement events are injected on a 4-bar cadence (or 2 bars in short sections).
- Call/response alternation and fill events reduce static loop feel.

## Validation
Added dedicated tests for:
- Hook intensity escalation (`Hook2 > Hook1`, `Hook3 > Hook2`)
- Verse vs hook layer contrast
- Bridge contrast behavior
- 4–8 bar movement cadence
- Repetition avoidance score thresholds
