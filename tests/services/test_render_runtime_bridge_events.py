import json
from pydub.generators import Sine

from app.services.arrangement_jobs import _render_producer_arrangement


def test_bridge_runtime_applies_mute_and_delay_events_with_stems():
    loop_audio = Sine(220).to_audio_segment(duration=8000).set_channels(2)
    stem = Sine(220).to_audio_segment(duration=8000).set_channels(2)
    stems = {"drums": stem, "bass": stem, "pads": stem}

    producer_arrangement = {
        "tempo": 120,
        "sections": [
            {"name": "Verse", "type": "verse", "bar_start": 0, "bars": 4, "instruments": ["drums", "bass"]},
            {
                "name": "Bridge",
                "type": "bridge",
                "bar_start": 4,
                "bars": 4,
                "instruments": ["pads", "bass"],
                "variations": [
                    {"bar": 4, "variation_type": "mute_role", "duration_bars": 1, "intensity": 0.8},
                    {"bar": 5, "variation_type": "delay_role", "duration_bars": 1, "intensity": 0.8},
                ],
            },
        ],
    }

    _audio, timeline_json = _render_producer_arrangement(loop_audio, producer_arrangement, bpm=120, stems=stems)
    timeline = json.loads(timeline_json)
    bridge = next(s for s in timeline["sections"] if str(s.get("type")) == "bridge")

    assert bridge["applied_events"], "bridge applied_events should not be empty"
    assert "mute_role" in bridge["applied_events"]
    assert "delay_role" in bridge["applied_events"]
