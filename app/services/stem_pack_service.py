"""Stem pack ingestion, validation, classification, and storage."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
from typing import Iterable
import zipfile

from pydub import AudioSegment

from app.services.stem_role_classifier import STEM_ROLES, classify_stem
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


def _iter_zip_audio_files(stem_zip: bytes) -> Iterable[StemSourceFile]:
    try:
        with zipfile.ZipFile(io.BytesIO(stem_zip)) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                ext = Path(name).suffix.lower()
                if ext not in ALLOWED_AUDIO_EXTENSIONS:
                    continue
                yield StemSourceFile(filename=Path(name).name, content=archive.read(name))
    except zipfile.BadZipFile as exc:
        raise StemPackError("Invalid ZIP stem pack") from exc


def ingest_stem_files(files: list[StemSourceFile]) -> StemPackIngestResult:
    if len(files) < 2:
        raise StemPackError("At least two stem files are required")

    decoded: list[tuple[str, AudioSegment]] = []
    sample_rates: set[int] = set()
    durations: list[int] = []

    for file in files:
        ext = Path(file.filename).suffix.lower()
        if ext not in ALLOWED_AUDIO_EXTENSIONS:
            raise StemPackError(f"Unsupported stem file type: {file.filename}")
        audio = _decode_audio(file.content, file.filename)
        decoded.append((file.filename, audio))
        sample_rates.add(int(audio.frame_rate))
        durations.append(len(audio))

    if len(sample_rates) != 1:
        raise StemPackError("All stems must have the same sample rate")

    min_duration = min(durations)
    max_duration = max(durations)
    if max_duration - min_duration > 120:
        raise StemPackError("All stems must be aligned and the same length")

    role_stems: dict[str, AudioSegment] = {}
    role_sources: dict[str, list[str]] = {}
    for filename, audio in decoded:
        classification = classify_stem(filename, audio)
        role = classification.role if classification.role in STEM_ROLES else "melody"
        trimmed = audio[:min_duration]
        if role in role_stems:
            role_stems[role] = role_stems[role].overlay(trimmed)
        else:
            role_stems[role] = trimmed
        role_sources.setdefault(role, []).append(filename)

    mixed = AudioSegment.silent(duration=min_duration)
    for audio in role_stems.values():
        mixed = mixed.overlay(audio)

    return StemPackIngestResult(
        mixed_preview=mixed,
        role_stems=role_stems,
        role_sources=role_sources,
        sample_rate=next(iter(sample_rates)),
        duration_ms=min_duration,
        source_files=[name for name, _ in decoded],
    )


def ingest_stem_zip(content: bytes) -> StemPackIngestResult:
    files = list(_iter_zip_audio_files(content))
    if not files:
        raise StemPackError("ZIP does not contain supported audio stem files")
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
