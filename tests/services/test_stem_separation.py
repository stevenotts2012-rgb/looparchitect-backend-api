"""Tests for the stem separation service, including the Demucs backend."""

from __future__ import annotations

import json
import subprocess
from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from app.services.stem_separation import (
    StemSeparationResult,
    _builtin_stems,
    _demucs_stems,
    separate_and_store_stems,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _silent_audio(duration_ms: int = 2000) -> AudioSegment:
    """Return a short silent stereo WAV segment."""
    return AudioSegment.silent(duration=duration_ms, frame_rate=44100)


# ---------------------------------------------------------------------------
# _builtin_stems
# ---------------------------------------------------------------------------

class TestBuiltinStems:
    def test_returns_four_stems(self):
        audio = _silent_audio()
        stems = _builtin_stems(audio)
        assert set(stems.keys()) == {"drums", "bass", "vocals", "other"}

    def test_stems_are_audio_segments(self):
        audio = _silent_audio()
        stems = _builtin_stems(audio)
        for name, seg in stems.items():
            assert isinstance(seg, AudioSegment), f"{name} is not an AudioSegment"


# ---------------------------------------------------------------------------
# _demucs_stems
# ---------------------------------------------------------------------------

class TestDemucsStems:
    """Tests for the Demucs subprocess wrapper."""

    def _make_fake_demucs(self, tmp_path: Path, audio: AudioSegment) -> None:
        """Pre-populate the expected Demucs output directory."""
        stem_dir = tmp_path / "out" / "htdemucs" / "input"
        stem_dir.mkdir(parents=True)
        for stem_name in ("drums", "bass", "vocals", "other"):
            audio.export(str(stem_dir / f"{stem_name}.wav"), format="wav")

    def test_success_returns_four_stems(self, tmp_path):
        audio = _silent_audio()

        def fake_run(cmd, timeout, capture_output, text):
            # Simulate Demucs writing output files
            out_dir = Path(cmd[cmd.index("--out") + 1])
            stem_dir = out_dir / "htdemucs" / "input"
            stem_dir.mkdir(parents=True, exist_ok=True)
            for stem_name in ("drums", "bass", "vocals", "other"):
                audio.export(str(stem_dir / f"{stem_name}.wav"), format="wav")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch("app.services.stem_separation.subprocess.run", side_effect=fake_run):
            stems = _demucs_stems(audio, timeout_seconds=30.0)

        assert set(stems.keys()) == {"drums", "bass", "vocals", "other"}
        for seg in stems.values():
            assert isinstance(seg, AudioSegment)

    def test_non_zero_exit_raises(self):
        audio = _silent_audio()

        def fake_run(cmd, timeout, capture_output, text):
            result = MagicMock()
            result.returncode = 1
            result.stderr = "Model not found"
            return result

        with patch("app.services.stem_separation.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="Demucs exited with code 1"):
                _demucs_stems(audio, timeout_seconds=30.0)

    def test_timeout_propagates(self):
        audio = _silent_audio()

        with patch(
            "app.services.stem_separation.subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="python -m demucs", timeout=5),
        ):
            with pytest.raises(subprocess.TimeoutExpired):
                _demucs_stems(audio, timeout_seconds=5.0)

    def test_missing_output_directory_raises(self):
        audio = _silent_audio()

        def fake_run(cmd, timeout, capture_output, text):
            # Does NOT write any files
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        with patch("app.services.stem_separation.subprocess.run", side_effect=fake_run):
            with pytest.raises(RuntimeError, match="output directory not found"):
                _demucs_stems(audio, timeout_seconds=30.0)


# ---------------------------------------------------------------------------
# separate_and_store_stems — demucs backend
# ---------------------------------------------------------------------------

class TestSeparateAndStoreStemsDemucs:
    """Integration-level tests for separate_and_store_stems with backend=demucs."""

    def _mock_storage(self) -> MagicMock:
        mock = MagicMock()
        mock.upload_file.return_value = None
        return mock

    def _make_demucs_run(self, audio: AudioSegment):
        """Return a fake subprocess.run that writes Demucs output files."""

        def fake_run(cmd, timeout, capture_output, text):
            out_dir = Path(cmd[cmd.index("--out") + 1])
            stem_dir = out_dir / "htdemucs" / "input"
            stem_dir.mkdir(parents=True, exist_ok=True)
            for stem_name in ("drums", "bass", "vocals", "other"):
                audio.export(str(stem_dir / f"{stem_name}.wav"), format="wav")
            result = MagicMock()
            result.returncode = 0
            result.stderr = ""
            return result

        return fake_run

    def test_demucs_success_returns_succeeded_true(self):
        audio = _silent_audio()

        with (
            patch("app.services.stem_separation.settings") as mock_settings,
            patch("app.services.stem_separation.storage") as mock_storage,
            patch(
                "app.services.stem_separation.subprocess.run",
                side_effect=self._make_demucs_run(audio),
            ),
        ):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs"
            mock_settings.demucs_timeout_seconds = 30

            result = separate_and_store_stems(source_audio=audio, loop_id=42, source_key="uploads/test.wav")

        assert result.succeeded is True
        assert result.enabled is True
        assert result.backend == "demucs"
        assert set(result.stems_generated) == {"drums", "bass", "vocals", "other"}
        assert set(result.stem_s3_keys.keys()) == {"drums", "bass", "vocals", "other"}

    def test_demucs_timeout_falls_back_to_builtin(self):
        audio = _silent_audio()

        with (
            patch("app.services.stem_separation.settings") as mock_settings,
            patch("app.services.stem_separation.storage") as mock_storage,
            patch(
                "app.services.stem_separation.subprocess.run",
                side_effect=subprocess.TimeoutExpired(cmd="demucs", timeout=1),
            ),
        ):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs"
            mock_settings.demucs_timeout_seconds = 1

            result = separate_and_store_stems(source_audio=audio, loop_id=42, source_key="uploads/test.wav")

        # Fallback to builtin still produces stems
        assert result.succeeded is True
        assert result.enabled is True
        assert len(result.stems_generated) == 4

    def test_demucs_error_falls_back_to_builtin(self):
        audio = _silent_audio()

        def failing_run(cmd, timeout, capture_output, text):
            result = MagicMock()
            result.returncode = 1
            result.stderr = "cuda out of memory"
            return result

        with (
            patch("app.services.stem_separation.settings") as mock_settings,
            patch("app.services.stem_separation.storage") as mock_storage,
            patch("app.services.stem_separation.subprocess.run", side_effect=failing_run),
        ):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs"
            mock_settings.demucs_timeout_seconds = 30

            result = separate_and_store_stems(source_audio=audio, loop_id=42, source_key="uploads/test.wav")

        assert result.succeeded is True
        assert len(result.stems_generated) == 4

    def test_feature_disabled_returns_not_enabled(self):
        audio = _silent_audio()

        with patch("app.services.stem_separation.settings") as mock_settings:
            mock_settings.feature_stem_separation = False
            mock_settings.stem_separation_backend = "demucs"

            result = separate_and_store_stems(source_audio=audio, loop_id=1, source_key="uploads/t.wav")

        assert result.enabled is False
        assert result.succeeded is False
        assert result.error == "feature_disabled"

    def test_result_to_dict_contains_stem_s3_keys(self):
        audio = _silent_audio()

        with (
            patch("app.services.stem_separation.settings") as mock_settings,
            patch("app.services.stem_separation.storage") as mock_storage,
            patch(
                "app.services.stem_separation.subprocess.run",
                side_effect=self._make_demucs_run(audio),
            ),
        ):
            mock_settings.feature_stem_separation = True
            mock_settings.stem_separation_backend = "demucs"
            mock_settings.demucs_timeout_seconds = 30

            result = separate_and_store_stems(source_audio=audio, loop_id=7, source_key="uploads/s.wav")

        d = result.to_dict()
        assert d["enabled"] is True
        assert d["succeeded"] is True
        assert isinstance(d["stem_s3_keys"], dict)
        assert all(k.startswith("stems/") for k in d["stem_s3_keys"].values())
