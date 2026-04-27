"""
Tests for ProductionQualityRepair
(app/services/production_quality_repair.py).

Covers (from the problem statement):
1.  Repeated sections are differentiated (≥ 2 audible dimensions changed)
2.  Weak hook gets stronger (energy, fullness, re_entry_accent, anchor roles)
3.  Pre-hook gets tension (anchor blocked, boundary event added)
4.  Outro removes drums/808 and adds outro_strip event
5.  No-op events are removed (empty action/type pattern & groove events)
6.  Duplicate boundary events are deduplicated (first occurrence kept)
7.  Render mismatch is repaired (active ∩ blocked → removed from active)
8.  Post-repair quality report is populated and shows improvement
9.  Repair failure is handled safely (original plan returned, failure recorded)
10. Clipping-risk intensity is lowered for high-gain reentry events
11. Fade guard is added when a silence event has no strip companion
12. Pre-hook re-entry is propagated to the next hook section
13. Feature flag default is False
"""

from __future__ import annotations

import dataclasses

import pytest

from app.services.production_quality_repair import (
    ProductionQualityRepair,
    _make_boundary_event,
)
from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _be(
    event_type: str = "drum_fill",
    intensity: float = 0.80,
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
    motif: dict | None = None,
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
        final_motif_treatment=motif,
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
        available_roles=available_roles or ["drums", "bass", "melody", "pads", "808"],
        genre="trap",
        noop_annotations=[],
    )


def _run(
    sections: list[ResolvedSection],
    report: dict | None = None,
    available_roles: list[str] | None = None,
) -> tuple[ResolvedRenderPlan, dict]:
    """Build a plan, run the repair, return (repaired_plan, metadata)."""
    p = _plan(sections, available_roles)
    r = report or {
        "repetition_groups": [],
        "impact_scores": {},
        "safety_findings": [],
        "no_op_event_count": 0,
        "render_mismatch_count": 0,
        "weak_sections": [],
        "recommended_fixes": [],
        "trap_structure_issues": [],
        "section_audits": [],
        "repetition_score": 1.0,
        "contrast_score": 1.0,
        "hook_payoff_score": 1.0,
        "transition_safety_score": 1.0,
    }
    repair = ProductionQualityRepair(
        resolved_plan=p,
        production_quality_report=r,
        available_roles=available_roles or list(p.available_roles),
        genre="trap",
        arrangement_id=999,
    )
    return repair.repair()


def _section_by_name(plan: ResolvedRenderPlan, name: str) -> ResolvedSection:
    for sec in plan.resolved_sections:
        if sec.section_name == name:
            return sec
    raise KeyError(name)


# ---------------------------------------------------------------------------
# 1. Repeated sections are differentiated
# ---------------------------------------------------------------------------


class TestRepeatedSectionDifferentiation:
    def test_two_identical_sections_get_differentiated(self):
        """Both verse sections share a fingerprint → second one is differentiated."""
        sec1 = _sec("Verse 1", "verse", 0, 8, 0.60, ["drums", "bass"])
        sec2 = _sec("Verse 2", "verse", 8, 8, 0.60, ["drums", "bass"])
        report = {
            "repetition_groups": [{"sections": ["Verse 1", "Verse 2"]}],
        }
        plan, meta = _run([sec1, sec2], report)

        orig_v2 = sec2
        repaired_v2 = _section_by_name(plan, "Verse 2")

        # Energy must have changed
        assert repaired_v2.energy != orig_v2.energy, "Energy was not nudged"
        # target_fullness must differ (or at least changed)
        assert repaired_v2.target_fullness != orig_v2.target_fullness, \
            "target_fullness was not rotated"
        # A pattern event must have been injected
        assert any("variation_pass" in str(e.get("action", "")) for e in repaired_v2.final_pattern_events), \
            "No variation_pass pattern event injected"
        # A groove event must have been injected
        assert any("groove_shift" in str(e.get("groove_type", "")) for e in repaired_v2.final_groove_events), \
            "No groove_shift groove event injected"

        assert meta["production_quality_repair_applied"] is True
        assert any(r["rule"] == "repeated_section_differentiated" for r in meta["production_quality_repairs"])

    def test_first_section_in_group_is_unchanged(self):
        """First section in a repetition group must not be modified."""
        sec1 = _sec("Verse 1", "verse", 0, 8, 0.60, ["drums", "bass"])
        sec2 = _sec("Verse 2", "verse", 8, 8, 0.60, ["drums", "bass"])
        report = {"repetition_groups": [{"sections": ["Verse 1", "Verse 2"]}]}
        plan, _ = _run([sec1, sec2], report)

        repaired_v1 = _section_by_name(plan, "Verse 1")
        assert repaired_v1.energy == sec1.energy
        assert repaired_v1.final_pattern_events == sec1.final_pattern_events

    def test_multiple_groups_all_differentiated(self):
        """Multiple independent repetition groups are each handled."""
        sec1 = _sec("V1", "verse", 0, 8, 0.60, ["drums", "bass"])
        sec2 = _sec("V2", "verse", 8, 8, 0.60, ["drums", "bass"])
        h1 = _sec("Hook 1", "hook", 16, 8, 0.90, ["drums", "bass", "melody"])
        h2 = _sec("Hook 2", "hook", 24, 8, 0.90, ["drums", "bass", "melody"])
        report = {
            "repetition_groups": [
                {"sections": ["V1", "V2"]},
                {"sections": ["Hook 1", "Hook 2"]},
            ]
        }
        plan, meta = _run([sec1, sec2, h1, h2], report)

        assert _section_by_name(plan, "V2").energy != sec2.energy
        assert _section_by_name(plan, "Hook 2").energy != h2.energy

    def test_no_repair_when_no_repetition_groups(self):
        """No differentiation repairs when repetition_groups is empty."""
        sec1 = _sec("Verse 1", "verse", 0, 8, 0.60, ["drums", "bass"])
        plan, meta = _run([sec1], {"repetition_groups": []})
        assert not any(r["rule"] == "repeated_section_differentiated"
                       for r in meta["production_quality_repairs"])


# ---------------------------------------------------------------------------
# 2. Weak hook gets stronger
# ---------------------------------------------------------------------------


class TestWeakHookRepair:
    def test_low_energy_hook_is_boosted(self):
        hook = _sec("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass", "melody"])
        plan, meta = _run([hook])
        repaired = _section_by_name(plan, "Hook 1")
        assert repaired.energy >= 0.82, f"Expected energy ≥ 0.82, got {repaired.energy}"

    def test_hook_target_fullness_set_to_full(self):
        hook = _sec("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass"], target_fullness="medium")
        plan, _ = _run([hook])
        assert _section_by_name(plan, "Hook 1").target_fullness == "full"

    def test_hook_gets_re_entry_accent_when_missing(self):
        hook = _sec("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass"])
        plan, meta = _run([hook])
        repaired = _section_by_name(plan, "Hook 1")
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert "re_entry_accent" in event_types, f"re_entry_accent not in {event_types}"

    def test_hook_does_not_duplicate_re_entry_accent(self):
        hook = _sec("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass"],
                    boundary_events=[_be("re_entry_accent", 0.75)])
        plan, _ = _run([hook])
        repaired = _section_by_name(plan, "Hook 1")
        accent_count = sum(1 for e in repaired.final_boundary_events
                           if e.event_type == "re_entry_accent")
        assert accent_count == 1, f"Expected 1 re_entry_accent, got {accent_count}"

    def test_hook_gains_anchor_roles_from_available(self):
        """Hook missing 808 should gain it from available_roles."""
        hook = _sec("Hook 1", "hook", 0, 8, 0.50, ["melody", "pads"])
        plan, _ = _run([hook], available_roles=["drums", "bass", "melody", "pads", "808"])
        repaired = _section_by_name(plan, "Hook 1")
        # At least one anchor role should have been added
        anchor_added = any(r in {"drums", "bass", "808"} for r in repaired.final_active_roles)
        assert anchor_added, f"No anchor role added to hook. Active: {repaired.final_active_roles}"

    def test_strong_hook_is_not_modified(self):
        """Hook that already meets all criteria should not be repaired."""
        hook = _sec("Hook 1", "hook", 0, 8, 0.90, ["drums", "bass", "melody", "808"],
                    boundary_events=[_be("re_entry_accent", 0.75)],
                    target_fullness="full")
        plan, meta = _run([hook])
        assert not any(r["rule"] == "weak_hook_repaired" for r in meta["production_quality_repairs"])

    def test_hook_has_more_roles_than_verse(self):
        """After repair, hook should have more active roles than verse."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60, ["drums", "bass"])
        hook = _sec("Hook 1", "hook", 8, 8, 0.50, ["melody"])
        plan, _ = _run([verse, hook], available_roles=["drums", "bass", "melody", "808", "pads"])
        repaired_hook = _section_by_name(plan, "Hook 1")
        assert len(repaired_hook.final_active_roles) > len(verse.final_active_roles), (
            f"Hook ({repaired_hook.final_active_roles}) should have more roles than verse "
            f"({verse.final_active_roles})"
        )


# ---------------------------------------------------------------------------
# 3. Pre-hook gets tension
# ---------------------------------------------------------------------------


class TestPreHookTensionRepair:
    def test_pre_hook_blocks_anchor_role(self):
        pre_hook = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["drums", "bass", "melody"])
        plan, meta = _run([pre_hook])
        repaired = _section_by_name(plan, "Pre Hook")
        anchor_blocked = any(r in {"drums", "kick", "808", "bass"}
                             for r in repaired.final_blocked_roles)
        assert anchor_blocked, f"No anchor role blocked. Blocked: {repaired.final_blocked_roles}"
        assert any(r["rule"] == "pre_hook_tension_added" for r in meta["production_quality_repairs"])

    def test_pre_hook_blocked_role_removed_from_active(self):
        pre_hook = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["drums", "bass", "melody"])
        plan, _ = _run([pre_hook])
        repaired = _section_by_name(plan, "Pre Hook")
        for blocked in repaired.final_blocked_roles:
            assert blocked not in repaired.final_active_roles, (
                f"Blocked role '{blocked}' still in final_active_roles"
            )

    def test_pre_hook_gets_tension_boundary_event(self):
        pre_hook = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["drums", "bass"])
        plan, _ = _run([pre_hook])
        repaired = _section_by_name(plan, "Pre Hook")
        tension_types = {"pre_hook_silence_drop", "pre_hook_drum_mute"}
        event_types = {e.event_type for e in repaired.final_boundary_events}
        assert tension_types & event_types, (
            f"No tension boundary event added. Events: {event_types}"
        )

    def test_pre_hook_already_blocking_anchor_not_modified(self):
        pre_hook = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["bass", "melody"],
                        blocked=["drums"])
        plan, meta = _run([pre_hook])
        assert not any(r["rule"] == "pre_hook_tension_added" for r in meta["production_quality_repairs"])

    def test_pre_hook_blocked_role_added_to_hook_reentries(self):
        """Role blocked in pre-hook should appear in the next hook's final_reentries."""
        pre_hook = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["drums", "bass"])
        hook = _sec("Hook 1", "hook", 4, 8, 0.90, ["drums", "bass", "melody"])
        plan, meta = _run([pre_hook, hook])
        repaired_pre = _section_by_name(plan, "Pre Hook")
        repaired_hook = _section_by_name(plan, "Hook 1")
        # Whichever anchor was blocked must appear in hook's reentries
        for blocked in repaired_pre.final_blocked_roles:
            if blocked in {"drums", "kick", "808", "bass"}:
                assert blocked in repaired_hook.final_reentries, (
                    f"Blocked anchor '{blocked}' not in hook reentries: "
                    f"{repaired_hook.final_reentries}"
                )
                break

    def test_pre_hook_no_anchor_active_skipped(self):
        """Pre-hook with no active anchor roles should not get a tension repair."""
        pre_hook = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["melody", "pads"])
        plan, meta = _run([pre_hook])
        assert not any(r["rule"] == "pre_hook_tension_added" for r in meta["production_quality_repairs"])


# ---------------------------------------------------------------------------
# 4. Outro removes drums/808
# ---------------------------------------------------------------------------


class TestOutroRepair:
    def test_outro_heavy_roles_removed(self):
        outro = _sec("Outro", "outro", 0, 8, 0.30, ["drums", "bass", "808", "melody"])
        plan, meta = _run([outro])
        repaired = _section_by_name(plan, "Outro")
        heavy = {"808", "bass", "drums", "kick"}
        still_active = [r for r in repaired.final_active_roles if r in heavy]
        assert not still_active, f"Heavy roles still active in outro: {still_active}"
        assert any(r["rule"] == "outro_heavy_roles_removed" for r in meta["production_quality_repairs"])

    def test_outro_heavy_roles_moved_to_blocked(self):
        outro = _sec("Outro", "outro", 0, 8, 0.30, ["drums", "bass", "melody"])
        plan, _ = _run([outro])
        repaired = _section_by_name(plan, "Outro")
        assert "drums" in repaired.final_blocked_roles
        assert "bass" in repaired.final_blocked_roles

    def test_outro_gets_outro_strip_event(self):
        outro = _sec("Outro", "outro", 0, 8, 0.30, ["drums", "bass", "melody"])
        plan, _ = _run([outro])
        repaired = _section_by_name(plan, "Outro")
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert "outro_strip" in event_types, f"outro_strip not added. Events: {event_types}"

    def test_outro_with_no_heavy_roles_not_modified(self):
        outro = _sec("Outro", "outro", 0, 8, 0.30, ["melody", "pads"])
        plan, meta = _run([outro])
        assert not any(r["rule"] == "outro_heavy_roles_removed" for r in meta["production_quality_repairs"])

    def test_outro_does_not_duplicate_outro_strip(self):
        outro = _sec("Outro", "outro", 0, 8, 0.30, ["drums", "melody"],
                     boundary_events=[_be("outro_strip", 0.6)])
        plan, _ = _run([outro])
        repaired = _section_by_name(plan, "Outro")
        strip_count = sum(1 for e in repaired.final_boundary_events
                          if e.event_type == "outro_strip")
        assert strip_count == 1, f"Expected 1 outro_strip, got {strip_count}"


# ---------------------------------------------------------------------------
# 5. No-op events are removed
# ---------------------------------------------------------------------------


class TestNoOpEventRemoval:
    def test_empty_action_pattern_events_removed(self):
        sec = _sec("Verse 1", pattern_events=[
            {"action": "velocity_accent"},
            {"action": ""},           # no-op
            {"action": None},         # no-op
            {},                       # no-op (no action or type key)
        ])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert len(repaired.final_pattern_events) == 1, (
            f"Expected 1 pattern event, got {repaired.final_pattern_events}"
        )
        assert any(r["rule"] == "no_op_events_removed" for r in meta["production_quality_repairs"])

    def test_empty_type_groove_events_removed(self):
        sec = _sec("Verse 1", groove_events=[
            {"groove_type": "swing"},
            {"groove_type": ""},    # no-op
            {},                      # no-op
        ])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert len(repaired.final_groove_events) == 1

    def test_type_fallback_used_for_pattern_events(self):
        """Events with 'type' key (instead of 'action') should be kept if non-empty."""
        sec = _sec("Verse 1", pattern_events=[
            {"type": "rhythm_shift"},
            {"type": ""},
        ])
        plan, _ = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert len(repaired.final_pattern_events) == 1

    def test_no_repair_when_all_events_valid(self):
        sec = _sec("Verse 1",
                   pattern_events=[{"action": "velocity_accent"}],
                   groove_events=[{"groove_type": "swing"}])
        plan, meta = _run([sec])
        assert not any(r["rule"] == "no_op_events_removed" for r in meta["production_quality_repairs"])


# ---------------------------------------------------------------------------
# 6. Duplicate boundary events are deduplicated
# ---------------------------------------------------------------------------


class TestBoundaryEventDeduplication:
    def test_duplicate_event_types_deduplicated(self):
        sec = _sec("Hook 1", "hook", boundary_events=[
            _be("drum_fill", 0.8),
            _be("drum_fill", 0.8),   # duplicate
            _be("crash_hit", 0.9),
        ])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Hook 1")
        type_counts: dict[str, int] = {}
        for evt in repaired.final_boundary_events:
            type_counts[evt.event_type] = type_counts.get(evt.event_type, 0) + 1
        for etype, count in type_counts.items():
            assert count == 1, f"Event '{etype}' appears {count} times after repair"
        assert any(r["rule"] == "deduplicate_boundary_events" for r in meta["production_quality_repairs"])

    def test_first_occurrence_of_duplicate_is_kept(self):
        """When two identical events exist, the first one should survive."""
        sec = _sec("Hook 1", "hook", boundary_events=[
            _be("drum_fill", 0.80),
            _be("drum_fill", 0.90),  # second — should be dropped
        ])
        plan, _ = _run([sec])
        repaired = _section_by_name(plan, "Hook 1")
        surviving = [e for e in repaired.final_boundary_events if e.event_type == "drum_fill"]
        assert len(surviving) == 1
        assert surviving[0].intensity == pytest.approx(0.80)

    def test_unique_events_are_all_kept(self):
        # Use a verse section (not hook) to avoid the weak-hook repair injecting extra events
        sec = _sec("Verse 1", "verse", boundary_events=[
            _be("drum_fill", 0.8),
            _be("crash_hit", 0.9),
            _be("riser_fx", 0.7),
        ])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert len(repaired.final_boundary_events) == 3
        assert not any(r["rule"] == "deduplicate_boundary_events" for r in meta["production_quality_repairs"])


# ---------------------------------------------------------------------------
# 7. Render mismatch is repaired
# ---------------------------------------------------------------------------


class TestRenderMismatchRepair:
    def test_blocked_role_removed_from_active(self):
        sec = _sec("Verse 1", active=["drums", "bass", "melody"],
                   blocked=["melody"])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert "melody" not in repaired.final_active_roles, (
            "Blocked role 'melody' should have been removed from final_active_roles"
        )
        assert any(r["rule"] == "render_mismatch" for r in meta["production_quality_repairs"])

    def test_multiple_blocked_roles_all_removed(self):
        sec = _sec("Verse 1", active=["drums", "bass", "melody", "pads"],
                   blocked=["melody", "pads"])
        plan, _ = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert "melody" not in repaired.final_active_roles
        assert "pads" not in repaired.final_active_roles

    def test_non_overlapping_section_not_modified(self):
        sec = _sec("Verse 1", active=["drums", "bass"], blocked=["melody"])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert repaired.final_active_roles == ["drums", "bass"]
        assert not any(r["rule"] == "render_mismatch" for r in meta["production_quality_repairs"])

    def test_active_roles_preserve_order_after_mismatch_repair(self):
        """Roles that survive the mismatch repair should retain their original order."""
        sec = _sec("Verse 1", active=["drums", "melody", "bass", "pads"],
                   blocked=["melody"])
        plan, _ = _run([sec])
        repaired = _section_by_name(plan, "Verse 1")
        assert repaired.final_active_roles == ["drums", "bass", "pads"]


# ---------------------------------------------------------------------------
# 8. Post-repair quality report is populated and shows improvement
# ---------------------------------------------------------------------------


class TestPostRepairQualityReport:
    def test_post_repair_report_populated_when_auditor_provided(self):
        """Caller inserts post_repair_quality_report into metadata before returning."""
        # We simulate what arrangement_jobs does: run auditor, repair, re-audit.
        from app.services.production_quality_auditor import ProductionQualityAuditor

        sections = [
            _sec("Intro", "intro", 0, 4, 0.30, ["melody"]),
            _sec("Verse 1", "verse", 4, 8, 0.60, ["drums", "bass"]),
            _sec("Verse 2", "verse", 12, 8, 0.60, ["drums", "bass"]),  # repeat
            _sec("Hook 1", "hook", 20, 8, 0.50, ["drums", "bass", "melody"]),
            _sec("Outro", "outro", 28, 8, 0.30, ["drums", "808", "melody"]),
        ]
        plan = _plan(sections)

        # Initial audit
        auditor = ProductionQualityAuditor(plan, arrangement_id=1)
        initial_report = auditor.audit()

        # Repair
        repair = ProductionQualityRepair(
            resolved_plan=plan,
            production_quality_report=initial_report,
            available_roles=list(plan.available_roles),
            genre="trap",
            arrangement_id=1,
        )
        repaired_plan, meta = repair.repair()

        # Re-audit
        post_auditor = ProductionQualityAuditor(repaired_plan, arrangement_id=1)
        post_report = post_auditor.audit()
        meta["post_repair_quality_report"] = post_report

        assert "post_repair_quality_report" in meta
        assert isinstance(meta["post_repair_quality_report"], dict)
        assert "repetition_score" in meta["post_repair_quality_report"]

    def test_repair_reduces_outro_issues(self):
        """After repair, outro heavy-role issue should disappear from weak_sections."""
        from app.services.production_quality_auditor import ProductionQualityAuditor

        outro = _sec("Outro", "outro", 0, 8, 0.30, ["drums", "808", "melody"])
        plan = _plan([outro])

        initial_report = ProductionQualityAuditor(plan, arrangement_id=1).audit()
        assert "Outro" in initial_report["weak_sections"]

        repair = ProductionQualityRepair(
            resolved_plan=plan,
            production_quality_report=initial_report,
            available_roles=list(plan.available_roles),
        )
        repaired_plan, _ = repair.repair()

        post_report = ProductionQualityAuditor(repaired_plan, arrangement_id=1).audit()
        assert "Outro" not in post_report["weak_sections"], (
            f"Outro still in weak_sections after repair: {post_report['weak_sections']}"
        )


# ---------------------------------------------------------------------------
# 9. Repair failure is safe
# ---------------------------------------------------------------------------


class TestRepairFailureSafety:
    def test_corrupted_report_returns_original_plan(self):
        """If repair encounters an internal error, original plan is returned safely."""
        sec = _sec("Verse 1")
        plan = _plan([sec])

        class _BadRepair(ProductionQualityRepair):
            def _repair_render_mismatches(self, sections):
                raise RuntimeError("Simulated repair failure")

        repair = _BadRepair(
            resolved_plan=plan,
            production_quality_report={},
            arrangement_id=1,
        )
        returned_plan, meta = repair.repair()

        assert returned_plan is plan, "Original plan must be returned on failure"
        assert meta["production_quality_repair_applied"] is False
        assert meta["production_quality_repair_count"] == 0
        assert "repair_failed_reason" in meta
        assert "Simulated repair failure" in meta["repair_failed_reason"]

    def test_repair_failure_records_reason(self):
        plan = _plan([_sec("Verse 1")])

        class _ErrorRepair(ProductionQualityRepair):
            def _repair_no_op_events(self, sections):
                raise ValueError("Intentional error")

        r = _ErrorRepair(resolved_plan=plan, production_quality_report={})
        _, meta = r.repair()
        assert "Intentional error" in meta.get("repair_failed_reason", "")

    def test_successful_repair_has_no_failure_reason(self):
        plan = _plan([_sec("Verse 1")])
        _, meta = _run([_sec("Verse 1")], report={"repetition_groups": []})
        assert "repair_failed_reason" not in meta


# ---------------------------------------------------------------------------
# 10. Clipping-risk intensity is lowered
# ---------------------------------------------------------------------------


class TestClippingRiskRepair:
    def test_high_intensity_reentry_accent_lowered(self):
        sec = _sec("Hook 1", "hook", reentries=["bass"],
                   boundary_events=[_be("re_entry_accent", intensity=0.95)])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Hook 1")
        accent_events = [e for e in repaired.final_boundary_events
                         if e.event_type == "re_entry_accent"]
        assert accent_events, "re_entry_accent missing from repaired section"
        assert accent_events[0].intensity < 0.80, (
            f"Expected intensity < 0.80, got {accent_events[0].intensity}"
        )
        assert any(r["rule"] == "clipping_risk_intensity_lowered"
                   for r in meta["production_quality_repairs"])

    def test_low_intensity_reentry_not_modified(self):
        sec = _sec("Hook 1", "hook", reentries=["bass"],
                   boundary_events=[_be("re_entry_accent", intensity=0.70)])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Hook 1")
        accent_events = [e for e in repaired.final_boundary_events
                         if e.event_type == "re_entry_accent"]
        assert accent_events[0].intensity == pytest.approx(0.70)
        assert not any(r["rule"] == "clipping_risk_intensity_lowered"
                       for r in meta["production_quality_repairs"])

    def test_high_intensity_without_reentries_not_lowered(self):
        """High-gain event with no role reentries is NOT flagged as clipping risk."""
        sec = _sec("Hook 1", "hook", reentries=[],
                   boundary_events=[_be("re_entry_accent", intensity=0.95)])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Hook 1")
        accent_events = [e for e in repaired.final_boundary_events
                         if e.event_type == "re_entry_accent"]
        assert accent_events[0].intensity == pytest.approx(0.95)


# ---------------------------------------------------------------------------
# 11. Fade guard is added when a silence event has no strip companion
# ---------------------------------------------------------------------------


class TestFadeGuardAddition:
    def test_silence_gap_without_strip_gets_bridge_strip(self):
        sec = _sec("Pre Hook", "pre_hook",
                   boundary_events=[_be("silence_gap", 0.8)])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Pre Hook")
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert "bridge_strip" in event_types, (
            f"Expected bridge_strip guard, got {event_types}"
        )
        assert any(r["rule"] == "fade_guard_added" for r in meta["production_quality_repairs"])

    def test_silence_with_outro_strip_does_not_get_bridge_strip(self):
        sec = _sec("Outro", "outro",
                   boundary_events=[_be("silence_gap", 0.8), _be("outro_strip", 0.6)])
        plan, meta = _run([sec])
        repaired = _section_by_name(plan, "Outro")
        event_types = [e.event_type for e in repaired.final_boundary_events]
        assert "bridge_strip" not in event_types
        assert not any(r["rule"] == "fade_guard_added" for r in meta["production_quality_repairs"])

    def test_section_without_silence_event_not_modified(self):
        sec = _sec("Verse 1", boundary_events=[_be("drum_fill", 0.8)])
        plan, meta = _run([sec])
        assert not any(r["rule"] == "fade_guard_added" for r in meta["production_quality_repairs"])


# ---------------------------------------------------------------------------
# 12. Pre-hook re-entry propagates to the next hook section
# ---------------------------------------------------------------------------


class TestPreHookReentryPropagation:
    def test_blocked_anchor_appears_in_next_hook_reentries(self):
        pre = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["drums", "bass", "melody"])
        hook = _sec("Hook 1", "hook", 4, 8, 0.90, ["drums", "bass", "melody"])
        plan, _ = _run([pre, hook])
        repaired_pre = _section_by_name(plan, "Pre Hook")
        repaired_hook = _section_by_name(plan, "Hook 1")
        for blocked in repaired_pre.final_blocked_roles:
            if blocked in {"drums", "kick", "808", "bass"}:
                assert blocked in repaired_hook.final_reentries, (
                    f"'{blocked}' not in hook reentries: {repaired_hook.final_reentries}"
                )
                return
        # If no anchor was blocked, that's also fine (covered by test_pre_hook_no_anchor_active_skipped)

    def test_reentry_not_duplicated_when_already_present(self):
        pre = _sec("Pre Hook", "pre_hook", 0, 4, 0.65, ["drums", "bass"])
        hook = _sec("Hook 1", "hook", 4, 8, 0.90, ["drums", "bass", "melody"],
                    reentries=["drums"])
        plan, _ = _run([pre, hook])
        repaired_hook = _section_by_name(plan, "Hook 1")
        drums_reentry_count = repaired_hook.final_reentries.count("drums")
        assert drums_reentry_count == 1, (
            f"Expected 'drums' in reentries exactly once, got {drums_reentry_count}"
        )


# ---------------------------------------------------------------------------
# 13. Feature flag default is False
# ---------------------------------------------------------------------------


class TestFeatureFlag:
    def test_feature_flag_default_is_false(self):
        from app.config import settings
        assert settings.feature_production_quality_repair is False

    def test_feature_flag_env_alias(self):
        """The field must use PRODUCTION_QUALITY_REPAIR as its env alias."""
        from app.config import Settings
        field_info = Settings.model_fields["feature_production_quality_repair"]
        alias = field_info.validation_alias
        assert alias == "PRODUCTION_QUALITY_REPAIR", (
            f"Expected alias 'PRODUCTION_QUALITY_REPAIR', got '{alias}'"
        )


# ---------------------------------------------------------------------------
# Integration: metadata keys are always present
# ---------------------------------------------------------------------------


class TestMetadataKeys:
    def test_success_metadata_has_required_keys(self):
        _, meta = _run([_sec("Verse 1")])
        assert "production_quality_repair_applied" in meta
        assert "production_quality_repairs" in meta
        assert "production_quality_repair_count" in meta
        assert isinstance(meta["production_quality_repairs"], list)
        assert isinstance(meta["production_quality_repair_count"], int)

    def test_repair_count_matches_repairs_list_length(self):
        outro = _sec("Outro", "outro", 0, 8, 0.30, ["drums", "bass", "melody"])
        _, meta = _run([outro])
        assert meta["production_quality_repair_count"] == len(meta["production_quality_repairs"])

    def test_all_repair_records_have_required_fields(self):
        outro = _sec("Outro", "outro", 0, 8, 0.30, ["drums", "bass"])
        _, meta = _run([outro])
        for record in meta["production_quality_repairs"]:
            assert "rule" in record, f"'rule' missing from record: {record}"
            assert "section" in record, f"'section' missing from record: {record}"
            assert "detail" in record, f"'detail' missing from record: {record}"
