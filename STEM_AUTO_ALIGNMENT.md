# Stem Auto-Alignment Implementation

## Summary
Implemented a robust stem auto-alignment workflow so uploaded stems with start-offset and moderate length mismatch are no longer hard-rejected.

The ingestion path now:
- Detects leading offsets per stem
- Auto-aligns stems via trim/pad operations
- Normalizes end lengths
- Computes alignment confidence
- Returns warnings instead of hard-failing for recoverable timing issues
- Marks low-confidence packs for stereo-loop fallback while still accepting upload

## Files Changed

### Backend
- `app/services/stem_alignment.py` (new)
  - Added alignment engine with:
    - onset/offset detection
    - trim/pad realignment
    - duration normalization
    - confidence scoring and low-confidence flagging
    - metadata conversion helper

- `app/services/stem_validation.py`
  - Replaced hard misalignment rejection with call into `align_stems(...)`
  - Expanded `StemValidationResult` to include:
    - `auto_aligned`
    - `alignment_confidence`
    - `alignment_metadata`
    - `warnings`
    - `fallback_to_loop`

- `app/services/stem_pack_service.py`
  - `StemPackIngestResult` now carries:
    - `alignment`
    - `validation_warnings`
    - `fallback_to_loop`
  - Metadata output (`to_metadata`) now includes alignment and warning/fallback fields

- `app/routes/loops.py`
  - Persists compatibility fields for stem render router:
    - `is_stem_pack`
    - `stem_roles_json`
    - `stem_files_json`
    - `stem_validation_json`
  - Uses low-confidence signal to set loop fallback mode (`is_stem_pack = "false"`) while preserving uploaded stem metadata

### Frontend
- `looparchitect-frontend/api/client.ts`
  - Extended `stem_metadata` type to include:
    - `warnings`
    - `fallback_to_loop`
    - nested `alignment` payload

- `looparchitect-frontend/src/components/UploadForm.tsx`
  - Added success-state messaging for:
    - “Stems were auto-aligned”
    - “Detected timing offsets and corrected them”
    - “Some stems required trimming/padding”
  - Added display of alignment notes/warnings
  - Fixed stem mode detection to use `upload_mode === "stem_pack"` and `succeeded`/fallback flags

## Behavior Changes
- Misaligned starts are auto-corrected (no hard rejection).
- Moderate length mismatches are normalized (no hard rejection).
- Truly unusable stems still hard-fail (empty/corrupt/too short/severely incompatible).
- Low-confidence alignment accepts upload but routes to stereo-loop fallback for arrangement/render path.

## Test Updates
- Updated `tests/services/test_stem_pack_service.py` with new policy coverage:
  - offsets are auto-aligned
  - length differences are normalized
  - low-confidence alignment triggers fallback signal
  - unusable stems still fail hard

## Validation Run
Executed:

```bash
pytest tests/services/test_stem_pack_service.py -q
```

Result:
- `6 passed`
- `1 warning` (pydub/ffmpeg runtime warning)
