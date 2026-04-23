"""Tests for app/services/stem_pack_service.py.

Covers: _decode_audio, ingest_stem_files, ingest_stem_zip, persist_role_stems,
StemPackIngestResult.to_metadata, StemPackIngestResult.roles_detected.
"""

from __future__ import annotations

import io
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.services.stem_pack_service import (
    StemPackError,
    StemPackIngestResult,
    StemSourceFile,
    _decode_audio,
    ingest_stem_files,
    ingest_stem_zip,
    persist_role_stems,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wav_bytes(frequency: int = 440, duration_ms: int = 1000, frame_rate: int = 44100) -> bytes:
    """Return WAV bytes for a tone at the given frequency."""
    seg = Sine(frequency).to_audio_segment(duration=duration_ms).set_frame_rate(frame_rate)
    buf = io.BytesIO()
    seg.export(buf, format="wav")
    return buf.getvalue()


def _silent_wav_bytes_for_decode(duration_ms: int = 500) -> bytes:
    """Return WAV bytes for a silent segment (only used for _decode_audio tests)."""
    seg = AudioSegment.silent(duration=duration_ms).set_frame_rate(44100)
    buf = io.BytesIO()
    seg.export(buf, format="wav")
    return buf.getvalue()


def _make_source_file(filename: str, frequency: int = 440, duration_ms: int = 1000) -> StemSourceFile:
    return StemSourceFile(filename=filename, content=_wav_bytes(frequency, duration_ms))


def _make_zip_bytes(*filenames: str) -> bytes:
    """Create a ZIP archive containing silent WAV files."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name in filenames:
            zf.writestr(name, _silent_wav_bytes())
    buf.seek(0)
    return buf.read()


# ===========================================================================
# _decode_audio
# ===========================================================================


class TestDecodeAudio:
    def test_decodes_wav_bytes(self):
        wav_bytes = _silent_wav_bytes_for_decode()
        result = _decode_audio(wav_bytes, "track.wav")
        assert isinstance(result, AudioSegment)

    def test_raises_stem_pack_error_on_invalid_bytes(self):
        with pytest.raises(StemPackError, match="Could not decode stem"):
            _decode_audio(b"not-audio-data", "bad.wav")

    def test_raises_for_corrupted_wav(self):
        with pytest.raises(StemPackError):
            _decode_audio(b"\x00" * 100, "corrupt.wav")


# ===========================================================================
# StemPackIngestResult
# ===========================================================================


class TestStemPackIngestResult:
    def _make_result(self) -> StemPackIngestResult:
        return StemPackIngestResult(
            mixed_preview=AudioSegment.silent(duration=500),
            role_stems={
                "drums": AudioSegment.silent(duration=500),
                "bass": AudioSegment.silent(duration=500),
            },
            role_sources={"drums": ["drums.wav"], "bass": ["bass.wav"]},
            sample_rate=44100,
            duration_ms=500,
            source_files=["drums.wav", "bass.wav"],
            alignment={"confidence": 0.9, "low_confidence": False},
            validation_warnings=[],
            fallback_to_loop=False,
        )

    def test_roles_detected_sorted(self):
        result = self._make_result()
        assert result.roles_detected == ["bass", "drums"]

    def test_stem_classifications_defaults_to_empty_dict(self):
        result = self._make_result()
        assert result.stem_classifications == {}

    def test_to_metadata_contains_required_keys(self):
        result = self._make_result()
        meta = result.to_metadata(
            loop_id=42,
            stem_s3_keys={"drums": "stems/42_drums.wav", "bass": "stems/42_bass.wav"},
        )
        assert meta["loop_id"] == 42
        assert meta["enabled"] is True
        assert meta["succeeded"] is True
        assert "roles_detected" in meta
        assert "stem_s3_keys" in meta
        assert "friendly_labels" in meta

    def test_to_metadata_fallback_when_true(self):
        result = self._make_result()
        result.fallback_to_loop = True
        meta = result.to_metadata(loop_id=1, stem_s3_keys={})
        assert meta["succeeded"] is False
        assert meta["fallback_to_loop"] is True

    def test_to_metadata_with_bars(self):
        result = self._make_result()
        meta = result.to_metadata(loop_id=1, stem_s3_keys={}, bars=8)
        assert meta["bars_validated"] == 8

    def test_to_metadata_classification_list(self):
        from app.services.stem_role_classifier import StemClassification

        result = self._make_result()
        result.stem_classifications = {
            "drums.wav": StemClassification(
                role="drums",
                group="rhythm",
                confidence=0.95,
                matched_keywords=["drums"],
                sources_used=["filename"],
                uncertain=False,
            )
        }
        meta = result.to_metadata(loop_id=1, stem_s3_keys={})
        assert len(meta["stem_classifications"]) == 1
        assert meta["stem_classifications"][0]["role"] == "drums"

    def test_arrangement_groups_detected(self):
        from app.services.stem_role_classifier import StemClassification

        result = self._make_result()
        result.stem_classifications = {
            "drums.wav": StemClassification(
                role="drums",
                group="rhythm",
                confidence=0.9,
                matched_keywords=[],
                sources_used=[],
                uncertain=False,
            ),
            "bass.wav": StemClassification(
                role="bass",
                group="low_end",
                confidence=0.85,
                matched_keywords=[],
                sources_used=[],
                uncertain=False,
            ),
        }
        meta = result.to_metadata(loop_id=1, stem_s3_keys={})
        assert "rhythm" in meta["arrangement_groups_detected"]
        assert "low_end" in meta["arrangement_groups_detected"]


# ===========================================================================
# ingest_stem_files
# ===========================================================================


class TestIngestStemFiles:
    def test_raises_when_fewer_than_two_files(self):
        with pytest.raises(StemPackError, match="At least two"):
            ingest_stem_files([_make_source_file("drums.wav")])

    def test_raises_on_unsupported_extension(self):
        files = [
            _make_source_file("drums.wav"),
            StemSourceFile(filename="loop.aiff", content=b"data"),
        ]
        with pytest.raises(StemPackError, match="Unsupported stem file type"):
            ingest_stem_files(files)

    def test_returns_ingest_result_with_two_valid_stems(self):
        files = [
            _make_source_file("drums.wav", frequency=80, duration_ms=1000),
            _make_source_file("bass.wav", frequency=55, duration_ms=1000),
        ]
        result = ingest_stem_files(files)
        assert isinstance(result, StemPackIngestResult)
        assert len(result.role_stems) >= 1

    def test_result_has_source_files(self):
        files = [
            _make_source_file("kick_drums.wav", frequency=80, duration_ms=1000),
            _make_source_file("sub_bass.wav", frequency=55, duration_ms=1000),
        ]
        result = ingest_stem_files(files)
        assert "kick_drums.wav" in result.source_files
        assert "sub_bass.wav" in result.source_files

    def test_result_has_mixed_preview(self):
        files = [
            _make_source_file("drums.wav", frequency=80, duration_ms=1000),
            _make_source_file("bass.wav", frequency=55, duration_ms=1000),
        ]
        result = ingest_stem_files(files)
        assert isinstance(result.mixed_preview, AudioSegment)
        assert len(result.mixed_preview) > 0

    def test_result_has_sample_rate(self):
        files = [
            _make_source_file("drums.wav", frequency=80, duration_ms=1000),
            _make_source_file("bass.wav", frequency=55, duration_ms=1000),
        ]
        result = ingest_stem_files(files)
        assert result.sample_rate == 44100

    def test_stem_classifications_populated(self):
        files = [
            _make_source_file("drums.wav", frequency=80, duration_ms=1000),
            _make_source_file("bass.wav", frequency=55, duration_ms=1000),
        ]
        result = ingest_stem_files(files)
        assert len(result.stem_classifications) >= 1


# ===========================================================================
# persist_role_stems
# ===========================================================================


class TestPersistRoleStems:
    def _tone(self) -> AudioSegment:
        return Sine(440).to_audio_segment(duration=500)

    def test_calls_upload_for_each_role(self):
        role_stems = {
            "drums": self._tone(),
            "bass": self._tone(),
        }
        mock_storage = MagicMock()
        mock_storage.upload_file.return_value = "stems/loop_1_drums.wav"

        with patch("app.services.stem_pack_service.storage", mock_storage):
            stem_keys = persist_role_stems(loop_id=1, role_stems=role_stems)

        assert mock_storage.upload_file.call_count == 2

    def test_returns_correct_keys(self):
        role_stems = {"drums": self._tone()}

        mock_storage = MagicMock()
        mock_storage.upload_file.return_value = "stems/loop_5_drums.wav"

        with patch("app.services.stem_pack_service.storage", mock_storage):
            stem_keys = persist_role_stems(loop_id=5, role_stems=role_stems)

        assert "drums" in stem_keys
        assert stem_keys["drums"] == "stems/loop_5_drums.wav"

    def test_key_format_contains_loop_id_and_role(self):
        uploaded_keys = []

        def _capture_upload(file_bytes, content_type, key):
            uploaded_keys.append(key)
            return key

        mock_storage = MagicMock()
        mock_storage.upload_file.side_effect = _capture_upload

        with patch("app.services.stem_pack_service.storage", mock_storage):
            persist_role_stems(loop_id=99, role_stems={"melody": self._tone()})

        assert any("99" in k and "melody" in k for k in uploaded_keys)
