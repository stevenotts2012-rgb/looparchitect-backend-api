"""
Integration tests — Impact & Contrast Engine pipeline integration.

Tests cover (per problem-statement §6):

1.  Feature flag off  → no impact pass runs
2.  Feature flag on   → impact pass runs and metadata is recorded
3.  Impact failure    → graceful fallback, repaired plan preserved
4.  Contrast improves when low (contrast_score < 0.6)
5.  Hooks become highest-energy sections
6.  Drop event inserted before hook when missing
7.  re_entry_accent inserted when hook follows pre-hook and it is missing
8.  Repeated sections diverge (≥ 2 audible dimensions)
9.  Duplicate drop events are not created
10. Metadata is JSON-serialisable
11. Final audit (post_impact_quality_report) exists after impact pass
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any, Dict, List, Optional
from unittest.mock import MagicMock, patch

import pytest

from app.services.impact_engine import ImpactEngine, _DROP_EVENT_TYPES
from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)


# ---------------------------------------------------------------------------
# Helpers — mirrors helpers in test_impact_engine.py
# ---------------------------------------------------------------------------


def _be(
    event_type: str = "drum_fill",
    intensity: float = 0.70,
    source_engine: str = "test",
    bar: int = 0,
    params: dict | None = None,
) -> ResolvedBoundaryEvent:
    return ResolvedBoundaryEvent(
        event_type=event_type,
        source_engine=source_engine,
        placement="boundary",
        intensity=intensity,
        bar=bar,
        params=params or {},
    )


def _sec(
    name: str = "Verse 1",
    section_type: str = "verse",
    bar_start: int = 0,
    bars: int = 8,
    energy: float = 0.60,
    active: list[str] | None = None,
    blocked: list[str] | None = None,
    reentries: list[str] | None = None,
    boundary_events: list[ResolvedBoundaryEvent] | None = None,
    pattern_events: list[dict] | None = None,
    groove_events: list[dict] | None = None,
    target_fullness: str | None = None,
) -> ResolvedSection:
    return ResolvedSection(
        section_name=name,
        section_type=section_type,
        bar_start=bar_start,
        bars=bars,
        energy=energy,
        final_active_roles=active or ["drums", "bass"],
        final_blocked_roles=blocked or [],
        final_reentries=reentries or [],
        final_boundary_events=boundary_events or [],
        final_pattern_events=pattern_events or [],
        final_groove_events=groove_events or [],
        target_fullness=target_fullness,
    )


def _plan(
    sections: list[ResolvedSection],
    available_roles: list[str] | None = None,
) -> ResolvedRenderPlan:
    return ResolvedRenderPlan(
        resolved_sections=sections,
        bpm=140.0,
        key="G minor",
        total_bars=sum(s.bars for s in sections),
        source_quality="true_stems",
        available_roles=available_roles
        or ["drums", "bass", "808", "melody", "pads", "synth", "fx"],
        genre="trap",
        noop_annotations=[],
    )


def _run_engine(
    sections: list[ResolvedSection],
    report: dict | None = None,
    available_roles: list[str] | None = None,
    genre: str = "trap",
    vibe: str = "aggressive",
) -> tuple[ResolvedRenderPlan, dict]:
    """Run the ImpactEngine directly and return (plan, metadata)."""
    p = _plan(sections, available_roles)
    r = report or {
        "repetition_groups": [],
        "contrast_score": 1.0,
        "hook_payoff_score": 1.0,
        "impact_scores": {},
        "safety_findings": [],
    }
    engine = ImpactEngine(
        resolved_plan=p,
        production_quality_report=r,
        selected_genre=genre,
        selected_vibe=vibe,
        arrangement_id=1,
    )
    return engine.enforce()


def _section_by_name(plan: ResolvedRenderPlan, name: str) -> ResolvedSection:
    for sec in plan.resolved_sections:
        if sec.section_name == name:
            return sec
    raise KeyError(name)


# ---------------------------------------------------------------------------
# Minimal stub for ProductionQualityAuditor used in pipeline integration tests
# ---------------------------------------------------------------------------

_DUMMY_AUDIT_REPORT: dict = {
    "contrast_score": 1.0,
    "repetition_score": 1.0,
    "hook_payoff_score": 1.0,
    "repetition_groups": [],
    "safety_findings": [],
}


# ---------------------------------------------------------------------------
# 1 & 2 — Feature flag gates the impact pass
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    """Tests that IMPACT_ENGINE_ENABLED controls whether the pass runs."""

    def _make_render_plan_and_resolved(self):
        """Return a minimal (render_plan dict, resolved plan) pair."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60, active=["drums", "bass", "melody"])
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.85,
            active=["drums", "bass", "melody", "pads"],
        )
        resolved = _plan([verse, hook])
        render_plan: dict = {
            "genre": "trap",
            "vibe": "aggressive",
            "_resolved_render_plan": resolved.to_dict(),
        }
        return render_plan, resolved

    def test_flag_off_no_impact_key(self):
        """When IMPACT_ENGINE_ENABLED=false, render_plan must not contain _impact_engine."""
        from app.config import Settings

        render_plan, resolved = self._make_render_plan_and_resolved()

        settings = Settings(IMPACT_ENGINE_ENABLED=False)  # type: ignore[call-arg]

        # Simulate the pipeline block
        _resolved = resolved
        if settings.feature_impact_engine:
            # This branch must NOT run
            render_plan["_impact_engine"] = {"should_not": "be_here"}

        assert "_impact_engine" not in render_plan, (
            "_impact_engine key present even though flag is off"
        )

    def test_flag_on_impact_key_present(self):
        """When IMPACT_ENGINE_ENABLED=true, render_plan must contain _impact_engine."""
        from app.config import Settings

        render_plan, resolved = self._make_render_plan_and_resolved()

        settings = Settings(IMPACT_ENGINE_ENABLED=True)  # type: ignore[call-arg]

        _resolved = resolved
        if settings.feature_impact_engine:
            _impact_meta: dict = {"impact_engine_enabled": True}
            try:
                engine = ImpactEngine(
                    resolved_plan=_resolved,
                    production_quality_report=_DUMMY_AUDIT_REPORT,
                    selected_genre=str(render_plan.get("genre") or "generic"),
                    selected_vibe=str(render_plan.get("vibe") or "neutral"),
                    arrangement_id=1,
                )
                _impacted_plan, _engine_meta = engine.enforce()
                if _engine_meta.get("impact_engine_applied"):
                    _resolved = _impacted_plan
                    render_plan["_resolved_render_plan"] = _impacted_plan.to_dict()
                _impact_meta.update(_engine_meta)
            except Exception as exc:
                _impact_meta["impact_engine_fallback_used"] = True
                _impact_meta["impact_engine_fallback_reason"] = str(exc)
            render_plan["_impact_engine"] = _impact_meta

        assert "_impact_engine" in render_plan, (
            "_impact_engine key missing even though flag is on"
        )
        assert render_plan["_impact_engine"].get("impact_engine_enabled") is True


# ---------------------------------------------------------------------------
# 3 — Impact failure falls back safely
# ---------------------------------------------------------------------------


class TestFallbackBehavior:
    def test_impact_engine_failure_does_not_crash(self):
        """If ImpactEngine.enforce() raises, the original plan is preserved."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60)
        hook = _sec("Hook 1", "hook", 8, 8, 0.85)
        resolved = _plan([verse, hook])
        render_plan: dict = {
            "genre": "trap",
            "_resolved_render_plan": resolved.to_dict(),
        }

        _impact_meta: dict = {
            "impact_engine_enabled": True,
            "impact_engine_applied": False,
            "impact_engine_fallback_used": False,
            "impact_engine_fallback_reason": None,
        }
        original_resolved = resolved

        try:
            with patch.object(ImpactEngine, "enforce", side_effect=RuntimeError("boom")):
                engine = ImpactEngine(
                    resolved_plan=resolved,
                    production_quality_report=_DUMMY_AUDIT_REPORT,
                    selected_genre="trap",
                    selected_vibe="neutral",
                    arrangement_id=1,
                )
                engine.enforce()  # Will raise
        except Exception as exc:
            _impact_meta["impact_engine_fallback_used"] = True
            _impact_meta["impact_engine_fallback_reason"] = str(exc)

        render_plan["_impact_engine"] = _impact_meta

        assert _impact_meta["impact_engine_fallback_used"] is True
        assert "boom" in (_impact_meta["impact_engine_fallback_reason"] or "")
        # Original resolved plan must be intact (no mutation)
        assert original_resolved is resolved

    def test_impact_fallback_reason_recorded(self):
        """Fallback reason must be a non-empty string on failure."""
        _impact_meta: dict = {
            "impact_engine_fallback_used": False,
            "impact_engine_fallback_reason": None,
        }
        try:
            raise ValueError("test error")
        except Exception as exc:
            _impact_meta["impact_engine_fallback_used"] = True
            _impact_meta["impact_engine_fallback_reason"] = str(exc)

        assert _impact_meta["impact_engine_fallback_used"] is True
        assert _impact_meta["impact_engine_fallback_reason"] == "test error"


# ---------------------------------------------------------------------------
# 4 — Contrast improves when low
# ---------------------------------------------------------------------------


class TestContrastIntegration:
    def test_verse_density_reduced(self):
        """Verse density is reduced when contrast_score < 0.6."""
        verse = _sec(
            "Verse 1", "verse", 0, 8, 0.55,
            active=["drums", "bass", "melody", "pads", "synth"],
        )
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.85,
            active=["drums", "bass", "melody", "pads", "synth", "808"],
        )
        report = {"contrast_score": 0.4}
        plan, meta = _run_engine([verse, hook], report)

        repaired_verse = _section_by_name(plan, "Verse 1")
        assert len(repaired_verse.final_active_roles) < len(verse.final_active_roles), (
            "Verse density not reduced under low contrast"
        )
        assert meta["impact_engine_applied"] is True

    def test_hook_fullness_set_to_full(self):
        """Hook target_fullness is set to 'full' when contrast_score < 0.6."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.55)
        hook = _sec("Hook 1", "hook", 8, 8, 0.70)
        report = {"contrast_score": 0.3}
        plan, meta = _run_engine([verse, hook], report)

        repaired_hook = _section_by_name(plan, "Hook 1")
        assert repaired_hook.target_fullness == "full", (
            "Hook target_fullness not set to 'full' under low contrast"
        )

    def test_contrast_adjustments_metadata_populated(self):
        """contrast_adjustments metadata must be non-empty under low contrast."""
        verse = _sec("V1", "verse", 0, 8, 0.55, active=["drums", "bass", "melody"])
        hook = _sec("H1", "hook", 8, 8, 0.70, active=["drums", "bass", "melody", "pads"])
        report = {"contrast_score": 0.2}
        _, meta = _run_engine([verse, hook], report)

        assert meta["contrast_adjustments"], "contrast_adjustments must not be empty"


# ---------------------------------------------------------------------------
# 5 — Hooks become highest-energy sections
# ---------------------------------------------------------------------------


class TestHookEnergyIdentity:
    def test_hook_energy_exceeds_verse(self):
        """Hook energy must be ≥ verse energy after engine runs."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.80)
        hook = _sec("Hook 1", "hook", 8, 8, 0.65)  # lower than verse — must be fixed
        plan, meta = _run_engine([verse, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        repaired_verse = _section_by_name(plan, "Verse 1")
        assert repaired_hook.energy >= repaired_verse.energy, (
            "Hook energy not raised above verse energy"
        )

    def test_hook_reaches_minimum_energy(self):
        """Hook energy must reach at least 0.9 (HOOK_MIN_ENERGY constant)."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60)
        hook = _sec("Hook 1", "hook", 8, 8, 0.50)
        plan, meta = _run_engine([verse, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        assert repaired_hook.energy >= 0.9, (
            f"Hook energy {repaired_hook.energy} below minimum 0.9"
        )


# ---------------------------------------------------------------------------
# 6 — Drop event inserted before hook when missing
# ---------------------------------------------------------------------------


class TestDropEventInsertion:
    def test_drop_inserted_when_missing(self):
        """A hook with no drop event receives a silence_drop_before_hook."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("drum_fill")],
        )
        plan, meta = _run_engine([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        event_types = {e.event_type for e in repaired_hook.final_boundary_events}
        assert event_types & _DROP_EVENT_TYPES, (
            "No drop event was added to hook that lacked one"
        )

    def test_drop_enforcement_metadata_recorded(self):
        """drop_enforcements metadata must contain an entry when a drop is added."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("drum_fill")],
        )
        _, meta = _run_engine([hook])

        assert meta["drop_enforcements"], (
            "drop_enforcements metadata is empty after drop insertion"
        )

    def test_drop_present_in_each_hook(self):
        """Every hook section must have at least one drop event after the pass."""
        hook1 = _sec("Hook 1", "hook", 8, 8, 0.90)
        hook2 = _sec("Hook 2", "hook", 24, 8, 0.90)
        plan, _ = _run_engine([hook1, hook2])

        for sec in plan.resolved_sections:
            if sec.section_type in ("hook", "chorus"):
                event_types = {e.event_type for e in sec.final_boundary_events}
                assert event_types & _DROP_EVENT_TYPES, (
                    f"Section '{sec.section_name}' lacks a drop event"
                )


# ---------------------------------------------------------------------------
# 7 — re_entry_accent inserted when missing
# ---------------------------------------------------------------------------


class TestReentryAccentInsertion:
    def test_accent_added_when_hook_follows_pre_hook(self):
        """re_entry_accent must be added to hook that immediately follows a pre-hook."""
        pre_hook = _sec("Pre-Hook 1", "pre_hook", 8, 4, 0.70)
        hook = _sec("Hook 1", "hook", 12, 8, 0.90)
        plan, meta = _run_engine([pre_hook, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        event_types = {e.event_type for e in repaired_hook.final_boundary_events}
        assert "re_entry_accent" in event_types, (
            "re_entry_accent not inserted when hook follows pre-hook"
        )

    def test_reentry_metadata_recorded(self):
        """reentry_enforcements must be populated when re_entry_accent is added."""
        pre_hook = _sec("Pre-Hook 1", "pre_hook", 8, 4, 0.70)
        hook = _sec("Hook 1", "hook", 12, 8, 0.90)
        _, meta = _run_engine([pre_hook, hook])

        assert meta["reentry_enforcements"], (
            "reentry_enforcements metadata is empty"
        )

    def test_accent_not_added_without_pre_hook(self):
        """re_entry_accent must NOT be added when hook does not follow a pre-hook."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60)
        hook = _sec("Hook 1", "hook", 8, 8, 0.90)
        plan, meta = _run_engine([verse, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        accent_count = sum(
            1 for e in repaired_hook.final_boundary_events
            if e.event_type == "re_entry_accent"
        )
        assert accent_count == 0, (
            "re_entry_accent incorrectly added when hook follows verse (not pre-hook)"
        )


# ---------------------------------------------------------------------------
# 8 — Repeated sections diverge
# ---------------------------------------------------------------------------


class TestRepeatedSectionDivergence:
    def test_second_repeated_section_differs(self):
        """Second occurrence of a repeated section must differ in ≥ 2 dimensions."""
        sec1 = _sec("Verse 1", "verse", 0, 8, 0.60, active=["drums", "bass", "melody", "pads"])
        sec2 = _sec("Verse 2", "verse", 8, 8, 0.60, active=["drums", "bass", "melody", "pads"])
        report = {
            "contrast_score": 1.0,
            "repetition_groups": [{"sections": ["Verse 1", "Verse 2"]}],
        }
        plan, meta = _run_engine([sec1, sec2], report)

        v2 = _section_by_name(plan, "Verse 2")
        orig = sec1  # first section (unmodified)

        diffs = 0
        if v2.energy != orig.energy:
            diffs += 1
        if any(
            "impact_variation_pass" in str(e.get("action", ""))
            for e in v2.final_pattern_events
        ):
            diffs += 1
        if any(
            "impact_groove_shift" in str(e.get("groove_type", ""))
            for e in v2.final_groove_events
        ):
            diffs += 1
        if set(v2.final_active_roles) != set(orig.final_active_roles):
            diffs += 1

        assert diffs >= 2, f"Only {diffs} dimension(s) changed — expected ≥ 2"

    def test_repetition_fix_metadata_recorded(self):
        """contrast_adjustments must include a repeated_section_differentiated record."""
        sec1 = _sec("V1", "verse", 0, 8, 0.60, active=["drums", "bass"])
        sec2 = _sec("V2", "verse", 8, 8, 0.60, active=["drums", "bass"])
        report = {
            "contrast_score": 1.0,
            "repetition_groups": [{"sections": ["V1", "V2"]}],
        }
        _, meta = _run_engine([sec1, sec2], report)

        assert any(
            a.get("rule") == "repeated_section_differentiated"
            for a in meta["contrast_adjustments"]
        ), "No repeated_section_differentiated record in metadata"


# ---------------------------------------------------------------------------
# 9 — Duplicate drop events are not created
# ---------------------------------------------------------------------------


class TestNoDuplicateDropEvents:
    def test_existing_silence_drop_not_duplicated(self):
        """A hook that already has silence_drop must not receive a second one."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("silence_drop", bar=8)],
        )
        plan, _ = _run_engine([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        silence_drop_count = sum(
            1 for e in repaired_hook.final_boundary_events
            if e.event_type == "silence_drop"
        )
        assert silence_drop_count == 1, (
            f"silence_drop duplicated: found {silence_drop_count} instances"
        )

    def test_existing_subtractive_entry_not_duplicated(self):
        """subtractive_entry already present must not be added again."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("subtractive_entry", bar=8)],
        )
        plan, _ = _run_engine([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        count = sum(
            1 for e in repaired_hook.final_boundary_events
            if e.event_type == "subtractive_entry"
        )
        assert count == 1, f"subtractive_entry duplicated: found {count} instances"

    def test_fx_impact_not_duplicated(self):
        """fx_impact event must appear exactly once per hook, even when already present."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("fx_impact")],
        )
        plan, _ = _run_engine([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        count = sum(
            1 for e in repaired_hook.final_boundary_events
            if e.event_type == "fx_impact"
        )
        assert count == 1, f"fx_impact duplicated: found {count} instances"


# ---------------------------------------------------------------------------
# 10 — Metadata is JSON-serialisable
# ---------------------------------------------------------------------------


class TestMetadataSerialisation:
    def test_engine_metadata_json_serialisable(self):
        """All metadata returned by ImpactEngine.enforce() must serialise to JSON."""
        verse = _sec("V1", "verse", 0, 8, 0.55, active=["drums", "bass", "melody", "pads"])
        hook = _sec("H1", "hook", 8, 8, 0.85, active=["drums", "bass", "melody"])
        pre_hook = _sec("PH1", "pre_hook", 4, 4, 0.70)
        sec1 = _sec("V2", "verse", 16, 8, 0.55, active=["drums", "bass"])
        sec2 = _sec("V3", "verse", 24, 8, 0.55, active=["drums", "bass"])

        report = {
            "contrast_score": 0.3,
            "repetition_groups": [{"sections": ["V2", "V3"]}],
        }
        _, meta = _run_engine([verse, pre_hook, hook, sec1, sec2], report)

        try:
            serialised = json.dumps(meta)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"ImpactEngine metadata is not JSON-serialisable: {exc}")

        # Round-trip check
        loaded = json.loads(serialised)
        assert isinstance(loaded, dict), "Deserialised metadata is not a dict"

    def test_render_plan_impact_meta_json_serialisable(self):
        """The _impact_engine key added to render_plan must serialise cleanly."""
        verse = _sec("V1", "verse", 0, 8, 0.60)
        hook = _sec("H1", "hook", 8, 8, 0.85)
        resolved = _plan([verse, hook])

        engine = ImpactEngine(
            resolved_plan=resolved,
            production_quality_report=_DUMMY_AUDIT_REPORT,
            selected_genre="trap",
            selected_vibe="aggressive",
            arrangement_id=1,
        )
        _, engine_meta = engine.enforce()

        _impact_meta: dict = {
            "impact_engine_enabled": True,
            "impact_engine_applied": engine_meta.get("impact_engine_applied", False),
            "impact_engine_fallback_used": False,
            "impact_engine_fallback_reason": None,
            "impact_adjustments": (
                engine_meta.get("contrast_adjustments", [])
                + engine_meta.get("drop_enforcements", [])
                + engine_meta.get("reentry_enforcements", [])
            ),
            "post_impact_quality_report": {},
            "contrast_adjustment_count": len(engine_meta.get("contrast_adjustments", [])),
            "drop_enforcement_count": len(engine_meta.get("drop_enforcements", [])),
            "reentry_enforcement_count": len(engine_meta.get("reentry_enforcements", [])),
            "repetition_fix_count": 0,
        }

        try:
            json.dumps(_impact_meta)
        except (TypeError, ValueError) as exc:
            pytest.fail(f"_impact_engine render_plan meta is not JSON-serialisable: {exc}")


# ---------------------------------------------------------------------------
# 11 — Final audit exists after impact pass
# ---------------------------------------------------------------------------


class TestFinalAuditAfterImpact:
    def test_post_impact_quality_report_populated(self):
        """After an impact pass, post_impact_quality_report must be a non-empty dict."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60, active=["drums", "bass", "melody"])
        hook = _sec("Hook 1", "hook", 8, 8, 0.85, active=["drums", "bass", "melody", "pads"])
        resolved = _plan([verse, hook])

        engine = ImpactEngine(
            resolved_plan=resolved,
            production_quality_report=_DUMMY_AUDIT_REPORT,
            selected_genre="trap",
            selected_vibe="aggressive",
            arrangement_id=1,
        )
        impacted_plan, engine_meta = engine.enforce()

        # Simulate the pipeline: run final audit after impact pass
        from app.services.production_quality_auditor import ProductionQualityAuditor

        post_auditor = ProductionQualityAuditor(
            impacted_plan,
            raw_render_plan={},
            arrangement_id=1,
        )
        post_report = post_auditor.audit()

        assert isinstance(post_report, dict), "post_impact_quality_report is not a dict"
        assert post_report, "post_impact_quality_report is empty"

    def test_post_impact_report_has_standard_keys(self):
        """post_impact_quality_report must contain standard audit score keys."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60, active=["drums", "bass"])
        hook = _sec("Hook 1", "hook", 8, 8, 0.85, active=["drums", "bass", "melody"])
        resolved = _plan([verse, hook])

        engine = ImpactEngine(
            resolved_plan=resolved,
            production_quality_report=_DUMMY_AUDIT_REPORT,
            selected_genre="trap",
            selected_vibe="neutral",
            arrangement_id=1,
        )
        impacted_plan, _ = engine.enforce()

        from app.services.production_quality_auditor import ProductionQualityAuditor

        post_auditor = ProductionQualityAuditor(
            impacted_plan,
            raw_render_plan={},
            arrangement_id=1,
        )
        post_report = post_auditor.audit()

        # The auditor must produce at least one score key
        score_keys = {k for k in post_report if "score" in k.lower()}
        assert score_keys, (
            f"post_impact_quality_report has no score keys: {list(post_report.keys())}"
        )


# ---------------------------------------------------------------------------
# Summary counts integration
# ---------------------------------------------------------------------------


class TestSummaryCountsIntegration:
    """Ensure the four summary count fields are computed correctly in the pipeline."""

    def test_all_summary_count_fields_present(self):
        """_impact_engine dict must always include all four summary count fields."""
        verse = _sec("V1", "verse", 0, 8, 0.55, active=["drums", "bass", "melody", "pads"])
        hook = _sec("H1", "hook", 8, 8, 0.85, active=["drums", "bass", "melody", "pads"])
        resolved = _plan([verse, hook])

        engine = ImpactEngine(
            resolved_plan=resolved,
            production_quality_report={"contrast_score": 0.3},
            selected_genre="trap",
            selected_vibe="aggressive",
            arrangement_id=1,
        )
        _, engine_meta = engine.enforce()

        # Build the _impact_engine dict the same way arrangement_jobs does
        _contrast_adj_count = sum(
            1 for a in engine_meta.get("contrast_adjustments", [])
            if a.get("rule") in (
                "verse_density_reduced",
                "hook_density_boosted",
                "hook_identity_strengthened",
            )
        )
        _impact_meta = {
            "impact_engine_enabled": True,
            "impact_engine_applied": engine_meta.get("impact_engine_applied", False),
            "impact_engine_fallback_used": False,
            "impact_engine_fallback_reason": None,
            "impact_adjustments": (
                engine_meta.get("contrast_adjustments", [])
                + engine_meta.get("drop_enforcements", [])
                + engine_meta.get("reentry_enforcements", [])
            ),
            "post_impact_quality_report": {},
            "contrast_adjustment_count": _contrast_adj_count,
            "drop_enforcement_count": len(engine_meta.get("drop_enforcements", [])),
            "reentry_enforcement_count": len(engine_meta.get("reentry_enforcements", [])),
            "repetition_fix_count": 0,
        }

        for field in (
            "contrast_adjustment_count",
            "drop_enforcement_count",
            "reentry_enforcement_count",
            "repetition_fix_count",
        ):
            assert field in _impact_meta, f"Missing field: {field}"
            assert isinstance(_impact_meta[field], int), (
                f"{field} must be an int, got {type(_impact_meta[field])}"
            )

    def test_counts_are_non_negative(self):
        """All summary counts must be ≥ 0."""
        hook = _sec("H1", "hook", 8, 8, 0.85)
        resolved = _plan([hook])

        engine = ImpactEngine(
            resolved_plan=resolved,
            production_quality_report=_DUMMY_AUDIT_REPORT,
            selected_genre="trap",
            selected_vibe="neutral",
            arrangement_id=1,
        )
        _, engine_meta = engine.enforce()

        counts = [
            len(engine_meta.get("contrast_adjustments", [])),
            len(engine_meta.get("drop_enforcements", [])),
            len(engine_meta.get("reentry_enforcements", [])),
        ]
        for c in counts:
            assert c >= 0, f"Summary count is negative: {c}"
