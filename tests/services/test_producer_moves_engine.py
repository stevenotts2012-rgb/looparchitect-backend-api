import os
import tempfile

from pydub import AudioSegment
from pydub.generators import Sine

from app.services.arrangement_jobs import _build_pre_render_plan
from app.services.render_executor import render_from_plan


REQUIRED_MOVE_TYPES = {
    "pre_hook_drum_mute",
    "silence_drop_before_hook",
    "hat_density_variation",
    "end_section_fill",
    "verse_melody_reduction",
    "bridge_bass_removal",
    "final_hook_expansion",
    "outro_strip_down",
    "call_response_variation",
}


def _bar_rms(audio: AudioSegment, bpm: float, bar_start: int, bars: int) -> float:
    bar_ms = int((60.0 / bpm) * 4.0 * 1000)
    start = bar_start * bar_ms
    end = start + max(1, bars) * bar_ms
    segment = audio[start:end]
    return float(segment.rms)


def test_producer_moves_injected_into_render_plan_events():
    producer_arrangement = {
        "tempo": 94.0,
        "key": "C",
        "total_bars": 48,
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 12, "energy": 0.55, "instruments": ["kick", "snare", "bass", "melody"]},
            {"name": "Hook 1", "type": "hook", "bar_start": 12, "bars": 8, "energy": 0.8, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
            {"name": "Bridge", "type": "bridge", "bar_start": 20, "bars": 8, "energy": 0.45, "instruments": ["pad", "bass", "melody"]},
            {"name": "Final Hook", "type": "hook", "bar_start": 28, "bars": 12, "energy": 0.92, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
            {"name": "Outro", "type": "outro", "bar_start": 40, "bars": 8, "energy": 0.35, "instruments": ["kick", "bass"]},
        ],
        "tracks": [],
    }

    plan = _build_pre_render_plan(
        arrangement_id=999,
        bpm=94.0,
        target_seconds=120,
        producer_arrangement=producer_arrangement,
        style_sections=None,
        genre_hint="rnb",
        stem_metadata={"enabled": True, "succeeded": True, "stem_s3_keys": {"bass": "stems/example_bass.wav"}},
    )

    event_types = {event.get("type") for event in plan.get("events", [])}
    missing = REQUIRED_MOVE_TYPES - event_types
    assert not missing, f"Missing move events: {sorted(missing)}"
    assert plan.get("render_profile", {}).get("producer_moves_enabled") is True


def test_hooks_are_louder_than_verses_and_final_hook_is_biggest():
    bpm = 96.0
    sections = [
        {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8, "energy": 0.5, "instruments": ["kick", "snare", "bass", "melody"]},
        {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8, "energy": 0.78, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
        {"name": "Verse 2", "type": "verse", "bar_start": 16, "bars": 8, "energy": 0.52, "instruments": ["kick", "snare", "bass", "melody"]},
        {"name": "Final Hook", "type": "hook", "bar_start": 24, "bars": 8, "energy": 0.95, "instruments": ["kick", "snare", "bass", "melody", "hats"]},
    ]

    base_plan = {
        "arrangement_id": 101,
        "bpm": bpm,
        "target_seconds": 80,
        "key": "C",
        "total_bars": 32,
        "sections": sections,
        "events": [{"type": "section_start", "bar": s["bar_start"], "description": f"{s['name']} starts"} for s in sections],
        "tracks": [],
        "render_profile": {
            "genre_profile": "rnb",
            "producer_arrangement_used": True,
            "stem_separation": {"enabled": False, "succeeded": False},
        },
    }

    render_plan = _build_pre_render_plan(
        arrangement_id=base_plan["arrangement_id"],
        bpm=bpm,
        target_seconds=base_plan["target_seconds"],
        producer_arrangement={
            "tempo": bpm,
            "key": "C",
            "total_bars": 32,
            "sections": sections,
            "tracks": [],
        },
        style_sections=None,
        genre_hint="rnb",
        stem_metadata={"enabled": False, "succeeded": False},
    )

    source = Sine(220).to_audio_segment(duration=1000).apply_gain(-8)
    source = source.overlay(Sine(880).to_audio_segment(duration=1000).apply_gain(-14))

    fd, temp_wav_path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    try:
        result = render_from_plan(render_plan_json=render_plan, audio_source=source, output_path=temp_wav_path)
        rendered = AudioSegment.from_wav(temp_wav_path)
    finally:
        if os.path.exists(temp_wav_path):
            os.remove(temp_wav_path)

    verse_rms = _bar_rms(rendered, bpm, bar_start=0, bars=8)
    first_hook_rms = _bar_rms(rendered, bpm, bar_start=8, bars=8)
    final_hook_rms = _bar_rms(rendered, bpm, bar_start=24, bars=8)

    assert first_hook_rms > verse_rms * 1.05
    assert final_hook_rms > first_hook_rms
    assert result.get("summary", {}).get("events_count", 0) > 0
