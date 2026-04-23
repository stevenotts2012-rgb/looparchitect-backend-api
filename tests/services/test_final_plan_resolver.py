"""
Tests for FinalPlanResolver (app/services/final_plan_resolver.py).

Covers:
- resolved plan merges roles from all engines correctly
- role subtraction actually changes final active role map
- role reintroduction adds back blocked roles
- boundary events are deduplicated across engines
- drop engine events win on deduplication
- repeated sections differ in resolved plan
- no-op annotations are surfaced for phantom blocked roles
- fallback path works when no sections
"""

from __future__ import annotations

import pytest

from app.services.final_plan_resolver import FinalPlanResolver
from app.services.resolved_render_plan import ResolvedRenderPlan, ResolvedSection


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_section(
    name: str = "Verse 1",
    section_type: str = "verse",
    bar_start: int = 0,
    bars: int = 8,
    energy: float = 0.6,
    instruments: list | None = None,
    boundary_events: list | None = None,
    timeline_events: list | None = None,
    active_stem_roles: list | None = None,
) -> dict:
    return {
        "name": name,
        "type": section_type,
        "bar_start": bar_start,
        "bars": bars,
        "energy": energy,
        "instruments": instruments or ["drums", "bass"],
        "active_stem_roles": active_stem_roles or instruments or ["drums", "bass"],
        "boundary_events": boundary_events or [],
        "timeline_events": timeline_events or [],
        "variations": [],
    }


def _make_decision_plan(sections: list | None = None) -> dict:
    return {
        "section_decisions": sections or [],
        "global_contrast_score": 0.7,
        "payoff_readiness_score": 0.6,
        "fallback_used": False,
    }


def _make_section_decision(
    section_name: str,
    occurrence_index: int = 0,
    target_fullness: str = "medium",
    allow_full_stack: bool = True,
    blocked_roles: list | None = None,
    subtractions: list | None = None,
    reentries: list | None = None,
    protected_roles: list | None = None,
) -> dict:
    return {
        "section_name": section_name,
        "occurrence_index": occurrence_index,
        "target_fullness": target_fullness,
        "allow_full_stack": allow_full_stack,
        "required_subtractions": subtractions or [],
        "required_reentries": reentries or [],
        "blocked_roles": blocked_roles or [],
        "protected_roles": protected_roles or [],
        "decision_score": 0.75,
        "rationale": [],
    }


def _make_drop_action(action_type: str, target_role: str) -> dict:
    return {
        "section_name": "Pre Hook",
        "occurrence_index": 0,
        "action_type": action_type,
        "target_role": target_role,
        "bar_start": None,
        "bar_end": None,
        "intensity": 0.8,
        "reason": "test",
    }


def _make_drop_plan(boundaries: list | None = None) -> dict:
    return {
        "total_drop_count": len(boundaries or []),
        "repeated_hook_drop_variation_score": 0.5,
        "fallback_used": False,
        "boundaries": boundaries or [],
    }


def _make_drop_boundary(
    from_section: str = "pre_hook",
    to_section: str = "hook",
    primary_event_type: str = "riser_build",
    support_event_types: list | None = None,
) -> dict:
    primary = {
        "boundary_name": f"{from_section} -> {to_section}",
        "from_section": from_section,
        "to_section": to_section,
        "placement": "pre_boundary",
        "event_type": primary_event_type,
        "intensity": 0.85,
        "parameters": {},
    }
    support = [
        {
            "boundary_name": f"{from_section} -> {to_section}",
            "from_section": from_section,
            "to_section": to_section,
            "placement": "post_boundary",
            "event_type": t,
            "intensity": 0.5,
            "parameters": {},
        }
        for t in (support_event_types or [])
    ]
    return {
        "boundary_name": f"{from_section} -> {to_section}",
        "from_section": from_section,
        "to_section": to_section,
        "occurrence_index": 0,
        "tension_score": 0.7,
        "payoff_score": 0.8,
        "primary_drop_event": primary,
        "support_events": support,
        "notes": [],
    }


def _make_render_plan(
    sections: list | None = None,
    decision_plan: dict | None = None,
    drop_plan: dict | None = None,
    bpm: float = 120.0,
) -> dict:
    return {
        "bpm": bpm,
        "key": "C major",
        "total_bars": sum(s.get("bars", 8) for s in (sections or [])),
        "sections": sections or [],
        "_decision_plan": decision_plan,
        "_drop_plan": drop_plan,
        "events": [],
        "render_profile": {"genre_profile": "hip-hop"},
    }


# ===========================================================================
# Basic resolve
# ===========================================================================


class TestFinalPlanResolverBasic:
    def test_returns_resolved_render_plan(self):
        plan = _make_render_plan(sections=[_make_section()])
        resolver = FinalPlanResolver(plan, available_roles=["drums", "bass"])
        result = resolver.resolve()
        assert isinstance(result, ResolvedRenderPlan)

    def test_section_count_matches_input(self):
        sections = [_make_section("Intro", bar_start=0), _make_section("Verse", bar_start=8)]
        plan = _make_render_plan(sections=sections)
        resolver = FinalPlanResolver(plan)
        result = resolver.resolve()
        assert result.section_count == 2

    def test_bpm_preserved(self):
        plan = _make_render_plan(sections=[_make_section()], bpm=140.0)
        result = FinalPlanResolver(plan).resolve()
        assert result.bpm == 140.0

    def test_key_preserved(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = FinalPlanResolver(plan).resolve()
        assert result.key == "C major"

    def test_empty_sections_returns_empty_resolved_plan(self):
        plan = _make_render_plan(sections=[])
        result = FinalPlanResolver(plan).resolve()
        assert result.section_count == 0
        assert isinstance(result, ResolvedRenderPlan)

    def test_active_roles_default_from_instruments(self):
        section = _make_section(instruments=["drums", "bass", "melody"])
        plan = _make_render_plan(sections=[section])
        result = FinalPlanResolver(plan).resolve()
        assert result.resolved_sections[0].final_active_roles == ["drums", "bass", "melody"]

    def test_source_quality_stored(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = FinalPlanResolver(plan, source_quality="true_stems").resolve()
        assert result.source_quality == "true_stems"

    def test_available_roles_stored(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = FinalPlanResolver(plan, available_roles=["drums", "bass", "melody"]).resolve()
        assert result.available_roles == ["drums", "bass", "melody"]

    def test_genre_comes_from_render_profile(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = FinalPlanResolver(plan).resolve()
        assert result.genre == "hip-hop"

    def test_resolver_version_is_positive(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = FinalPlanResolver(plan).resolve()
        assert result.resolver_version >= 1


# ===========================================================================
# Role subtraction (Decision Engine)
# ===========================================================================


class TestRoleSubtraction:
    def test_blocked_role_removed_from_active_roles(self):
        section = _make_section(
            name="Pre Hook",
            section_type="pre_hook",
            instruments=["drums", "bass", "melody"],
        )
        decision = _make_decision_plan(sections=[
            _make_section_decision(
                section_name="Pre Hook",
                blocked_roles=["drums"],
            )
        ])
        plan = _make_render_plan(sections=[section], decision_plan=decision)
        result = FinalPlanResolver(plan, available_roles=["drums", "bass", "melody"]).resolve()

        resolved_sec = result.resolved_sections[0]
        assert "drums" not in resolved_sec.final_active_roles
        assert "bass" in resolved_sec.final_active_roles
        assert "melody" in resolved_sec.final_active_roles

    def test_blocked_roles_in_final_blocked_roles(self):
        section = _make_section(instruments=["drums", "bass"])
        decision = _make_decision_plan(sections=[
            _make_section_decision(section_name="Verse 1", blocked_roles=["bass"])
        ])
        plan = _make_render_plan(sections=[section], decision_plan=decision)
        result = FinalPlanResolver(plan).resolve()
        assert "bass" in result.resolved_sections[0].final_blocked_roles

    def test_multiple_blocked_roles_all_removed(self):
        section = _make_section(instruments=["drums", "bass", "melody", "pads"])
        decision = _make_decision_plan(sections=[
            _make_section_decision(section_name="Verse 1", blocked_roles=["melody", "pads"])
        ])
        plan = _make_render_plan(sections=[section], decision_plan=decision)
        result = FinalPlanResolver(plan).resolve()
        roles = result.resolved_sections[0].final_active_roles
        assert "melody" not in roles
        assert "pads" not in roles

    def test_subtraction_via_hold_back_action(self):
        """hold_back_role in required_subtractions also removes the role."""
        section = _make_section(instruments=["drums", "bass", "melody"])
        subtraction = _make_drop_action("hold_back_role", "melody")
        decision = _make_decision_plan(sections=[
            _make_section_decision(
                section_name="Verse 1",
                subtractions=[subtraction],
            )
        ])
        plan = _make_render_plan(sections=[section], decision_plan=decision)
        result = FinalPlanResolver(plan).resolve()
        roles = result.resolved_sections[0].final_active_roles
        assert "melody" not in roles

    def test_final_section_role_map_reflects_subtractions(self):
        sections = [
            _make_section("Intro", instruments=["melody", "pads"]),
            _make_section("Hook 1", section_type="hook", bar_start=8, instruments=["drums", "bass", "melody"]),
        ]
        decision = _make_decision_plan(sections=[
            _make_section_decision("Intro", blocked_roles=["pads"]),
        ])
        plan = _make_render_plan(sections=sections, decision_plan=decision)
        result = FinalPlanResolver(plan, available_roles=["drums", "bass", "melody", "pads"]).resolve()

        role_map = result.final_section_role_map
        assert "pads" not in role_map["Intro"]
        assert "melody" in role_map["Intro"]
        assert set(role_map["Hook 1"]) == {"drums", "bass", "melody"}


# ===========================================================================
# Role reintroduction (Decision Engine)
# ===========================================================================


class TestRoleReintroduction:
    def test_reentry_role_added_when_available(self):
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            instruments=["drums", "bass"],
        )
        reentry = {
            "section_name": "Hook 1",
            "occurrence_index": 0,
            "action_type": "reintroduce_role",
            "target_role": "melody",
            "bar_start": None,
            "bar_end": None,
            "intensity": 0.9,
            "reason": "hook payoff",
        }
        decision = _make_decision_plan(sections=[
            _make_section_decision(
                section_name="Hook 1",
                reentries=[reentry],
            )
        ])
        plan = _make_render_plan(sections=[section], decision_plan=decision)
        result = FinalPlanResolver(
            plan, available_roles=["drums", "bass", "melody"]
        ).resolve()
        assert "melody" in result.resolved_sections[0].final_active_roles
        assert "melody" in result.resolved_sections[0].final_reentries

    def test_reentry_role_not_added_if_not_in_available_roles(self):
        section = _make_section(
            name="Hook 1",
            instruments=["drums", "bass"],
        )
        reentry = {
            "section_name": "Hook 1",
            "occurrence_index": 0,
            "action_type": "reintroduce_role",
            "target_role": "ghost_role",
            "bar_start": None,
            "bar_end": None,
            "intensity": 0.9,
            "reason": "test",
        }
        decision = _make_decision_plan(sections=[
            _make_section_decision(section_name="Hook 1", reentries=[reentry])
        ])
        plan = _make_render_plan(sections=[section], decision_plan=decision)
        result = FinalPlanResolver(
            plan, available_roles=["drums", "bass", "melody"]
        ).resolve()
        assert "ghost_role" not in result.resolved_sections[0].final_active_roles


# ===========================================================================
# Boundary event deduplication
# ===========================================================================


class TestBoundaryEventDeduplication:
    def test_drop_engine_event_registered(self):
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            bar_start=8,
            instruments=["drums", "bass"],
        )
        drop_plan = _make_drop_plan(boundaries=[
            _make_drop_boundary("pre_hook", "hook", primary_event_type="riser_build"),
        ])
        plan = _make_render_plan(sections=[section], drop_plan=drop_plan)
        result = FinalPlanResolver(plan).resolve()
        event_types = {e.event_type for e in result.resolved_sections[0].final_boundary_events}
        assert "riser_fx" in event_types  # riser_build maps to riser_fx

    def test_duplicate_event_type_deduplicated(self):
        """Same event_type from section.boundary_events AND drop engine → only one kept."""
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            bar_start=8,
            instruments=["drums", "bass"],
            boundary_events=[
                {"type": "riser_fx", "placement": "pre_boundary", "intensity": 0.7}
            ],
        )
        drop_plan = _make_drop_plan(boundaries=[
            _make_drop_boundary("pre_hook", "hook", primary_event_type="riser_build"),
        ])
        plan = _make_render_plan(sections=[section], drop_plan=drop_plan)
        result = FinalPlanResolver(plan).resolve()

        # The event type should appear exactly once
        type_counts: dict = {}
        for evt in result.resolved_sections[0].final_boundary_events:
            type_counts[evt.event_type] = type_counts.get(evt.event_type, 0) + 1
        assert type_counts.get("riser_fx", 0) <= 1

    def test_duplicate_registered_as_noop(self):
        """When a boundary event is deduped, a no-op annotation is created."""
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            bar_start=8,
            instruments=["drums", "bass"],
            boundary_events=[
                {"type": "riser_fx", "placement": "pre_boundary", "intensity": 0.7}
            ],
        )
        drop_plan = _make_drop_plan(boundaries=[
            _make_drop_boundary("pre_hook", "hook", primary_event_type="riser_build"),
        ])
        plan = _make_render_plan(sections=[section], drop_plan=drop_plan)
        result = FinalPlanResolver(plan).resolve()

        noop_types = [ann.get("planned_action", "") for ann in result.noop_annotations]
        assert any("riser_fx" in t for t in noop_types)

    def test_drop_engine_wins_over_section_boundary_event(self):
        """Drop engine is registered first so wins deduplication."""
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            bar_start=8,
            instruments=["drums", "bass"],
            boundary_events=[
                {"type": "riser_fx", "placement": "boundary", "intensity": 0.5}
            ],
        )
        drop_plan = _make_drop_plan(boundaries=[
            _make_drop_boundary("pre_hook", "hook", primary_event_type="riser_build"),
        ])
        plan = _make_render_plan(sections=[section], drop_plan=drop_plan)
        result = FinalPlanResolver(plan).resolve()

        riser_events = [
            e for e in result.resolved_sections[0].final_boundary_events
            if e.event_type == "riser_fx"
        ]
        assert len(riser_events) == 1
        assert riser_events[0].source_engine == "drop"

    def test_boundary_event_applied_once_per_section(self):
        """No boundary event type should appear more than once in a section."""
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            bar_start=8,
            instruments=["drums", "bass"],
            boundary_events=[
                {"type": "drum_fill", "placement": "boundary", "intensity": 0.6},
                {"type": "drum_fill", "placement": "post_boundary", "intensity": 0.9},
            ],
        )
        plan = _make_render_plan(sections=[section])
        result = FinalPlanResolver(plan).resolve()

        type_counts: dict = {}
        for evt in result.resolved_sections[0].final_boundary_events:
            type_counts[evt.event_type] = type_counts.get(evt.event_type, 0) + 1
        for count in type_counts.values():
            assert count == 1


# ===========================================================================
# Repeated sections differ in resolved plan
# ===========================================================================


class TestRepeatedSectionsDiffer:
    def test_two_hooks_have_different_roles(self):
        """Hook 2 gets melody reintroduced while Hook 1 is sparse."""
        sections = [
            _make_section("Hook 1", "hook", bar_start=0, instruments=["drums", "bass"]),
            _make_section("Hook 2", "hook", bar_start=16, instruments=["drums", "bass", "melody"]),
        ]
        decision = _make_decision_plan(sections=[
            _make_section_decision("Hook 1", occurrence_index=0, blocked_roles=["melody"]),
        ])
        plan = _make_render_plan(sections=sections, decision_plan=decision)
        result = FinalPlanResolver(plan, available_roles=["drums", "bass", "melody"]).resolve()

        hook1_roles = set(result.resolved_sections[0].final_active_roles)
        hook2_roles = set(result.resolved_sections[1].final_active_roles)
        assert hook1_roles != hook2_roles

    def test_two_verses_with_different_blocked_roles(self):
        sections = [
            _make_section("Verse 1", "verse", bar_start=0, instruments=["drums", "bass", "melody"]),
            _make_section("Verse 2", "verse", bar_start=16, instruments=["drums", "bass", "melody"]),
        ]
        decision = _make_decision_plan(sections=[
            _make_section_decision("Verse 1", occurrence_index=0, blocked_roles=["melody"]),
        ])
        plan = _make_render_plan(sections=sections, decision_plan=decision)
        result = FinalPlanResolver(plan, available_roles=["drums", "bass", "melody"]).resolve()

        v1_roles = result.resolved_sections[0].final_active_roles
        v2_roles = result.resolved_sections[1].final_active_roles
        assert "melody" not in v1_roles
        assert "melody" in v2_roles


# ===========================================================================
# No-op annotations
# ===========================================================================


class TestNoopAnnotations:
    def test_phantom_blocked_role_creates_noop(self):
        """Blocking a role not in section base_roles creates a no-op annotation."""
        section = _make_section(instruments=["drums", "bass"])
        decision = _make_decision_plan(sections=[
            _make_section_decision(
                section_name="Verse 1",
                blocked_roles=["phantom_role"],
            )
        ])
        plan = _make_render_plan(sections=[section], decision_plan=decision)
        result = FinalPlanResolver(plan).resolve()

        assert len(result.noop_annotations) >= 1
        noop_actions = [ann["planned_action"] for ann in result.noop_annotations]
        assert any("phantom_role" in a for a in noop_actions)

    def test_duplicate_boundary_event_creates_noop(self):
        section = _make_section(
            section_type="hook",
            bar_start=8,
            boundary_events=[
                {"type": "drum_fill", "placement": "boundary", "intensity": 0.6},
                {"type": "drum_fill", "placement": "post_boundary", "intensity": 0.9},
            ],
        )
        plan = _make_render_plan(sections=[section])
        result = FinalPlanResolver(plan).resolve()
        noop_actions = [ann.get("planned_action", "") for ann in result.noop_annotations]
        assert any("drum_fill" in a for a in noop_actions)


# ===========================================================================
# to_dict serialisation
# ===========================================================================


class TestResolvedRenderPlanSerialization:
    def test_to_dict_contains_required_keys(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = FinalPlanResolver(plan).resolve()
        d = result.to_dict()
        for key in (
            "resolver_version", "bpm", "key", "total_bars", "source_quality",
            "available_roles", "genre", "section_count", "resolved_sections",
            "final_section_role_map", "noop_annotations",
        ):
            assert key in d, f"Missing key: {key}"

    def test_resolved_section_to_dict_contains_required_keys(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = FinalPlanResolver(plan).resolve()
        sec_dict = result.resolved_sections[0].to_dict()
        for key in (
            "section_name", "section_type", "bar_start", "bars", "energy",
            "final_active_roles", "final_blocked_roles", "final_reentries",
            "final_boundary_events", "timeline_events",
        ):
            assert key in sec_dict, f"Missing key: {key}"
