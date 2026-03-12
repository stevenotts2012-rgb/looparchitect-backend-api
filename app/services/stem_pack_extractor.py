"""ZIP stem-pack extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass
import io
from pathlib import Path
import zipfile


ALLOWED_AUDIO_EXTENSIONS = {".wav", ".mp3", ".ogg", ".flac"}


class StemPackExtractionError(ValueError):
    pass


@dataclass
class ExtractedStemFile:
    filename: str
    content: bytes


def extract_stem_files_from_zip(stem_zip: bytes) -> list[ExtractedStemFile]:
    """Extract supported audio files from a zip archive.

    Returns a flat list of extracted files using base names only.
    """
    extracted: list[ExtractedStemFile] = []
    try:
        with zipfile.ZipFile(io.BytesIO(stem_zip)) as archive:
            for name in archive.namelist():
                if name.endswith("/"):
                    continue
                ext = Path(name).suffix.lower()
                if ext not in ALLOWED_AUDIO_EXTENSIONS:
                    continue
                extracted.append(
                    ExtractedStemFile(
                        filename=Path(name).name,
                        content=archive.read(name),
                    )
                )
    except zipfile.BadZipFile as exc:
        raise StemPackExtractionError("Invalid ZIP stem pack") from exc

    if not extracted:
        raise StemPackExtractionError("ZIP does not contain supported audio stem files")

    return extracted
