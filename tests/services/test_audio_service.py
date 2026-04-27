"""Tests for app/services/audio_service.py — AudioService class."""

from __future__ import annotations

import io
import struct
import wave
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_wav_file(tmp_path: Path, duration_ms: int = 200) -> str:
    """Write a minimal valid WAV file and return its path as a string."""
    n_frames = int(22050 * duration_ms / 1000)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(22050)
        wf.writeframes(struct.pack(f"<{n_frames}h", *([0] * n_frames)))
    path = tmp_path / "test.wav"
    path.write_bytes(buf.getvalue())
    return str(path)


# ---------------------------------------------------------------------------
# AudioService initialisation
# ---------------------------------------------------------------------------


class TestAudioServiceInit:
    def test_instance_created(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        assert svc is not None

    def test_global_instance_exists(self):
        from app.services.audio_service import audio_service

        assert audio_service is not None


# ---------------------------------------------------------------------------
# analyze_loop
# ---------------------------------------------------------------------------


class TestAnalyzeLoop:
    def test_raises_file_not_found_for_missing_file(self, tmp_path):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with pytest.raises(FileNotFoundError, match="Audio file not found"):
            svc.analyze_loop(str(tmp_path / "nonexistent.wav"))

    def test_returns_expected_keys(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        svc = AudioService()

        mock_audio = MagicMock()
        mock_audio.channels = 2

        with (
            patch("librosa.load", return_value=(np.zeros(100), 22050)),
            patch("librosa.onset.onset_strength", return_value=np.zeros(50)),
            patch("librosa.beat.tempo", return_value=np.array([120.0])),
            patch("librosa.get_duration", return_value=4.5),
            patch("librosa.feature.chroma_cqt", return_value=np.zeros((12, 50))),
            patch("pydub.AudioSegment.from_file", return_value=mock_audio),
        ):
            result = svc.analyze_loop(wav_path)

        assert set(result.keys()) == {"bpm", "key", "duration_seconds", "sample_rate", "channels"}

    def test_bpm_and_duration_values(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        svc = AudioService()

        mock_audio = MagicMock()
        mock_audio.channels = 1

        with (
            patch("librosa.load", return_value=(np.zeros(100), 44100)),
            patch("librosa.onset.onset_strength", return_value=np.zeros(50)),
            patch("librosa.beat.tempo", return_value=np.array([140.0])),
            patch("librosa.get_duration", return_value=8.0),
            patch("librosa.feature.chroma_cqt", return_value=np.zeros((12, 50))),
            patch("pydub.AudioSegment.from_file", return_value=mock_audio),
        ):
            result = svc.analyze_loop(wav_path)

        assert result["bpm"] == 140.0
        assert result["duration_seconds"] == 8.0
        assert result["sample_rate"] == 44100
        assert result["channels"] == 1

    def test_propagates_exception_on_load_failure(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        svc = AudioService()

        with patch("librosa.load", side_effect=RuntimeError("load failed")):
            with pytest.raises(RuntimeError, match="load failed"):
                svc.analyze_loop(wav_path)


# ---------------------------------------------------------------------------
# _detect_bpm
# ---------------------------------------------------------------------------


class TestDetectBpm:
    def test_returns_float_in_normal_range(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        y = np.zeros(1000)
        with (
            patch("librosa.onset.onset_strength", return_value=np.zeros(50)),
            patch("librosa.beat.tempo", return_value=np.array([128.0])),
        ):
            bpm = svc._detect_bpm(y, 22050)
        assert isinstance(bpm, float)
        assert bpm == 128.0

    def test_doubles_bpm_when_below_40(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with (
            patch("librosa.onset.onset_strength", return_value=np.zeros(50)),
            patch("librosa.beat.tempo", return_value=np.array([30.0])),
        ):
            bpm = svc._detect_bpm(np.zeros(100), 22050)
        assert bpm == 60.0

    def test_halves_bpm_when_above_250(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with (
            patch("librosa.onset.onset_strength", return_value=np.zeros(50)),
            patch("librosa.beat.tempo", return_value=np.array([300.0])),
        ):
            bpm = svc._detect_bpm(np.zeros(100), 22050)
        assert bpm == 150.0

    def test_returns_default_120_on_exception(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with patch("librosa.onset.onset_strength", side_effect=RuntimeError("fail")):
            bpm = svc._detect_bpm(np.zeros(100), 22050)
        assert bpm == 120.0


# ---------------------------------------------------------------------------
# _detect_key
# ---------------------------------------------------------------------------


class TestDetectKey:
    def test_returns_c_when_c_dominant(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        chroma = np.zeros((12, 50))
        chroma[0] = 1.0  # C is index 0
        with patch("librosa.feature.chroma_cqt", return_value=chroma):
            key = svc._detect_key(np.zeros(100), 22050)
        assert key == "C"

    def test_returns_g_sharp_when_g_sharp_dominant(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        chroma = np.zeros((12, 50))
        chroma[8] = 1.0  # G# is index 8
        with patch("librosa.feature.chroma_cqt", return_value=chroma):
            key = svc._detect_key(np.zeros(100), 22050)
        assert key == "G#"

    def test_returns_default_c_on_exception(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with patch("librosa.feature.chroma_cqt", side_effect=RuntimeError("fail")):
            key = svc._detect_key(np.zeros(100), 22050)
        assert key == "C"

    def test_all_pitch_classes_accessible(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        expected = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        for i, expected_key in enumerate(expected):
            chroma = np.zeros((12, 50))
            chroma[i] = 1.0
            with patch("librosa.feature.chroma_cqt", return_value=chroma):
                key = svc._detect_key(np.zeros(100), 22050)
            assert key == expected_key, f"Index {i} should map to {expected_key}"


# ---------------------------------------------------------------------------
# extend_loop
# ---------------------------------------------------------------------------


class TestExtendLoop:
    def test_raises_file_not_found(self, tmp_path):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with pytest.raises(FileNotFoundError, match="Source audio not found"):
            svc.extend_loop(str(tmp_path / "none.wav"), str(tmp_path / "out.wav"), bars=8)

    def test_returns_output_path_and_metadata(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        output_path = str(tmp_path / "extended.wav")
        svc = AudioService()

        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=500)
        mock_audio.__mul__ = MagicMock(return_value=mock_audio)
        mock_audio.__getitem__ = MagicMock(return_value=mock_audio)
        mock_audio.export = MagicMock()

        with patch("pydub.AudioSegment.from_file", return_value=mock_audio):
            result_path, metadata = svc.extend_loop(wav_path, output_path, bars=4, bpm=120.0)

        assert result_path == output_path
        assert metadata["bars"] == 4
        assert metadata["bpm"] == 120.0
        assert "duration_seconds" in metadata
        assert "loops_repeated" in metadata

    def test_detects_bpm_when_not_provided(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        output_path = str(tmp_path / "out2.wav")
        svc = AudioService()

        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=500)
        mock_audio.__mul__ = MagicMock(return_value=mock_audio)
        mock_audio.__getitem__ = MagicMock(return_value=mock_audio)
        mock_audio.export = MagicMock()

        with (
            patch("pydub.AudioSegment.from_file", return_value=mock_audio),
            patch("librosa.load", return_value=(np.zeros(100), 22050)),
            patch("librosa.onset.onset_strength", return_value=np.zeros(50)),
            patch("librosa.beat.tempo", return_value=np.array([140.0])),
        ):
            _, metadata = svc.extend_loop(wav_path, output_path, bars=4)

        assert metadata["bpm"] == 140.0

    def test_propagates_exception_on_audio_load_failure(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        svc = AudioService()
        with patch("pydub.AudioSegment.from_file", side_effect=RuntimeError("bad audio")):
            with pytest.raises(RuntimeError, match="bad audio"):
                svc.extend_loop(wav_path, str(tmp_path / "out.wav"), bars=4, bpm=120.0)


# ---------------------------------------------------------------------------
# generate_full_beat
# ---------------------------------------------------------------------------


class TestGenerateFullBeat:
    def test_raises_file_not_found(self, tmp_path):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with pytest.raises(FileNotFoundError, match="Source audio not found"):
            svc.generate_full_beat(
                str(tmp_path / "none.wav"),
                str(tmp_path / "out.wav"),
                target_length_seconds=30,
            )

    def test_returns_path_and_metadata(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        output_path = str(tmp_path / "beat.wav")
        svc = AudioService()

        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=2000)
        mock_audio.__mul__ = MagicMock(return_value=mock_audio)
        mock_audio.__getitem__ = MagicMock(return_value=mock_audio)
        mock_audio.fade_in = MagicMock(return_value=mock_audio)
        mock_audio.fade_out = MagicMock(return_value=mock_audio)
        mock_audio.export = MagicMock()

        with patch("pydub.AudioSegment.from_file", return_value=mock_audio):
            result_path, metadata = svc.generate_full_beat(
                wav_path, output_path, target_length_seconds=10, bpm=120.0
            )

        assert result_path == output_path
        assert metadata["target_length_seconds"] == 10
        assert metadata["bpm"] == 120.0
        assert "loops_repeated" in metadata
        assert "fade_duration_ms" in metadata

    def test_detects_bpm_when_not_provided(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        output_path = str(tmp_path / "beat2.wav")
        svc = AudioService()

        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=1000)
        mock_audio.__mul__ = MagicMock(return_value=mock_audio)
        mock_audio.__getitem__ = MagicMock(return_value=mock_audio)
        mock_audio.fade_in = MagicMock(return_value=mock_audio)
        mock_audio.fade_out = MagicMock(return_value=mock_audio)
        mock_audio.export = MagicMock()

        with (
            patch("pydub.AudioSegment.from_file", return_value=mock_audio),
            patch("librosa.load", return_value=(np.zeros(100), 22050)),
            patch("librosa.onset.onset_strength", return_value=np.zeros(50)),
            patch("librosa.beat.tempo", return_value=np.array([100.0])),
        ):
            _, metadata = svc.generate_full_beat(wav_path, output_path, target_length_seconds=5)

        assert metadata["bpm"] == 100.0

    def test_applies_fade_when_audio_is_long_enough(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        output_path = str(tmp_path / "fade_test.wav")
        svc = AudioService()

        mock_audio = MagicMock()
        # Length > 2 * fade_duration (2000 ms) — fade applied
        mock_audio.__len__ = MagicMock(return_value=8000)
        mock_audio.__mul__ = MagicMock(return_value=mock_audio)
        mock_audio.__getitem__ = MagicMock(return_value=mock_audio)
        mock_audio.fade_in = MagicMock(return_value=mock_audio)
        mock_audio.fade_out = MagicMock(return_value=mock_audio)
        mock_audio.export = MagicMock()

        with patch("pydub.AudioSegment.from_file", return_value=mock_audio):
            svc.generate_full_beat(wav_path, output_path, target_length_seconds=8, bpm=120.0)

        mock_audio.fade_in.assert_called_once()
        mock_audio.fade_out.assert_called_once()

    def test_skips_fade_when_audio_too_short_for_double_fade(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        output_path = str(tmp_path / "no_fade.wav")
        svc = AudioService()

        mock_audio = MagicMock()
        # Very short: length <= 2 * fade_duration — no fade
        mock_audio.__len__ = MagicMock(return_value=10)
        mock_audio.__mul__ = MagicMock(return_value=mock_audio)
        mock_audio.__getitem__ = MagicMock(return_value=mock_audio)
        mock_audio.fade_in = MagicMock(return_value=mock_audio)
        mock_audio.fade_out = MagicMock(return_value=mock_audio)
        mock_audio.export = MagicMock()

        with patch("pydub.AudioSegment.from_file", return_value=mock_audio):
            svc.generate_full_beat(wav_path, output_path, target_length_seconds=10, bpm=120.0)

        mock_audio.fade_in.assert_not_called()

    def test_propagates_exception(self, tmp_path):
        from app.services.audio_service import AudioService

        wav_path = _make_wav_file(tmp_path)
        svc = AudioService()
        with patch("pydub.AudioSegment.from_file", side_effect=RuntimeError("codec error")):
            with pytest.raises(RuntimeError, match="codec error"):
                svc.generate_full_beat(
                    wav_path, str(tmp_path / "out.wav"), target_length_seconds=10, bpm=120.0
                )


# ---------------------------------------------------------------------------
# get_audio_info
# ---------------------------------------------------------------------------


class TestGetAudioInfo:
    def test_returns_expected_keys(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=3000)
        mock_audio.channels = 2
        mock_audio.sample_width = 2
        mock_audio.frame_rate = 44100
        mock_audio.frame_count = MagicMock(return_value=132300.0)

        with patch("pydub.AudioSegment.from_file", return_value=mock_audio):
            info = svc.get_audio_info("test.wav")

        assert "duration_seconds" in info
        assert "channels" in info
        assert "sample_width" in info
        assert "frame_rate" in info
        assert "frame_count" in info

    def test_duration_calculated_correctly(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        mock_audio = MagicMock()
        mock_audio.__len__ = MagicMock(return_value=5000)  # 5000 ms
        mock_audio.channels = 1
        mock_audio.sample_width = 2
        mock_audio.frame_rate = 22050
        mock_audio.frame_count = MagicMock(return_value=110250.0)

        with patch("pydub.AudioSegment.from_file", return_value=mock_audio):
            info = svc.get_audio_info("audio.wav")

        assert info["duration_seconds"] == pytest.approx(5.0)
        assert info["channels"] == 1
        assert info["frame_rate"] == 22050

    def test_propagates_exception(self):
        from app.services.audio_service import AudioService

        svc = AudioService()
        with patch("pydub.AudioSegment.from_file", side_effect=Exception("bad file")):
            with pytest.raises(Exception, match="bad file"):
                svc.get_audio_info("missing.wav")
