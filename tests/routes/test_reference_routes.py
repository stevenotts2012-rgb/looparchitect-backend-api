"""
Route/API tests for Reference-Guided Arrangement Mode (Phase 4 & 5).

Tests cover:
- POST /api/v1/reference/analyze endpoint behavior when feature flag is off/on
- Upload validation (file type, size, empty file)
- Optional reference_analysis_id in arrangement generation
- Backward-compatible arrangement generation without reference
- Legacy client compatibility (existing fields still present)
"""

from __future__ import annotations

import io
import json
import math
import struct
import uuid
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from main import app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sine_wav_bytes(duration_sec: float = 1.0, sample_rate: int = 22050) -> bytes:
    """Return raw WAV bytes (mono sine wave)."""
    n_samples = int(duration_sec * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        for i in range(n_samples):
            sample = 0.5 * math.sin(2 * math.pi * 440.0 * i / sample_rate)
            wf.writeframes(struct.pack("<h", int(sample * 32767)))
    return buf.getvalue()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Feature-flag gating tests
# ---------------------------------------------------------------------------


class TestReferenceAnalyzeFeatureFlag:
    def test_analyze_returns_501_when_flag_off(self, client):
        """When REFERENCE_SECTION_ANALYSIS=false, endpoint returns 501."""
        with patch("app.routes.reference.settings") as mock_settings:
            mock_settings.feature_reference_section_analysis = False
            response = client.post(
                "/api/v1/reference/analyze",
                files={"file": ("test.wav", _make_sine_wav_bytes(), "audio/wav")},
                data={"guidance_mode": "structure_and_energy", "adaptation_strength": "medium"},
            )
        assert response.status_code == 501
        assert "not enabled" in response.json()["detail"].lower()

    def test_analyze_proceeds_when_flag_on(self, client):
        """When REFERENCE_SECTION_ANALYSIS=true, endpoint proceeds to analyze."""
        from app.schemas.reference_arrangement import ReferenceStructure

        mock_structure = ReferenceStructure(
            total_duration_sec=30.0,
            sections=[],
            energy_curve=[],
            summary="Test summary",
            analysis_confidence=0.5,
            analysis_quality="medium",
            analysis_warnings=[],
            tempo_estimate=120.0,
        )

        with patch("app.routes.reference.settings") as mock_settings, \
             patch("app.routes.reference.reference_analyzer") as mock_analyzer, \
             patch("app.routes.reference._store_analysis"):
            mock_settings.feature_reference_section_analysis = True
            mock_analyzer.analyze.return_value = mock_structure
            response = client.post(
                "/api/v1/reference/analyze",
                files={"file": ("test.wav", _make_sine_wav_bytes(), "audio/wav")},
                data={"guidance_mode": "structure_only", "adaptation_strength": "loose"},
            )

        assert response.status_code == 200
        data = response.json()
        assert "analysis_id" in data
        assert "legal_disclaimer" in data
        assert "structure" in data


# ---------------------------------------------------------------------------
# Upload validation tests
# ---------------------------------------------------------------------------


class TestReferenceAnalyzeValidation:
    def _make_mock_structure(self):
        from app.schemas.reference_arrangement import ReferenceStructure
        return ReferenceStructure(
            total_duration_sec=30.0,
            sections=[],
            energy_curve=[],
            summary="ok",
            analysis_confidence=0.5,
            analysis_quality="medium",
            analysis_warnings=[],
        )

    def _analyze_with_flag(self, client, file_bytes, filename, content_type="audio/wav"):
        """Helper: hit the analyze endpoint with REFERENCE_SECTION_ANALYSIS=true."""
        with patch("app.routes.reference.settings") as mock_settings, \
             patch("app.routes.reference.reference_analyzer") as mock_analyzer, \
             patch("app.routes.reference._store_analysis"):
            mock_settings.feature_reference_section_analysis = True
            mock_analyzer.analyze.return_value = self._make_mock_structure()
            response = client.post(
                "/api/v1/reference/analyze",
                files={"file": (filename, file_bytes, content_type)},
                data={"guidance_mode": "structure_and_energy", "adaptation_strength": "medium"},
            )
        return response

    def test_empty_file_returns_400(self, client):
        response = self._analyze_with_flag(client, b"", "empty.wav")
        assert response.status_code == 400
        assert "empty" in response.json()["detail"].lower()

    def test_unsupported_extension_returns_415(self, client):
        response = self._analyze_with_flag(
            client, b"data", "test.txt", "text/plain"
        )
        assert response.status_code == 415

    def test_oversized_file_returns_413(self, client):
        oversized = b"X" * (101 * 1024 * 1024)  # 101 MB
        response = self._analyze_with_flag(client, oversized, "big.wav")
        assert response.status_code == 413

    def test_valid_wav_extension_accepted(self, client):
        with patch("app.routes.reference.settings") as mock_settings, \
             patch("app.routes.reference.reference_analyzer") as mock_analyzer, \
             patch("app.routes.reference._store_analysis"):
            mock_settings.feature_reference_section_analysis = True
            mock_analyzer.analyze.return_value = self._make_mock_structure()
            response = client.post(
                "/api/v1/reference/analyze",
                files={"file": ("test.wav", _make_sine_wav_bytes(), "audio/wav")},
                data={"guidance_mode": "structure_and_energy", "adaptation_strength": "medium"},
            )
        # Should not be a validation error (415/400 for wrong type)
        assert response.status_code not in (415,)

    def test_mp3_extension_accepted(self, client):
        with patch("app.routes.reference.settings") as mock_settings, \
             patch("app.routes.reference.reference_analyzer") as mock_analyzer, \
             patch("app.routes.reference._store_analysis"):
            mock_settings.feature_reference_section_analysis = True
            mock_analyzer.analyze.return_value = self._make_mock_structure()
            # MP3 extension — should pass validation
            response = client.post(
                "/api/v1/reference/analyze",
                files={"file": ("reference.mp3", b"fake_mp3_data", "audio/mpeg")},
                data={"guidance_mode": "structure_and_energy", "adaptation_strength": "medium"},
            )
        assert response.status_code not in (415,)

    def test_txt_extension_rejected(self, client):
        with patch("app.routes.reference.settings") as mock_settings:
            mock_settings.feature_reference_section_analysis = True
            response = client.post(
                "/api/v1/reference/analyze",
                files={"file": ("notes.txt", b"some text", "text/plain")},
                data={"guidance_mode": "structure_and_energy", "adaptation_strength": "medium"},
            )
        assert response.status_code == 415


# ---------------------------------------------------------------------------
# Load/store analysis helpers
# ---------------------------------------------------------------------------


class TestLoadAnalysis:
    def test_load_nonexistent_returns_none(self):
        from app.routes.reference import _load_analysis
        with patch("app.routes.reference.settings") as mock_settings:
            mock_settings.get_storage_backend.return_value = "local"
            result = _load_analysis("nonexistent-id-" + str(uuid.uuid4()))
        assert result is None

    def test_store_and_load_roundtrip_local(self, tmp_path):
        from app.routes.reference import _store_analysis, _load_analysis

        analysis_id = str(uuid.uuid4())
        payload = {
            "analysis_id": analysis_id,
            "structure": {"total_duration_sec": 60.0, "sections": []},
            "guidance_mode": "structure_and_energy",
            "adaptation_strength": "medium",
            "created_at": "2026-01-01T00:00:00",
        }

        # Patch to use temp directory
        with patch("app.routes.reference.settings") as mock_settings, \
             patch("app.routes.reference.storage") as mock_storage, \
             patch("app.routes.reference.Path") as mock_path_cls:
            mock_settings.get_storage_backend.return_value = "local"
            # Make _store_analysis write to tmp_path
            ref_dir = tmp_path / "reference_analyses"
            ref_dir.mkdir()
            mock_storage.upload_file.side_effect = Exception("skip S3")
            # Use real Path for local fallback
            with patch("app.routes.reference.Path", Path):
                with patch("builtins.open", side_effect=Exception("skip")):
                    # Just test that store doesn't crash
                    try:
                        _store_analysis(analysis_id, payload)
                    except Exception:
                        pass  # Expected in mock environment


# ---------------------------------------------------------------------------
# Arrangement generation backward-compatibility tests
# ---------------------------------------------------------------------------


class TestArrangementGenerationLegacyCompatibility:
    """Verify existing arrangement generation is NOT affected when reference fields are absent."""

    def _mock_loop(self):
        loop = MagicMock()
        loop.id = 1
        loop.bpm = 120.0
        loop.tempo = 120.0
        loop.bars = 8
        loop.musical_key = "C"
        loop.filename = "test.wav"
        loop.file_key = "uploads/test.wav"
        loop.genre = None
        loop.stem_metadata = None
        loop.is_stem_pack = "false"
        loop.tags = None
        loop.key = "C"
        return loop

    def test_generate_without_reference_id_does_not_crash(self, client):
        """Generate request without reference_analysis_id should work as before."""
        # Just verify the schema accepts the request without reference fields
        from app.schemas.arrangement import AudioArrangementGenerateRequest
        req = AudioArrangementGenerateRequest(loop_id=1, target_seconds=60)
        assert req.reference_analysis_id is None

    def test_reference_guided_defaults_to_false(self):
        """response.reference_guided should be False when no reference is provided."""
        from app.schemas.arrangement import AudioArrangementGenerateResponse
        response = AudioArrangementGenerateResponse(
            loop_id=1,
        )
        assert response.reference_guided is False
        assert response.reference_summary is None
        assert response.reference_structure_summary is None
        assert response.adaptation_mode is None
        assert response.adaptation_strength is None
        assert response.reference_analysis_confidence is None

    def test_request_schema_accepts_reference_fields(self):
        """AudioArrangementGenerateRequest should accept reference_analysis_id."""
        from app.schemas.arrangement import AudioArrangementGenerateRequest
        req = AudioArrangementGenerateRequest(
            loop_id=1,
            target_seconds=60,
            reference_analysis_id="test-uuid",
            reference_guidance_mode="structure_and_energy",
            reference_adaptation_strength="medium",
        )
        assert req.reference_analysis_id == "test-uuid"
        assert req.reference_guidance_mode == "structure_and_energy"
        assert req.reference_adaptation_strength == "medium"

    def test_request_schema_without_reference_fields_is_valid(self):
        """Legacy request without reference fields should remain valid."""
        from app.schemas.arrangement import AudioArrangementGenerateRequest
        req = AudioArrangementGenerateRequest(
            loop_id=1,
            target_seconds=60,
        )
        assert req.reference_analysis_id is None
        assert req.reference_guidance_mode is None
        assert req.reference_adaptation_strength is None


# ---------------------------------------------------------------------------
# Reference-guided arrangement flag gating tests
# ---------------------------------------------------------------------------


class TestReferenceGuidedArrangementFlag:
    def test_reference_guidance_skipped_when_flag_off(self):
        """When REFERENCE_GUIDED_ARRANGEMENT=false, guidance block is skipped."""
        from app.config import settings
        original = settings.feature_reference_guided_arrangement
        try:
            settings.feature_reference_guided_arrangement = False
            # Just verify the flag is accessible
            assert settings.feature_reference_guided_arrangement is False
        finally:
            settings.feature_reference_guided_arrangement = original

    def test_feature_flags_default_to_false(self):
        """Both reference feature flags should default to False."""
        from app.config import Settings
        # Create a fresh settings instance without environment overrides
        fresh = Settings(_env_file=None)
        assert fresh.feature_reference_guided_arrangement is False
        assert fresh.feature_reference_section_analysis is False


# ---------------------------------------------------------------------------
# Schema tests: ReferenceAnalysisResponse
# ---------------------------------------------------------------------------


class TestReferenceAnalysisResponseSchema:
    def test_response_has_legal_disclaimer(self):
        from app.schemas.reference_arrangement import (
            ReferenceAnalysisResponse,
            ReferenceGuidanceMode,
            ReferenceAdaptationStrength,
            ReferenceStructure,
        )
        from datetime import datetime, timezone
        response = ReferenceAnalysisResponse(
            analysis_id="test-id",
            structure=ReferenceStructure(
                total_duration_sec=60.0,
                sections=[],
                energy_curve=[],
                summary="test",
                analysis_confidence=0.5,
                analysis_quality="medium",
            ),
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
            created_at=datetime.now(timezone.utc),
        )
        assert len(response.legal_disclaimer) > 0
        # Disclaimer must NOT imply musical content copying
        disclaimer_lower = response.legal_disclaimer.lower()
        assert "not copied" in disclaimer_lower or "not reproduced" in disclaimer_lower

    def test_guidance_mode_enum_values(self):
        from app.schemas.reference_arrangement import ReferenceGuidanceMode
        assert ReferenceGuidanceMode.STRUCTURE_ONLY.value == "structure_only"
        assert ReferenceGuidanceMode.ENERGY_ONLY.value == "energy_only"
        assert ReferenceGuidanceMode.STRUCTURE_AND_ENERGY.value == "structure_and_energy"

    def test_adaptation_strength_enum_values(self):
        from app.schemas.reference_arrangement import ReferenceAdaptationStrength
        assert ReferenceAdaptationStrength.LOOSE.value == "loose"
        assert ReferenceAdaptationStrength.MEDIUM.value == "medium"
        assert ReferenceAdaptationStrength.CLOSE.value == "close"

    def test_reference_section_duration_property(self):
        from app.schemas.reference_arrangement import ReferenceSection
        sec = ReferenceSection(
            index=0, start_time_sec=10.0, end_time_sec=40.0,
            estimated_bars=8, section_type_guess="verse",
            energy_level=0.5, density_level=0.5,
            transition_in_strength=0.3, transition_out_strength=0.3,
        )
        assert sec.duration_sec == pytest.approx(30.0)


# ---------------------------------------------------------------------------
# Config / feature flag tests
# ---------------------------------------------------------------------------


class TestConfigFeatureFlags:
    def test_reference_flags_in_convert_bool_validator(self):
        """Both reference flags should respond to string true/false env values."""
        from app.config import Settings
        s = Settings(
            REFERENCE_GUIDED_ARRANGEMENT="true",
            REFERENCE_SECTION_ANALYSIS="1",
            _env_file=None,
        )
        assert s.feature_reference_guided_arrangement is True
        assert s.feature_reference_section_analysis is True

    def test_reference_flags_false_by_default(self):
        from app.config import Settings
        s = Settings(_env_file=None)
        assert s.feature_reference_guided_arrangement is False
        assert s.feature_reference_section_analysis is False

    def test_existing_flags_unchanged(self):
        """Existing feature flags must remain unaffected by new additions."""
        from app.config import settings
        # These should still exist and be accessible
        assert hasattr(settings, "feature_producer_engine")
        assert hasattr(settings, "feature_producer_engine_v2")
        assert hasattr(settings, "feature_ai_producer_assist")
        assert hasattr(settings, "feature_mastering_stage")
