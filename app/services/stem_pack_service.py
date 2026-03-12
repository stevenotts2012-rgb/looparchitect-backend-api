"""Stem pack ingestion, validation, classification, and storage."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path

from pydub import AudioSegment

from app.services.stem_role_classifier import STEM_ROLES, classify_stem
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


@dataclass
class StemPackIngestResult:
    mixed_preview: AudioSegment
    role_stems: dict[str, AudioSegment]
    role_sources: dict[str, list[str]]
    sample_rate: int
    duration_ms: int
    source_files: list[str]

    @property
    def roles_detected(self) -> list[str]:
        return sorted(self.role_stems.keys())

    def to_metadata(self, *, loop_id: int, stem_s3_keys: dict[str, str], bars: int | None = None) -> dict:
        return {
            "enabled": True,
            "backend": "uploaded_pack",
            "succeeded": True,
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
            "validation": {
                "aligned": True,
                "same_length": True,
                "same_sample_rate": True,
                "normalized": True,
                "bars_range": "4-16",
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
    for filename, audio in validated.stems:
        classification = classify_stem(filename, audio)
        role = classification.role if classification.role in STEM_ROLES else "melody"
        trimmed = audio[:validated.duration_ms]
        if role in role_stems:
            role_stems[role] = role_stems[role].overlay(trimmed)
        else:
            role_stems[role] = trimmed
        role_sources.setdefault(role, []).append(filename)

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
