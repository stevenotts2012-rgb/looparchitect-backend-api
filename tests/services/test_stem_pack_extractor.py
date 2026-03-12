import io
import zipfile

import pytest

from app.services.stem_pack_extractor import (
    StemPackExtractionError,
    extract_stem_files_from_zip,
)


def _zip_bytes(file_map: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w") as archive:
        for name, content in file_map.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_extract_stem_files_from_zip_reads_audio_files_only() -> None:
    payload = _zip_bytes(
        {
            "pack/drums.wav": b"RIFF....WAVE",
            "pack/bass.mp3": b"ID3....",
            "pack/readme.txt": b"ignore me",
        }
    )

    extracted = extract_stem_files_from_zip(payload)
    names = sorted(item.filename for item in extracted)

    assert names == ["bass.mp3", "drums.wav"]


def test_extract_stem_files_from_zip_rejects_invalid_archive() -> None:
    with pytest.raises(StemPackExtractionError, match="Invalid ZIP"):
        extract_stem_files_from_zip(b"not a zip")
