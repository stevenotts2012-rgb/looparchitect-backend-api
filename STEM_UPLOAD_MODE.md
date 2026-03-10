# STEM Upload Mode

## Overview
LoopArchitect upload now supports three mutually-exclusive modes on the existing `POST /api/v1/loops/upload` pipeline:

1. `file` (single stereo loop fallback mode)
2. `stem_files` (multi-file stem upload)
3. `stem_zip` (ZIP stem pack upload)

The route rejects mixed submissions and requires exactly one mode.

## Supported Stem Inputs
- Multiple files: `drums.wav`, `bass.wav`, `melody.wav`, `pads.wav`, `fx.wav`
- ZIP pack: `beat_stems.zip` (server extracts supported audio files)

Supported formats inside stem uploads:
- `.wav`, `.mp3`, `.ogg`, `.flac`

## Validation Rules
Stem uploads are validated before arrangement generation:
- At least two stem files required
- All stems must have the same sample rate
- All stems must be aligned to effectively equal duration (<= 120ms drift)
- Analyzer-detected loop length must be between 4 and 16 bars

Rejected uploads return `400` with clear error details.

## Metadata Stored
For stem uploads, `Loop.analysis_json.stem_separation` includes:
- `roles_detected`
- `stem_s3_keys`
- `source_files`
- `role_sources`
- `sample_rate`
- `duration_ms`
- `upload_mode=stem_pack`
- validation flags

## Backward Compatibility
Single-loop uploads continue using the existing loop analyzer and loop variation pipeline unchanged.