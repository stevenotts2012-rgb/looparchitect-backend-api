"""Tests for stem_separation_policy — complexity classifier and routing layer.

Coverage
--------
* SourceComplexityClass classification via classify_source_complexity()
* select_policy() auto-selection rules
* quality / balanced / speed preference decisions
* AudioShake selection (with/without API key)
* htdemucs_ft routing (quality, no API key)
* htdemucs_6s routing (dense/rich + max_complexity_mode)
* htdemucs as safe fallback
* Explicit DEMUCS_MODEL passthrough
* fallback_model propagation for AudioShake path
* Observability fields in ProviderResult (policy_reason, complexity_class, model_used, etc.)
* StemSeparationResult extended observability fields
* Regression: no breakage to existing upload/separation flow
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from app.services.stem_separation_policy import (
    DEMUCS_MODEL_HTDEMUCS,
    DEMUCS_MODEL_HTDEMUCS_FT,
    DEMUCS_MODEL_HTDEMUCS_6S,
    SourceComplexityClass,
    classify_source_complexity,
    select_policy,
)
from app.services.stem_separation_providers import (
    AudioShakeProvider,
    DemucsProvider,
    ProviderResult,
    get_provider,
    separate_with_provider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent(duration_ms: int = 2000) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms)


def _make_stems(names=("drums", "bass", "vocals", "other")):
    return {n: _silent() for n in names}


def _settings(
    provider="demucs",
    preference="balanced",
    max_complexity=False,
    demucs_model="htdemucs",
    demucs_timeout=300,
    api_key="",
):
    m = MagicMock()
    m.stem_separator_provider = provider
    m.stem_separator_preference = preference
    m.stem_separator_max_complexity_mode = max_complexity
    m.demucs_model = demucs_model
    m.demucs_timeout = demucs_timeout
    m.audioshake_api_key = api_key
    return m


# ---------------------------------------------------------------------------
# SourceComplexityClass — classify_source_complexity
# ---------------------------------------------------------------------------

class TestClassifySourceComplexity:
    def test_no_metadata_returns_simple_loop(self):
        cls = classify_source_complexity()
        assert cls == SourceComplexityClass.SIMPLE_LOOP

    def test_stem_rich_request_by_count(self):
        cls = classify_source_complexity(requested_stem_count=5)
        assert cls == SourceComplexityClass.STEM_RICH_REQUEST

    def test_stem_rich_request_by_count_6(self):
        cls = classify_source_complexity(requested_stem_count=6)
        assert cls == SourceComplexityClass.STEM_RICH_REQUEST

    def test_four_stems_not_rich(self):
        cls = classify_source_complexity(requested_stem_count=4)
        assert cls != SourceComplexityClass.STEM_RICH_REQUEST

    def test_true_stems_returns_moderate(self):
        cls = classify_source_complexity(is_true_stems=True)
        assert cls == SourceComplexityClass.MODERATE_MIX

    def test_zip_stems_returns_moderate(self):
        cls = classify_source_complexity(is_stem_zip=True)
        assert cls == SourceComplexityClass.MODERATE_MIX

    def test_dense_mix_three_signals(self):
        # duration + channels + sample_rate → 3 dense signals → DENSE_MIX
        cls = classify_source_complexity(
            duration_seconds=90.0,
            channels=2,
            sample_rate=48000,
        )
        assert cls == SourceComplexityClass.DENSE_MIX

    def test_dense_mix_four_signals_with_rms(self):
        cls = classify_source_complexity(
            duration_seconds=90.0,
            channels=2,
            sample_rate=48000,
            rms_db=-6.0,
        )
        assert cls == SourceComplexityClass.DENSE_MIX

    def test_moderate_mix_one_signal(self):
        cls = classify_source_complexity(channels=2)
        assert cls == SourceComplexityClass.MODERATE_MIX

    def test_simple_loop_short_mono_low_rate(self):
        cls = classify_source_complexity(
            duration_seconds=10.0,
            channels=1,
            sample_rate=22050,
        )
        assert cls == SourceComplexityClass.SIMPLE_LOOP

    def test_stem_rich_request_wins_over_is_true_stems(self):
        # requested_stem_count ≥ 5 takes priority
        cls = classify_source_complexity(
            requested_stem_count=5,
            is_true_stems=True,
        )
        assert cls == SourceComplexityClass.STEM_RICH_REQUEST

    def test_moderate_mix_two_signals(self):
        cls = classify_source_complexity(channels=2, sample_rate=44100)
        assert cls == SourceComplexityClass.MODERATE_MIX

    def test_loud_rms_alone_gives_moderate(self):
        cls = classify_source_complexity(rms_db=-8.0)
        assert cls == SourceComplexityClass.MODERATE_MIX

    def test_quiet_rms_with_other_dense_signals(self):
        # rms_db below threshold: only duration + channels + sample_rate
        cls = classify_source_complexity(
            duration_seconds=90.0,
            channels=2,
            sample_rate=48000,
            rms_db=-20.0,
        )
        # 3 signals still qualifies as DENSE_MIX
        assert cls == SourceComplexityClass.DENSE_MIX


# ---------------------------------------------------------------------------
# select_policy — auto-selection rules
# ---------------------------------------------------------------------------

class TestSelectPolicy:
    # ------------------------------------------------------------------
    # Balanced (default)
    # ------------------------------------------------------------------

    def test_balanced_no_api_key_returns_demucs_htdemucs(self):
        with patch("app.config.settings", _settings(provider="demucs", preference="balanced", demucs_model="auto")):
            policy = select_policy()
        assert policy.provider == "demucs"
        assert policy.model == DEMUCS_MODEL_HTDEMUCS
        assert policy.policy_reason == "balanced"

    def test_auto_provider_balanced_returns_demucs_htdemucs(self):
        with patch("app.config.settings", _settings(provider="auto", preference="balanced", demucs_model="auto")):
            policy = select_policy()
        assert policy.provider == "demucs"
        assert policy.model == DEMUCS_MODEL_HTDEMUCS
        assert policy.policy_reason == "balanced"

    # ------------------------------------------------------------------
    # Quality
    # ------------------------------------------------------------------

    def test_quality_with_api_key_returns_audioshake(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="quality", api_key="sk-key", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.provider == "audioshake"
        assert policy.policy_reason == "quality_api"

    def test_quality_no_api_key_returns_htdemucs_ft(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="quality", api_key="", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.provider == "demucs"
        assert policy.model == DEMUCS_MODEL_HTDEMUCS_FT
        assert policy.policy_reason == "quality_no_api"

    def test_demucs_provider_quality_returns_htdemucs_ft(self):
        with patch("app.config.settings", _settings(
            provider="demucs", preference="quality", api_key="", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.provider == "demucs"
        assert policy.model == DEMUCS_MODEL_HTDEMUCS_FT

    # ------------------------------------------------------------------
    # Speed
    # ------------------------------------------------------------------

    def test_speed_preference_returns_htdemucs(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="speed", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.provider == "demucs"
        assert policy.model == DEMUCS_MODEL_HTDEMUCS
        assert policy.policy_reason == "speed"

    def test_speed_with_api_key_still_uses_demucs(self):
        # speed overrides quality preference — no AudioShake
        with patch("app.config.settings", _settings(
            provider="auto", preference="speed", api_key="sk-key", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.provider == "demucs"
        assert policy.model == DEMUCS_MODEL_HTDEMUCS

    # ------------------------------------------------------------------
    # htdemucs_6s routing
    # ------------------------------------------------------------------

    def test_dense_mix_max_complexity_returns_6s(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="balanced", max_complexity=True, demucs_model="auto"
        )):
            policy = select_policy(
                source_metadata={"duration_seconds": 90.0, "channels": 2, "sample_rate": 48000}
            )
        assert policy.model == DEMUCS_MODEL_HTDEMUCS_6S
        assert "6s" in policy.policy_reason

    def test_stem_rich_request_max_complexity_returns_6s(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="balanced", max_complexity=True, demucs_model="auto"
        )):
            policy = select_policy(source_metadata={"requested_stem_count": 6})
        assert policy.model == DEMUCS_MODEL_HTDEMUCS_6S
        assert "6s" in policy.policy_reason

    def test_dense_mix_without_max_complexity_stays_htdemucs(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="balanced", max_complexity=False, demucs_model="auto"
        )):
            policy = select_policy(
                source_metadata={"duration_seconds": 90.0, "channels": 2, "sample_rate": 48000}
            )
        assert policy.model == DEMUCS_MODEL_HTDEMUCS

    def test_speed_with_dense_mix_max_complexity_avoids_6s(self):
        # speed preference blocks 6s even with max_complexity enabled
        with patch("app.config.settings", _settings(
            provider="auto", preference="speed", max_complexity=True, demucs_model="auto"
        )):
            policy = select_policy(
                source_metadata={"duration_seconds": 90.0, "channels": 2, "sample_rate": 48000}
            )
        assert policy.model == DEMUCS_MODEL_HTDEMUCS

    # ------------------------------------------------------------------
    # Explicit AudioShake
    # ------------------------------------------------------------------

    def test_explicit_audioshake_with_key(self):
        with patch("app.config.settings", _settings(
            provider="audioshake", preference="balanced", api_key="sk-key"
        )):
            policy = select_policy()
        assert policy.provider == "audioshake"
        assert "audioshake" in policy.policy_reason

    def test_explicit_audioshake_missing_key_falls_back_to_demucs(self):
        with patch("app.config.settings", _settings(
            provider="audioshake", preference="balanced", api_key="", demucs_model="htdemucs"
        )):
            policy = select_policy()
        # Falls through to demucs policy
        assert policy.provider == "demucs"

    # ------------------------------------------------------------------
    # Explicit DEMUCS_MODEL passthrough
    # ------------------------------------------------------------------

    def test_explicit_demucs_model_htdemucs_ft(self):
        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="htdemucs_ft"
        )):
            policy = select_policy()
        assert policy.model == DEMUCS_MODEL_HTDEMUCS_FT
        assert "htdemucs_ft" in policy.policy_reason

    def test_explicit_demucs_model_htdemucs_6s(self):
        with patch("app.config.settings", _settings(
            provider="demucs", preference="speed", demucs_model="htdemucs_6s"
        )):
            policy = select_policy()
        # Explicit model wins even over speed preference
        assert policy.model == DEMUCS_MODEL_HTDEMUCS_6S

    def test_explicit_demucs_model_htdemucs(self):
        with patch("app.config.settings", _settings(
            provider="demucs", preference="quality", demucs_model="htdemucs"
        )):
            policy = select_policy()
        # Explicit htdemucs wins over quality preference
        assert policy.model == DEMUCS_MODEL_HTDEMUCS

    # ------------------------------------------------------------------
    # Timeout propagation
    # ------------------------------------------------------------------

    def test_timeout_from_settings(self):
        s = _settings(provider="demucs", demucs_timeout=600)
        with patch("app.config.settings", s):
            policy = select_policy()
        assert policy.timeout == 600

    # ------------------------------------------------------------------
    # Complexity class in policy
    # ------------------------------------------------------------------

    def test_policy_has_complexity_class(self):
        with patch("app.config.settings", _settings(provider="demucs", preference="balanced")):
            policy = select_policy()
        assert isinstance(policy.complexity_class, SourceComplexityClass)

    def test_policy_complexity_class_propagated_for_dense(self):
        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="auto"
        )):
            policy = select_policy(
                source_metadata={"duration_seconds": 90.0, "channels": 2, "sample_rate": 48000}
            )
        assert policy.complexity_class == SourceComplexityClass.DENSE_MIX

    # ------------------------------------------------------------------
    # Fallback model propagation for AudioShake
    # ------------------------------------------------------------------

    def test_audioshake_policy_fallback_model_quality_no_api(self):
        # When AudioShake is primary but fails, fallback model should be htdemucs_ft for quality
        with patch("app.config.settings", _settings(
            provider="audioshake", preference="quality", api_key="sk-key", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.provider == "audioshake"
        assert policy.fallback_model == DEMUCS_MODEL_HTDEMUCS_FT

    def test_audioshake_policy_fallback_model_balanced(self):
        with patch("app.config.settings", _settings(
            provider="audioshake", preference="balanced", api_key="sk-key", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.fallback_model == DEMUCS_MODEL_HTDEMUCS

    def test_audioshake_quality_api_fallback_model_is_ft(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="quality", api_key="sk-key", demucs_model="auto"
        )):
            policy = select_policy()
        assert policy.provider == "audioshake"
        assert policy.fallback_model == DEMUCS_MODEL_HTDEMUCS_FT


# ---------------------------------------------------------------------------
# get_provider — wired to policy layer
# ---------------------------------------------------------------------------

class TestGetProviderWithPolicy:
    def test_auto_balanced_returns_demucs(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="balanced", demucs_model="auto"
        )):
            provider = get_provider()
        assert isinstance(provider, DemucsProvider)

    def test_auto_quality_with_api_key_returns_audioshake(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="quality", api_key="sk-key", demucs_model="auto"
        )):
            provider = get_provider()
        assert isinstance(provider, AudioShakeProvider)

    def test_auto_quality_no_api_returns_demucs(self):
        with patch("app.config.settings", _settings(
            provider="auto", preference="quality", api_key="", demucs_model="auto"
        )):
            provider = get_provider()
        assert isinstance(provider, DemucsProvider)

    def test_demucs_explicit_model_is_passed_to_provider(self):
        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="htdemucs_6s"
        )):
            provider = get_provider()
        assert isinstance(provider, DemucsProvider)
        assert provider._model == DEMUCS_MODEL_HTDEMUCS_6S

    def test_demucs_quality_preference_auto_model_is_ft(self):
        with patch("app.config.settings", _settings(
            provider="demucs", preference="quality", demucs_model="auto"
        )):
            provider = get_provider()
        assert isinstance(provider, DemucsProvider)
        assert provider._model == DEMUCS_MODEL_HTDEMUCS_FT


# ---------------------------------------------------------------------------
# separate_with_provider — observability fields
# ---------------------------------------------------------------------------

class TestSeparateWithProviderObservability:
    def test_result_has_policy_reason(self):
        audio = _silent()
        mock_provider = MagicMock(spec=DemucsProvider)
        mock_provider.name = "demucs"
        mock_provider.separate.return_value = _make_stems()

        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="htdemucs"
        )):
            result = separate_with_provider(audio, provider=mock_provider)

        assert result.policy_reason is not None
        assert result.complexity_class is not None

    def test_result_has_model_fields(self):
        audio = _silent()
        mock_provider = MagicMock(spec=DemucsProvider)
        mock_provider.name = "demucs"
        mock_provider.separate.return_value = _make_stems()

        with patch("app.config.settings", _settings(
            provider="demucs", preference="quality", demucs_model="auto"
        )):
            result = separate_with_provider(audio, provider=mock_provider)

        assert result.model_requested == DEMUCS_MODEL_HTDEMUCS_FT
        assert result.model_used == DEMUCS_MODEL_HTDEMUCS_FT

    def test_audioshake_fallback_populates_fallback_reason(self):
        audio = _silent()
        audioshake_provider = AudioShakeProvider(api_key="test-key")
        fallback_stems = _make_stems()

        with patch.object(audioshake_provider, "separate", side_effect=RuntimeError("API timeout")):
            with patch(
                "app.services.stem_separation_providers.DemucsProvider.separate",
                return_value=fallback_stems,
            ):
                with patch("app.config.settings", _settings(
                    provider="audioshake", preference="balanced", api_key="test-key",
                    demucs_model="htdemucs",
                )):
                    result = separate_with_provider(audio, provider=audioshake_provider)

        assert result.fallback_used is True
        assert result.fallback_reason is not None
        assert "API timeout" in result.fallback_reason
        assert result.provider_name == "demucs"

    def test_provider_requested_set_for_demucs(self):
        audio = _silent()
        mock_provider = MagicMock(spec=DemucsProvider)
        mock_provider.name = "demucs"
        mock_provider.separate.return_value = _make_stems()

        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="htdemucs"
        )):
            result = separate_with_provider(audio, provider=mock_provider)

        assert result.provider_requested == "demucs"

    def test_complexity_class_from_source_metadata(self):
        audio = _silent()
        mock_provider = MagicMock(spec=DemucsProvider)
        mock_provider.name = "demucs"
        mock_provider.separate.return_value = _make_stems()

        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="auto"
        )):
            result = separate_with_provider(
                audio,
                provider=mock_provider,
                source_metadata={"duration_seconds": 90.0, "channels": 2, "sample_rate": 48000},
            )

        assert result.complexity_class == SourceComplexityClass.DENSE_MIX.value


# ---------------------------------------------------------------------------
# StemSeparationResult — extended observability fields
# ---------------------------------------------------------------------------

class TestStemSeparationResultObservabilityFields:
    def test_to_dict_includes_all_extended_fields(self):
        from app.services.stem_separation import StemSeparationResult

        r = StemSeparationResult(
            enabled=True,
            backend="demucs",
            succeeded=True,
            stems_generated=["drums", "bass"],
            stem_s3_keys={"drums": "stems/loop_1_drums.wav"},
            stem_separator_provider_used="demucs",
            stem_separator_fallback_used=False,
            stem_separator_duration_ms=500,
            stem_separator_provider_requested="demucs",
            stem_separator_model_requested="htdemucs_ft",
            stem_separator_model_used="htdemucs_ft",
            stem_separator_policy_reason="quality_no_api",
            stem_separator_complexity_class="moderate_mix",
            stem_separator_fallback_reason=None,
        )
        d = r.to_dict()
        assert d["stem_separator_provider_requested"] == "demucs"
        assert d["stem_separator_model_requested"] == "htdemucs_ft"
        assert d["stem_separator_model_used"] == "htdemucs_ft"
        assert d["stem_separator_policy_reason"] == "quality_no_api"
        assert d["stem_separator_complexity_class"] == "moderate_mix"
        assert d["stem_separator_fallback_reason"] is None

    def test_separate_and_store_stems_populates_observability_fields(self):
        from app.services.stem_separation import separate_and_store_stems

        audio = _silent()
        fallback_stems = _make_stems()
        mock_storage = MagicMock()
        mock_demucs = MagicMock(spec=DemucsProvider)
        mock_demucs.name = "demucs"
        mock_demucs.separate.return_value = fallback_stems

        with patch("app.services.stem_separation.settings") as mock_settings, \
             patch("app.services.stem_separation.storage", mock_storage), \
             patch(
                 "app.services.stem_separation_providers.get_provider",
                 return_value=mock_demucs,
             ), \
             patch("app.config.settings", _settings(
                 provider="demucs", preference="quality", demucs_model="auto"
             )):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs"
            result = separate_and_store_stems(audio, loop_id=1)

        # Provider-system fields populated
        assert result.stem_separator_provider_used == "demucs"
        assert result.stem_separator_fallback_used is False
        assert result.stem_separator_duration_ms is not None
        # Extended observability fields populated (policy_reason at minimum)
        assert result.stem_separator_policy_reason is not None

    def test_separate_and_store_stems_with_source_metadata(self):
        from app.services.stem_separation import separate_and_store_stems

        audio = _silent()
        fallback_stems = _make_stems()
        mock_storage = MagicMock()
        mock_demucs = MagicMock(spec=DemucsProvider)
        mock_demucs.name = "demucs"
        mock_demucs.separate.return_value = fallback_stems

        with patch("app.services.stem_separation.settings") as mock_settings, \
             patch("app.services.stem_separation.storage", mock_storage), \
             patch(
                 "app.services.stem_separation_providers.get_provider",
                 return_value=mock_demucs,
             ), \
             patch("app.config.settings", _settings(
                 provider="demucs", preference="balanced", demucs_model="auto",
                 max_complexity=True,
             )):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs"
            result = separate_and_store_stems(
                audio,
                loop_id=2,
                source_metadata={"duration_seconds": 90.0, "channels": 2, "sample_rate": 48000},
            )

        assert result.stem_separator_complexity_class is not None


# ---------------------------------------------------------------------------
# Fallback chain — htdemucs is always final safe fallback
# ---------------------------------------------------------------------------

class TestFallbackChain:
    def test_htdemucs_ft_failure_falls_back_via_demucs_provider_builtin(self):
        """When htdemucs_ft is requested but Demucs fails, builtin stems are returned."""
        audio = _silent()

        with patch("app.config.settings", _settings(
            provider="demucs", preference="quality", demucs_model="auto"
        )):
            provider = get_provider()

        assert isinstance(provider, DemucsProvider)
        assert provider._model == DEMUCS_MODEL_HTDEMUCS_FT

        # DemucsProvider internally falls back to builtin when Demucs unavailable
        from app.services.stem_separation import DemucsUnavailableError

        with patch(
            "app.services.stem_separation._demucs_stems",
            side_effect=DemucsUnavailableError("not installed"),
        ):
            stems = provider.separate(audio)

        assert set(stems.keys()) == {"drums", "bass", "vocals", "other"}

    def test_htdemucs_6s_failure_falls_back_to_builtin(self):
        audio = _silent()

        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="htdemucs_6s"
        )):
            provider = get_provider()

        from app.services.stem_separation import DemucsUnavailableError

        with patch(
            "app.services.stem_separation._demucs_stems",
            side_effect=DemucsUnavailableError("not installed"),
        ):
            stems = provider.separate(audio)

        assert "drums" in stems

    def test_audioshake_failure_falls_back_to_htdemucs_fallback_model(self):
        """AudioShake failure triggers Demucs with the policy's fallback_model."""
        audio = _silent()
        audioshake_provider = AudioShakeProvider(api_key="sk-key")
        fallback_stems = _make_stems()

        with patch.object(audioshake_provider, "separate", side_effect=RuntimeError("Network error")):
            with patch(
                "app.services.stem_separation_providers.DemucsProvider.separate",
                return_value=fallback_stems,
            ):
                with patch("app.config.settings", _settings(
                    provider="audioshake", preference="quality", api_key="sk-key",
                    demucs_model="auto",
                )):
                    result = separate_with_provider(audio, provider=audioshake_provider)

        assert result.fallback_used is True
        assert result.provider_name == "demucs"
        # Fallback model for quality preference should be htdemucs_ft
        assert result.model_used == DEMUCS_MODEL_HTDEMUCS_FT

    def test_htdemucs_is_ultimate_safe_fallback_when_all_fails(self):
        """DemucsProvider with htdemucs falls back to builtin — always succeeds."""
        audio = _silent()

        with patch("app.config.settings", _settings(
            provider="demucs", preference="balanced", demucs_model="htdemucs"
        )):
            provider = get_provider()

        from app.services.stem_separation import DemucsUnavailableError

        with patch(
            "app.services.stem_separation._demucs_stems",
            side_effect=DemucsUnavailableError("not installed"),
        ):
            stems = provider.separate(audio)

        assert set(stems.keys()) == {"drums", "bass", "vocals", "other"}
