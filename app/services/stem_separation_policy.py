"""Stem Separation Policy / Router.

This module provides a deterministic routing layer that decides:
- which separation provider to use (AudioShake / Demucs / builtin)
- which Demucs model to use (htdemucs / htdemucs_ft / htdemucs_6s)
- what timeout to apply
- why each decision was made (policy_reason)
- what fallback path to follow

Source Complexity Classification
---------------------------------
``classify_source_complexity()`` analyses available audio metadata and
returns a ``SourceComplexityClass``:

    simple_loop      — short file, single channel or low sample rate, low RMS
    moderate_mix     — typical stereo loop, single file upload
    dense_mix        — long duration, high sample rate, wide stereo
    stem_rich_request — caller explicitly requests ≥ 5 stems or 6s model

Auto-Selection Rules
---------------------
STEM_SEPARATOR_PROVIDER=audioshake AND AUDIOSHAKE_API_KEY AND preference=quality:
    → AudioShake (primary); Demucs on failure

STEM_SEPARATOR_PROVIDER=audioshake AND AUDIOSHAKE_API_KEY AND preference≠quality:
    → AudioShake (still explicit; preference affects Demucs fallback model)

STEM_SEPARATOR_PROVIDER=auto OR preference set:
    quality + API available  → AudioShake  (policy_reason="quality_api")
    quality + no API         → htdemucs_ft  (policy_reason="quality_no_api")
    balanced                 → htdemucs     (policy_reason="balanced")
    speed                    → htdemucs     (policy_reason="speed")
    dense_mix + max_complexity_mode → htdemucs_6s  (policy_reason="dense_6s")
    stem_rich_request + max_complexity_mode → htdemucs_6s (policy_reason="rich_6s")

Demucs model selection sub-rules (when provider is demucs):
    DEMUCS_MODEL != "auto"   → use configured model verbatim
    DEMUCS_MODEL == "auto"   → apply preference/complexity rules above

Fallback chain (documented; execution handled in stem_separation_providers.py):
    AudioShake failure → htdemucs (or htdemucs_ft / htdemucs_6s per policy)
    htdemucs_ft failure → htdemucs
    htdemucs_6s failure → htdemucs
    htdemucs failure    → builtin (frequency-based)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEMUCS_MODEL_HTDEMUCS = "htdemucs"
DEMUCS_MODEL_HTDEMUCS_FT = "htdemucs_ft"
DEMUCS_MODEL_HTDEMUCS_6S = "htdemucs_6s"

# Models that produce 6 stems (use STEM_NAMES_6 downstream)
DEMUCS_6S_MODELS: frozenset[str] = frozenset({DEMUCS_MODEL_HTDEMUCS_6S})

# Minimum duration (seconds) to classify a source as potentially dense
_DENSE_DURATION_THRESHOLD_S = 60.0

# Minimum sample rate (Hz) to nudge toward richer separation
_HIGH_SAMPLE_RATE_THRESHOLD = 44_100


# ---------------------------------------------------------------------------
# Source Complexity Classification
# ---------------------------------------------------------------------------

class SourceComplexityClass(str, Enum):
    """Deterministic complexity bucket assigned to a source file.

    Used by the policy layer to decide which Demucs model is most appropriate.
    """

    SIMPLE_LOOP = "simple_loop"
    MODERATE_MIX = "moderate_mix"
    DENSE_MIX = "dense_mix"
    STEM_RICH_REQUEST = "stem_rich_request"


def classify_source_complexity(
    *,
    duration_seconds: float | None = None,
    channels: int | None = None,
    sample_rate: int | None = None,
    requested_stem_count: int | None = None,
    is_stem_zip: bool = False,
    is_true_stems: bool = False,
    rms_db: float | None = None,
) -> SourceComplexityClass:
    """Classify the complexity of a source file based on available metadata.

    All parameters are optional.  Missing values are treated conservatively
    (as if they indicate a simple source).

    Parameters
    ----------
    duration_seconds:
        Total audio duration.  Long files suggest richer content.
    channels:
        Number of audio channels (1 = mono, 2 = stereo, …).
    sample_rate:
        Sample rate in Hz (e.g. 44100, 48000).
    requested_stem_count:
        How many stems the caller wants (≥ 5 implies 6s model territory).
    is_stem_zip:
        True when the upload was a ZIP of pre-separated stems.
    is_true_stems:
        True when the user uploaded individual stem files directly.
    rms_db:
        Root-mean-square level in dBFS (negative; louder ≈ denser mix).
        A value close to 0 dBFS may indicate a loud / compressed dense mix.

    Returns
    -------
    SourceComplexityClass
    """
    # Explicit stem-rich request (caller wants ≥5 stems)
    if requested_stem_count is not None and requested_stem_count >= 5:
        logger.debug(
            "classify_source_complexity: stem_rich_request (requested_stem_count=%d)",
            requested_stem_count,
        )
        return SourceComplexityClass.STEM_RICH_REQUEST

    # True stems or ZIP stems: content is already split — classify as moderate
    # (we do not need to push toward htdemucs_6s for already-separated sources)
    if is_true_stems or is_stem_zip:
        logger.debug(
            "classify_source_complexity: moderate_mix (pre-separated stems)"
        )
        return SourceComplexityClass.MODERATE_MIX

    # Dense mix heuristics
    dense_signals: int = 0

    if duration_seconds is not None and duration_seconds >= _DENSE_DURATION_THRESHOLD_S:
        dense_signals += 1

    if channels is not None and channels >= 2:
        dense_signals += 1

    if sample_rate is not None and sample_rate >= _HIGH_SAMPLE_RATE_THRESHOLD:
        dense_signals += 1

    # Loud mix (rms close to 0 dBFS, e.g. > -12) suggests a dense production
    if rms_db is not None and rms_db > -12.0:
        dense_signals += 1

    if dense_signals >= 3:
        logger.debug(
            "classify_source_complexity: dense_mix (dense_signals=%d)", dense_signals
        )
        return SourceComplexityClass.DENSE_MIX

    if dense_signals >= 1:
        logger.debug(
            "classify_source_complexity: moderate_mix (dense_signals=%d)", dense_signals
        )
        return SourceComplexityClass.MODERATE_MIX

    logger.debug("classify_source_complexity: simple_loop")
    return SourceComplexityClass.SIMPLE_LOOP


# ---------------------------------------------------------------------------
# Separation Policy
# ---------------------------------------------------------------------------

@dataclass
class SeparationPolicy:
    """Output of the policy router.

    Describes which provider and model to use for a separation run.
    """

    provider: str
    """Primary provider to use: ``"audioshake"`` | ``"demucs"``."""

    model: str
    """Demucs model (ignored when provider is not demucs): e.g. ``"htdemucs"``."""

    timeout: int
    """Maximum seconds to wait for the separation call."""

    policy_reason: str
    """Human-readable explanation of why this policy was chosen."""

    complexity_class: SourceComplexityClass
    """Complexity bucket inferred from source metadata."""

    fallback_model: str = DEMUCS_MODEL_HTDEMUCS
    """Demucs model to fall back to when the primary model fails."""

    metadata: dict[str, Any] = field(default_factory=dict)
    """Additional key/value pairs for observability logging."""


def select_policy(
    *,
    source_metadata: dict[str, Any] | None = None,
) -> SeparationPolicy:
    """Select the best separation policy based on environment configuration
    and source metadata.

    Parameters
    ----------
    source_metadata:
        Optional dict with keys matching the parameters of
        :func:`classify_source_complexity` (``duration_seconds``,
        ``channels``, ``sample_rate``, ``requested_stem_count``,
        ``is_stem_zip``, ``is_true_stems``, ``rms_db``).

    Returns
    -------
    SeparationPolicy
        The resolved policy (provider, model, timeout, reason, etc.).
    """
    from app.config import settings

    provider_cfg = (settings.stem_separator_provider or "demucs").strip().lower()
    preference = (settings.stem_separator_preference or "balanced").strip().lower()
    max_complexity = settings.stem_separator_max_complexity_mode
    demucs_model_cfg = (settings.demucs_model or "htdemucs").strip().lower()
    timeout = int(getattr(settings, "demucs_timeout", 300))
    api_key = (settings.audioshake_api_key or "").strip()

    # Classify source complexity
    meta = source_metadata or {}
    complexity = classify_source_complexity(
        duration_seconds=meta.get("duration_seconds"),
        channels=meta.get("channels"),
        sample_rate=meta.get("sample_rate"),
        requested_stem_count=meta.get("requested_stem_count"),
        is_stem_zip=meta.get("is_stem_zip", False),
        is_true_stems=meta.get("is_true_stems", False),
        rms_db=meta.get("rms_db"),
    )

    logger.info(
        "select_policy: provider_cfg=%s preference=%s max_complexity=%s "
        "demucs_model_cfg=%s complexity=%s",
        provider_cfg,
        preference,
        max_complexity,
        demucs_model_cfg,
        complexity.value,
    )

    # ------------------------------------------------------------------
    # Explicit AudioShake path
    # ------------------------------------------------------------------
    if provider_cfg == "audioshake":
        if api_key:
            reason = f"explicit_audioshake_preference={preference}"
            logger.info("select_policy: AudioShake selected (%s)", reason)
            return SeparationPolicy(
                provider="audioshake",
                model=DEMUCS_MODEL_HTDEMUCS,  # fallback model
                timeout=timeout,
                policy_reason=reason,
                complexity_class=complexity,
                fallback_model=_fallback_demucs_model(preference, complexity, max_complexity),
            )
        # API key missing → warn and fall through to demucs
        logger.warning(
            "select_policy: STEM_SEPARATOR_PROVIDER=audioshake but AUDIOSHAKE_API_KEY "
            "is not set — falling back to Demucs policy"
        )

    # ------------------------------------------------------------------
    # Auto or demucs path
    # ------------------------------------------------------------------

    # Step 1: quality preference with AudioShake available
    if preference == "quality" and api_key:
        reason = "quality_api"
        logger.info("select_policy: AudioShake selected (%s)", reason)
        return SeparationPolicy(
            provider="audioshake",
            model=DEMUCS_MODEL_HTDEMUCS,
            timeout=timeout,
            policy_reason=reason,
            complexity_class=complexity,
            fallback_model=_fallback_demucs_model(preference, complexity, max_complexity),
        )

    # Step 2: Demucs model selection
    chosen_model = _choose_demucs_model(
        preference=preference,
        complexity=complexity,
        max_complexity=max_complexity,
        demucs_model_cfg=demucs_model_cfg,
    )
    reason = _build_demucs_reason(preference, complexity, max_complexity, demucs_model_cfg, chosen_model)

    logger.info("select_policy: Demucs selected model=%s reason=%s", chosen_model, reason)
    return SeparationPolicy(
        provider="demucs",
        model=chosen_model,
        timeout=timeout,
        policy_reason=reason,
        complexity_class=complexity,
        fallback_model=DEMUCS_MODEL_HTDEMUCS,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _choose_demucs_model(
    *,
    preference: str,
    complexity: SourceComplexityClass,
    max_complexity: bool,
    demucs_model_cfg: str,
) -> str:
    """Return the Demucs model name to use.

    When ``DEMUCS_MODEL`` is set to a concrete model (not ``"auto"``), that
    value is used verbatim.  When it is ``"auto"`` (or when ``auto``-selection
    is triggered by ``STEM_SEPARATOR_PROVIDER=auto``), the preference and
    complexity rules apply.
    """
    if demucs_model_cfg and demucs_model_cfg != "auto":
        # Explicit model: honour it regardless of preference/complexity
        return demucs_model_cfg

    # Auto-model selection rules
    if preference == "quality":
        # Highest-quality Demucs model (fine-tuned)
        return DEMUCS_MODEL_HTDEMUCS_FT

    if preference == "speed":
        # Avoid heavier models
        return DEMUCS_MODEL_HTDEMUCS

    # balanced (default)
    if max_complexity:
        if complexity in (
            SourceComplexityClass.DENSE_MIX,
            SourceComplexityClass.STEM_RICH_REQUEST,
        ):
            # 6-stem split for rich / dense sources when explicitly enabled
            return DEMUCS_MODEL_HTDEMUCS_6S

    return DEMUCS_MODEL_HTDEMUCS


def _fallback_demucs_model(
    preference: str,
    complexity: SourceComplexityClass,
    max_complexity: bool,
) -> str:
    """Return the Demucs model to fall back to when AudioShake is the primary."""
    return _choose_demucs_model(
        preference=preference,
        complexity=complexity,
        max_complexity=max_complexity,
        demucs_model_cfg="auto",
    )


def _build_demucs_reason(
    preference: str,
    complexity: SourceComplexityClass,
    max_complexity: bool,
    demucs_model_cfg: str,
    chosen_model: str,
) -> str:
    if demucs_model_cfg and demucs_model_cfg != "auto":
        return f"explicit_model_{demucs_model_cfg}"
    if preference == "quality":
        return "quality_no_api"
    if preference == "speed":
        return "speed"
    if chosen_model == DEMUCS_MODEL_HTDEMUCS_6S:
        return f"dense_6s" if complexity == SourceComplexityClass.DENSE_MIX else "rich_6s"
    return "balanced"
