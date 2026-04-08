"""Stem ingestion router — normalises all three upload modes into a canonical stem manifest.

Modes
-----
A. single_file  → AI separation pipeline → CanonicalStemManifest
B. multi_stem   → existing StemPackIngestResult → CanonicalStemManifest
C. zip_stem     → existing StemPackIngestResult → CanonicalStemManifest

The canonical manifest is the single internal object that downstream services
(arrangement planner, render executor) consume.

Source priority (Phase 4)
--------------------------
1. uploaded_stem   (multi_stem mode)
2. zip_stem        (zip_stem mode)
3. ai_separated    (single_file mode)

AI separation is NEVER run when the user has already provided real stems.
User-provided stems are NEVER replaced by AI-derived stems.
"""

from __future__ import annotations

import logging

from app.services.canonical_stem_manifest import (
    CANONICAL_TO_BROAD,
    CanonicalStemEntry,
    CanonicalStemManifest,
    SOURCE_AI_SEPARATED,
    SOURCE_UPLOADED_STEM,
    SOURCE_ZIP_STEM,
)
from app.services.stem_pack_service import StemPackIngestResult
from app.services.stem_role_mapper import map_ai_stem_to_role, map_filename_to_role

logger = logging.getLogger(__name__)

SOURCE_MODE_SINGLE_FILE = "single_file"
SOURCE_MODE_MULTI_STEM = "multi_stem"
SOURCE_MODE_ZIP_STEM = "zip_stem"


# ---------------------------------------------------------------------------
# Path B & C: uploaded stems / ZIP stems → manifest
# ---------------------------------------------------------------------------


def build_manifest_from_uploaded_stems(
    ingest_result: StemPackIngestResult,
    *,
    loop_id: int,
    stem_s3_keys: dict[str, str],
    source_type: str = SOURCE_UPLOADED_STEM,
    source_mode: str = SOURCE_MODE_MULTI_STEM,
) -> CanonicalStemManifest:
    """Build a CanonicalStemManifest from an already-ingested StemPackIngestResult.

    This is called for both multi_stem and zip_stem modes.
    All existing classification data is preserved; the role mapper attempts to
    derive richer sub-roles from filenames where possible.

    Parameters
    ----------
    ingest_result:
        Result from ingest_stem_files() or ingest_stem_zip().
    loop_id:
        The owning loop ID.
    stem_s3_keys:
        Mapping of broad_role → storage key, as returned by persist_role_stems().
    source_type:
        SOURCE_UPLOADED_STEM or SOURCE_ZIP_STEM.
    source_mode:
        SOURCE_MODE_MULTI_STEM or SOURCE_MODE_ZIP_STEM.
    """
    manifest = CanonicalStemManifest(source_mode=source_mode, loop_id=loop_id)

    # Build a reverse index: broad_role → list of filenames that contributed
    broad_role_to_filenames: dict[str, list[str]] = {}
    for filename, sc in (ingest_result.stem_classifications or {}).items():
        broad_role_to_filenames.setdefault(sc.role, []).append(filename)

    # For each uploaded file, derive the richest canonical role we can
    for filename, stem_classification in (ingest_result.stem_classifications or {}).items():
        broad_role = stem_classification.role  # existing broad classification

        mapper_result = map_filename_to_role(filename, source_type=source_type)

        # Use richer role only when the mapper is reasonably confident
        if mapper_result.confidence >= 0.55:
            canonical_role = mapper_result.canonical_role
            confidence = mapper_result.confidence
            fallback = mapper_result.fallback
            matched_keywords = mapper_result.matched_keywords
        else:
            # Fall back to the existing broad classification
            canonical_role = broad_role
            confidence = stem_classification.confidence
            fallback = True
            matched_keywords = list(stem_classification.matched_keywords)

        actual_broad = CANONICAL_TO_BROAD.get(canonical_role, canonical_role)
        # Resolve the storage key: try canonical broad, then original broad role
        file_key = stem_s3_keys.get(actual_broad) or stem_s3_keys.get(broad_role, "")

        entry = CanonicalStemEntry(
            role=canonical_role,
            broad_role=actual_broad,
            file_key=file_key,
            confidence=confidence,
            source_type=source_type,
            fallback=fallback,
            parent_broad_stem=actual_broad if actual_broad != canonical_role else None,
            original_filename=filename,
        )
        manifest.stems.append(entry)
        logger.debug(
            "Ingestion router [%s]: %s → canonical=%s broad=%s conf=%.2f fallback=%s",
            source_mode,
            filename,
            canonical_role,
            actual_broad,
            confidence,
            fallback,
        )

    # Safety net: ensure every persisted stem key is represented in the manifest,
    # even if the classification step didn't produce a matching entry.
    accounted_keys = {e.file_key for e in manifest.stems if e.file_key}
    for broad_role, file_key in stem_s3_keys.items():
        if file_key not in accounted_keys:
            broad = CANONICAL_TO_BROAD.get(broad_role, broad_role)
            manifest.stems.append(
                CanonicalStemEntry(
                    role=broad_role,
                    broad_role=broad,
                    file_key=file_key,
                    confidence=0.70,
                    source_type=source_type,
                    fallback=True,
                    parent_broad_stem=broad if broad != broad_role else None,
                )
            )
            logger.debug(
                "Ingestion router [%s]: safety-net entry for broad_role=%s key=%s",
                source_mode,
                broad_role,
                file_key,
            )

    return manifest


# ---------------------------------------------------------------------------
# Path A: AI-separated stems → manifest
# ---------------------------------------------------------------------------


def build_manifest_from_ai_separation(
    separated_stems: dict[str, str],
    *,
    loop_id: int,
) -> CanonicalStemManifest:
    """Build a CanonicalStemManifest from AI-separated stems.

    Parameters
    ----------
    separated_stems:
        Mapping of stem_name → storage_key
        (e.g. {"drums": "stems/loop_1_drums.wav", "bass": "stems/loop_1_bass.wav"}).
    loop_id:
        The owning loop ID.
    """
    manifest = CanonicalStemManifest(
        source_mode=SOURCE_MODE_SINGLE_FILE, loop_id=loop_id
    )

    for stem_name, file_key in separated_stems.items():
        mapper_result = map_ai_stem_to_role(stem_name, confidence=0.72)
        entry = CanonicalStemEntry(
            role=mapper_result.canonical_role,
            broad_role=mapper_result.broad_role,
            file_key=file_key,
            confidence=mapper_result.confidence,
            source_type=SOURCE_AI_SEPARATED,
            fallback=mapper_result.fallback,
            parent_broad_stem=mapper_result.parent_broad_stem,
        )
        manifest.stems.append(entry)
        logger.debug(
            "Ingestion router [single_file]: %s → canonical=%s broad=%s conf=%.2f",
            stem_name,
            mapper_result.canonical_role,
            mapper_result.broad_role,
            mapper_result.confidence,
        )

    return manifest
