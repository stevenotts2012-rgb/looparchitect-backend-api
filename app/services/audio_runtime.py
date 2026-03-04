import logging
import shutil
from typing import Optional

from pydub import AudioSegment


logger = logging.getLogger(__name__)


def configure_audio_binaries(
    ffmpeg_binary: Optional[str] = None,
    ffprobe_binary: Optional[str] = None,
    raise_if_missing: bool = False,
) -> None:
    """Configure and validate ffmpeg/ffprobe binaries for pydub.

    Args:
        ffmpeg_binary: Optional explicit path to ffmpeg binary
        ffprobe_binary: Optional explicit path to ffprobe binary
        raise_if_missing: If True, raises RuntimeError when binaries are missing
    """
    ffmpeg_path = ffmpeg_binary or shutil.which("ffmpeg")
    ffprobe_path = ffprobe_binary or shutil.which("ffprobe")

    if ffmpeg_path:
        AudioSegment.converter = ffmpeg_path
    if ffprobe_path:
        AudioSegment.ffprobe = ffprobe_path

    missing: list[str] = []
    if not ffmpeg_path:
        missing.append("ffmpeg")
    if not ffprobe_path:
        missing.append("ffprobe")

    if missing:
        message = (
            "Missing required audio binaries: "
            f"{', '.join(missing)}. "
            "Install ffmpeg/ffprobe for reliable audio decoding across WAV/MP3/OGG/M4A."
        )
        if raise_if_missing:
            raise RuntimeError(message)
        logger.warning(message)
        return

    logger.info(
        "Audio binaries configured: ffmpeg=%s, ffprobe=%s",
        ffmpeg_path,
        ffprobe_path,
    )
