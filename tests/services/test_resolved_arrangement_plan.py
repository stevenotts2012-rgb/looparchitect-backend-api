"""Tests for ResolvedArrangementPlan dataclasses (app/services/resolved_arrangement_plan.py)."""

from __future__ import annotations

import pytest

from app.services.resolved_arrangement_plan import (
    ResolvedArrangementPlan,
    ResolvedArrangementSection,
)


def _make_section(**kwargs) -> ResolvedArrangementSection:
    defaults = dict(
        section_name="Hook 1",
        section_type="hook",
        occurrence_index=0,
        start_bar=0,
        length_bars=16,
        target_energy=0.9,
        target_fullness=0.85,
        final_active_roles=["drums", "bass", "melody"],
    )
    defaults.update(kwargs)
    return ResolvedArrangementSection(**defaults)


def _make_plan(**kwargs) -> ResolvedArrangementPlan:
    defaults = dict(
        loop_id=1,
        selected_genre="trap",
        selected_vibe="dark",
        style_profile="trap_dark_balanced",
        template_id="trap_A",
        variation_seed=0,
        sections=[_make_section()],
        global_scores={"genre_confidence": 0.85, "vibe_confidence": 0.80, "contrast_score": 0.3},
        warnings=[],
        fallback_used=False,
        arrangement_strategy_summary={"genre": "trap"},
        resolver_conflicts=[],
        resolver_skipped_actions=[],
    )
    defaults.update(kwargs)
    return ResolvedArrangementPlan(**defaults)


def test_section_to_dict():
    """ResolvedArrangementSection.to_dict() has expected keys."""
    sec = _make_section()
    d = sec.to_dict()
    for key in (
        "section_name", "section_type", "occurrence_index", "start_bar",
        "length_bars", "target_energy", "target_fullness", "final_active_roles",
        "final_blocked_roles", "final_reentry_roles", "final_pattern_events",
        "final_groove_events", "final_boundary_events", "final_motif_treatment",
        "final_transition_profile", "final_hook_payoff_level", "final_notes",
    ):
        assert key in d, f"Missing key in section dict: {key}"


def test_plan_to_dict_keys():
    """ResolvedArrangementPlan.to_dict() has expected top-level keys."""
    plan = _make_plan()
    d = plan.to_dict()
    for key in (
        "loop_id", "selected_genre", "selected_vibe", "style_profile",
        "template_id", "variation_seed", "section_count", "sections",
        "global_scores", "warnings", "fallback_used",
        "arrangement_strategy_summary", "resolver_conflicts",
        "resolver_skipped_actions",
    ):
        assert key in d, f"Missing key in plan dict: {key}"


def test_section_count_property():
    """section_count == len(sections)."""
    sections = [_make_section(section_name=f"Section {i}") for i in range(3)]
    plan = _make_plan(sections=sections)
    assert plan.section_count == 3


def test_fallback_flag():
    """fallback_used field is present and boolean."""
    plan = _make_plan(fallback_used=True)
    d = plan.to_dict()
    assert isinstance(d["fallback_used"], bool)
    assert d["fallback_used"] is True


def test_metadata_fields():
    """selected_genre, selected_vibe, style_profile, template_id all serialized."""
    plan = _make_plan()
    d = plan.to_dict()
    assert d["selected_genre"] == "trap"
    assert d["selected_vibe"] == "dark"
    assert d["style_profile"] == "trap_dark_balanced"
    assert d["template_id"] == "trap_A"


def test_conflicts_serialization():
    """resolver_conflicts serializes as a list."""
    plan = _make_plan(
        resolver_conflicts=[{"conflict_type": "decision_blocks_motif_role", "role": "melody"}]
    )
    d = plan.to_dict()
    assert isinstance(d["resolver_conflicts"], list)
    assert len(d["resolver_conflicts"]) == 1


def test_skipped_actions_serialization():
    """resolver_skipped_actions serializes as a list."""
    plan = _make_plan(
        resolver_skipped_actions=[{"engine_name": "motif", "proposed_action": "add_role"}]
    )
    d = plan.to_dict()
    assert isinstance(d["resolver_skipped_actions"], list)
    assert len(d["resolver_skipped_actions"]) == 1
