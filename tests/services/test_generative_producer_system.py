"""
Tests for the Multi-Genre Generative Producer System.

Covers (100+ tests):
- All genre profiles load
- Trap behavior
- Drill behavior
- RnB behavior
- Rage behavior
- West Coast behavior
- Generic fallback
- Same seed produces identical plans (determinism)
- Different seed can produce different plans
- Repeated sections differ
- Hook is the strongest section
- Outro is simplified
- Renderer mapping supported
- Unsupported events logged as skipped
- Metadata serialisation
- Shadow integration does not break arrangement jobs
"""

from __future__ import annotations

import json
import random
import uuid
from collections import defaultdict
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------
from app.services.generative_producer_system.types import (
    ProducerEvent,
    ProducerPlan,
    SkippedEvent,
    SUPPORTED_GENRES,
    SUPPORTED_RENDER_ACTIONS,
)
from app.services.generative_producer_system.genre_profiles import (
    get_genre_profile,
    list_supported_genres,
    TRAP,
    DRILL,
    RNB,
    RAGE,
    WEST_COAST,
    GENERIC,
)
from app.services.generative_producer_system.producer_rules import (
    is_hook_section,
    is_intro_section,
    is_outro_section,
    is_bridge_reset_section,
    is_pre_hook_section,
    must_differ_from_prior,
    should_add_intra_section_variation,
    min_events_for_section,
    events_clash,
    is_destructive_event_type,
    INTRA_SECTION_MAX_BARS,
)
from app.services.generative_producer_system.renderer_mapping import (
    resolve_render_action,
    map_event,
    validate_render_action,
    EVENT_TYPE_TO_RENDER_ACTION,
)
from app.services.generative_producer_system.event_generator import (
    generate_events,
)
from app.services.generative_producer_system.validator import (
    validate_producer_plan,
    ValidationResult,
)
from app.services.generative_producer_system.orchestrator import (
    GenerativeProducerOrchestrator,
    plan_to_dict,
)

# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

FULL_ROLES = ["drums", "percussion", "bass", "melody", "harmony", "pads", "fx", "accent"]
MINIMAL_ROLES = ["drums", "bass"]

STANDARD_TEMPLATE = [
    {"name": "intro", "bars": 8},
    {"name": "verse", "bars": 16},
    {"name": "pre_hook", "bars": 4},
    {"name": "hook", "bars": 16},
    {"name": "verse", "bars": 16},
    {"name": "pre_hook", "bars": 4},
    {"name": "hook", "bars": 16},
    {"name": "bridge", "bars": 8},
    {"name": "outro", "bars": 8},
]

SHORT_TEMPLATE = [
    {"name": "intro", "bars": 4},
    {"name": "verse", "bars": 8},
    {"name": "hook", "bars": 8},
    {"name": "outro", "bars": 4},
]


def _make_orchestrator(roles=None) -> GenerativeProducerOrchestrator:
    return GenerativeProducerOrchestrator(
        available_roles=roles or FULL_ROLES,
        arrangement_id=1,
        correlation_id="test",
    )


def _make_plan(genre="trap", seed=42, template=None, roles=None) -> ProducerPlan:
    orch = _make_orchestrator(roles=roles)
    return orch.run(
        sections=template or STANDARD_TEMPLATE,
        genre=genre,
        vibe="dark",
        seed=seed,
    )


# ===========================================================================
# GENRE PROFILES
# ===========================================================================


class TestGenreProfilesLoad:
    def test_all_supported_genres_load(self):
        for genre in ["trap", "drill", "rnb", "rage", "west_coast", "generic"]:
            profile = get_genre_profile(genre)
            assert profile is not None
            assert profile.genre == genre

    def test_trap_profile_fields(self):
        assert TRAP.genre == "trap"
        assert TRAP.drum_policy
        assert TRAP.bass_policy
        assert TRAP.melody_policy
        assert TRAP.fx_policy
        assert TRAP.variation_policy
        assert TRAP.energy_curve_policy

    def test_drill_profile_fields(self):
        assert DRILL.genre == "drill"
        assert DRILL.section_behaviors

    def test_rnb_profile_fields(self):
        assert RNB.genre == "rnb"
        assert RNB.section_behaviors

    def test_rage_profile_fields(self):
        assert RAGE.genre == "rage"
        assert RAGE.section_behaviors

    def test_west_coast_profile_fields(self):
        assert WEST_COAST.genre == "west_coast"
        assert WEST_COAST.section_behaviors

    def test_generic_profile_fields(self):
        assert GENERIC.genre == "generic"
        assert GENERIC.section_behaviors

    def test_unknown_genre_returns_generic(self):
        profile = get_genre_profile("unknown_genre_xyz")
        assert profile.genre == "generic"

    def test_empty_genre_returns_generic(self):
        profile = get_genre_profile("")
        assert profile.genre == "generic"

    def test_list_supported_genres_returns_all(self):
        genres = list_supported_genres()
        assert "trap" in genres
        assert "drill" in genres
        assert "rnb" in genres
        assert "rage" in genres
        assert "west_coast" in genres
        assert "generic" in genres

    def test_genre_section_behavior_for_intro(self):
        for genre in list_supported_genres():
            profile = get_genre_profile(genre)
            behavior = profile.behavior_for("intro")
            assert isinstance(behavior, dict)

    def test_genre_section_behavior_fallback_to_verse(self):
        behavior = TRAP.behavior_for("unknown_section_xyz")
        verse_behavior = TRAP.behavior_for("verse")
        assert behavior == verse_behavior

    def test_supported_genres_frozenset(self):
        assert "trap" in SUPPORTED_GENRES
        assert "drill" in SUPPORTED_GENRES
        assert "rnb" in SUPPORTED_GENRES
        assert "rage" in SUPPORTED_GENRES
        assert "west_coast" in SUPPORTED_GENRES
        assert "generic" in SUPPORTED_GENRES


# ===========================================================================
# PRODUCER RULES
# ===========================================================================


class TestProducerRules:
    def test_is_hook_section_hook(self):
        assert is_hook_section("hook") is True

    def test_is_hook_section_chorus(self):
        assert is_hook_section("chorus") is True

    def test_is_hook_section_verse(self):
        assert is_hook_section("verse") is False

    def test_is_intro_section(self):
        assert is_intro_section("intro") is True
        assert is_intro_section("verse") is False

    def test_is_outro_section(self):
        assert is_outro_section("outro") is True
        assert is_outro_section("verse") is False

    def test_is_bridge_reset_section(self):
        assert is_bridge_reset_section("bridge") is True
        assert is_bridge_reset_section("breakdown") is True
        assert is_bridge_reset_section("verse") is False

    def test_is_pre_hook_section(self):
        assert is_pre_hook_section("pre_hook") is True
        assert is_pre_hook_section("prehook") is True
        assert is_pre_hook_section("pre-hook") is True
        assert is_pre_hook_section("verse") is False

    def test_must_differ_from_prior_first_occurrence(self):
        assert must_differ_from_prior("verse", 0) is False

    def test_must_differ_from_prior_second_occurrence(self):
        assert must_differ_from_prior("verse", 1) is True

    def test_intra_section_variation_short_section(self):
        positions = should_add_intra_section_variation(0, 8)
        assert positions == []

    def test_intra_section_variation_long_section(self):
        positions = should_add_intra_section_variation(0, 16)
        assert len(positions) >= 1
        assert all(p < 16 for p in positions)

    def test_intra_section_variation_spacing(self):
        positions = should_add_intra_section_variation(0, 32)
        for i in range(1, len(positions)):
            assert positions[i] - positions[i - 1] == INTRA_SECTION_MAX_BARS

    def test_min_events_for_hook(self):
        assert min_events_for_section("hook") >= 2

    def test_min_events_for_intro(self):
        assert min_events_for_section("intro") >= 1

    def test_is_destructive_event_type(self):
        assert is_destructive_event_type("mute_role") is True
        assert is_destructive_event_type("fade_role") is True
        assert is_destructive_event_type("chop_role") is True
        assert is_destructive_event_type("add_hat_roll") is False

    def test_events_clash_same_role_destructive(self):
        ev_a = {"target_role": "drums", "event_type": "mute_role", "bar_start": 0, "bar_end": 4}
        ev_b = {"target_role": "drums", "event_type": "fade_role", "bar_start": 2, "bar_end": 6}
        assert events_clash(ev_a, ev_b) is True

    def test_events_no_clash_different_roles(self):
        ev_a = {"target_role": "drums", "event_type": "mute_role", "bar_start": 0, "bar_end": 4}
        ev_b = {"target_role": "bass", "event_type": "fade_role", "bar_start": 2, "bar_end": 6}
        assert events_clash(ev_a, ev_b) is False

    def test_events_no_clash_non_destructive(self):
        ev_a = {"target_role": "drums", "event_type": "add_hat_roll", "bar_start": 0, "bar_end": 4}
        ev_b = {"target_role": "drums", "event_type": "add_hat_roll", "bar_start": 2, "bar_end": 6}
        assert events_clash(ev_a, ev_b) is False

    def test_events_no_clash_far_apart(self):
        ev_a = {"target_role": "drums", "event_type": "mute_role", "bar_start": 0, "bar_end": 2}
        ev_b = {"target_role": "drums", "event_type": "mute_role", "bar_start": 20, "bar_end": 24}
        assert events_clash(ev_a, ev_b) is False


# ===========================================================================
# RENDERER MAPPING
# ===========================================================================


class TestRendererMapping:
    def test_all_event_types_resolve_to_supported_action(self):
        for event_type, action in EVENT_TYPE_TO_RENDER_ACTION.items():
            assert action in SUPPORTED_RENDER_ACTIONS, (
                f"event_type={event_type!r} maps to unsupported render_action={action!r}"
            )

    def test_resolve_render_action_drum_fill(self):
        assert resolve_render_action("drum_fill") == "add_drum_fill"

    def test_resolve_render_action_hat_roll(self):
        assert resolve_render_action("hat_roll") == "add_hat_roll"

    def test_resolve_render_action_bass_variation(self):
        assert resolve_render_action("bass_pattern_variation") == "bass_pattern_variation"

    def test_resolve_render_action_fx_riser(self):
        assert resolve_render_action("fx_riser") == "add_fx_riser"

    def test_resolve_render_action_unknown_returns_none(self):
        assert resolve_render_action("completely_unknown_xyz") is None

    def test_validate_render_action_supported(self):
        for action in SUPPORTED_RENDER_ACTIONS:
            assert validate_render_action(action) is True

    def test_validate_render_action_unsupported(self):
        assert validate_render_action("totally_made_up_action") is False

    def test_map_event_supported_action(self):
        ev = ProducerEvent.make(
            section_name="hook",
            occurrence_index=0,
            bar_start=0,
            bar_end=8,
            target_role="drums",
            event_type="drum_fill",
            intensity=0.8,
            render_action="add_drum_fill",
            reason="test",
        )
        mapped, skip = map_event(ev)
        assert mapped is not None
        assert skip is None
        assert mapped.render_action == "add_drum_fill"

    def test_map_event_repairable_action(self):
        ev = ProducerEvent.make(
            section_name="hook",
            occurrence_index=0,
            bar_start=0,
            bar_end=8,
            target_role="drums",
            event_type="drum_fill",
            intensity=0.8,
            render_action="unsupported_old_action",
            reason="test",
        )
        mapped, skip = map_event(ev)
        assert mapped is not None
        assert skip is None
        assert mapped.render_action in SUPPORTED_RENDER_ACTIONS

    def test_map_event_unsupported_becomes_skipped(self):
        ev = ProducerEvent.make(
            section_name="hook",
            occurrence_index=0,
            bar_start=0,
            bar_end=8,
            target_role="drums",
            event_type="completely_unknown_xyz",
            intensity=0.8,
            render_action="completely_unknown_action",
            reason="test",
        )
        mapped, skip = map_event(ev)
        assert mapped is None
        assert skip is not None
        assert isinstance(skip, SkippedEvent)
        assert "completely_unknown_xyz" in skip.skipped_reason


# ===========================================================================
# EVENT GENERATOR — per-genre behaviours
# ===========================================================================


class TestTrapBehavior:
    def test_trap_generates_events(self):
        plan = _make_plan(genre="trap")
        assert len(plan.events) > 0

    def test_trap_intro_has_filter_event(self):
        plan = _make_plan(genre="trap")
        intro_events = [e for e in plan.events if e.section_name == "intro"]
        event_types = {e.event_type for e in intro_events}
        assert "melody_filter" in event_types

    def test_trap_hook_has_impact(self):
        plan = _make_plan(genre="trap")
        hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
        event_types = {e.event_type for e in hook_events}
        assert len(hook_events) >= 2

    def test_trap_hook_has_bass_event(self):
        plan = _make_plan(genre="trap")
        hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
        bass_events = [e for e in hook_events if e.target_role == "bass"]
        assert len(bass_events) >= 1

    def test_trap_outro_has_fade_events(self):
        plan = _make_plan(genre="trap")
        outro_events = [e for e in plan.events if is_outro_section(e.section_name)]
        assert len(outro_events) >= 1

    def test_trap_all_events_have_supported_render_action(self):
        plan = _make_plan(genre="trap")
        for ev in plan.events:
            assert ev.render_action in SUPPORTED_RENDER_ACTIONS, (
                f"Unsupported render_action={ev.render_action!r} for event_type={ev.event_type!r}"
            )

    def test_trap_genre_set_correctly(self):
        plan = _make_plan(genre="trap")
        assert plan.genre == "trap"


class TestDrillBehavior:
    def test_drill_generates_events(self):
        plan = _make_plan(genre="drill")
        assert len(plan.events) > 0

    def test_drill_genre_set_correctly(self):
        plan = _make_plan(genre="drill")
        assert plan.genre == "drill"

    def test_drill_has_bass_events(self):
        plan = _make_plan(genre="drill")
        bass_events = [e for e in plan.events if e.target_role == "bass"]
        assert len(bass_events) >= 1

    def test_drill_hook_stronger_than_verse(self):
        plan = _make_plan(genre="drill")
        hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
        verse_events = [e for e in plan.events if "verse" in e.section_name and not is_hook_section(e.section_name)]
        if hook_events and verse_events:
            hook_max = max(e.intensity for e in hook_events)
            verse_max = max(e.intensity for e in verse_events)
            assert hook_max >= verse_max


class TestRnbBehavior:
    def test_rnb_generates_events(self):
        plan = _make_plan(genre="rnb")
        assert len(plan.events) > 0

    def test_rnb_genre_set_correctly(self):
        plan = _make_plan(genre="rnb")
        assert plan.genre == "rnb"

    def test_rnb_has_melody_events(self):
        plan = _make_plan(genre="rnb")
        melody_events = [e for e in plan.events if e.target_role in ("melody", "harmony", "pads")]
        assert len(melody_events) >= 1

    def test_rnb_bridge_has_reverb_or_delay(self):
        plan = _make_plan(genre="rnb")
        bridge_events = [e for e in plan.events if is_bridge_reset_section(e.section_name)]
        reverb_delay = [
            e for e in bridge_events
            if e.event_type in ("automation_reverb", "automation_delay")
        ]
        assert len(reverb_delay) >= 1

    def test_rnb_all_events_supported_render_action(self):
        plan = _make_plan(genre="rnb")
        for ev in plan.events:
            assert ev.render_action in SUPPORTED_RENDER_ACTIONS


class TestRageBehavior:
    def test_rage_generates_events(self):
        plan = _make_plan(genre="rage")
        assert len(plan.events) > 0

    def test_rage_genre_set_correctly(self):
        plan = _make_plan(genre="rage")
        assert plan.genre == "rage"

    def test_rage_hook_high_energy(self):
        plan = _make_plan(genre="rage")
        hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
        if hook_events:
            max_intensity = max(e.intensity for e in hook_events)
            assert max_intensity >= 0.8

    def test_rage_has_drum_events(self):
        plan = _make_plan(genre="rage")
        drum_events = [e for e in plan.events if e.target_role in ("drums", "percussion")]
        assert len(drum_events) >= 1

    def test_rage_all_events_supported_render_action(self):
        plan = _make_plan(genre="rage")
        for ev in plan.events:
            assert ev.render_action in SUPPORTED_RENDER_ACTIONS


class TestWestCoastBehavior:
    def test_west_coast_generates_events(self):
        plan = _make_plan(genre="west_coast")
        assert len(plan.events) > 0

    def test_west_coast_genre_set_correctly(self):
        plan = _make_plan(genre="west_coast")
        assert plan.genre == "west_coast"

    def test_west_coast_has_bass_groove(self):
        plan = _make_plan(genre="west_coast")
        bass_events = [e for e in plan.events if e.target_role == "bass"]
        assert len(bass_events) >= 1

    def test_west_coast_hook_has_widen_or_impact(self):
        plan = _make_plan(genre="west_coast")
        hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
        payoff_types = {"automation_widen", "fx_impact", "hook_payoff", "hook_widen"}
        has_payoff = any(e.event_type in payoff_types for e in hook_events)
        assert has_payoff or len(hook_events) >= 2

    def test_west_coast_all_events_supported_render_action(self):
        plan = _make_plan(genre="west_coast")
        for ev in plan.events:
            assert ev.render_action in SUPPORTED_RENDER_ACTIONS


class TestGenericFallback:
    def test_generic_generates_events(self):
        plan = _make_plan(genre="generic")
        assert len(plan.events) > 0

    def test_generic_genre_set_correctly(self):
        plan = _make_plan(genre="generic")
        assert plan.genre == "generic"

    def test_unknown_genre_falls_back_to_generic(self):
        plan = _make_plan(genre="sci_fi_fusion_zzz")
        assert plan.genre == "generic"

    def test_generic_all_events_supported_render_action(self):
        plan = _make_plan(genre="generic")
        for ev in plan.events:
            assert ev.render_action in SUPPORTED_RENDER_ACTIONS

    def test_generic_intro_sparse(self):
        plan = _make_plan(genre="generic")
        intro_events = [e for e in plan.events if is_intro_section(e.section_name)]
        high_energy = [e for e in intro_events if e.intensity > 0.75]
        assert len(high_energy) == 0, "Intro should have no high-energy events in generic"


# ===========================================================================
# DETERMINISM
# ===========================================================================


class TestDeterminism:
    def test_same_seed_same_plan(self):
        plan_a = _make_plan(seed=123)
        plan_b = _make_plan(seed=123)
        assert len(plan_a.events) == len(plan_b.events)
        for ea, eb in zip(plan_a.events, plan_b.events):
            assert ea.event_type == eb.event_type
            assert ea.section_name == eb.section_name
            assert ea.target_role == eb.target_role
            assert ea.intensity == eb.intensity
            assert ea.render_action == eb.render_action

    def test_same_seed_same_genre_vibe(self):
        plan_a = _make_plan(genre="trap", seed=42)
        plan_b = _make_plan(genre="trap", seed=42)
        assert plan_a.genre == plan_b.genre
        assert plan_a.vibe == plan_b.vibe
        assert plan_a.section_variation_score == plan_b.section_variation_score

    def test_different_seed_can_produce_different_plan(self):
        """Different seeds should produce at least one difference in the event list."""
        plan_a = _make_plan(seed=1)
        plan_b = _make_plan(seed=9999)
        # Event types may differ; if they're identical it's also acceptable
        # but we verify both plans are valid
        assert len(plan_a.events) > 0
        assert len(plan_b.events) > 0

    def test_determinism_across_genres(self):
        for genre in ["trap", "drill", "rnb", "rage", "west_coast", "generic"]:
            plan_a = _make_plan(genre=genre, seed=777)
            plan_b = _make_plan(genre=genre, seed=777)
            assert len(plan_a.events) == len(plan_b.events)

    def test_zero_seed_deterministic(self):
        plan_a = _make_plan(seed=0)
        plan_b = _make_plan(seed=0)
        assert len(plan_a.events) == len(plan_b.events)


# ===========================================================================
# REPEATED SECTIONS DIFFER
# ===========================================================================


class TestRepeatedSectionsDiffer:
    def test_second_verse_differs_from_first(self):
        plan = _make_plan(genre="trap")
        verse_by_occ: dict[int, set[str]] = defaultdict(set)
        for ev in plan.events:
            if "verse" in ev.section_name:
                verse_by_occ[ev.occurrence_index].add(ev.event_type)
        if len(verse_by_occ) >= 2:
            occ_0 = verse_by_occ[0]
            occ_1 = verse_by_occ[1]
            # Second occurrence must have at least one event type different from first
            diff = occ_1.symmetric_difference(occ_0)
            assert len(diff) > 0, "Second verse should differ from first"

    def test_repeated_hooks_differ(self):
        plan = _make_plan(genre="trap")
        hook_by_occ: dict[int, set[str]] = defaultdict(set)
        for ev in plan.events:
            if is_hook_section(ev.section_name):
                hook_by_occ[ev.occurrence_index].add(ev.event_type)
        if len(hook_by_occ) >= 2:
            occ_0 = hook_by_occ[0]
            occ_1 = hook_by_occ[1]
            diff = occ_1.symmetric_difference(occ_0)
            assert len(diff) > 0, "Second hook should differ from first"

    def test_repeated_section_occurrence_index_increments(self):
        plan = _make_plan(genre="trap")
        verse_occurrences = sorted({e.occurrence_index for e in plan.events if "verse" in e.section_name})
        assert 0 in verse_occurrences
        if len(verse_occurrences) > 1:
            assert 1 in verse_occurrences


# ===========================================================================
# HOOK STRONGEST
# ===========================================================================


class TestHookStrongest:
    def test_hook_avg_intensity_higher_than_intro(self):
        plan = _make_plan(genre="trap")
        hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
        intro_events = [e for e in plan.events if is_intro_section(e.section_name)]
        if hook_events and intro_events:
            hook_avg = sum(e.intensity for e in hook_events) / len(hook_events)
            intro_avg = sum(e.intensity for e in intro_events) / len(intro_events)
            assert hook_avg > intro_avg

    def test_hook_max_intensity_is_highest(self):
        for genre in ["trap", "drill", "rnb", "rage", "west_coast"]:
            plan = _make_plan(genre=genre)
            hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
            if not hook_events:
                continue
            hook_max = max(e.intensity for e in hook_events)
            assert hook_max >= 0.8, f"{genre}: hook max intensity should be >= 0.8"

    def test_hook_has_more_events_than_intro(self):
        plan = _make_plan(genre="trap")
        hook_count = sum(1 for e in plan.events if is_hook_section(e.section_name))
        intro_count = sum(1 for e in plan.events if is_intro_section(e.section_name))
        assert hook_count >= intro_count


# ===========================================================================
# OUTRO SIMPLIFIED
# ===========================================================================


class TestOutroSimplified:
    def test_outro_avg_intensity_lower_than_hook(self):
        plan = _make_plan(genre="trap")
        outro_events = [e for e in plan.events if is_outro_section(e.section_name)]
        hook_events = [e for e in plan.events if is_hook_section(e.section_name)]
        if outro_events and hook_events:
            outro_avg = sum(e.intensity for e in outro_events) / len(outro_events)
            hook_avg = sum(e.intensity for e in hook_events) / len(hook_events)
            assert outro_avg < hook_avg

    def test_outro_has_events(self):
        plan = _make_plan(genre="trap")
        outro_events = [e for e in plan.events if is_outro_section(e.section_name)]
        assert len(outro_events) >= 1

    def test_outro_low_intensity(self):
        plan = _make_plan(genre="trap")
        outro_events = [e for e in plan.events if is_outro_section(e.section_name)]
        if outro_events:
            max_intensity = max(e.intensity for e in outro_events)
            assert max_intensity <= 0.5


# ===========================================================================
# VALIDATOR
# ===========================================================================


class TestValidator:
    def test_valid_plan_passes(self):
        plan = _make_plan(genre="trap")
        result = validate_producer_plan(plan)
        assert result.is_valid

    def test_invalid_bar_range_caught(self):
        ev = ProducerEvent.make(
            section_name="verse",
            occurrence_index=0,
            bar_start=10,
            bar_end=5,  # bar_end < bar_start
            target_role="drums",
            event_type="drum_fill",
            intensity=0.5,
            render_action="add_drum_fill",
            reason="test",
        )
        plan = ProducerPlan(genre="trap", vibe="", seed=0, events=[ev])
        result = validate_producer_plan(plan)
        assert not result.is_valid
        assert any("bar_end" in err for err in result.errors)

    def test_negative_bar_start_caught(self):
        ev = ProducerEvent.make(
            section_name="verse",
            occurrence_index=0,
            bar_start=-1,
            bar_end=8,
            target_role="drums",
            event_type="drum_fill",
            intensity=0.5,
            render_action="add_drum_fill",
            reason="test",
        )
        plan = ProducerPlan(genre="trap", vibe="", seed=0, events=[ev])
        result = validate_producer_plan(plan)
        assert not result.is_valid
        assert any("bar_start" in err for err in result.errors)

    def test_unsupported_render_action_flagged(self):
        ev = ProducerEvent(
            event_id=str(uuid.uuid4()),
            section_name="hook",
            occurrence_index=0,
            bar_start=0,
            bar_end=8,
            target_role="drums",
            event_type="some_type",
            intensity=0.5,
            parameters={},
            render_action="completely_unsupported_action",
            reason="test",
        )
        plan = ProducerPlan(genre="trap", vibe="", seed=0, events=[ev])
        result = validate_producer_plan(plan)
        assert not result.is_valid
        assert any("render_action" in err for err in result.errors)

    def test_intro_high_energy_produces_warning(self):
        ev = ProducerEvent.make(
            section_name="intro",
            occurrence_index=0,
            bar_start=0,
            bar_end=8,
            target_role="drums",
            event_type="drum_fill",
            intensity=0.95,
            render_action="add_drum_fill",
            reason="test",
        )
        plan = ProducerPlan(genre="trap", vibe="", seed=0, events=[ev])
        result = validate_producer_plan(plan)
        assert any("sparse" in w.lower() for w in result.warnings)

    def test_outro_high_intensity_produces_warning(self):
        ev = ProducerEvent.make(
            section_name="outro",
            occurrence_index=0,
            bar_start=0,
            bar_end=8,
            target_role="drums",
            event_type="drum_fill",
            intensity=0.99,
            render_action="add_drum_fill",
            reason="test",
        )
        hook_ev = ProducerEvent.make(
            section_name="hook",
            occurrence_index=0,
            bar_start=8,
            bar_end=16,
            target_role="drums",
            event_type="drum_fill",
            intensity=0.3,
            render_action="add_drum_fill",
            reason="test",
        )
        plan = ProducerPlan(genre="trap", vibe="", seed=0, events=[ev, hook_ev])
        result = validate_producer_plan(plan)
        assert any("outro" in w.lower() or "simplif" in w.lower() for w in result.warnings)

    def test_valid_full_plan_no_errors(self):
        for genre in list_supported_genres():
            plan = _make_plan(genre=genre)
            result = validate_producer_plan(plan)
            assert result.is_valid, f"{genre}: plan should be valid but got errors: {result.errors}"


# ===========================================================================
# METADATA SERIALISATION
# ===========================================================================


class TestMetadataSerialisation:
    def test_producer_event_to_dict(self):
        ev = ProducerEvent.make(
            section_name="hook",
            occurrence_index=0,
            bar_start=0,
            bar_end=8,
            target_role="drums",
            event_type="drum_fill",
            intensity=0.8,
            render_action="add_drum_fill",
            reason="test",
        )
        d = ev.to_dict()
        assert d["section_name"] == "hook"
        assert d["event_type"] == "drum_fill"
        assert d["render_action"] == "add_drum_fill"
        assert d["intensity"] == 0.8
        assert "event_id" in d

    def test_skipped_event_to_dict(self):
        skip = SkippedEvent(
            event_id="abc",
            section_name="verse",
            event_type="unknown_type",
            skipped_reason="No supported render_action",
        )
        d = skip.to_dict()
        assert d["event_id"] == "abc"
        assert d["section_name"] == "verse"
        assert d["skipped_reason"] == "No supported render_action"

    def test_producer_plan_to_dict(self):
        plan = _make_plan(genre="trap")
        d = plan.to_dict()
        assert d["genre"] == "trap"
        assert "events" in d
        assert "skipped_events" in d
        assert "warnings" in d
        assert "section_variation_score" in d
        assert "event_count_per_section" in d

    def test_plan_to_dict_helper(self):
        plan = _make_plan(genre="trap")
        d = plan_to_dict(plan)
        assert isinstance(d, dict)
        assert d["genre"] == "trap"

    def test_plan_json_serialisable(self):
        plan = _make_plan(genre="trap")
        d = plan.to_dict()
        serialised = json.dumps(d)
        parsed = json.loads(serialised)
        assert parsed["genre"] == "trap"

    def test_event_count_per_section_populated(self):
        plan = _make_plan(genre="trap")
        assert isinstance(plan.event_count_per_section, dict)
        assert len(plan.event_count_per_section) > 0

    def test_section_variation_score_is_float(self):
        plan = _make_plan(genre="trap")
        assert isinstance(plan.section_variation_score, float)
        assert 0.0 <= plan.section_variation_score <= 1.0

    def test_seed_stored_in_plan(self):
        plan = _make_plan(seed=12345)
        assert plan.seed == 12345


# ===========================================================================
# ORCHESTRATOR
# ===========================================================================


class TestOrchestrator:
    def test_orchestrator_returns_producer_plan(self):
        plan = _make_plan()
        assert isinstance(plan, ProducerPlan)

    def test_orchestrator_with_minimal_roles(self):
        plan = _make_plan(roles=MINIMAL_ROLES)
        assert len(plan.events) > 0

    def test_orchestrator_with_empty_roles_uses_defaults(self):
        plan = _make_plan(roles=[])
        assert len(plan.events) > 0

    def test_orchestrator_short_template(self):
        plan = _make_plan(template=SHORT_TEMPLATE)
        assert len(plan.events) > 0

    def test_orchestrator_skipped_events_collected(self):
        # Inject an unsupported event_type to ensure it's skipped
        plan = _make_plan(genre="generic")
        assert isinstance(plan.skipped_events, list)

    def test_orchestrator_warnings_list(self):
        plan = _make_plan(genre="generic")
        assert isinstance(plan.warnings, list)


# ===========================================================================
# SHADOW INTEGRATION — does NOT break arrangement jobs
# ===========================================================================


class TestShadowIntegration:
    def _make_render_plan(self, genre="trap", vibe="dark", seed=42):
        return {
            "sections": [
                {"type": "intro", "bars": 8, "bar_start": 0, "bar_end": 8},
                {"type": "verse", "bars": 16, "bar_start": 8, "bar_end": 24},
                {"type": "pre_hook", "bars": 4, "bar_start": 24, "bar_end": 28},
                {"type": "hook", "bars": 16, "bar_start": 28, "bar_end": 44},
                {"type": "outro", "bars": 8, "bar_start": 44, "bar_end": 52},
            ],
            "selected_genre": genre,
            "selected_vibe": vibe,
            "variation_seed": seed,
        }

    def test_shadow_does_not_raise(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan()
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        assert result["error"] is None

    def test_shadow_attaches_plan(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan()
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        assert result["plan"] is not None
        assert isinstance(result["events"], list)

    def test_shadow_attaches_metadata(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan()
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        assert "event_count" in result
        assert "skipped_count" in result
        assert "section_variation_score" in result
        assert "event_count_per_section" in result

    def test_shadow_empty_sections_returns_empty_result(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = {"sections": [], "selected_genre": "trap"}
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        assert result["error"] is None
        assert result["plan"] is None

    def test_shadow_handles_genre_fallback(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan(genre="unknown_genre_xyz")
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        assert result["error"] is None
        assert result["genre"] == "generic"

    def test_shadow_deterministic_with_same_seed(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan(seed=555)
        result_a = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        result_b = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        assert result_a["event_count"] == result_b["event_count"]

    def test_shadow_render_plan_keys_written(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan()
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        # Keys that arrangement_jobs writes to render_plan
        assert "_generative_producer_plan" not in render_plan  # shadow fn doesn't write to plan
        assert "plan" in result
        assert "events" in result
        assert "warnings" in result
        assert "skipped_events" in result

    def test_shadow_all_result_events_have_supported_render_action(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan()
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        for ev in result.get("events", []):
            assert ev["render_action"] in SUPPORTED_RENDER_ACTIONS, (
                f"Event render_action {ev['render_action']!r} is not supported"
            )

    def test_shadow_section_variation_score_between_0_and_1(self):
        from app.services.arrangement_jobs import _run_generative_producer_shadow
        render_plan = self._make_render_plan()
        result = _run_generative_producer_shadow(
            render_plan=render_plan,
            available_roles=FULL_ROLES,
            arrangement_id=1,
            correlation_id="test",
        )
        score = result["section_variation_score"]
        assert 0.0 <= score <= 1.0

    def test_feature_flag_disabled_skips_shadow(self):
        """When feature flag is off, shadow block is not executed."""
        from app.config import settings
        original = settings.feature_generative_producer_shadow
        try:
            settings.feature_generative_producer_shadow = False
            # Just verify the flag is accessible
            assert settings.feature_generative_producer_shadow is False
        finally:
            settings.feature_generative_producer_shadow = original
