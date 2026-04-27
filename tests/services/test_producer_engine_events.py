"""
Tests for generate_producer_events — Multi-Genre Producer System.

Verifies:
1.  Sections produce events that differ from each other (verse1 ≠ verse2,
    hook1 ≠ hook2).
2.  Hook is the strongest section (highest event count / energy).
3.  Intro is sparse (fewest events, low energy).
4.  Outro is stripped (drums removed, melody tail kept).
5.  Every event has a non-empty render_action (maps to a real render action).
6.  Deterministic seed: same seed → same output, different seed → different output.
7.  All four genres (trap, drill, rnb, rage) are supported without error.
8.  Unknown genres fall back gracefully.
9.  Metadata fields are present and valid.
"""

import pytest

from app.services.producer_engine import (
    generate_producer_events,
    ProducerEventsResult,
    ProducerEvent,
)
from app.services.producer_models import (
    ProducerArrangement,
    Section,
    SectionType,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


def _make_plan(section_names: list[str]) -> list[dict]:
    """Build a minimal list-of-dicts plan with the given section types."""
    bar = 0
    sections = []
    lengths = {
        "intro": 8,
        "verse": 16,
        "pre_hook": 4,
        "hook": 8,
        "bridge": 8,
        "breakdown": 8,
        "outro": 8,
    }
    for name in section_names:
        length = lengths.get(name, 8)
        sections.append(
            {
                "section_type": name,
                "label": name.capitalize(),
                "start_bar": bar,
                "length_bars": length,
            }
        )
        bar += length
    return sections


def _full_arrangement_plan() -> list[dict]:
    """Standard INTRO → VERSE → PRE_HOOK → HOOK → VERSE → HOOK → OUTRO plan."""
    return _make_plan(
        ["intro", "verse", "pre_hook", "hook", "verse", "hook", "outro"]
    )


# ---------------------------------------------------------------------------
# 1. Sections differ
# ---------------------------------------------------------------------------


class TestSectionDifference:
    """Verse 1 and Verse 2 must produce different event sets.
    Hook 1 and Hook 2 must produce different event sets."""

    def test_verse1_differs_from_verse2_trap(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="dark", seed=42)

        verse1_events = [e for e in result.events if e.section == "verse_1"]
        verse2_events = [e for e in result.events if e.section == "verse_2"]

        assert verse1_events, "verse_1 must have events"
        assert verse2_events, "verse_2 must have events"

        v1_types = {e.event_type for e in verse1_events}
        v2_types = {e.event_type for e in verse2_events}
        # verse_2 must have at least one event type not present in verse_1
        assert v2_types - v1_types, (
            f"verse_2 must introduce new event types. "
            f"verse_1={v1_types}, verse_2={v2_types}"
        )

    def test_hook1_differs_from_hook2_trap(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="hard", seed=99)

        hook1_events = [e for e in result.events if e.section == "hook_1"]
        hook2_events = [e for e in result.events if e.section == "hook_2"]

        assert hook1_events, "hook_1 must have events"
        assert hook2_events, "hook_2 must have events"

        h1_types = {e.event_type for e in hook1_events}
        h2_types = {e.event_type for e in hook2_events}
        assert h2_types - h1_types, (
            f"hook_2 must introduce new event types. "
            f"hook_1={h1_types}, hook_2={h2_types}"
        )

    def test_section_variation_score_above_zero(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="rnb", vibe="smooth", seed=7)
        assert result.section_variation_score > 0.0


# ---------------------------------------------------------------------------
# 2. Hook is the strongest section
# ---------------------------------------------------------------------------


class TestHookStrength:
    """Hook should have more events than intro and outro."""

    def test_hook_has_more_events_than_intro(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="dark", seed=1)
        hook_count = result.event_count_per_section.get("hook_1", 0)
        intro_count = result.event_count_per_section.get("intro_1", 0)
        assert hook_count > intro_count, (
            f"hook event count ({hook_count}) should exceed intro ({intro_count})"
        )

    def test_hook_energy_highest(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="drill", vibe="dark", seed=2)
        energies = {e["section"]: e["energy"] for e in result.energy_curve}
        hook_energy = energies.get("hook_1", 0.0)
        intro_energy = energies.get("intro_1", 1.0)
        outro_energy = energies.get("outro_1", 1.0)
        assert hook_energy > intro_energy
        assert hook_energy > outro_energy

    def test_hook2_energy_at_least_as_high_as_hook1(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="hard", seed=3)
        energies = {e["section"]: e["energy"] for e in result.energy_curve}
        hook1 = energies.get("hook_1", 0.0)
        hook2 = energies.get("hook_2", 0.0)
        assert hook2 >= hook1, f"hook_2 energy ({hook2}) should be >= hook_1 ({hook1})"


# ---------------------------------------------------------------------------
# 3. Intro is sparse
# ---------------------------------------------------------------------------


class TestIntroSparse:
    """Intro must have fewer events than hook and low energy."""

    def test_intro_event_count_less_than_hook(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="rage", vibe="dark", seed=10)
        intro_count = result.event_count_per_section.get("intro_1", 0)
        hook_count = result.event_count_per_section.get("hook_1", 0)
        assert intro_count < hook_count

    def test_intro_low_energy(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="chill", seed=11)
        energies = {e["section"]: e["energy"] for e in result.energy_curve}
        assert energies.get("intro_1", 1.0) <= 0.5, "Intro energy should be low"

    def test_intro_no_full_drums(self):
        """Intro must not contain an 808_active or full drum pattern event."""
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="dark", seed=12)
        intro_events = [e for e in result.events if e.section == "intro_1"]
        high_power_types = {"808_active", "full_drums"}
        for ev in intro_events:
            assert ev.event_type not in high_power_types, (
                f"Intro should not contain high-power event: {ev.event_type}"
            )


# ---------------------------------------------------------------------------
# 4. Outro is stripped
# ---------------------------------------------------------------------------


class TestOutroStripped:
    """Outro must remove drums and keep a melody tail."""

    def test_outro_has_drum_remove_event(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="dark", seed=20)
        outro_events = [e for e in result.events if e.section == "outro_1"]
        drum_remove = [e for e in outro_events if e.event_type == "drum_remove"]
        assert drum_remove, "Outro must contain a drum_remove event"

    def test_outro_has_melody_tail_event(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="rnb", vibe="smooth", seed=21)
        outro_events = [e for e in result.events if e.section == "outro_1"]
        melody_tail = [e for e in outro_events if e.event_type == "melody_tail"]
        assert melody_tail, "Outro must contain a melody_tail event"

    def test_outro_lower_energy_than_hook(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="drill", vibe="hard", seed=22)
        energies = {e["section"]: e["energy"] for e in result.energy_curve}
        outro_energy = energies.get("outro_1", 1.0)
        hook_energy = energies.get("hook_1", 0.0)
        assert outro_energy < hook_energy


# ---------------------------------------------------------------------------
# 5. Events affect actual audio (render_action is never empty)
# ---------------------------------------------------------------------------


class TestEventsAffectAudio:
    """Every ProducerEvent must have a non-empty render_action."""

    @pytest.mark.parametrize("genre", ["trap", "drill", "rnb", "rage"])
    def test_all_events_have_render_action(self, genre):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre=genre, vibe="dark", seed=42)
        for event in result.events:
            assert event.render_action, (
                f"Event {event.event_type} in {event.section} has no render_action"
            )

    @pytest.mark.parametrize("genre", ["trap", "drill", "rnb", "rage"])
    def test_render_action_contains_verb(self, genre):
        """render_action strings must start with a verb (lowercase word)."""
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre=genre, vibe="dark", seed=42)
        for event in result.events:
            first_word = event.render_action.split()[0]
            assert first_word.islower(), (
                f"render_action should start with a lowercase verb, got: "
                f"{event.render_action!r}"
            )


# ---------------------------------------------------------------------------
# 6. Deterministic seed behaviour
# ---------------------------------------------------------------------------


class TestDeterministicSeed:
    """Same seed → identical output. Different seed → different output."""

    def test_same_seed_same_output(self):
        plan = _full_arrangement_plan()
        r1 = generate_producer_events(plan, genre="trap", vibe="dark", seed=1234)
        r2 = generate_producer_events(plan, genre="trap", vibe="dark", seed=1234)

        assert r1.producer_events_generated == r2.producer_events_generated
        for e1, e2 in zip(r1.events, r2.events):
            assert e1.event_type == e2.event_type
            assert e1.intensity == e2.intensity
            assert e1.render_action == e2.render_action

    def test_different_seed_different_output(self):
        plan = _full_arrangement_plan()
        r1 = generate_producer_events(plan, genre="trap", vibe="dark", seed=1)
        r2 = generate_producer_events(plan, genre="trap", vibe="dark", seed=999)

        # At least some intensities must differ
        intensities_1 = [e.intensity for e in r1.events]
        intensities_2 = [e.intensity for e in r2.events]
        assert intensities_1 != intensities_2, (
            "Different seeds should produce different intensity values"
        )


# ---------------------------------------------------------------------------
# 7. All four genres produce valid output
# ---------------------------------------------------------------------------


class TestGenreSupport:
    @pytest.mark.parametrize("genre", ["trap", "drill", "rnb", "rage"])
    def test_genre_produces_events(self, genre):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre=genre, vibe="dark", seed=42)
        assert isinstance(result, ProducerEventsResult)
        assert result.producer_events_generated > 0

    @pytest.mark.parametrize("genre", ["trap", "drill", "rnb", "rage"])
    def test_genre_has_hook_events(self, genre):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre=genre, vibe="dark", seed=42)
        hook_events = [e for e in result.events if e.section_type == "hook"]
        assert hook_events, f"Genre {genre!r} must produce hook events"


# ---------------------------------------------------------------------------
# 8. Unknown genre falls back gracefully
# ---------------------------------------------------------------------------


class TestUnknownGenre:
    def test_unknown_genre_fallback(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(
            plan, genre="jazz_funk", vibe="smooth", seed=42
        )
        assert result.producer_events_generated > 0

    def test_unknown_genre_fallback_has_all_metadata(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(
            plan, genre="electro_pop", vibe="chill", seed=1
        )
        assert result.energy_curve
        assert result.event_count_per_section


# ---------------------------------------------------------------------------
# 9. Metadata completeness
# ---------------------------------------------------------------------------


class TestMetadata:
    def test_producer_events_generated_count_matches_events_list(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="dark", seed=42)
        assert result.producer_events_generated == len(result.events)

    def test_energy_curve_has_entry_per_section(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="dark", seed=42)
        # Should have one energy entry per section in the plan
        assert len(result.energy_curve) == len(plan)

    def test_event_count_per_section_covers_all_sections(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="rnb", vibe="smooth", seed=5)
        # Every section in the plan should appear in event_count_per_section
        assert len(result.event_count_per_section) == len(plan)

    def test_section_variation_score_in_range(self):
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="rage", vibe="dark", seed=77)
        assert 0.0 <= result.section_variation_score <= 1.0

    def test_to_dict_is_json_serialisable(self):
        import json
        plan = _full_arrangement_plan()
        result = generate_producer_events(plan, genre="trap", vibe="dark", seed=42)
        data = result.to_dict()
        json_str = json.dumps(data)
        parsed = json.loads(json_str)
        assert parsed["producer_events_generated"] == result.producer_events_generated


# ---------------------------------------------------------------------------
# 10. Plan type compatibility
# ---------------------------------------------------------------------------


class TestPlanTypeCompatibility:
    """generate_producer_events must accept ProducerArrangement objects."""

    def test_accepts_producer_arrangement(self):
        arrangement = ProducerArrangement(
            tempo=140.0,
            total_bars=64,
            total_seconds=109.7,
            genre="trap",
        )
        arrangement.sections = [
            Section(name="Intro", section_type=SectionType.INTRO, bar_start=0, bars=8),
            Section(name="Verse", section_type=SectionType.VERSE, bar_start=8, bars=16),
            Section(name="Hook", section_type=SectionType.HOOK, bar_start=24, bars=8),
            Section(name="Outro", section_type=SectionType.OUTRO, bar_start=32, bars=8),
        ]
        result = generate_producer_events(
            arrangement, genre="trap", vibe="dark", seed=42
        )
        assert result.producer_events_generated > 0

    def test_accepts_dict_with_sections_key(self):
        plan = {"sections": _make_plan(["intro", "verse", "hook", "outro"])}
        result = generate_producer_events(plan, genre="drill", vibe="hard", seed=1)
        assert result.producer_events_generated > 0
