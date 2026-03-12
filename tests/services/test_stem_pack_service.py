import io

import pytest
from pydub import AudioSegment
from pydub.generators import Sine

from app.services.stem_pack_service import StemPackError, StemSourceFile, ingest_stem_files


def _wav_bytes(*, frequency: int, duration_ms: int, frame_rate: int = 44100) -> bytes:
    segment = Sine(frequency).to_audio_segment(duration=duration_ms).set_frame_rate(frame_rate)
    buffer = io.BytesIO()
    segment.export(buffer, format="wav")
    return buffer.getvalue()


def _wav_bytes_with_lead_silence(*, frequency: int, duration_ms: int, lead_ms: int, frame_rate: int = 44100) -> bytes:
    tone = Sine(frequency).to_audio_segment(duration=duration_ms).set_frame_rate(frame_rate)
    segment = AudioSegment.silent(duration=lead_ms) + tone
    buffer = io.BytesIO()
    segment.export(buffer, format="wav")
    return buffer.getvalue()


def test_ingest_stem_files_detects_roles_from_filenames() -> None:
    result = ingest_stem_files(
        [
            StemSourceFile(filename="kick.wav", content=_wav_bytes(frequency=80, duration_ms=1000)),
            StemSourceFile(filename="sub_bass.wav", content=_wav_bytes(frequency=55, duration_ms=1000)),
            StemSourceFile(filename="lead_synth.wav", content=_wav_bytes(frequency=440, duration_ms=1000)),
            StemSourceFile(filename="pad.wav", content=_wav_bytes(frequency=330, duration_ms=1000)),
            StemSourceFile(filename="fx_riser.wav", content=_wav_bytes(frequency=2000, duration_ms=1000)),
        ]
    )

    assert result.roles_detected == ["bass", "drums", "fx", "harmony", "melody"]
    assert result.sample_rate == 44100
    assert result.duration_ms == 1000
    assert result.role_sources["drums"] == ["kick.wav"]
    assert result.role_sources["bass"] == ["sub_bass.wav"]
    assert len(result.mixed_preview) == 1000


def test_ingest_stem_files_rejects_misaligned_lengths() -> None:
    with pytest.raises(StemPackError, match="same length"):
        ingest_stem_files(
            [
                StemSourceFile(filename="kick.wav", content=_wav_bytes(frequency=80, duration_ms=1000)),
                StemSourceFile(filename="bass.wav", content=_wav_bytes(frequency=55, duration_ms=1300)),
            ]
        )


def test_ingest_stem_files_normalizes_sample_rate() -> None:
    result = ingest_stem_files(
        [
            StemSourceFile(filename="kick.wav", content=_wav_bytes(frequency=80, duration_ms=1200, frame_rate=44100)),
            StemSourceFile(filename="bass.wav", content=_wav_bytes(frequency=55, duration_ms=1200, frame_rate=48000)),
        ]
    )

    assert result.sample_rate == 44100
    assert result.duration_ms == 1200
    assert result.roles_detected == ["bass", "drums"]


def test_ingest_stem_files_rejects_start_offset_misalignment() -> None:
    with pytest.raises(StemPackError, match="misaligned"):
        ingest_stem_files(
            [
                StemSourceFile(
                    filename="kick.wav",
                    content=_wav_bytes_with_lead_silence(frequency=80, duration_ms=1000, lead_ms=0),
                ),
                StemSourceFile(
                    filename="bass.wav",
                    content=_wav_bytes_with_lead_silence(frequency=55, duration_ms=1000, lead_ms=120),
                ),
            ]
        )
