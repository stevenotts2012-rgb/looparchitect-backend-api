"""Stem separation service with backend abstraction and safe fallback behavior."""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

from pydub import AudioSegment

from app.config import settings
from app.services.storage import storage

logger = logging.getLogger(__name__)


@dataclass
class StemSeparationResult:
    enabled: bool
    backend: str
    succeeded: bool
    stems_generated: list[str]
    stem_s3_keys: dict[str, str]
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "succeeded": self.succeeded,
            "stems_generated": self.stems_generated,
            "stem_s3_keys": self.stem_s3_keys,
            "error": self.error,
        }


def _builtin_stems(audio: AudioSegment) -> dict[str, AudioSegment]:
    """Generate approximate stems using frequency-based splits."""
    bass = audio.low_pass_filter(180)
    vocals = audio.high_pass_filter(200).low_pass_filter(3500)
    drums = audio.high_pass_filter(60).low_pass_filter(9000)
    other = audio.high_pass_filter(3500)

    return {
        "bass": bass,
        "drums": drums,
        "vocals": vocals,
        "other": other,
    }


def _export_segment_to_wav_bytes(audio: AudioSegment) -> bytes:
    output = io.BytesIO()
    audio.export(output, format="wav")
    return output.getvalue()


def separate_and_store_stems(
    source_audio: AudioSegment,
    *,
    loop_id: int,
    source_key: str | None = None,
) -> StemSeparationResult:
    """Run stem separation (when enabled) and persist stems to storage."""
    backend = (settings.stem_separation_backend or "builtin").strip().lower()
    enabled = bool(settings.feature_stem_separation)
    if not enabled:
        return StemSeparationResult(
            enabled=False,
            backend=backend,
            succeeded=False,
            stems_generated=[],
            stem_s3_keys={},
            error="feature_disabled",
        )

    try:
        if backend in {"builtin", "mock"}:
            stems = _builtin_stems(source_audio)
        else:
            raise ValueError(f"Unsupported stem backend: {backend}")

        stem_s3_keys: dict[str, str] = {}
        for stem_name, stem_audio in stems.items():
            stem_key = f"stems/loop_{loop_id}_{stem_name}.wav"
            stem_bytes = _export_segment_to_wav_bytes(stem_audio)
            storage.upload_file(
                file_bytes=stem_bytes,
                content_type="audio/wav",
                key=stem_key,
            )
            stem_s3_keys[stem_name] = stem_key

        return StemSeparationResult(
            enabled=True,
            backend=backend,
            succeeded=True,
            stems_generated=list(stem_s3_keys.keys()),
            stem_s3_keys=stem_s3_keys,
            error=None,
        )
    except Exception as e:
        logger.warning(
            "Stem separation failed for loop_id=%s source_key=%s: %s",
            loop_id,
            source_key,
            e,
            exc_info=True,
        )
        return StemSeparationResult(
            enabled=True,
            backend=backend,
            succeeded=False,
            stems_generated=[],
            stem_s3_keys={},
            error=str(e),
        )
