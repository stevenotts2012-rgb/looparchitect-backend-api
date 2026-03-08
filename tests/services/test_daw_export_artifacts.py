import io
import zipfile

from pydub import AudioSegment
from pydub.generators import Sine

from app.services.daw_export import DAWExporter


def test_build_export_zip_creates_real_artifacts():
    full_mix = (
        Sine(60).to_audio_segment(duration=1200).apply_gain(-8)
        .overlay(Sine(180).to_audio_segment(duration=1200).apply_gain(-10))
        .overlay(Sine(880).to_audio_segment(duration=1200).apply_gain(-14))
    )

    sections = [
        {"name": "Intro", "bar_start": 0, "bars": 2},
        {"name": "Hook", "bar_start": 2, "bars": 2},
    ]

    zip_bytes, contents = DAWExporter.build_export_zip(
        arrangement_id=123,
        full_mix=full_mix,
        bpm=120.0,
        musical_key="C",
        sections=sections,
        midi_files={},
    )

    assert zip_bytes
    assert len(zip_bytes) > 0

    archive = zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r")
    names = sorted(archive.namelist())

    expected_stems = {
        "stems/kick.wav",
        "stems/bass.wav",
        "stems/snare.wav",
        "stems/hats.wav",
        "stems/melody.wav",
        "stems/pads.wav",
    }

    assert expected_stems.issubset(set(names))
    assert "markers.csv" in names
    assert "tempo_map.json" in names
    assert "README.txt" in names

    for path in expected_stems:
        payload = archive.read(path)
        assert payload
        assert len(payload) > 44  # beyond WAV header-only size

    durations = []
    for path in expected_stems:
        audio = AudioSegment.from_wav(io.BytesIO(archive.read(path)))
        durations.append(len(audio))

    assert all(duration > 0 for duration in durations)
    assert len(set(durations)) == 1

    assert contents["metadata"] == ["markers.csv", "tempo_map.json", "README.txt"]
    assert set(contents["stems"]) == expected_stems
    assert contents["midi"] == []
