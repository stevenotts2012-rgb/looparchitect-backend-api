"""Tests for app/services/audio_runtime.py — configure_audio_binaries."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestConfigureAudioBinariesWithSystemBinaries:
    """Tests when system ffmpeg/ffprobe binaries are found via shutil.which."""

    def test_sets_converter_and_ffprobe_from_system(self):
        import pydub
        from app.services.audio_runtime import configure_audio_binaries

        with patch("shutil.which", side_effect=lambda x: f"/usr/bin/{x}"):
            configure_audio_binaries()

        assert pydub.AudioSegment.converter == "/usr/bin/ffmpeg"
        assert pydub.AudioSegment.ffprobe == "/usr/bin/ffprobe"

    def test_explicit_binaries_take_precedence_over_system(self):
        import pydub
        from app.services.audio_runtime import configure_audio_binaries

        configure_audio_binaries(
            ffmpeg_binary="/opt/custom/ffmpeg",
            ffprobe_binary="/opt/custom/ffprobe",
        )

        assert pydub.AudioSegment.converter == "/opt/custom/ffmpeg"
        assert pydub.AudioSegment.ffprobe == "/opt/custom/ffprobe"

    def test_only_ffmpeg_explicit_uses_system_ffprobe(self):
        import pydub
        from app.services.audio_runtime import configure_audio_binaries

        with patch("shutil.which", return_value="/usr/bin/ffprobe"):
            configure_audio_binaries(ffmpeg_binary="/custom/ffmpeg")

        assert pydub.AudioSegment.converter == "/custom/ffmpeg"


class TestConfigureAudioBinariesWithImageioFallback:
    """Tests the imageio-ffmpeg fallback path when system binaries are absent."""

    def test_falls_back_to_imageio_ffmpeg_for_ffmpeg_binary(self):
        import pydub
        from app.services.audio_runtime import configure_audio_binaries

        mock_imageio = MagicMock()
        mock_imageio.get_ffmpeg_exe.return_value = "/bundled/ffmpeg"

        with (
            patch("shutil.which", return_value=None),
            patch.dict("sys.modules", {"imageio_ffmpeg": mock_imageio}),
        ):
            configure_audio_binaries()

        assert pydub.AudioSegment.converter == "/bundled/ffmpeg"

    def test_imageio_ffprobe_set_when_file_exists(self, tmp_path):
        import pydub
        from app.services.audio_runtime import configure_audio_binaries

        # Create a fake bundled ffmpeg and a matching ffprobe.exe
        bundled_ffmpeg = tmp_path / "ffmpeg"
        bundled_ffmpeg.touch()
        bundled_ffprobe = tmp_path / "ffprobe.exe"
        bundled_ffprobe.touch()

        mock_imageio = MagicMock()
        mock_imageio.get_ffmpeg_exe.return_value = str(bundled_ffmpeg)

        with (
            patch("shutil.which", return_value=None),
            patch.dict("sys.modules", {"imageio_ffmpeg": mock_imageio}),
        ):
            configure_audio_binaries()

        assert pydub.AudioSegment.converter == str(bundled_ffmpeg)
        assert pydub.AudioSegment.ffprobe == str(bundled_ffprobe)

    def test_handles_imageio_exception_gracefully(self):
        from app.services.audio_runtime import configure_audio_binaries

        mock_imageio = MagicMock()
        mock_imageio.get_ffmpeg_exe.side_effect = RuntimeError("bundled not found")

        with (
            patch("shutil.which", return_value=None),
            patch.dict("sys.modules", {"imageio_ffmpeg": mock_imageio}),
        ):
            # Should not raise
            configure_audio_binaries(raise_if_missing=False)

    def test_handles_imageio_import_error(self):
        from app.services.audio_runtime import configure_audio_binaries
        import sys

        # Remove imageio_ffmpeg from sys.modules so the import fails
        original = sys.modules.pop("imageio_ffmpeg", None)
        try:
            with patch("shutil.which", return_value=None):
                # Should not raise
                configure_audio_binaries(raise_if_missing=False)
        finally:
            if original is not None:
                sys.modules["imageio_ffmpeg"] = original


class TestConfigureAudioBinariesMissingBinaries:
    """Tests when binaries cannot be found anywhere."""

    def test_warns_but_does_not_raise_by_default(self):
        from app.services.audio_runtime import configure_audio_binaries
        import sys

        mock_imageio = MagicMock()
        mock_imageio.get_ffmpeg_exe.return_value = None

        with (
            patch("shutil.which", return_value=None),
            patch.dict("sys.modules", {"imageio_ffmpeg": mock_imageio}),
        ):
            # Should not raise (raise_if_missing defaults to False)
            configure_audio_binaries()

    def test_raises_runtime_error_when_required(self):
        from app.services.audio_runtime import configure_audio_binaries

        mock_imageio = MagicMock()
        mock_imageio.get_ffmpeg_exe.return_value = None

        with (
            patch("shutil.which", return_value=None),
            patch.dict("sys.modules", {"imageio_ffmpeg": mock_imageio}),
        ):
            with pytest.raises(RuntimeError, match="Missing required audio binaries"):
                configure_audio_binaries(raise_if_missing=True)

    def test_error_message_mentions_ffmpeg_and_ffprobe(self):
        from app.services.audio_runtime import configure_audio_binaries

        mock_imageio = MagicMock()
        mock_imageio.get_ffmpeg_exe.return_value = None

        with (
            patch("shutil.which", return_value=None),
            patch.dict("sys.modules", {"imageio_ffmpeg": mock_imageio}),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                configure_audio_binaries(raise_if_missing=True)

        msg = str(exc_info.value)
        assert "ffmpeg" in msg.lower()
        assert "ffprobe" in msg.lower()

    def test_only_ffprobe_missing_raises_with_ffprobe_in_message(self):
        from app.services.audio_runtime import configure_audio_binaries

        mock_imageio = MagicMock()
        mock_imageio.get_ffmpeg_exe.return_value = None

        def _which(name):
            return "/usr/bin/ffmpeg" if name == "ffmpeg" else None

        with (
            patch("shutil.which", side_effect=_which),
            patch.dict("sys.modules", {"imageio_ffmpeg": mock_imageio}),
        ):
            with pytest.raises(RuntimeError) as exc_info:
                configure_audio_binaries(raise_if_missing=True)

        assert "ffprobe" in str(exc_info.value)
        assert "ffmpeg" not in str(exc_info.value).replace("ffprobe", "").lower().split("missing")[0]
