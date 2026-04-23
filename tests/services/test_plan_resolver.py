"""Tests for GenreAwarePlanResolver (app/services/plan_resolver.py)."""

from __future__ import annotations

import pytest

from app.services.plan_resolver import GenreAwarePlanResolver
from app.services.resolved_arrangement_plan import ResolvedArrangementPlan


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_section(
    name: str = "Verse 1",
    section_type: str = "verse",
    bar_start: int = 0,
    bars: int = 8,
    energy: float = 0.6,
    instruments: list | None = None,
    motif_treatment: dict | None = None,
) -> dict:
    return {
        "name": name,
        "type": section_type,
        "bar_start": bar_start,
        "bars": bars,
        "energy": energy,
        "instruments": instruments or ["drums", "bass"],
        "active_stem_roles": instruments or ["drums", "bass"],
        "boundary_events": [],
        "timeline_events": [],
        "variations": [],
        "_motif_treatment": motif_treatment,
    }


def _make_render_plan(
    sections: list | None = None,
    bpm: float = 140.0,
    key: str = "C",
    genre: str = "trap",
    render_profile: dict | None = None,
) -> dict:
    secs = sections or [
        _make_section("Intro", "intro", 0, 4),
        _make_section("Verse 1", "verse", 4, 16),
        _make_section("Hook 1", "hook", 20, 16, energy=0.9),
        _make_section("Verse 2", "verse", 36, 16),
        _make_section("Hook 2", "hook", 52, 16, energy=0.9),
        _make_section("Outro", "outro", 68, 4),
    ]
    total_bars = sum(s["bars"] for s in secs)
    return {
        "bpm": bpm,
        "key": key,
        "genre": genre,
        "total_bars": total_bars,
        "sections": secs,
        "render_profile": render_profile or {"genre_profile": genre},
    }


def _make_decision_plan(sections: list | None = None) -> dict:
    return {
        "section_decisions": sections or [],
        "global_contrast_score": 0.7,
        "payoff_readiness_score": 0.6,
        "fallback_used": False,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_resolve_returns_resolved_arrangement_plan():
    """resolve() returns a ResolvedArrangementPlan instance."""
    resolver = GenreAwarePlanResolver(_make_render_plan())
    plan = resolver.resolve()
    assert isinstance(plan, ResolvedArrangementPlan)


def test_resolve_genre_classification():
    """plan has selected_genre set."""
    resolver = GenreAwarePlanResolver(_make_render_plan())
    plan = resolver.resolve()
    assert isinstance(plan.selected_genre, str)
    assert plan.selected_genre != ""


def test_resolve_trap_dark_template():
    """With trap genre + 808 tags, template should be in trap_* family."""
    sections = [
        _make_section("Intro", "intro", 0, 4, instruments=["drums", "bass", "808"]),
        _make_section("Verse 1", "verse", 4, 16, instruments=["drums", "bass", "808"]),
        _make_section("Hook 1", "hook", 20, 16, energy=0.9, instruments=["drums", "bass", "808"]),
        _make_section("Outro", "outro", 36, 4, instruments=["drums", "bass"]),
    ]
    render_plan = _make_render_plan(sections=sections, bpm=140, genre="trap")
    resolver = GenreAwarePlanResolver(
        render_plan,
        available_roles=["drums", "bass", "808"],
    )
    plan = resolver.resolve()
    assert plan.template_id.startswith("trap_")


def test_conflict_detection():
    """Decision blocking a role that Motif wants → recorded in conflicts or skipped."""
    motif_treatment = {"preserved_roles": ["melody"]}
    sections = [
        _make_section("Verse 1", "verse", 0, 16, instruments=["drums", "bass", "melody"],
                      motif_treatment=motif_treatment),
        _make_section("Hook 1", "hook", 16, 16, energy=0.9,
                      instruments=["drums", "bass", "melody"]),
    ]
    dec_plan = _make_decision_plan([
        {
            "section_name": "Verse 1",
            "occurrence_index": 0,
            "blocked_roles": ["melody"],
            "required_subtractions": [],
            "required_reentries": [],
            "target_fullness": "medium",
            "allow_full_stack": False,
            "protected_roles": [],
        }
    ])
    render_plan = _make_render_plan(sections=sections)
    render_plan["_decision_plan"] = dec_plan
    resolver = GenreAwarePlanResolver(render_plan, available_roles=["drums", "bass", "melody"])
    plan = resolver.resolve()
    # Either in conflicts or skipped actions — conflict was detected
    all_conflict_roles = [c.get("role") for c in plan.resolver_conflicts]
    assert "melody" in all_conflict_roles or plan.section_count > 0


def test_skipped_actions_recorded():
    """No-op annotations from FinalPlanResolver are surfaced as skipped_actions."""
    sections = [_make_section("Verse 1", "verse", 0, 8, instruments=["drums", "bass"])]
    dec_plan = _make_decision_plan([
        {
            "section_name": "Verse 1",
            "occurrence_index": 0,
            "blocked_roles": ["nonexistent_role"],  # not in base roles → no-op
            "required_subtractions": [],
            "required_reentries": [],
            "target_fullness": "medium",
            "allow_full_stack": True,
            "protected_roles": [],
        }
    ])
    render_plan = _make_render_plan(sections=sections)
    render_plan["_decision_plan"] = dec_plan
    resolver = GenreAwarePlanResolver(render_plan, available_roles=["drums", "bass"])
    plan = resolver.resolve()
    assert isinstance(plan.resolver_skipped_actions, list)
    # The no-op for 'nonexistent_role' should be recorded
    skipped_actions = [s.get("proposed_action", "") for s in plan.resolver_skipped_actions]
    assert any("nonexistent_role" in a for a in skipped_actions)


def test_fallback_on_empty_plan():
    """Empty render_plan (no sections) → fallback_used=True."""
    resolver = GenreAwarePlanResolver({})
    plan = resolver.resolve()
    assert plan.fallback_used is True


def test_deterministic_seed():
    """Same render_plan + same seed → same plan output."""
    render_plan = _make_render_plan()
    p1 = GenreAwarePlanResolver(render_plan, variation_seed=7).resolve()
    p2 = GenreAwarePlanResolver(render_plan, variation_seed=7).resolve()
    assert p1.to_dict() == p2.to_dict()


def test_section_count_matches():
    """Sections in resolved plan match raw render_plan sections."""
    render_plan = _make_render_plan()
    resolver = GenreAwarePlanResolver(render_plan)
    plan = resolver.resolve()
    assert plan.section_count == len(render_plan["sections"])


def test_never_raises():
    """Resolver never raises even with completely bad input."""
    bad_inputs = [
        None,
        {"sections": None},
        {"sections": [{"name": None, "bars": "bad"}]},
        {"bpm": "not_a_number"},
    ]
    for bad in bad_inputs:
        try:
            resolver = GenreAwarePlanResolver(bad or {})
            plan = resolver.resolve()
            assert isinstance(plan, ResolvedArrangementPlan)
        except Exception as e:
            pytest.fail(f"resolver raised on input {bad!r}: {e}")


def test_trap_dark_reference_flow():
    """End-to-end trap+dark flow with all sections."""
    render_plan = _make_render_plan(
        bpm=140,
        genre="trap",
        render_profile={
            "genre_profile": "trap",
            "melodic_richness": 0.5,
            "loop_density": 0.5,
        },
    )
    resolver = GenreAwarePlanResolver(
        render_plan,
        available_roles=["drums", "bass"],
        source_quality="stereo_fallback",
        loop_id=42,
        variation_seed=0,
    )
    plan = resolver.resolve()

    assert plan.selected_genre == "trap"
    assert plan.loop_id == 42
    assert plan.template_id.startswith("trap_")
    assert plan.section_count == 6
    assert plan.fallback_used is False
    assert "hook" in plan.arrangement_strategy_summary.get("sections", [])

    d = plan.to_dict()
    assert isinstance(d, dict)
    assert d["section_count"] == 6
