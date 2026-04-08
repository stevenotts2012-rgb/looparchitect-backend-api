"""Stem separation service with backend abstraction and safe fallback behavior."""

from __future__ import annotations

import io
import logging
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydub import AudioSegment

from app.config import settings
from app.services.storage import storage

logger = logging.getLogger(__name__)

_MAX_STDERR_LOG_LENGTH = 500


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


def _demucs_stems(audio: AudioSegment, timeout_seconds: float) -> dict[str, AudioSegment]:
    """Run Demucs stem separation via subprocess, returning up to 4 stems.

    Uses the ``htdemucs`` model which produces: drums, bass, vocals, other.
    Raises ``RuntimeError`` on failure and ``subprocess.TimeoutExpired`` on timeout
    so that callers can fall back to the builtin separator.

    Args:
        audio: Source audio to separate.
        timeout_seconds: Maximum wall-clock seconds allowed for the subprocess.

    Returns:
        Dict mapping stem name to ``AudioSegment``.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / "input.wav"
        out_dir = Path(tmpdir) / "out"
        out_dir.mkdir()

        audio.export(str(input_path), format="wav")

        cmd = [
            "python",
            "-m",
            "demucs",
            "--out",
            str(out_dir),
            "-n",
            "htdemucs",
            str(input_path),
        ]

        proc = subprocess.run(
            cmd,
            timeout=timeout_seconds,
            capture_output=True,
            text=True,
        )

        if proc.returncode != 0:
            raise RuntimeError(
                f"Demucs exited with code {proc.returncode}: {proc.stderr[:_MAX_STDERR_LOG_LENGTH]}"
            )

        # htdemucs writes: <out_dir>/htdemucs/<input_stem>/{drums,bass,vocals,other}.wav
        stem_dir = out_dir / "htdemucs" / input_path.stem
        if not stem_dir.exists():
            raise RuntimeError(
                f"Demucs output directory not found at expected path: {stem_dir}"
            )

        stems: dict[str, AudioSegment] = {}
        for stem_name in ("drums", "bass", "vocals", "other"):
            stem_path = stem_dir / f"{stem_name}.wav"
            if stem_path.exists():
                stems[stem_name] = AudioSegment.from_wav(str(stem_path))
            else:
                logger.warning("Demucs output missing expected stem: %s", stem_name)

        if not stems:
            raise RuntimeError("Demucs produced no recognizable output stems")

        return stems


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
        elif backend == "demucs":
            timeout = float(settings.demucs_timeout_seconds)
            try:
                stems = _demucs_stems(source_audio, timeout_seconds=timeout)
                logger.info(
                    "Demucs separation succeeded for loop_id=%s: stems=%s",
                    loop_id,
                    list(stems.keys()),
                )
            except subprocess.TimeoutExpired:
                logger.warning(
                    "Demucs timed out after %.0fs for loop_id=%s; falling back to builtin",
                    timeout,
                    loop_id,
                )
                stems = _builtin_stems(source_audio)
            except Exception as demucs_err:
                logger.warning(
                    "Demucs failed for loop_id=%s (%s); falling back to builtin",
                    loop_id,
                    demucs_err,
                )
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
