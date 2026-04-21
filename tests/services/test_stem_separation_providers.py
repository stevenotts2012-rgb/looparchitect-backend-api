"""Tests for the multi-provider stem separation system.

Coverage
--------
* Provider selection logic (``get_provider``)
* AudioShake → Demucs fallback when AudioShake raises
* DemucsProvider alone (no AudioShake configured)
* ``StemSeparationResult`` metadata fields populated correctly
* No regression on the existing ``separate_and_store_stems`` mock-backend path
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from app.services.stem_separation_providers import (
    AudioShakeProvider,
    DemucsProvider,
    ProviderResult,
    StemSeparatorProvider,
    get_provider,
    separate_with_provider,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent_audio(duration_ms: int = 2000) -> AudioSegment:
    return AudioSegment.silent(duration=duration_ms)


def _make_stems(names: tuple[str, ...] = ("drums", "bass", "vocals", "other")) -> dict[str, AudioSegment]:
    return {name: _silent_audio() for name in names}


# ---------------------------------------------------------------------------
# StemSeparatorProvider interface
# ---------------------------------------------------------------------------

class TestStemSeparatorProviderInterface:
    def test_abstract_methods_required(self):
        """Cannot instantiate the abstract base class directly."""
        with pytest.raises(TypeError):
            StemSeparatorProvider()  # type: ignore[abstract]

    def test_concrete_subclass_can_be_instantiated(self):
        class MyProvider(StemSeparatorProvider):
            @property
            def name(self) -> str:
                return "my_provider"

            def separate(self, audio):
                return _make_stems()

        p = MyProvider()
        assert p.name == "my_provider"
        assert set(p.separate(_silent_audio()).keys()) == {"drums", "bass", "vocals", "other"}


# ---------------------------------------------------------------------------
# DemucsProvider
# ---------------------------------------------------------------------------

class TestDemucsProvider:
    def test_name(self):
        p = DemucsProvider()
        assert p.name == "demucs"

    def test_separate_falls_back_to_builtin_when_demucs_unavailable(self):
        """DemucsProvider returns builtin stems when demucs package absent."""
        audio = _silent_audio()
        with patch(
            "app.services.stem_separation._demucs_stems",
            side_effect=__import__(
                "app.services.stem_separation", fromlist=["DemucsUnavailableError"]
            ).DemucsUnavailableError("not installed"),
        ):
            p = DemucsProvider(model="htdemucs")
            stems = p.separate(audio)
        # Builtin always returns 4 stems
        assert set(stems.keys()) == {"drums", "bass", "vocals", "other"}

    def test_separate_falls_back_to_builtin_on_generic_error(self):
        audio = _silent_audio()
        with patch(
            "app.services.stem_separation._demucs_stems",
            side_effect=RuntimeError("inference failed"),
        ):
            p = DemucsProvider()
            stems = p.separate(audio)
        assert "drums" in stems
        assert "bass" in stems

    def test_separate_uses_demucs_when_available(self):
        """DemucsProvider returns Demucs stems when _demucs_stems succeeds."""
        expected_stems = _make_stems(("drums", "bass", "vocals", "guitar", "piano", "other"))
        audio = _silent_audio()
        with patch(
            "app.services.stem_separation._demucs_stems",
            return_value=expected_stems,
        ):
            p = DemucsProvider(model="htdemucs_6s")
            stems = p.separate(audio)
        assert stems is expected_stems


# ---------------------------------------------------------------------------
# AudioShakeProvider
# ---------------------------------------------------------------------------

class TestAudioShakeProvider:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="API key"):
            AudioShakeProvider(api_key="")

    def test_name(self):
        p = AudioShakeProvider(api_key="test-key")
        assert p.name == "audioshake"

    def test_normalise_stems_maps_melody_to_vocals(self):
        p = AudioShakeProvider(api_key="test-key")
        raw = {"melody": _silent_audio(1000), "drums": _silent_audio(1000), "bass": _silent_audio(1000)}
        normalised = p._normalise_stems(raw)
        assert "vocals" in normalised
        assert "melody" not in normalised

    def test_normalise_stems_fills_missing_with_silence(self):
        p = AudioShakeProvider(api_key="test-key")
        raw = {"drums": _silent_audio(1000)}
        normalised = p._normalise_stems(raw)
        for stem in ("drums", "bass", "vocals", "other"):
            assert stem in normalised

    def test_separate_calls_upload_submit_poll_download(self):
        """Happy path: all HTTP calls succeed."""
        p = AudioShakeProvider(api_key="test-key")
        audio = _silent_audio()

        mock_session = MagicMock()

        # _upload returns asset_id
        upload_resp = MagicMock()
        upload_resp.json.return_value = {"assetId": "asset-123"}
        mock_session.post.return_value = upload_resp

        # _submit_job returns job_id
        submit_resp = MagicMock()
        submit_resp.json.return_value = {"job": {"id": "job-456"}}

        # _poll_job returns completed job with output assets
        poll_resp = MagicMock()
        stem_wav = io.BytesIO()
        _silent_audio(500).export(stem_wav, format="wav")
        poll_resp.json.return_value = {
            "job": {
                "status": "completed",
                "outputAssets": [
                    {"name": "drums", "url": "http://example.com/drums.wav"},
                    {"name": "bass", "url": "http://example.com/bass.wav"},
                    {"name": "vocals", "url": "http://example.com/vocals.wav"},
                    {"name": "other", "url": "http://example.com/other.wav"},
                ],
            }
        }

        # Map POST calls: first is upload, second is submit_job
        mock_session.post.side_effect = [upload_resp, submit_resp]
        mock_session.get.side_effect = [
            poll_resp,
            *[_make_wav_response() for _ in range(4)],  # 4 stem downloads
        ]

        with patch("requests.Session", return_value=mock_session):
            stems = p.separate(audio)

        assert set(stems.keys()) == {"drums", "bass", "vocals", "other"}

    def test_separate_raises_on_failed_job(self):
        """AudioShakeProvider raises RuntimeError when job status is 'failed'."""
        p = AudioShakeProvider(api_key="test-key")
        audio = _silent_audio()

        mock_session = MagicMock()

        upload_resp = MagicMock()
        upload_resp.json.return_value = {"assetId": "asset-x"}
        submit_resp = MagicMock()
        submit_resp.json.return_value = {"job": {"id": "job-x"}}
        poll_resp = MagicMock()
        poll_resp.json.return_value = {"job": {"status": "failed"}}

        mock_session.post.side_effect = [upload_resp, submit_resp]
        mock_session.get.return_value = poll_resp

        with patch("requests.Session", return_value=mock_session):
            with pytest.raises(RuntimeError, match="failed"):
                p.separate(audio)


def _make_wav_response():
    """Create a mock HTTP response containing a valid WAV file."""
    buf = io.BytesIO()
    AudioSegment.silent(duration=500).export(buf, format="wav")
    resp = MagicMock()
    resp.content = buf.getvalue()
    return resp


# ---------------------------------------------------------------------------
# get_provider — selection logic
# ---------------------------------------------------------------------------

class TestGetProvider:
    def test_returns_demucs_by_default(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.stem_separator_provider = "demucs"
            mock_settings.audioshake_api_key = ""
            mock_settings.demucs_model = "htdemucs"
            mock_settings.demucs_timeout = 300
            provider = get_provider()
        assert isinstance(provider, DemucsProvider)

    def test_returns_demucs_when_audioshake_provider_but_no_key(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.stem_separator_provider = "audioshake"
            mock_settings.audioshake_api_key = ""
            mock_settings.demucs_model = "htdemucs"
            mock_settings.demucs_timeout = 300
            provider = get_provider()
        assert isinstance(provider, DemucsProvider)

    def test_returns_audioshake_when_provider_and_key_set(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.stem_separator_provider = "audioshake"
            mock_settings.audioshake_api_key = "sk-test-key"
            mock_settings.demucs_model = "htdemucs"
            mock_settings.demucs_timeout = 300
            provider = get_provider()
        assert isinstance(provider, AudioShakeProvider)

    def test_unknown_provider_defaults_to_demucs(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.stem_separator_provider = "unknown_provider"
            mock_settings.audioshake_api_key = ""
            mock_settings.demucs_model = "htdemucs"
            mock_settings.demucs_timeout = 300
            provider = get_provider()
        assert isinstance(provider, DemucsProvider)

    def test_provider_name_is_case_insensitive(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.stem_separator_provider = "AudioShake"
            mock_settings.audioshake_api_key = "sk-test"
            mock_settings.demucs_model = "htdemucs"
            mock_settings.demucs_timeout = 300
            provider = get_provider()
        assert isinstance(provider, AudioShakeProvider)


# ---------------------------------------------------------------------------
# separate_with_provider — fallback logic
# ---------------------------------------------------------------------------

class TestSeparateWithProvider:
    def test_successful_provider_returns_result(self):
        audio = _silent_audio()
        expected_stems = _make_stems()
        mock_provider = MagicMock(spec=StemSeparatorProvider)
        mock_provider.name = "mock"
        mock_provider.separate.return_value = expected_stems

        result = separate_with_provider(audio, provider=mock_provider)

        assert isinstance(result, ProviderResult)
        assert result.stems is expected_stems
        assert result.provider_name == "mock"
        assert result.fallback_used is False
        assert result.duration_ms >= 0
        assert result.error is None

    def test_audioshake_failure_triggers_demucs_fallback(self):
        """When AudioShake raises, separate_with_provider falls back to Demucs."""
        audio = _silent_audio()
        audioshake_provider = AudioShakeProvider(api_key="test-key")

        fallback_stems = _make_stems()

        with patch.object(audioshake_provider, "separate", side_effect=RuntimeError("API error")):
            with patch(
                "app.services.stem_separation_providers.DemucsProvider.separate",
                return_value=fallback_stems,
            ):
                with patch("app.config.settings") as mock_settings:
                    mock_settings.demucs_model = "htdemucs"
                    mock_settings.demucs_timeout = 300
                    result = separate_with_provider(audio, provider=audioshake_provider)

        assert result.fallback_used is True
        assert result.provider_name == "demucs"
        assert result.stems is fallback_stems
        assert "API error" in (result.error or "")

    def test_demucs_failure_does_not_trigger_extra_fallback(self):
        """DemucsProvider failure is not caught by separate_with_provider (it handles its own fallback)."""
        audio = _silent_audio()
        demucs_provider = DemucsProvider()

        with patch.object(demucs_provider, "separate", side_effect=RuntimeError("demucs crashed")):
            with pytest.raises(RuntimeError, match="demucs crashed"):
                separate_with_provider(audio, provider=demucs_provider)

    def test_uses_configured_provider_when_none_given(self):
        audio = _silent_audio()
        mock_demucs = MagicMock(spec=DemucsProvider)
        mock_demucs.name = "demucs"
        mock_demucs.separate.return_value = _make_stems()

        with patch(
            "app.services.stem_separation_providers.get_provider",
            return_value=mock_demucs,
        ):
            result = separate_with_provider(audio)

        assert result.provider_name == "demucs"
        assert result.fallback_used is False


# ---------------------------------------------------------------------------
# Regression: separate_and_store_stems mock-backend path
# ---------------------------------------------------------------------------

class TestSeparateAndStoreStemsRegression:
    """Ensure no regression on the existing separate_and_store_stems interface."""

    def test_feature_disabled_returns_disabled_result(self):
        from app.services.stem_separation import separate_and_store_stems

        audio = _silent_audio()
        with patch("app.services.stem_separation.settings") as mock_settings:
            mock_settings.feature_stem_separation = False
            mock_settings.stem_separation_backend = "builtin"
            result = separate_and_store_stems(audio, loop_id=1)

        assert result.enabled is False
        assert result.succeeded is False
        assert result.error == "feature_disabled"

    def test_mock_backend_succeeds_and_stores_stems(self):
        from app.services.stem_separation import separate_and_store_stems

        audio = _silent_audio()

        mock_storage = MagicMock()

        with patch("app.services.stem_separation.settings") as mock_settings, \
             patch("app.services.stem_separation.storage", mock_storage):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "mock"
            result = separate_and_store_stems(audio, loop_id=42)

        assert result.enabled is True
        assert result.succeeded is True
        assert len(result.stems_generated) > 0
        assert mock_storage.upload_file.call_count == len(result.stems_generated)

    def test_result_includes_provider_metadata(self):
        from app.services.stem_separation import separate_and_store_stems
        from app.services.stem_separation_providers import DemucsProvider

        audio = _silent_audio()
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
             ):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs"
            result = separate_and_store_stems(audio, loop_id=99)

        assert result.stem_separator_provider_used == "demucs"
        assert result.stem_separator_fallback_used is False
        assert result.stem_separator_duration_ms is not None
        assert result.stem_separator_duration_ms >= 0

    def test_to_dict_includes_provider_metadata_keys(self):
        from app.services.stem_separation import StemSeparationResult

        r = StemSeparationResult(
            enabled=True,
            backend="demucs",
            succeeded=True,
            stems_generated=["drums", "bass"],
            stem_s3_keys={"drums": "stems/loop_1_drums.wav", "bass": "stems/loop_1_bass.wav"},
            stem_separator_provider_used="demucs",
            stem_separator_fallback_used=False,
            stem_separator_duration_ms=1234,
        )
        d = r.to_dict()
        assert d["stem_separator_provider_used"] == "demucs"
        assert d["stem_separator_fallback_used"] is False
        assert d["stem_separator_duration_ms"] == 1234
