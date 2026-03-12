"""Stem pack ingestion, validation, classification, and storage."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path

from pydub import AudioSegment

from app.services.stem_role_classifier import STEM_ROLES, StemClassification, classify_stem
from app.services.stem_pack_extractor import (
    StemPackExtractionError,
    extract_stem_files_from_zip,
)
from app.services.stem_validation import (
    StemValidationError,
    validate_and_normalize_stems,
)
from app.services.storage import storage


ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac"}


class StemPackError(ValueError):
    pass


@dataclass
class StemSourceFile:
    filename: str
    content: bytes


# Friendly display labels for UI (Phase 7)
_FRIENDLY_LABELS: dict[str, str] = {
    "drums":      "Drums",
    "percussion": "Percussion",
    "bass":       "Bass",
    "melody":     "Melody",
    "vocals":     "Vocals",
    "harmony":    "Harmony",
    "pads":       "Pads",
    "fx":         "FX",
    "accent":     "Accent",
    "full_mix":   "Full Mix",
}


@dataclass
class StemPackIngestResult:
    mixed_preview: AudioSegment
    role_stems: dict[str, AudioSegment]
    role_sources: dict[str, list[str]]
    sample_rate: int
    duration_ms: int
    source_files: list[str]
    alignment: dict
    validation_warnings: list[str]
    fallback_to_loop: bool
    # Per-filename classification details (Phase 5)
    stem_classifications: dict[str, StemClassification] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.stem_classifications is None:
            self.stem_classifications = {}

    @property
    def roles_detected(self) -> list[str]:
        return sorted(self.role_stems.keys())

    def to_metadata(self, *, loop_id: int, stem_s3_keys: dict[str, str], bars: int | None = None) -> dict:
        # Build per-stem classification list for frontend/API consumers
        classifications_list = [
            {
                "filename": fname,
                "role": sc.role,
                "group": sc.group,
                "confidence": sc.confidence,
                "matched_keywords": sc.matched_keywords,
                "sources_used": sc.sources_used,
                "uncertain": sc.uncertain,
                "friendly_label": _FRIENDLY_LABELS.get(sc.role, sc.role.replace("_", " ").title()),
            }
            for fname, sc in (self.stem_classifications or {}).items()
        ]

        # Unique arrangement groups detected (sorted for determinism)
        groups_detected = sorted({
            sc.group
            for sc in (self.stem_classifications or {}).values()
        })

        # Friendly labels for display (Phase 7)
        friendly_labels = sorted({
            _FRIENDLY_LABELS.get(role, role.replace("_", " ").title())
            for role in self.roles_detected
        })

        return {
            "enabled": True,
            "backend": "uploaded_pack",
            "succeeded": not self.fallback_to_loop,
            "upload_mode": "stem_pack",
            "roles_detected": self.roles_detected,
            "stems_generated": self.roles_detected,
            "stem_s3_keys": stem_s3_keys,
            "source_files": self.source_files,
            "role_sources": self.role_sources,
            "sample_rate": self.sample_rate,
            "duration_ms": self.duration_ms,
            "loop_id": loop_id,
            "bars_validated": bars,
            "alignment": self.alignment,
            "warnings": self.validation_warnings,
            "fallback_to_loop": self.fallback_to_loop,
            # Phase 5: rich classification metadata
            "stem_classifications": classifications_list,
            "arrangement_groups_detected": groups_detected,
            "friendly_labels": friendly_labels,
            "validation": {
                "aligned": not self.fallback_to_loop,
                "same_length": True,
                "same_sample_rate": True,
                "normalized": True,
                "bars_range": "4-16",
                "confidence": self.alignment.get("confidence"),
                "low_confidence": self.alignment.get("low_confidence", False),
            },
        }


def _decode_audio(content: bytes, filename: str) -> AudioSegment:
    ext = Path(filename).suffix.lower().lstrip(".")
    try:
        if ext == "wav":
            return AudioSegment.from_wav(io.BytesIO(content))
        return AudioSegment.from_file(io.BytesIO(content), format=ext or None)
    except Exception as exc:
        raise StemPackError(f"Could not decode stem '{filename}': {exc}") from exc


def ingest_stem_files(files: list[StemSourceFile]) -> StemPackIngestResult:
    if len(files) < 2:
        raise StemPackError("At least two stem files are required")

    decoded: list[tuple[str, AudioSegment]] = []

    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise StemPackError(f"Unsupported stem file type: {file.filename}")
        audio = _decode_audio(file.content, file.filename)
        decoded.append((file.filename, audio))

    try:
        validated = validate_and_normalize_stems(decoded)
    except StemValidationError as exc:
        raise StemPackError(str(exc)) from exc

    role_stems: dict[str, AudioSegment] = {}
    role_sources: dict[str, list[str]] = {}
    stem_classifications: dict[str, StemClassification] = {}
    for filename, audio in validated.stems:
        classification = classify_stem(filename, audio)
        role = classification.role if classification.role in STEM_ROLES else "full_mix"
        trimmed = audio[:validated.duration_ms]
        if role in role_stems:
            role_stems[role] = role_stems[role].overlay(trimmed)
        else:
            role_stems[role] = trimmed
        role_sources.setdefault(role, []).append(filename)
        stem_classifications[filename] = classification

    mixed = AudioSegment.silent(duration=validated.duration_ms)
    for audio in role_stems.values():
        mixed = mixed.overlay(audio)

    return StemPackIngestResult(
        mixed_preview=mixed,
        role_stems=role_stems,
        role_sources=role_sources,
        sample_rate=validated.sample_rate,
        duration_ms=validated.duration_ms,
        source_files=[name for name, _ in decoded],
        alignment=validated.alignment_metadata,
        validation_warnings=list(validated.warnings),
        fallback_to_loop=bool(validated.fallback_to_loop),
        stem_classifications=stem_classifications,
    )


def ingest_stem_zip(content: bytes) -> StemPackIngestResult:
    try:
        extracted = extract_stem_files_from_zip(content)
    except StemPackExtractionError as exc:
        raise StemPackError(str(exc)) from exc
    files = [StemSourceFile(filename=item.filename, content=item.content) for item in extracted]
    return ingest_stem_files(files)


def persist_role_stems(loop_id: int, role_stems: dict[str, AudioSegment]) -> dict[str, str]:
    stem_keys: dict[str, str] = {}
    for role, audio in role_stems.items():
        key = f"stems/loop_{loop_id}_{role}.wav"
        output = io.BytesIO()
        audio.export(output, format="wav")
        storage.upload_file(file_bytes=output.getvalue(), content_type="audio/wav", key=key)
        stem_keys[role] = key
    return stem_keys
