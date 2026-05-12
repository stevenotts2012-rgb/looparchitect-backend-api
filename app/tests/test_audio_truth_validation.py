from pydub import AudioSegment
from pydub.generators import Sine

from app.services.audio_renderer import _section_audio_metrics


def _mix(melody_db=-2.0, bass_db=-2.0, drum_db=-2.0):
    melody = Sine(1200).to_audio_segment(duration=2000).apply_gain(melody_db)
    bass = Sine(90).to_audio_segment(duration=2000).apply_gain(bass_db)
    drum = Sine(3500).to_audio_segment(duration=2000).apply_gain(drum_db)
    return melody.overlay(bass).overlay(drum)


def test_muted_melody_fails_audibility_ratio():
    audio = _mix(melody_db=-30, bass_db=-2, drum_db=-2)
    m = _section_audio_metrics(audio)
    assert m["melody_to_rhythm_ratio"] < -6
    assert m["melody_masking_score"] > 0.55


def test_overpowering_rhythm_detected_as_masking():
    audio = _mix(melody_db=-14, bass_db=-1, drum_db=-1)
    m = _section_audio_metrics(audio)
    assert m["melody_masking_score"] > 0.5


def test_hook_melody_lift_increases_measured_melodic_rms():
    buried = _mix(melody_db=-16, bass_db=-2, drum_db=-2)
    lifted = _mix(melody_db=-8, bass_db=-2, drum_db=-2)
    before = _section_audio_metrics(buried)
    after = _section_audio_metrics(lifted)
    assert after["melodic_rms"] > before["melodic_rms"]
