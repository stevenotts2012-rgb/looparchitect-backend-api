# STEM Render Pipeline

## End-to-End Flow
1. Upload stems (`stem_files` or `stem_zip`) through existing loops upload endpoint
2. Ingest and classify stems by role (`drums`, `bass`, `melody`, `harmony/pads`, `fx`, `full_mix` fallback)
3. Persist per-role stem WAVs to object storage (`stems/loop_<id>_<role>.wav`)
4. Build arrangement render plan with per-section `active_stem_roles`
5. Render executor loads stems and mixes enabled roles per section
6. Concatenate section audio and apply transitions/post-processing

## Renderer Source Selection
Inside producer render:
- Prefer stems when present (`use_stems=true`)
- Else use loop variations if present
- Else use stereo DSP fallback

This preserves compatibility while prioritizing stem-driven arrangements.

## Audible Variation Guarantee
Sections produce real differences because each section can enable a different stem subset and apply section-specific processing. Example:
- Intro: melody/pads
- Verse: drums/bass
- Hook: full or near-full stems

## DAW Export Compatibility
The render path remains compatible with existing DAW export artifacts (audio + stems metadata), since stem keys are persisted in loop metadata and consumed through the same arrangement job pipeline.