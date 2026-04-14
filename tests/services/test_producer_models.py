"""Unit tests for producer_models data structures."""

from __future__ import annotations

import json
import pytest

from app.services.producer_models import (
    EnergyPoint,
    InstrumentLayer,
    InstrumentType,
    ProducerArrangement,
    RenderEvent,
    RenderPlan,
    Section,
    SectionLayering,
    SectionType,
    StyleProfile,
    Track,
    Transition,
    TransitionType,
    Variation,
    VariationType,
)


# ---------------------------------------------------------------------------
# Enum smoke tests
# ---------------------------------------------------------------------------


class TestEnumValues:
    def test_section_type_values(self):
        assert SectionType.INTRO == "Intro"
        assert SectionType.VERSE == "Verse"
        assert SectionType.HOOK == "Hook"
        assert SectionType.CHORUS == "Chorus"
        assert SectionType.BRIDGE == "Bridge"
        assert SectionType.BREAKDOWN == "Breakdown"
        assert SectionType.OUTRO == "Outro"
        assert SectionType.TRANSITION == "Transition"

    def test_instrument_type_has_expected_members(self):
        expected = {
            "KICK", "SNARE", "HATS", "CLAP", "PERCUSSION",
            "BASS", "PAD", "LEAD", "MELODY", "SYNTH",
            "FX", "VOCAL", "STRINGS", "HORN",
        }
        actual = {member.name for member in InstrumentType}
        assert expected == actual

    def test_transition_type_values(self):
        assert TransitionType.DRUM_FILL == "drum_fill"
        assert TransitionType.RISER == "riser"
        assert TransitionType.CROSSFADE == "crossfade"

    def test_variation_type_values(self):
        assert VariationType.HIHAT_ROLL == "hihat_roll"
        assert VariationType.DRUM_FILL == "drum_fill"
        assert VariationType.INSTRUMENT_DROPOUT == "instrument_dropout"


# ---------------------------------------------------------------------------
# Section
# ---------------------------------------------------------------------------


class TestSection:
    def test_bar_end_computed(self):
        section = Section(name="Verse", section_type=SectionType.VERSE, bar_start=8, bars=16)
        # bar_end should be bar_start + bars - 1
        assert section.bar_end == 23

    def test_bar_end_single_bar(self):
        section = Section(name="Fill", section_type=SectionType.TRANSITION, bar_start=0, bars=1)
        assert section.bar_end == 0

    def test_default_energy_level(self):
        section = Section(name="Intro", section_type=SectionType.INTRO)
        assert section.energy_level == 0.5

    def test_default_instruments_empty(self):
        section = Section()
        assert section.instruments == []

    def test_default_variations_empty(self):
        section = Section()
        assert section.variations == []


# ---------------------------------------------------------------------------
# InstrumentLayer
# ---------------------------------------------------------------------------


class TestInstrumentLayer:
    def test_has_instrument_true(self):
        layer = InstrumentLayer(
            section_type=SectionType.HOOK,
            instruments=[InstrumentType.KICK, InstrumentType.BASS],
        )
        assert layer.has_instrument(InstrumentType.KICK) is True
        assert layer.has_instrument(InstrumentType.BASS) is True

    def test_has_instrument_false(self):
        layer = InstrumentLayer(
            section_type=SectionType.HOOK,
            instruments=[InstrumentType.KICK],
        )
        assert layer.has_instrument(InstrumentType.VOCAL) is False

    def test_has_instrument_empty_layer(self):
        layer = InstrumentLayer(section_type=SectionType.VERSE, instruments=[])
        assert layer.has_instrument(InstrumentType.KICK) is False


# ---------------------------------------------------------------------------
# ProducerArrangement.to_dict()
# ---------------------------------------------------------------------------


class TestProducerArrangementToDict:
    def _make_arrangement(self) -> ProducerArrangement:
        arr = ProducerArrangement(
            tempo=120.0,
            key="C",
            total_bars=32,
            total_seconds=64.0,
            genre="trap",
            drum_style="programmed",
            melody_style="melodic",
            bass_style="sub",
        )
        arr.sections = [
            Section(
                name="Intro",
                section_type=SectionType.INTRO,
                bar_start=0,
                bars=8,
                energy_level=0.4,
                instruments=[InstrumentType.KICK],
            )
        ]
        arr.energy_curve = [EnergyPoint(bar=0, energy=0.4, description="Intro")]
        arr.tracks = [Track(name="Kick", instrument=InstrumentType.KICK, volume_db=-3.0)]
        arr.all_variations = [
            Variation(bar=6, section_index=0, variation_type=VariationType.DRUM_FILL, intensity=0.7)
        ]
        return arr

    def test_to_dict_returns_dict(self):
        arr = self._make_arrangement()
        d = arr.to_dict()
        assert isinstance(d, dict)

    def test_to_dict_required_keys(self):
        arr = self._make_arrangement()
        d = arr.to_dict()
        for key in ("tempo", "key", "total_bars", "total_seconds", "sections", "energy_curve",
                    "tracks", "genre", "drum_style", "melody_style", "bass_style",
                    "is_valid", "validation_errors"):
            assert key in d, f"Missing key: {key}"

    def test_to_dict_section_structure(self):
        arr = self._make_arrangement()
        d = arr.to_dict()
        assert len(d["sections"]) == 1
        section = d["sections"][0]
        assert section["name"] == "Intro"
        assert section["type"] == SectionType.INTRO.value
        assert section["bar_start"] == 0
        assert section["bars"] == 8
        assert section["energy"] == 0.4
        assert InstrumentType.KICK.value in section["instruments"]

    def test_to_dict_energy_curve(self):
        arr = self._make_arrangement()
        d = arr.to_dict()
        assert len(d["energy_curve"]) == 1
        assert d["energy_curve"][0]["bar"] == 0
        assert d["energy_curve"][0]["energy"] == 0.4

    def test_to_dict_tracks(self):
        arr = self._make_arrangement()
        d = arr.to_dict()
        assert len(d["tracks"]) == 1
        track = d["tracks"][0]
        assert track["name"] == "Kick"
        assert track["instrument"] == InstrumentType.KICK.value
        assert track["volume_db"] == -3.0
        assert track["enabled"] is True

    def test_to_dict_no_layering_plan(self):
        arr = self._make_arrangement()
        d = arr.to_dict()
        assert d["layering_plan"] is None

    def test_to_dict_with_layering_plan(self):
        arr = self._make_arrangement()
        arr.layering_plan = [
            SectionLayering(
                section_name="Intro",
                active_elements=["kick"],
                muted_elements=[],
                introduced_elements=["kick"],
                removed_elements=[],
                transition_in=None,
                transition_out=None,
                variation_strategy=None,
                energy_level=0.4,
            )
        ]
        d = arr.to_dict()
        assert d["layering_plan"] is not None
        assert len(d["layering_plan"]) == 1

    def test_to_json_is_valid_json(self):
        arr = self._make_arrangement()
        json_str = arr.to_json()
        assert isinstance(json_str, str)
        parsed = json.loads(json_str)
        assert parsed["tempo"] == 120.0

    def test_to_json_round_trip_tempo(self):
        arr = self._make_arrangement()
        arr.tempo = 140.5
        parsed = json.loads(arr.to_json())
        assert parsed["tempo"] == 140.5

    def test_to_json_round_trip_key(self):
        arr = self._make_arrangement()
        arr.key = "F#"
        parsed = json.loads(arr.to_json())
        assert parsed["key"] == "F#"


# ---------------------------------------------------------------------------
# StyleProfile
# ---------------------------------------------------------------------------


class TestStyleProfile:
    def test_to_dict_keys(self):
        profile = StyleProfile(
            genre="trap",
            bpm_range=(85, 115),
            energy=0.8,
            drum_style="programmed",
            melody_style="melodic",
            bass_style="sub",
            structure_template="standard",
            description="Trap vibe",
            references=["southside"],
        )
        d = profile.to_dict()
        assert d["genre"] == "trap"
        assert d["bpm_range"] == (85, 115)
        assert d["energy"] == 0.8
        assert d["drum_style"] == "programmed"
        assert d["references"] == ["southside"]

    def test_to_json_round_trip(self):
        profile = StyleProfile(
            genre="rnb",
            bpm_range=(80, 100),
            energy=0.6,
            drum_style="live",
            melody_style="melodic",
            bass_style="synth",
        )
        parsed = json.loads(profile.to_json())
        assert parsed["genre"] == "rnb"

    def test_default_references_is_empty(self):
        profile = StyleProfile()
        assert profile.references == []

    def test_default_energy_is_half(self):
        profile = StyleProfile()
        assert profile.energy == 0.5


# ---------------------------------------------------------------------------
# RenderPlan
# ---------------------------------------------------------------------------


class TestRenderPlan:
    def test_to_dict_has_expected_keys(self):
        plan = RenderPlan(
            bpm=120.0,
            key="C",
            total_bars=32,
            sections=[{"name": "Intro"}],
            events=[],
            tracks=[],
        )
        d = plan.to_dict()
        assert "bpm" in d
        assert "key" in d
        assert "total_bars" in d
        assert "sections" in d
        assert "events" in d
        assert "tracks" in d

    def test_to_dict_events_serialization(self):
        plan = RenderPlan(
            bpm=120.0,
            key="C",
            total_bars=32,
            sections=[],
            events=[
                RenderEvent(bar=0, track_name="Kick", event_type="enter", description="Kick enters")
            ],
            tracks=[],
        )
        d = plan.to_dict()
        assert len(d["events"]) == 1
        event = d["events"][0]
        assert event["bar"] == 0
        assert event["track"] == "Kick"
        assert event["type"] == "enter"

    def test_to_json_valid(self):
        plan = RenderPlan(bpm=90.0, key="Am", total_bars=16, sections=[], events=[], tracks=[])
        j = plan.to_json()
        parsed = json.loads(j)
        assert parsed["bpm"] == 90.0
        assert parsed["key"] == "Am"


# ---------------------------------------------------------------------------
# Track defaults
# ---------------------------------------------------------------------------


class TestTrack:
    def test_default_volume_db(self):
        track = Track(name="Kick", instrument=InstrumentType.KICK)
        assert track.volume_db == 0.0

    def test_default_pan(self):
        track = Track(name="Kick", instrument=InstrumentType.KICK)
        assert track.pan_left_right == 0.0

    def test_default_enabled(self):
        track = Track(name="Kick", instrument=InstrumentType.KICK)
        assert track.enabled is True

    def test_default_effects_empty(self):
        track = Track(name="Kick", instrument=InstrumentType.KICK)
        assert track.effects == []


# ---------------------------------------------------------------------------
# Variation
# ---------------------------------------------------------------------------


class TestVariation:
    def test_default_intensity(self):
        v = Variation(bar=4, section_index=0, variation_type=VariationType.DRUM_FILL)
        assert v.intensity == 0.5

    def test_custom_intensity(self):
        v = Variation(bar=4, section_index=0, variation_type=VariationType.INSTRUMENT_DROPOUT, intensity=0.9)
        assert v.intensity == 0.9
