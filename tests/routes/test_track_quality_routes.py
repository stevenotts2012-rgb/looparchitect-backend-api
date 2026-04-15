"""
Route/API tests for the Track Technical Quality Analysis endpoint.

Tests cover:
- POST /api/v1/track/analyze-quality
  - Feature-flag gating (501 when disabled, proceeds when enabled)
  - File upload validation (missing file, wrong extension, empty file, oversized)
  - Successful analysis returns valid response structure
  - Response fields contain expected types and value ranges
"""

from __future__ import annotations

import io
import math
import struct
import wave
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sine_wav_bytes(
    duration_sec: float = 2.0,
    sample_rate: int = 44100,
    amplitude: float = 0.5,
    channels: int = 1,
) -> bytes:
    """Return raw WAV bytes (mono or stereo sine wave, 16-bit PCM)."""
    n_samples = int(duration_sec * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            t = i / sample_rate
            sample = int(amplitude * math.sin(2 * math.pi * 440.0 * t) * 32767)
            if channels == 2:
                wf.writeframes(struct.pack("<hh", sample, sample))
            else:
                wf.writeframes(struct.pack("<h", sample))
    return buf.getvalue()


@pytest.fixture
def client():
    return TestClient(app)


def _mock_quality_response():
    """Return a minimal TrackQualityAnalysisResponse mock."""
    from app.schemas.track_quality import (
        ClippingLevel,
        StereoFieldWidth,
        TonalBandStatus,
        TonalProfile,
        TrackQualityAnalysisResponse,
    )

    return TrackQualityAnalysisResponse(
        sample_rate=44100,
        bit_depth=16,
        clipping=ClippingLevel.NONE,
        mono_compatibility=True,
        integrated_loudness=-18.0,
        true_peak=-3.0,
        phase_issues=False,
        stereo_field=StereoFieldWidth.NORMAL,
        tonal_profile=TonalProfile(
            low=TonalBandStatus.OPTIMAL,
            low_mid=TonalBandStatus.OPTIMAL,
            mid=TonalBandStatus.OPTIMAL,
            high=TonalBandStatus.OPTIMAL,
        ),
        suggestions=[],
        analysis_version="1.0.0",
    )


# ---------------------------------------------------------------------------
# Feature-flag gating
# ---------------------------------------------------------------------------


class TestTrackQualityFeatureFlag:
    def test_returns_501_when_flag_disabled(self, client):
        """Endpoint must return 501 when TRACK_QUALITY_ANALYSIS=false."""
        with patch("app.routes.track_quality.settings") as mock_settings:
            mock_settings.feature_track_quality_analysis = False
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 501
        assert "not enabled" in response.json()["detail"].lower()

    def test_proceeds_when_flag_enabled(self, client):
        """Endpoint proceeds to analysis when TRACK_QUALITY_ANALYSIS=true."""
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# File upload validation
# ---------------------------------------------------------------------------


class TestFileUploadValidation:
    def _post_with_flag(self, client, filename: str, content_bytes: bytes, content_type: str):
        with patch("app.routes.track_quality.settings") as mock_settings:
            mock_settings.feature_track_quality_analysis = True
            return client.post(
                "/api/v1/track/analyze-quality",
                files={"file": (filename, content_bytes, content_type)},
            )

    def test_missing_file_returns_422(self, client):
        with patch("app.routes.track_quality.settings") as mock_settings:
            mock_settings.feature_track_quality_analysis = True
            response = client.post("/api/v1/track/analyze-quality")
        assert response.status_code == 422

    def test_empty_file_returns_400(self, client):
        response = self._post_with_flag(client, "track.wav", b"", "audio/wav")
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_unsupported_extension_returns_415(self, client):
        response = self._post_with_flag(
            client, "track.txt", b"not audio", "text/plain"
        )
        assert response.status_code == 415
        assert "unsupported" in response.json()["detail"].lower()

    def test_oversized_file_returns_413(self, client):
        # 101 MB of zeros — over the 100 MB limit
        big_bytes = b"\x00" * (101 * 1024 * 1024)
        response = self._post_with_flag(client, "big.wav", big_bytes, "audio/wav")
        assert response.status_code == 413

    def test_valid_wav_accepted(self, client):
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 200


# ---------------------------------------------------------------------------
# Response structure
# ---------------------------------------------------------------------------


class TestResponseStructure:
    def test_response_contains_required_fields(self, client):
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        assert response.status_code == 200
        body = response.json()

        required_fields = [
            "sample_rate",
            "bit_depth",
            "clipping",
            "mono_compatibility",
            "integrated_loudness",
            "true_peak",
            "phase_issues",
            "stereo_field",
            "tonal_profile",
            "suggestions",
            "analysis_version",
        ]
        for field in required_fields:
            assert field in body, f"Missing field: {field}"

    def test_tonal_profile_contains_four_bands(self, client):
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        body = response.json()
        tp = body["tonal_profile"]
        assert set(tp.keys()) >= {"low", "low_mid", "mid", "high"}

    def test_clipping_value_is_valid_enum(self, client):
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        body = response.json()
        assert body["clipping"] in ("None", "Minor", "Severe")

    def test_stereo_field_value_is_valid_enum(self, client):
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        body = response.json()
        assert body["stereo_field"] in ("Narrow", "Normal", "Wide")

    def test_suggestions_is_a_list(self, client):
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        body = response.json()
        assert isinstance(body["suggestions"], list)

    def test_analysis_version_present(self, client):
        with (
            patch("app.routes.track_quality.settings") as mock_settings,
            patch(
                "app.routes.track_quality.track_quality_analyzer.analyze",
                return_value=_mock_quality_response(),
            ),
        ):
            mock_settings.feature_track_quality_analysis = True
            response = client.post(
                "/api/v1/track/analyze-quality",
                files={"file": ("track.wav", _make_sine_wav_bytes(), "audio/wav")},
            )
        body = response.json()
        assert body["analysis_version"] == "1.0.0"
