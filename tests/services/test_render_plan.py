"""Unit tests for RenderPlanGenerator."""

from __future__ import annotations

import pytest

from app.services.render_plan import RenderPlanGenerator
from app.services.producer_models import (
    EnergyPoint,
    InstrumentType,
    ProducerArrangement,
    RenderEvent,
    RenderPlan,
    Section,
    SectionType,
    Track,
    Variation,
    VariationType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_arrangement(sections: list[Section] | None = None) -> ProducerArrangement:
    """Build a minimal ProducerArrangement for testing."""
    arr = ProducerArrangement(
        tempo=120.0,
        key="C",
        total_bars=32,
        total_seconds=64.0,
        genre="trap",
    )
    if sections is not None:
        arr.sections = sections
    else:
        arr.sections = [
            Section(
                name="Intro",
                section_type=SectionType.INTRO,
                bar_start=0,
                bars=8,
                energy_level=0.3,
                instruments=[InstrumentType.KICK, InstrumentType.HATS],
            ),
            Section(
                name="Verse",
                section_type=SectionType.VERSE,
                bar_start=8,
                bars=16,
                energy_level=0.6,
                instruments=[InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.BASS],
            ),
            Section(
                name="Hook",
                section_type=SectionType.HOOK,
                bar_start=24,
                bars=8,
                energy_level=0.9,
                instruments=[
                    InstrumentType.KICK,
                    InstrumentType.SNARE,
                    InstrumentType.BASS,
                    InstrumentType.LEAD,
                ],
            ),
        ]
    return arr


# ---------------------------------------------------------------------------
# generate()
# ---------------------------------------------------------------------------


class TestRenderPlanGeneratorGenerate:
    def test_returns_render_plan(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        assert isinstance(plan, RenderPlan)

    def test_plan_tempo_matches(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        assert plan.bpm == arr.tempo

    def test_plan_key_matches(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        assert plan.key == arr.key

    def test_plan_total_bars_matches(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        assert plan.total_bars == arr.total_bars

    def test_sections_count_matches(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        assert len(plan.sections) == len(arr.sections)

    def test_section_metadata_structure(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)

        for section_meta in plan.sections:
            assert "name" in section_meta
            assert "type" in section_meta
            assert "bar_start" in section_meta
            assert "bars" in section_meta
            assert "energy" in section_meta
            assert "instruments" in section_meta

    def test_section_instrument_values_are_strings(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        for section_meta in plan.sections:
            for instrument in section_meta["instruments"]:
                assert isinstance(instrument, str)

    def test_events_list_present(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        assert isinstance(plan.events, list)

    def test_events_contain_enter_for_new_instruments(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)

        enter_events = [e for e in plan.events if e.event_type == "enter"]
        assert len(enter_events) > 0

    def test_events_contain_exit_when_instrument_removed(self):
        """Hook removes HATS from intro/verse → exit event expected."""
        arr = _make_arrangement()
        # Add hats to verse but remove from hook
        arr.sections[1].instruments = [
            InstrumentType.KICK,
            InstrumentType.SNARE,
            InstrumentType.BASS,
            InstrumentType.HATS,
        ]
        arr.sections[2].instruments = [
            InstrumentType.KICK,
            InstrumentType.SNARE,
            InstrumentType.BASS,
            InstrumentType.LEAD,
        ]
        plan = RenderPlanGenerator.generate(arr)
        exit_events = [e for e in plan.events if e.event_type == "exit"]
        assert len(exit_events) > 0

    def test_events_sorted_by_bar(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        bars = [e.bar for e in plan.events]
        assert bars == sorted(bars)

    def test_variation_events_included(self):
        arr = _make_arrangement()
        arr.sections[1].variations = [
            Variation(bar=10, section_index=1, variation_type=VariationType.DRUM_FILL, intensity=0.8),
        ]
        plan = RenderPlanGenerator.generate(arr)
        variation_events = [e for e in plan.events if e.event_type == "variation"]
        assert len(variation_events) == 1
        assert variation_events[0].bar == 10

    def test_empty_arrangement_returns_empty_plan(self):
        arr = _make_arrangement(sections=[])
        plan = RenderPlanGenerator.generate(arr)
        assert plan.sections == []
        assert plan.events == []

    def test_tracks_metadata_from_arrangement(self):
        arr = _make_arrangement()
        arr.tracks = [
            Track(name="Kick", instrument=InstrumentType.KICK, volume_db=-3.0),
            Track(name="Bass", instrument=InstrumentType.BASS, volume_db=-6.0),
        ]
        plan = RenderPlanGenerator.generate(arr)
        assert len(plan.tracks) == 2
        track_names = {t["name"] for t in plan.tracks}
        assert "Kick" in track_names
        assert "Bass" in track_names

    def test_tracks_metadata_structure(self):
        arr = _make_arrangement()
        arr.tracks = [
            Track(name="Kick", instrument=InstrumentType.KICK, volume_db=-3.0, pan_left_right=0.1),
        ]
        plan = RenderPlanGenerator.generate(arr)
        track = plan.tracks[0]
        assert track["name"] == "Kick"
        assert track["instrument"] == InstrumentType.KICK.value
        assert track["volume_db"] == -3.0
        assert track["enabled"] is True


# ---------------------------------------------------------------------------
# _get_track_name()
# ---------------------------------------------------------------------------


class TestGetTrackName:
    @pytest.mark.parametrize("instrument,expected_name", [
        (InstrumentType.KICK, "Kick"),
        (InstrumentType.SNARE, "Snare"),
        (InstrumentType.HATS, "Hi-Hats"),
        (InstrumentType.CLAP, "Clap"),
        (InstrumentType.PERCUSSION, "Percussion"),
        (InstrumentType.BASS, "Bass"),
        (InstrumentType.PAD, "Pad"),
        (InstrumentType.LEAD, "Lead"),
        (InstrumentType.MELODY, "Melody"),
        (InstrumentType.SYNTH, "Synth"),
        (InstrumentType.FX, "Effects"),
        (InstrumentType.VOCAL, "Vocal"),
        (InstrumentType.STRINGS, "Strings"),
        (InstrumentType.HORN, "Horn"),
    ])
    def test_known_instrument_name(self, instrument, expected_name):
        assert RenderPlanGenerator._get_track_name(instrument) == expected_name


# ---------------------------------------------------------------------------
# RenderPlan.to_dict() / to_json()
# ---------------------------------------------------------------------------


class TestRenderPlanSerialization:
    def test_to_dict_returns_dict(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        d = plan.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_keys(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        d = plan.to_dict()
        assert "bpm" in d
        assert "key" in d
        assert "total_bars" in d
        assert "sections" in d
        assert "events" in d
        assert "tracks" in d

    def test_to_dict_events_structure(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        d = plan.to_dict()
        for event in d["events"]:
            assert "bar" in event
            assert "track" in event
            assert "type" in event
            assert "description" in event

    def test_to_json_returns_string(self):
        arr = _make_arrangement()
        plan = RenderPlanGenerator.generate(arr)
        import json
        json_str = plan.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["bpm"] == arr.tempo

    def test_round_trip_bpm(self):
        arr = _make_arrangement()
        arr.tempo = 140.0
        plan = RenderPlanGenerator.generate(arr)
        import json
        d = json.loads(plan.to_json())
        assert d["bpm"] == 140.0
