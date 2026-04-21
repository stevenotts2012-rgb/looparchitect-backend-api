"""Stem separation service with backend abstraction and safe fallback behavior.

Backend priority (highest-quality first)
-----------------------------------------
1. demucs_htdemucs_6s  — 6-stem Demucs model (drums/bass/vocals/guitar/piano/other)
2. demucs_htdemucs     — 4-stem Demucs model (drums/bass/vocals/other)
3. demucs              — alias for demucs_htdemucs
4. builtin / mock      — frequency-based spectral split (always available, no ML deps)

When a Demucs backend is configured but the ``demucs`` package is not installed,
a ``DemucsUnavailableError`` is raised so callers can fall back gracefully.
The legacy ``separate_and_store_stems`` helper also falls back automatically.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass
from typing import Any

from pydub import AudioSegment

from app.config import settings
from app.services.storage import storage

logger = logging.getLogger(__name__)

# Demucs model names recognised by this service
DEMUCS_MODEL_HTDEMUCS_6S = "htdemucs_6s"
DEMUCS_MODEL_HTDEMUCS = "htdemucs"

# Map of service backend alias → Demucs model name
_DEMUCS_BACKEND_TO_MODEL: dict[str, str] = {
    "demucs_htdemucs_6s": DEMUCS_MODEL_HTDEMUCS_6S,
    "demucs_htdemucs": DEMUCS_MODEL_HTDEMUCS,
    "demucs": DEMUCS_MODEL_HTDEMUCS,
}

# Stem names produced by each Demucs model
DEMUCS_6S_STEMS: tuple[str, ...] = ("drums", "bass", "vocals", "guitar", "piano", "other")
DEMUCS_4S_STEMS: tuple[str, ...] = ("drums", "bass", "vocals", "other")


class DemucsUnavailableError(RuntimeError):
    """Raised when the demucs package is not installed or the model cannot be loaded."""


@dataclass
class StemSeparationResult:
    enabled: bool
    backend: str
    succeeded: bool
    stems_generated: list[str]
    stem_s3_keys: dict[str, str]
    error: str | None = None
    # Provider-system metadata (populated when the multi-provider path is used)
    stem_separator_provider_used: str | None = None
    stem_separator_fallback_used: bool = False
    stem_separator_duration_ms: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "backend": self.backend,
            "succeeded": self.succeeded,
            "stems_generated": self.stems_generated,
            "stem_s3_keys": self.stem_s3_keys,
            "error": self.error,
            "stem_separator_provider_used": self.stem_separator_provider_used,
            "stem_separator_fallback_used": self.stem_separator_fallback_used,
            "stem_separator_duration_ms": self.stem_separator_duration_ms,
        }


def _builtin_stems(audio: AudioSegment) -> dict[str, AudioSegment]:
    """Generate approximate stems using frequency-based splits.

    This is the always-available fallback that requires no ML dependencies.
    Output stem names match the Demucs 4-stem naming convention so downstream
    consumers (advanced_stem_separation, stem_role_mapper) can handle them
    uniformly.
    """
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


def _demucs_stems(
    audio: AudioSegment,
    model_name: str | None = None,
) -> dict[str, AudioSegment]:
    """Separate *audio* using the Demucs ML library.

    Parameters
    ----------
    audio:
        Full mix to separate.
    model_name:
        Demucs model identifier (e.g. ``htdemucs_6s``, ``htdemucs``).
        When *None* (default), the value of the ``DEMUCS_MODEL`` environment
        variable is used (``settings.demucs_model``; default ``"htdemucs"``).

    Returns
    -------
    dict[str, AudioSegment]
        Stem name → separated AudioSegment.

    Raises
    ------
    DemucsUnavailableError
        When the ``demucs`` package is not installed or the model cannot load.
    RuntimeError
        When inference fails for any other reason.

    Notes
    -----
    Full Demucs inference requires the ``demucs`` package (``pip install demucs``)
    and a compatible CPU/GPU environment.  This method is intentionally left as
    a well-typed stub that raises ``DemucsUnavailableError`` when the package is
    absent.  The calling code falls back to ``_builtin_stems`` automatically.
    To enable real Demucs inference, install the package and replace the body of
    this function with the appropriate ``demucs.api`` or ``demucs.apply`` call.
    """
    # Resolve model: explicit argument takes precedence over the env-var default.
    # Explicit None-check (rather than `model_name or …`) preserves any empty-string
    # passthrough in case callers ever need to defer resolution to the demucs library.
    resolved_model = model_name if model_name is not None else settings.demucs_model

    try:
        import demucs  # noqa: F401 — availability check only
    except ImportError as exc:
        raise DemucsUnavailableError(
            f"demucs package is not installed (model={resolved_model!r}). "
            "Install it with: pip install demucs"
        ) from exc

    # ── Real Demucs inference would be implemented here ──────────────────────
    # Example (requires demucs>=4.0):
    #
    #   from demucs.api import Separator
    #   separator = Separator(model=resolved_model)
    #   origin, separated = separator.separate_audio_segment(
    #       audio, timeout=settings.demucs_timeout
    #   )
    #   return {name: seg for name, seg in separated.items()}
    #
    # The stub below raises so that callers fall back to _builtin_stems.
    raise DemucsUnavailableError(
        f"Demucs package found but inference is not configured (model={resolved_model!r}). "
        "Implement the separator call in _demucs_stems() to enable ML-based separation."
    )


def _export_segment_to_wav_bytes(audio: AudioSegment) -> bytes:
    output = io.BytesIO()
    audio.export(output, format="wav")
    return output.getvalue()


def separate_stems_with_fallback(
    audio: AudioSegment,
    preferred_backend: str = "builtin",
) -> tuple[dict[str, AudioSegment], str]:
    """Separate *audio* using the best available backend.

    Tries *preferred_backend* first; falls back through the priority chain
    until a backend succeeds.  Always succeeds — worst case returns
    frequency-based ``_builtin_stems``.

    Parameters
    ----------
    audio:
        Full-mix AudioSegment to separate.
    preferred_backend:
        Backend alias to try first (``demucs_htdemucs_6s``, ``demucs_htdemucs``,
        ``demucs``, ``builtin``).

    Returns
    -------
    (stems_dict, used_backend_name)
        ``stems_dict`` maps stem name → AudioSegment.
        ``used_backend_name`` is the alias of the backend that actually ran.
    """
    norm = preferred_backend.strip().lower()

    # ── Demucs backends ──────────────────────────────────────────────────────
    if norm in _DEMUCS_BACKEND_TO_MODEL:
        model_name = _DEMUCS_BACKEND_TO_MODEL[norm]
        try:
            stems = _demucs_stems(audio, model_name=model_name)
            logger.info("Demucs separation succeeded (backend=%s model=%s)", norm, model_name)
            return stems, norm
        except DemucsUnavailableError as exc:
            logger.info(
                "Demucs unavailable for backend=%s: %s — falling back to builtin",
                norm,
                exc,
            )
        except Exception as exc:
            logger.warning(
                "Demucs separation failed (backend=%s model=%s): %s — falling back to builtin",
                norm,
                model_name,
                exc,
                exc_info=True,
            )

    # ── Builtin frequency-based fallback ─────────────────────────────────────
    stems = _builtin_stems(audio)
    return stems, "builtin"


def _run_separation(
    source_audio: AudioSegment,
    configured_backend: str,
    loop_id: int,
) -> tuple[dict[str, AudioSegment], str, str, bool, int | None]:
    """Execute separation and return (stems, used_backend, provider_name, fallback_used, duration_ms).

    Handles the mock path and the multi-provider path in one place so that
    ``separate_and_store_stems`` only needs to deal with the result.
    """
    from app.services.stem_separation_providers import (
        get_provider,
        separate_with_provider,
    )

    if configured_backend == "mock":
        stems = _builtin_stems(source_audio)
        return stems, "mock", "mock", False, None

    provider = get_provider()
    logger.info(
        "separate_and_store_stems: loop_id=%s provider_requested=%s",
        loop_id,
        provider.name,
    )
    provider_result = separate_with_provider(source_audio, provider=provider)
    if provider_result.fallback_used:
        logger.info(
            "separate_and_store_stems: loop_id=%s fallback_used=True provider_used=%s duration_ms=%s",
            loop_id,
            provider_result.provider_name,
            provider_result.duration_ms,
        )
    else:
        logger.info(
            "separate_and_store_stems: loop_id=%s provider_used=%s duration_ms=%s",
            loop_id,
            provider_result.provider_name,
            provider_result.duration_ms,
        )
    return (
        provider_result.stems,
        provider_result.provider_name,
        provider_result.provider_name,
        provider_result.fallback_used,
        provider_result.duration_ms,
    )


def separate_and_store_stems(
    source_audio: AudioSegment,
    *,
    loop_id: int,
    source_key: str | None = None,
) -> StemSeparationResult:
    """Run stem separation (when enabled) and persist stems to storage.

    Uses the multi-provider system configured via ``STEM_SEPARATOR_PROVIDER``
    and ``AUDIOSHAKE_API_KEY``.  When AudioShake is requested but fails it
    automatically falls back to Demucs.  Demucs itself falls back to the
    builtin frequency-based splitter when the package is unavailable.

    Legacy ``STEM_SEPARATION_BACKEND`` is still honoured for callers that
    bypass the provider system (e.g. mock mode in tests).
    """
    configured_backend = (settings.stem_separation_backend or "builtin").strip().lower()
    enabled = bool(settings.feature_stem_separation)
    if not enabled:
        return StemSeparationResult(
            enabled=False,
            backend=configured_backend,
            succeeded=False,
            stems_generated=[],
            stem_s3_keys={},
            error="feature_disabled",
        )

    try:
        stems, used_backend, provider_name, provider_fallback, provider_duration_ms = (
            _run_separation(source_audio, configured_backend, loop_id)
        )

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
            backend=used_backend,
            succeeded=True,
            stems_generated=list(stem_s3_keys.keys()),
            stem_s3_keys=stem_s3_keys,
            error=None,
            stem_separator_provider_used=provider_name,
            stem_separator_fallback_used=provider_fallback,
            stem_separator_duration_ms=provider_duration_ms,
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
            backend=configured_backend,
            succeeded=False,
            stems_generated=[],
            stem_s3_keys={},
            error=str(e),
        )
