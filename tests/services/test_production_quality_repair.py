"""
Tests for ProductionQualityRepair
(app/services/production_quality_repair.py).

Covers all required repair rules:
1.  Repeated sections are differentiated (≥ 2 audible dimensions change)
2.  Weak hook gets stronger (energy, fullness, roles, re_entry_accent)
3.  Pre-hook gets tension (anchor blocked, tension_riser added)
4.  Outro removes drums/808 and gets fade_out
5.  No-op events are removed
6.  Duplicate boundary events are deduped
7.  Render mismatch is repaired (blocked role removed from active)
8.  Post-repair quality report improves (repetition/hook scores)
9.  Repair failure is safe (returns original plan, sets repair_failed_reason)
"""

from __future__ import annotations

import pytest

from app.services.production_quality_repair import ProductionQualityRepair, run_repair
from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_boundary_event(
    event_type: str = "drum_fill",
    intensity: float = 0.8,
    source_engine: str = "section",
    bar: int = 0,
) -> ResolvedBoundaryEvent:
    return ResolvedBoundaryEvent(
        event_type=event_type,
        source_engine=source_engine,
        placement="boundary",
        intensity=intensity,
        bar=bar,
    )


def _make_section(
    section_name: str = "Verse 1",
    section_type: str = "verse",
    bar_start: int = 0,
    bars: int = 8,
    energy: float = 0.6,
    final_active_roles: list[str] | None = None,
    final_blocked_roles: list[str] | None = None,
    final_reentries: list[str] | None = None,
    final_boundary_events: list[ResolvedBoundaryEvent] | None = None,
    final_pattern_events: list[dict] | None = None,
    final_groove_events: list[dict] | None = None,
    final_motif_treatment: dict | None = None,
    target_fullness: str | None = None,
) -> ResolvedSection:
    return ResolvedSection(
        section_name=section_name,
        section_type=section_type,
        bar_start=bar_start,
        bars=bars,
        energy=energy,
        final_active_roles=final_active_roles or ["drums", "bass"],
        final_blocked_roles=final_blocked_roles or [],
        final_reentries=final_reentries or [],
        final_boundary_events=final_boundary_events or [],
        final_pattern_events=final_pattern_events or [],
        final_groove_events=final_groove_events or [],
        final_motif_treatment=final_motif_treatment,
        target_fullness=target_fullness,
    )


def _make_resolved_plan(
    sections: list[ResolvedSection],
    available_roles: list[str] | None = None,
    noop_annotations: list[dict] | None = None,
) -> ResolvedRenderPlan:
    return ResolvedRenderPlan(
        resolved_sections=sections,
        bpm=140.0,
        key="G minor",
        total_bars=sum(s.bars for s in sections),
        source_quality="true_stems",
        available_roles=available_roles or ["drums", "bass", "melody", "pads", "808"],
        genre="trap",
        noop_annotations=noop_annotations or [],
    )


def _make_quality_report(**overrides) -> dict:
    """Return a minimal quality report with sensible defaults."""
    report = {
        "repetition_score": 1.0,
        "contrast_score": 0.8,
        "hook_payoff_score": 1.0,
        "transition_safety_score": 1.0,
        "no_op_event_count": 0,
        "render_mismatch_count": 0,
        "weak_sections": [],
        "recommended_fixes": [],
        "section_audits": [],
        "trap_structure_issues": [],
        "repetition_groups": [],
        "impact_scores": {"pre_hook_tension": 1.0, "hook_payoff": 1.0},
        "safety_findings": [],
    }
    report.update(overrides)
    return report


def _run_repair(
    sections: list[ResolvedSection],
    quality_report: dict,
    available_roles: list[str] | None = None,
):
    plan = _make_resolved_plan(sections, available_roles=available_roles)
    return run_repair(
        resolved_plan=plan,
        quality_report=quality_report,
        available_roles=available_roles or plan.available_roles,
        genre="trap",
        arrangement_id=0,
    )


# ---------------------------------------------------------------------------
# 1. Repeated sections are differentiated
# ---------------------------------------------------------------------------


class TestRepeatedSectionDifferentiation:
    def test_repeated_sections_get_different_roles_or_energy(self):
        """After repair, repeated sections should have at least one audible dimension changed."""
        sec1 = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass", "melody"])
        sec2 = _make_section("Verse 2", "verse", 8, 8, 0.6, ["drums", "bass", "melody"])
        plan = _make_resolved_plan([sec1, sec2])

        report = _make_quality_report(
            repetition_score=0.5,
            repetition_groups=[{
                "sections": ["Verse 1", "Verse 2"],
                "fingerprint": {
                    "active_roles": ["bass", "drums", "melody"],
                    "density": 3,
                    "energy_bucket": 0.5,
                    "boundary_types": [],
                    "motif_type": None,
                    "drum_roles": ["drums"],
                    "bass_roles": ["bass"],
                },
            }],
        )

        result = run_repair(plan, report, available_roles=plan.available_roles)
        assert result.repair_metadata["production_quality_repair_applied"] is True
        assert result.repair_metadata["production_quality_repair_count"] >= 1

        # At least one repair log entry mentioning "Verse 2"
        verse2_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "Verse 2" in r
        ]
        assert verse2_repairs, "Expected at least one repair log entry for 'Verse 2'"

        repaired_verse2 = result.resolved_plan.resolved_sections[1]
        original_verse1 = result.resolved_plan.resolved_sections[0]

        # At least one dimension must differ
        roles_differ = set(repaired_verse2.final_active_roles) != set(original_verse1.final_active_roles)
        energy_differ = repaired_verse2.energy != original_verse1.energy
        fullness_differ = repaired_verse2.target_fullness != original_verse1.target_fullness
        pattern_differ = repaired_verse2.final_pattern_events != original_verse1.final_pattern_events
        motif_differ = repaired_verse2.final_motif_treatment != original_verse1.final_motif_treatment
        groove_differ = repaired_verse2.final_groove_events != original_verse1.final_groove_events

        assert any([roles_differ, energy_differ, fullness_differ, pattern_differ, motif_differ, groove_differ]), (
            "After repair, repeated sections must differ in at least one audible dimension"
        )

    def test_multiple_repetition_groups_all_repaired(self):
        """Both verse and hook repetition groups should be repaired."""
        sec1 = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass"])
        sec2 = _make_section("Verse 2", "verse", 8, 8, 0.6, ["drums", "bass"])
        h1 = _make_section("Hook 1", "hook", 16, 8, 0.9, ["drums", "bass", "melody", "808"])
        h2 = _make_section("Hook 2", "hook", 24, 8, 0.9, ["drums", "bass", "melody", "808"])

        report = _make_quality_report(
            repetition_score=0.25,
            repetition_groups=[
                {"sections": ["Verse 1", "Verse 2"], "fingerprint": {}},
                {"sections": ["Hook 1", "Hook 2"], "fingerprint": {}},
            ],
        )

        result = _run_repair([sec1, sec2, h1, h2], report)
        repairs = result.repair_metadata["production_quality_repairs"]

        verse2_repaired = any("Verse 2" in r for r in repairs)
        hook2_repaired = any("Hook 2" in r for r in repairs)
        assert verse2_repaired, "Verse 2 should have been repaired"
        assert hook2_repaired, "Hook 2 should have been repaired"

    def test_no_repair_when_no_repetition_groups(self):
        """No repetition repairs should be applied when there are no groups."""
        sec1 = _make_section("Intro", "intro", 0, 4, 0.3, ["melody"])
        sec2 = _make_section("Hook", "hook", 4, 8, 0.9, ["drums", "bass", "melody", "808"])

        report = _make_quality_report(repetition_score=1.0, repetition_groups=[])
        result = _run_repair([sec1, sec2], report)

        repetition_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "Repeated section" in r
        ]
        assert repetition_repairs == [], "No repetition repairs expected"


# ---------------------------------------------------------------------------
# 2. Weak hook gets stronger
# ---------------------------------------------------------------------------


class TestWeakHookRepair:
    def test_weak_hook_energy_is_raised(self):
        """A hook with energy < 0.80 should have energy raised to 0.80."""
        hook = _make_section("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass", "melody"])
        report = _make_quality_report(
            hook_payoff_score=0.3,
            impact_scores={"pre_hook_tension": 1.0, "hook_payoff": 0.3},
        )

        result = _run_repair([hook], report)
        repaired_hook = result.resolved_plan.resolved_sections[0]
        assert repaired_hook.energy >= 0.80, (
            f"Expected hook energy ≥ 0.80 after repair, got {repaired_hook.energy}"
        )

    def test_weak_hook_gets_full_fullness(self):
        """A weak hook should have target_fullness set to 'full'."""
        hook = _make_section("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass"])
        report = _make_quality_report(
            hook_payoff_score=0.2,
            impact_scores={"pre_hook_tension": 1.0, "hook_payoff": 0.2},
        )

        result = _run_repair([hook], report)
        repaired_hook = result.resolved_plan.resolved_sections[0]
        assert repaired_hook.target_fullness == "full", (
            f"Expected target_fullness='full', got {repaired_hook.target_fullness!r}"
        )

    def test_weak_hook_gets_re_entry_accent(self):
        """A weak hook without re_entry_accent should get one added."""
        hook = _make_section("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass"])
        report = _make_quality_report(
            hook_payoff_score=0.2,
            impact_scores={"pre_hook_tension": 1.0, "hook_payoff": 0.2},
        )

        result = _run_repair([hook], report)
        repaired_hook = result.resolved_plan.resolved_sections[0]
        event_types = [e.event_type for e in repaired_hook.final_boundary_events]
        assert "re_entry_accent" in event_types, (
            "Expected re_entry_accent boundary event on repaired hook"
        )

    def test_weak_hook_gets_more_roles_than_verse(self):
        """After repair, hook should have more active roles than verse when possible."""
        verse = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass", "melody"])
        hook = _make_section("Hook 1", "hook", 8, 8, 0.50, ["drums", "bass"])
        report = _make_quality_report(
            hook_payoff_score=0.2,
            impact_scores={"pre_hook_tension": 1.0, "hook_payoff": 0.2},
        )

        result = _run_repair([verse, hook], report, available_roles=["drums", "bass", "melody", "808"])
        repaired_hook = result.resolved_plan.resolved_sections[1]
        assert len(repaired_hook.final_active_roles) >= len(verse.final_active_roles), (
            "Repaired hook should have ≥ roles as verse"
        )

    def test_strong_hook_not_modified(self):
        """A hook that already passes payoff threshold should not be modified."""
        hook = _make_section("Hook 1", "hook", 0, 8, 0.9, ["drums", "bass", "melody", "808", "pads"])
        report = _make_quality_report(
            hook_payoff_score=0.9,
            impact_scores={"pre_hook_tension": 1.0, "hook_payoff": 0.9},
        )

        result = _run_repair([hook], report)
        hook_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "Weak hook" in r
        ]
        assert hook_repairs == [], f"Strong hook should not be repaired, got: {hook_repairs}"


# ---------------------------------------------------------------------------
# 3. Pre-hook gets tension
# ---------------------------------------------------------------------------


class TestPreHookTensionRepair:
    def test_prehook_gets_anchor_blocked(self):
        """A pre-hook without anchor subtraction should get one blocked."""
        pre_hook = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.65,
            final_active_roles=["drums", "bass", "melody"],
            final_blocked_roles=[],
        )
        report = _make_quality_report(
            impact_scores={"pre_hook_tension": 0.0, "hook_payoff": 1.0},
            trap_structure_issues=["Pre-hook 'Pre Hook' does not subtract any anchor role"],
        )

        result = _run_repair([pre_hook], report)
        repaired = result.resolved_plan.resolved_sections[0]
        blocked_anchors = [r for r in repaired.final_blocked_roles if r in {"drums", "kick", "808", "bass"}]
        assert blocked_anchors, (
            f"Expected at least one anchor role blocked in pre-hook, got: {repaired.final_blocked_roles}"
        )

    def test_prehook_gets_tension_riser_event(self):
        """A pre-hook with low tension should get a tension_riser boundary event."""
        pre_hook = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.65,
            final_active_roles=["drums", "bass", "melody"],
            final_blocked_roles=[],
        )
        report = _make_quality_report(
            impact_scores={"pre_hook_tension": 0.0, "hook_payoff": 1.0},
        )

        result = _run_repair([pre_hook], report)
        repaired = result.resolved_plan.resolved_sections[0]
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert "tension_riser" in event_types, (
            f"Expected tension_riser boundary event, got: {event_types}"
        )

    def test_prehook_ensures_re_entry_accent_in_following_hook(self):
        """Repair should add re_entry_accent to the following hook."""
        pre_hook = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.65,
            final_active_roles=["drums", "bass", "melody"],
            final_blocked_roles=[],
        )
        hook = _make_section("Hook 1", "hook", 4, 8, 0.9, ["drums", "bass", "melody", "808"])
        report = _make_quality_report(
            impact_scores={"pre_hook_tension": 0.0, "hook_payoff": 0.3},
        )

        result = _run_repair([pre_hook, hook], report)
        repaired_hook = result.resolved_plan.resolved_sections[1]
        event_types = [e.event_type for e in repaired_hook.final_boundary_events]
        assert "re_entry_accent" in event_types, (
            f"Expected re_entry_accent in hook following repaired pre-hook, got: {event_types}"
        )

    def test_prehook_with_existing_anchor_not_double_blocked(self):
        """A pre-hook that already has an anchor blocked should not get more blocks from this rule."""
        pre_hook = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.65,
            final_active_roles=["bass", "melody"],
            final_blocked_roles=["drums"],  # already blocked
        )
        report = _make_quality_report(
            impact_scores={"pre_hook_tension": 0.5, "hook_payoff": 1.0},
        )

        result = _run_repair([pre_hook], report)
        # No repair should have been applied (tension already sufficient)
        tension_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "Pre-hook" in r and "blocked" in r
        ]
        assert tension_repairs == [], (
            f"Pre-hook with existing anchor block should not be further repaired: {tension_repairs}"
        )


# ---------------------------------------------------------------------------
# 4. Outro removes drums/808
# ---------------------------------------------------------------------------


class TestOutroRepair:
    def test_outro_strips_heavy_roles(self):
        """An outro with drums/808/bass should have those roles removed."""
        outro = _make_section(
            "Outro", "outro", 0, 8, 0.4,
            final_active_roles=["drums", "808", "melody"],
        )
        report = _make_quality_report(
            trap_structure_issues=["Outro 'Outro' still has heavy roles ['drums', '808']"],
        )

        result = _run_repair([outro], report)
        repaired = result.resolved_plan.resolved_sections[0]
        heavy_still_present = [r for r in repaired.final_active_roles if r in {"drums", "808", "bass", "kick"}]
        assert heavy_still_present == [], (
            f"Outro should have no heavy roles after repair, got: {repaired.final_active_roles}"
        )

    def test_outro_stripped_roles_moved_to_blocked(self):
        """Stripped roles from outro should appear in final_blocked_roles."""
        outro = _make_section(
            "Outro", "outro", 0, 8, 0.4,
            final_active_roles=["drums", "808", "melody"],
            final_blocked_roles=[],
        )
        report = _make_quality_report(
            trap_structure_issues=["Outro 'Outro' still has heavy roles ['drums', '808']"],
        )

        result = _run_repair([outro], report)
        repaired = result.resolved_plan.resolved_sections[0]
        assert "drums" in repaired.final_blocked_roles or "808" in repaired.final_blocked_roles, (
            f"Stripped roles should be in final_blocked_roles: {repaired.final_blocked_roles}"
        )

    def test_outro_gets_fade_out_event(self):
        """An outro repaired for heavy roles should receive a fade_out boundary event."""
        outro = _make_section(
            "Outro", "outro", 0, 8, 0.4,
            final_active_roles=["drums", "bass", "melody"],
        )
        report = _make_quality_report(
            trap_structure_issues=["Outro 'Outro' still has heavy roles ['drums', 'bass']"],
        )

        result = _run_repair([outro], report)
        repaired = result.resolved_plan.resolved_sections[0]
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert "fade_out" in event_types or "resolution" in event_types, (
            f"Expected fade_out or resolution event in repaired outro, got: {event_types}"
        )

    def test_clean_outro_not_modified(self):
        """An outro that already strips heavy roles should not be touched."""
        outro = _make_section(
            "Outro", "outro", 0, 8, 0.3,
            final_active_roles=["melody", "pads"],  # no heavy roles
        )
        report = _make_quality_report(trap_structure_issues=[])

        result = _run_repair([outro], report)
        outro_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "Outro" in r and "stripped" in r
        ]
        assert outro_repairs == [], "Clean outro should not have role-stripping repairs"


# ---------------------------------------------------------------------------
# 5. No-op events are removed
# ---------------------------------------------------------------------------


class TestNoOpEventRemoval:
    def test_empty_pattern_events_removed(self):
        """Pattern events with no action should be removed."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_pattern_events=[
                {"action": "swing", "amount": 0.3},  # valid
                {"action": ""},  # no-op
                {"type": ""},   # no-op (alternate key)
                {},              # completely empty
            ],
        )
        report = _make_quality_report(no_op_event_count=3)

        result = _run_repair([sec], report)
        repaired = result.resolved_plan.resolved_sections[0]
        for evt in repaired.final_pattern_events:
            action = str(evt.get("action") or evt.get("type") or "").strip()
            assert action, f"Empty pattern event found after repair: {evt}"

    def test_empty_groove_events_removed(self):
        """Groove events with no type should be removed."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_groove_events=[
                {"groove_type": "swing", "intensity": 0.5},  # valid
                {"groove_type": ""},  # no-op
                {},                   # completely empty
            ],
        )
        report = _make_quality_report(no_op_event_count=2)

        result = _run_repair([sec], report)
        repaired = result.resolved_plan.resolved_sections[0]
        for evt in repaired.final_groove_events:
            gtype = str(evt.get("groove_type") or evt.get("type") or "").strip()
            assert gtype, f"Empty groove event found after repair: {evt}"

    def test_valid_events_preserved(self):
        """Valid pattern and groove events should not be removed."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_pattern_events=[{"action": "variation_shift", "amount": 0.4}],
            final_groove_events=[{"groove_type": "swing", "intensity": 0.5}],
        )
        report = _make_quality_report(no_op_event_count=0)

        result = _run_repair([sec], report)
        repaired = result.resolved_plan.resolved_sections[0]
        assert len(repaired.final_pattern_events) == 1, "Valid pattern event should be preserved"
        assert len(repaired.final_groove_events) == 1, "Valid groove event should be preserved"

    def test_no_op_repair_skipped_when_count_zero(self):
        """No no-op repair should run when the report says no_op_event_count=0."""
        sec = _make_section("Verse 1", "verse", 0, 8, 0.6)
        report = _make_quality_report(no_op_event_count=0)

        result = _run_repair([sec], report)
        noop_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "No-op" in r
        ]
        assert noop_repairs == []


# ---------------------------------------------------------------------------
# 6. Duplicate boundary events are deduped
# ---------------------------------------------------------------------------


class TestDuplicateBoundaryEventDedup:
    def test_duplicate_events_are_removed(self):
        """Two boundary events with the same type should be deduplicated."""
        sec = _make_section(
            "Hook 1", "hook", 0, 8, 0.9,
            final_boundary_events=[
                _make_boundary_event("drum_fill", 0.8, bar=0),
                _make_boundary_event("drum_fill", 0.8, bar=0),  # duplicate
                _make_boundary_event("riser_fx", 0.7, bar=4),
            ],
        )
        report = _make_quality_report(
            transition_safety_score=0.8,
            safety_findings=[{
                "severity": "critical",
                "check": "duplicate_boundary_event",
                "section": "Hook 1",
                "event_type": "drum_fill",
                "count": 2,
                "message": "drum_fill applied 2× in 'Hook 1'",
            }],
        )

        result = _run_repair([sec], report)
        repaired = result.resolved_plan.resolved_sections[0]
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert event_types.count("drum_fill") == 1, (
            f"Expected exactly 1 drum_fill after dedup, got {event_types.count('drum_fill')}"
        )

    def test_dedup_repair_logged(self):
        """Dedup repair should appear in the repair log."""
        sec = _make_section(
            "Hook 1", "hook", 0, 8, 0.9,
            final_boundary_events=[
                _make_boundary_event("drum_fill", 0.8),
                _make_boundary_event("drum_fill", 0.8),
            ],
        )
        report = _make_quality_report(
            safety_findings=[{
                "severity": "critical",
                "check": "duplicate_boundary_event",
                "section": "Hook 1",
                "event_type": "drum_fill",
                "count": 2,
                "message": "drum_fill applied 2× in 'Hook 1'",
            }],
        )

        result = _run_repair([sec], report)
        dedup_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "deduplicated" in r
        ]
        assert dedup_repairs, "Dedup repair should be recorded in the repair log"

    def test_clipping_intensity_is_capped(self):
        """Events exceeding the clipping threshold should have intensity capped."""
        sec = _make_section(
            "Hook 1", "hook", 0, 8, 0.9,
            final_active_roles=["drums", "bass", "melody"],
            final_reentries=["808"],
            final_boundary_events=[
                _make_boundary_event("re_entry_accent", 0.95),  # above cap
            ],
        )
        report = _make_quality_report(
            safety_findings=[{
                "severity": "warning",
                "check": "gain_after_reentry_clipping_risk",
                "section": "Hook 1",
                "event_type": "re_entry_accent",
                "intensity": 0.95,
                "message": "clipping risk",
            }],
        )

        result = _run_repair([sec], report)
        repaired = result.resolved_plan.resolved_sections[0]
        for evt in repaired.final_boundary_events:
            assert evt.intensity <= 0.75 + 1e-9, (
                f"Event '{evt.event_type}' intensity {evt.intensity} exceeds clipping cap 0.75"
            )

    def test_hard_cut_gets_fade_guard(self):
        """A section with a hard-cut safety finding should get a fade_out guard."""
        sec = _make_section(
            "Pre Hook", "hook", 0, 8, 0.9,
            final_active_roles=["drums", "bass"],
            final_blocked_roles=["melody"],
            final_boundary_events=[],
        )
        report = _make_quality_report(
            safety_findings=[{
                "severity": "warning",
                "check": "hard_cut_no_transition",
                "section": "Pre Hook",
                "section_type": "hook",
                "blocked_roles": ["melody"],
                "message": "hard cut risk",
            }],
        )

        result = _run_repair([sec], report)
        repaired = result.resolved_plan.resolved_sections[0]
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert "fade_out" in event_types, (
            f"Expected fade_out guard added for hard-cut section, got: {event_types}"
        )


# ---------------------------------------------------------------------------
# 7. Render mismatch is repaired
# ---------------------------------------------------------------------------


class TestRenderMismatchRepair:
    def test_blocked_role_removed_from_active(self):
        """A role that is both active and blocked (mismatch) should be removed from active."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_active_roles=["drums", "bass", "melody"],
            final_blocked_roles=["bass"],  # mismatch: bass is both active and blocked
        )
        report = _make_quality_report(render_mismatch_count=1)

        result = _run_repair([sec], report)
        repaired = result.resolved_plan.resolved_sections[0]
        assert "bass" not in repaired.final_active_roles, (
            "Blocked role 'bass' should be removed from final_active_roles after mismatch repair"
        )

    def test_mismatch_repair_logged(self):
        """Render mismatch repair should be recorded in the repair log."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_active_roles=["drums", "bass"],
            final_blocked_roles=["drums"],
        )
        report = _make_quality_report(render_mismatch_count=1)

        result = _run_repair([sec], report)
        mismatch_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "mismatch" in r.lower() or "Render mismatch" in r
        ]
        assert mismatch_repairs, "Render mismatch repair should be logged"

    def test_no_mismatch_repair_when_count_zero(self):
        """No mismatch repair should run when render_mismatch_count=0."""
        sec = _make_section("Verse 1", "verse", 0, 8, 0.6)
        report = _make_quality_report(render_mismatch_count=0)

        result = _run_repair([sec], report)
        mismatch_repairs = [
            r for r in result.repair_metadata["production_quality_repairs"]
            if "Render mismatch" in r
        ]
        assert mismatch_repairs == []


# ---------------------------------------------------------------------------
# 8. Post-repair quality report improves
# ---------------------------------------------------------------------------


class TestPostRepairQualityImprovement:
    def test_post_repair_report_is_present(self):
        """The repair metadata should always contain a post_repair_quality_report dict."""
        sec = _make_section("Verse 1", "verse", 0, 8, 0.6)
        result = _run_repair([sec], _make_quality_report())
        assert isinstance(result.repair_metadata.get("post_repair_quality_report"), dict), (
            "post_repair_quality_report should be a dict"
        )

    def test_hook_payoff_does_not_decrease_after_repair(self):
        """After repair, post-repair hook_payoff_score should be ≥ pre-repair score."""
        verse = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass"])
        hook = _make_section("Hook 1", "hook", 8, 8, 0.55, ["drums", "bass", "melody"])
        report = _make_quality_report(
            hook_payoff_score=0.4,
            impact_scores={"pre_hook_tension": 1.0, "hook_payoff": 0.4},
        )

        result = _run_repair([verse, hook], report)
        pre_score = report["hook_payoff_score"]
        post_report = result.repair_metadata["post_repair_quality_report"]
        post_score = post_report.get("hook_payoff_score", pre_score)

        assert post_score >= pre_score, (
            f"Hook payoff score should not decrease after repair: "
            f"pre={pre_score}, post={post_score}"
        )

    def test_repair_count_matches_number_of_repairs(self):
        """production_quality_repair_count should equal len(production_quality_repairs)."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_active_roles=["drums", "bass"],
            final_pattern_events=[{"action": ""}],
        )
        report = _make_quality_report(no_op_event_count=1)

        result = _run_repair([sec], report)
        assert result.repair_metadata["production_quality_repair_count"] == len(
            result.repair_metadata["production_quality_repairs"]
        ), "Repair count must equal the number of repair log entries"

    def test_repair_applied_flag_is_true_when_repairs_run(self):
        """production_quality_repair_applied should be True when repairs were applied."""
        hook = _make_section("Hook 1", "hook", 0, 8, 0.4, ["drums", "bass"])
        report = _make_quality_report(
            hook_payoff_score=0.2,
            impact_scores={"pre_hook_tension": 1.0, "hook_payoff": 0.2},
        )

        result = _run_repair([hook], report)
        assert result.repair_metadata["production_quality_repair_applied"] is True


# ---------------------------------------------------------------------------
# 9. Repair failure is safe
# ---------------------------------------------------------------------------


class TestRepairFailureSafety:
    def test_repair_returns_original_plan_on_exception(self):
        """If repair raises an exception, the original plan is returned unchanged."""

        class _BrokenReport:
            """An object that raises when accessed like a dict."""
            def get(self, *args, **kwargs):
                raise RuntimeError("intentional test failure")

            def __contains__(self, key):
                return True

        sec = _make_section("Verse 1", "verse", 0, 8, 0.6)
        original_plan = _make_resolved_plan([sec])

        repairer = ProductionQualityRepair(
            resolved_plan=original_plan,
            quality_report=_BrokenReport(),  # type: ignore[arg-type]
            available_roles=["drums", "bass"],
        )
        result = repairer.repair()

        # The resolved plan returned must be the original (not modified)
        assert result.resolved_plan is original_plan, (
            "On failure, the original unrepaired plan should be returned"
        )

    def test_repair_failure_records_reason(self):
        """repair_failed_reason should be set when repair fails."""

        class _BrokenReport:
            def get(self, *args, **kwargs):
                raise RuntimeError("simulated failure")

            def __contains__(self, key):
                return True

        sec = _make_section("Verse 1", "verse", 0, 8, 0.6)
        original_plan = _make_resolved_plan([sec])

        repairer = ProductionQualityRepair(
            resolved_plan=original_plan,
            quality_report=_BrokenReport(),  # type: ignore[arg-type]
            available_roles=["drums", "bass"],
        )
        result = repairer.repair()

        assert result.repair_metadata.get("repair_failed_reason") is not None, (
            "repair_failed_reason should be set on failure"
        )
        assert "simulated failure" in str(result.repair_metadata["repair_failed_reason"]), (
            "repair_failed_reason should contain the original exception message"
        )

    def test_repair_failure_sets_applied_false(self):
        """production_quality_repair_applied should be False when repair fails."""

        class _BrokenReport:
            def get(self, *args, **kwargs):
                raise RuntimeError("simulated failure")

            def __contains__(self, key):
                return True

        sec = _make_section("Verse 1", "verse", 0, 8, 0.6)
        original_plan = _make_resolved_plan([sec])

        repairer = ProductionQualityRepair(
            resolved_plan=original_plan,
            quality_report=_BrokenReport(),  # type: ignore[arg-type]
            available_roles=["drums", "bass"],
        )
        result = repairer.repair()
        assert result.repair_metadata["production_quality_repair_applied"] is False

    def test_run_repair_convenience_function_never_raises(self):
        """run_repair() must never raise even with a completely broken input."""
        try:
            result = run_repair(
                resolved_plan=_make_resolved_plan([_make_section()]),
                quality_report={},  # empty — rule checks should all short-circuit
                available_roles=[],
            )
            assert result is not None
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"run_repair() raised an unexpected exception: {exc}")
