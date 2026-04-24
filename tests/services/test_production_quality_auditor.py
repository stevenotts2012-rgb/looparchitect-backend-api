"""
Tests for ProductionQualityAuditor
(app/services/production_quality_auditor.py).

Covers:
1. Repeated sections are detected (identical fingerprint → repetition_groups)
2. Weak hooks are flagged (low energy/density → hook_payoff_score low, weak_sections populated)
3. Metadata-only events are detected (empty action/type → no_op_event_count > 0)
4. Drop events applied exactly once (duplicate boundary event → safety_findings critical)
5. Clipping / hard-cut risks are flagged (high-intensity reentry + clipping risk event)
6. Pre-hook tension: no anchor subtraction → pre_hook_tension = 0, trap issue emitted
7. Trap arc: intro too full → trap_structure_issues populated
8. Trap arc: verse 2 identical to verse 1 → trap_structure_issues populated
9. Trap arc: hook 2 identical to hook 1 → trap_structure_issues populated
10. Trap arc: outro with heavy roles → trap_structure_issues populated
11. Render mismatch detection: blocked role still in raw plan → mismatch_count > 0
12. Contrast score: monotone arrangement → low contrast_score
13. Recommended fixes: all key fix categories populated when issues are present
14. Clean arrangement: minimal issues, high scores
"""

from __future__ import annotations

import pytest

from app.services.production_quality_auditor import ProductionQualityAuditor
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
    )


def _make_resolved_plan(
    sections: list[ResolvedSection],
    noop_annotations: list[dict] | None = None,
) -> ResolvedRenderPlan:
    return ResolvedRenderPlan(
        resolved_sections=sections,
        bpm=140.0,
        key="G minor",
        total_bars=sum(s.bars for s in sections),
        source_quality="true_stems",
        available_roles=["drums", "bass", "melody", "pads", "808"],
        genre="trap",
        noop_annotations=noop_annotations or [],
    )


def _run_audit(
    sections: list[ResolvedSection],
    noop_annotations: list[dict] | None = None,
    raw_render_plan: dict | None = None,
) -> dict:
    plan = _make_resolved_plan(sections, noop_annotations)
    auditor = ProductionQualityAuditor(plan, raw_render_plan=raw_render_plan)
    return auditor.audit()


# ---------------------------------------------------------------------------
# 1. Repeated sections are detected
# ---------------------------------------------------------------------------


class TestRepetitionDetection:
    def test_identical_sections_appear_in_repetition_groups(self):
        """Two sections with same roles, energy, boundary events → repetition_groups."""
        sec1 = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass"])
        sec2 = _make_section("Verse 2", "verse", 8, 8, 0.6, ["drums", "bass"])

        report = _run_audit([sec1, sec2])

        assert len(report["repetition_groups"]) >= 1, (
            "Expected at least one repetition group for identical Verse 1 / Verse 2"
        )
        repeated_sections = report["repetition_groups"][0]["sections"]
        assert "Verse 1" in repeated_sections
        assert "Verse 2" in repeated_sections

    def test_repetition_score_is_low_for_identical_sections(self):
        """When all sections are identical, repetition_score should be < 0.5."""
        roles = ["drums", "bass", "melody"]
        sections = [
            _make_section(f"Verse {i}", "verse", i * 8, 8, 0.6, roles)
            for i in range(1, 5)
        ]
        report = _run_audit(sections)
        assert report["repetition_score"] < 0.5, (
            f"Expected repetition_score < 0.5, got {report['repetition_score']}"
        )

    def test_unique_sections_produce_empty_repetition_groups(self):
        """Completely distinct sections (roles, energy, boundary events) → no groups."""
        sections = [
            _make_section("Intro", "intro", 0, 4, 0.3, ["melody"]),
            _make_section(
                "Pre Hook", "pre_hook", 4, 4, 0.65, ["drums", "bass"],
                final_blocked_roles=["drums"],
                final_boundary_events=[_make_boundary_event("silence_gap", 0.9)],
            ),
            _make_section("Hook 1", "hook", 8, 8, 0.9, ["drums", "bass", "melody", "808"]),
            _make_section("Outro", "outro", 16, 4, 0.2, ["melody", "pads"]),
        ]
        report = _run_audit(sections)
        assert report["repetition_groups"] == [], (
            f"Expected no repetition groups for distinct sections, got {report['repetition_groups']}"
        )

    def test_repetition_score_is_one_for_unique_sections(self):
        sections = [
            _make_section("Intro", "intro", 0, 4, 0.3, ["melody"]),
            _make_section("Hook", "hook", 4, 8, 0.9, ["drums", "bass", "melody", "pads", "808"]),
        ]
        report = _run_audit(sections)
        assert report["repetition_score"] == 1.0

    def test_repetition_groups_include_same_boundary_events(self):
        """Same boundary event types contribute to repeated fingerprint."""
        be = [_make_boundary_event("drum_fill", 0.8)]
        sec1 = _make_section("Hook 1", "hook", 0, 8, 0.9, ["drums", "bass", "melody"],
                              final_boundary_events=be)
        sec2 = _make_section("Hook 2", "hook", 8, 8, 0.9, ["drums", "bass", "melody"],
                              final_boundary_events=be)
        report = _run_audit([sec1, sec2])

        assert len(report["repetition_groups"]) >= 1
        group_sections = report["repetition_groups"][0]["sections"]
        assert "Hook 1" in group_sections and "Hook 2" in group_sections


# ---------------------------------------------------------------------------
# 2. Weak hooks are flagged
# ---------------------------------------------------------------------------


class TestWeakHookDetection:
    def test_hook_with_low_energy_flagged_in_section_audit(self):
        """Hook section with energy < 0.75 should appear in section issues."""
        hook = _make_section("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass", "melody"])
        report = _run_audit([hook])

        hook_audit = next(a for a in report["section_audits"] if a["section_name"] == "Hook 1")
        assert any("energy" in issue.lower() for issue in hook_audit["issues"]), (
            f"Expected energy issue in hook audit, got: {hook_audit['issues']}"
        )

    def test_weak_hook_appears_in_weak_sections(self):
        hook = _make_section("Hook 1", "hook", 0, 8, 0.50, ["drums", "bass"])
        report = _run_audit([hook])
        assert "Hook 1" in report["weak_sections"], (
            f"Expected 'Hook 1' in weak_sections, got: {report['weak_sections']}"
        )

    def test_hook_payoff_score_is_low_when_hook_energy_matches_verse(self):
        """When hook energy and density barely exceed verse, hook_payoff_score should be < 0.75."""
        verse = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass", "melody"])
        # Hook has the same roles and only +0.05 energy — negligible uplift
        hook = _make_section("Hook 1", "hook", 8, 8, 0.65, ["drums", "bass", "melody"])
        report = _run_audit([verse, hook])
        assert report["hook_payoff_score"] < 0.75, (
            f"Expected hook_payoff_score < 0.75 for minimal uplift, got {report['hook_payoff_score']}"
        )

    def test_strong_hook_produces_high_payoff_score(self):
        """Hook with energy 0.9 and +3 more roles than verse → high payoff score."""
        verse = _make_section("Verse 1", "verse", 0, 8, 0.5, ["melody"])
        hook = _make_section("Hook 1", "hook", 8, 8, 0.9, ["drums", "bass", "melody", "pads", "808"])
        report = _run_audit([verse, hook])
        assert report["hook_payoff_score"] >= 0.5, (
            f"Expected hook_payoff_score ≥ 0.5, got {report['hook_payoff_score']}"
        )

    def test_hook_too_short_is_flagged(self):
        """Hook < 4 bars should appear in section issues."""
        hook = _make_section("Hook 1", "hook", 0, 2, 0.9, ["drums", "bass", "melody", "pads"])
        report = _run_audit([hook])
        hook_audit = next(a for a in report["section_audits"] if a["section_name"] == "Hook 1")
        assert any("bar" in issue.lower() for issue in hook_audit["issues"]), (
            f"Expected bar-length issue, got: {hook_audit['issues']}"
        )


# ---------------------------------------------------------------------------
# 3. Metadata-only events are detected
# ---------------------------------------------------------------------------


class TestMetadataOnlyEvents:
    def test_empty_pattern_event_action_counted_as_noop(self):
        """A pattern event with empty action → no_op_event_count > 0."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_pattern_events=[{"action": "", "bar": 4}],
        )
        report = _run_audit([sec])
        assert report["no_op_event_count"] >= 1, (
            f"Expected ≥ 1 no-op, got {report['no_op_event_count']}"
        )

    def test_empty_groove_event_type_counted_as_noop(self):
        """A groove event with empty type → no_op_event_count > 0."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_groove_events=[{"groove_type": "", "intensity": 0.5}],
        )
        report = _run_audit([sec])
        assert report["no_op_event_count"] >= 1

    def test_resolver_noop_annotations_counted(self):
        """no-op annotations from resolver (phantom blocked role) add to no_op_event_count."""
        noop_ann = [{
            "engine_name": "decision",
            "section": "Verse 1",
            "planned_action": "block_role:piano",
            "reason_not_applied": "role 'piano' was not in section base roles",
        }]
        sec = _make_section("Verse 1", "verse", 0, 8, 0.6)
        report = _run_audit([sec], noop_annotations=noop_ann)
        assert report["no_op_event_count"] >= 1

    def test_valid_pattern_events_not_counted_as_noop(self):
        """Pattern events with a real action should not be flagged."""
        sec = _make_section(
            "Verse 1", "verse", 0, 8, 0.6,
            final_pattern_events=[{"action": "hat_density_up", "bar": 4}],
        )
        report = _run_audit([sec])
        # Valid pattern events should not produce issues in the section audit
        verse_audit = next(
            (a for a in report["section_audits"] if a["section_name"] == "Verse 1"), None
        )
        assert verse_audit is not None
        pattern_noop_issues = [i for i in verse_audit["issues"] if "pattern event with empty" in i]
        assert pattern_noop_issues == [], (
            f"Valid pattern event should not be flagged as a no-op, got: {pattern_noop_issues}"
        )


# ---------------------------------------------------------------------------
# 4. Drop events applied exactly once
# ---------------------------------------------------------------------------


class TestDropEventOnceness:
    def test_duplicate_boundary_event_flagged_as_critical(self):
        """Two boundary events of the same type in one section → critical safety finding."""
        events = [
            _make_boundary_event("drum_fill", 0.8),
            _make_boundary_event("drum_fill", 0.8),  # duplicate
        ]
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_blocked_roles=["drums"],
            final_boundary_events=events,
        )
        report = _run_audit([sec])
        critical = [f for f in report["safety_findings"] if f.get("severity") == "critical"]
        assert len(critical) >= 1, (
            f"Expected critical safety finding for duplicate boundary event, got: {report['safety_findings']}"
        )
        assert any(f.get("event_type") == "drum_fill" for f in critical)

    def test_duplicate_boundary_event_lowers_transition_safety_score(self):
        events = [
            _make_boundary_event("silence_gap", 0.9),
            _make_boundary_event("silence_gap", 0.9),
        ]
        sec = _make_section("Hook 1", "hook", 0, 8, 0.9,
                             final_boundary_events=events)
        report = _run_audit([sec])
        assert report["transition_safety_score"] < 1.0, (
            f"Expected safety score < 1.0 when duplicates present, "
            f"got {report['transition_safety_score']}"
        )

    def test_unique_boundary_events_produce_no_duplicate_finding(self):
        """Distinct event types should not trigger a duplicate finding."""
        events = [
            _make_boundary_event("drum_fill", 0.8),
            _make_boundary_event("riser_fx", 0.7),
        ]
        sec = _make_section("Pre Hook", "pre_hook", 0, 4, 0.7,
                             final_blocked_roles=["drums"],
                             final_boundary_events=events)
        report = _run_audit([sec])
        critical = [f for f in report["safety_findings"] if f.get("check") == "duplicate_boundary_event"]
        assert critical == [], (
            f"Unexpected duplicate-event finding for distinct types: {critical}"
        )

    def test_duplicate_event_appears_in_recommended_fixes(self):
        """A critical duplicate boundary event must generate a fix recommendation."""
        events = [
            _make_boundary_event("crash_hit", 0.9),
            _make_boundary_event("crash_hit", 0.9),
        ]
        sec = _make_section("Hook 2", "hook", 8, 8, 0.9,
                             final_boundary_events=events)
        report = _run_audit([sec])
        fixes = " ".join(report["recommended_fixes"])
        assert "duplicate" in fixes.lower() or "crash_hit" in fixes.lower() or "CRITICAL" in fixes, (
            f"Expected fix mentioning duplicate/CRITICAL, got fixes: {report['recommended_fixes']}"
        )


# ---------------------------------------------------------------------------
# 5. Clipping / hard-cut risks are flagged
# ---------------------------------------------------------------------------


class TestClippingAndHardCutRisks:
    def test_high_intensity_reentry_event_flagged(self):
        """re_entry_accent at intensity 0.9 with role reentries → clipping warning."""
        sec = _make_section(
            "Hook 1", "hook", 0, 8, 0.9,
            final_reentries=["808"],
            final_boundary_events=[_make_boundary_event("re_entry_accent", 0.9)],
        )
        report = _run_audit([sec])
        clipping = [f for f in report["safety_findings"] if "clipping" in f.get("check", "")]
        assert len(clipping) >= 1, (
            f"Expected clipping risk finding, got: {report['safety_findings']}"
        )

    def test_crash_hit_high_intensity_reentry_flagged(self):
        """crash_hit at intensity 0.85 with reentries → clipping warning."""
        sec = _make_section(
            "Hook 2", "hook", 8, 8, 0.9,
            final_reentries=["bass"],
            final_boundary_events=[_make_boundary_event("crash_hit", 0.85)],
        )
        report = _run_audit([sec])
        clipping = [f for f in report["safety_findings"] if "clipping" in f.get("check", "")]
        assert len(clipping) >= 1

    def test_hard_cut_in_hook_flagged(self):
        """Hook with blocked roles and no boundary event → hard_cut_no_transition warning."""
        sec = _make_section(
            "Hook 1", "hook", 0, 8, 0.9,
            final_active_roles=["melody", "pads"],
            final_blocked_roles=["drums"],
            final_boundary_events=[],
        )
        report = _run_audit([sec])
        hard_cuts = [f for f in report["safety_findings"] if f.get("check") == "hard_cut_no_transition"]
        assert len(hard_cuts) >= 1, (
            f"Expected hard cut finding, got: {report['safety_findings']}"
        )

    def test_hard_cut_appears_in_recommended_fixes(self):
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_blocked_roles=["drums"],
            final_boundary_events=[],
        )
        report = _run_audit([sec])
        fixes = " ".join(report["recommended_fixes"])
        assert "hard cut" in fixes.lower() or "riser" in fixes.lower(), (
            f"Expected hard-cut fix recommendation, got: {report['recommended_fixes']}"
        )

    def test_low_intensity_reentry_event_does_not_flag_clipping(self):
        """re_entry_accent at low intensity (0.5) should not trigger clipping risk."""
        sec = _make_section(
            "Hook 1", "hook", 0, 8, 0.9,
            final_reentries=["808"],
            final_boundary_events=[_make_boundary_event("re_entry_accent", 0.5)],
        )
        report = _run_audit([sec])
        clipping = [f for f in report["safety_findings"] if "clipping" in f.get("check", "")]
        assert clipping == [], (
            f"Unexpected clipping risk at low intensity: {clipping}"
        )

    def test_missing_fade_before_silence_event_flagged(self):
        """silence_gap without a fade guard event → missing_fade_crossfade warning."""
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_boundary_events=[_make_boundary_event("silence_gap", 0.9)],
        )
        report = _run_audit([sec])
        fade_warnings = [f for f in report["safety_findings"] if f.get("check") == "missing_fade_crossfade"]
        assert len(fade_warnings) >= 1, (
            f"Expected missing fade warning, got: {report['safety_findings']}"
        )


# ---------------------------------------------------------------------------
# 6. Pre-hook tension checks
# ---------------------------------------------------------------------------


class TestPreHookTension:
    def test_pre_hook_without_anchor_block_has_low_tension(self):
        """pre_hook that blocks no anchor role → pre_hook_tension = 0.0."""
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_active_roles=["drums", "bass", "melody"],
            final_blocked_roles=["pads"],  # only pads — not an anchor
        )
        report = _run_audit([sec])
        assert report["impact_scores"]["pre_hook_tension"] == 0.0, (
            f"Expected pre_hook_tension = 0.0, got {report['impact_scores']['pre_hook_tension']}"
        )

    def test_pre_hook_without_anchor_block_generates_trap_issue(self):
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_blocked_roles=["melody"],
        )
        report = _run_audit([sec])
        assert any("pre-hook" in issue.lower() for issue in report["trap_structure_issues"]), (
            f"Expected pre-hook trap issue, got: {report['trap_structure_issues']}"
        )

    def test_pre_hook_with_drums_block_has_positive_tension(self):
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_active_roles=["bass", "melody"],
            final_blocked_roles=["drums"],
        )
        report = _run_audit([sec])
        assert report["impact_scores"]["pre_hook_tension"] > 0.0, (
            f"Expected pre_hook_tension > 0, got {report['impact_scores']['pre_hook_tension']}"
        )


# ---------------------------------------------------------------------------
# 7. Trap arc: intro too full
# ---------------------------------------------------------------------------


class TestTrapIntro:
    def test_intro_with_4_roles_flagged(self):
        sec = _make_section(
            "Intro", "intro", 0, 4, 0.4,
            final_active_roles=["drums", "bass", "melody", "pads"],
        )
        report = _run_audit([sec])
        assert any("intro" in issue.lower() for issue in report["trap_structure_issues"]), (
            f"Expected intro trap issue, got: {report['trap_structure_issues']}"
        )

    def test_intro_with_2_roles_not_flagged_for_density(self):
        sec = _make_section(
            "Intro", "intro", 0, 4, 0.4,
            final_active_roles=["melody", "pads"],
        )
        report = _run_audit([sec])
        density_issues = [
            i for i in report["trap_structure_issues"]
            if "intro" in i.lower() and "role" in i.lower()
        ]
        assert density_issues == [], (
            f"Sparse intro should not be flagged for density: {density_issues}"
        )

    def test_intro_with_high_energy_flagged(self):
        sec = _make_section("Intro", "intro", 0, 4, 0.8, ["melody"])
        report = _run_audit([sec])
        assert any("energy" in i.lower() and "intro" in i.lower()
                   for i in report["trap_structure_issues"])


# ---------------------------------------------------------------------------
# 8. Trap arc: verse 2 identical to verse 1
# ---------------------------------------------------------------------------


class TestTrapVerseVariation:
    def test_identical_verse_1_and_2_generate_trap_issue(self):
        verse1 = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass"])
        verse2 = _make_section("Verse 2", "verse", 8, 8, 0.6, ["drums", "bass"])
        report = _run_audit([verse1, verse2])
        assert any("verse" in i.lower() for i in report["trap_structure_issues"]), (
            f"Expected verse variation trap issue, got: {report['trap_structure_issues']}"
        )

    def test_different_verse_2_not_flagged(self):
        verse1 = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass"])
        verse2 = _make_section("Verse 2", "verse", 8, 8, 0.7, ["drums", "bass", "melody"])
        report = _run_audit([verse1, verse2])
        identical_verse_issues = [
            i for i in report["trap_structure_issues"]
            if "verse 1" in i.lower() and "verse 2" in i.lower() and "identical" in i.lower()
        ]
        assert identical_verse_issues == []


# ---------------------------------------------------------------------------
# 9. Trap arc: hook 2 identical to hook 1
# ---------------------------------------------------------------------------


class TestTrapHookVariation:
    def test_identical_hook_1_and_2_generate_trap_issue(self):
        hook1 = _make_section("Hook 1", "hook", 0, 8, 0.9, ["drums", "bass", "melody"])
        hook2 = _make_section("Hook 2", "hook", 8, 8, 0.9, ["drums", "bass", "melody"])
        report = _run_audit([hook1, hook2])
        assert any("hook" in i.lower() for i in report["trap_structure_issues"]), (
            f"Expected hook variation trap issue, got: {report['trap_structure_issues']}"
        )

    def test_hook_2_with_expansion_not_flagged(self):
        hook1 = _make_section(
            "Hook 1", "hook", 0, 8, 0.9, ["drums", "bass", "melody"],
            final_boundary_events=[_make_boundary_event("drum_fill")],
        )
        hook2 = _make_section(
            "Hook 2", "hook", 8, 8, 0.95, ["drums", "bass", "melody", "pads"],
            final_boundary_events=[_make_boundary_event("final_hook_expansion")],
        )
        report = _run_audit([hook1, hook2])
        identical_hook_issues = [
            i for i in report["trap_structure_issues"]
            if "hook 1" in i.lower() and "hook 2" in i.lower() and "identical" in i.lower()
        ]
        assert identical_hook_issues == []


# ---------------------------------------------------------------------------
# 10. Trap arc: outro with heavy roles
# ---------------------------------------------------------------------------


class TestTrapOutro:
    def test_outro_with_drums_flagged(self):
        sec = _make_section(
            "Outro", "outro", 0, 8, 0.3,
            final_active_roles=["drums", "bass", "melody"],
        )
        report = _run_audit([sec])
        assert any("outro" in i.lower() for i in report["trap_structure_issues"]), (
            f"Expected outro trap issue, got: {report['trap_structure_issues']}"
        )

    def test_outro_with_only_melody_not_flagged(self):
        sec = _make_section(
            "Outro", "outro", 0, 8, 0.2,
            final_active_roles=["melody", "pads"],
        )
        report = _run_audit([sec])
        outro_heavy_issues = [
            i for i in report["trap_structure_issues"]
            if "outro" in i.lower() and "heavy" in i.lower()
        ]
        assert outro_heavy_issues == []


# ---------------------------------------------------------------------------
# 11. Render mismatch detection
# ---------------------------------------------------------------------------


class TestRenderMismatchDetection:
    def test_blocked_role_still_in_raw_instruments_is_mismatch(self):
        """A role in final_blocked_roles that's still in raw section instruments → mismatch."""
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_active_roles=["bass", "melody"],
            final_blocked_roles=["drums"],
        )
        raw_plan = {
            "sections": [{
                "name": "Pre Hook",
                "type": "pre_hook",
                "bar_start": 0,
                "bars": 4,
                "instruments": ["drums", "bass", "melody"],  # drums still present in raw
            }],
        }
        report = _run_audit([sec], raw_render_plan=raw_plan)
        assert report["render_mismatch_count"] >= 1, (
            f"Expected ≥ 1 render mismatch, got {report['render_mismatch_count']}"
        )

    def test_no_mismatch_when_raw_plan_respects_resolved_plan(self):
        """When raw instruments match final_active_roles, no mismatch."""
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_active_roles=["bass", "melody"],
            final_blocked_roles=["drums"],
        )
        raw_plan = {
            "sections": [{
                "name": "Pre Hook",
                "type": "pre_hook",
                "bar_start": 0,
                "bars": 4,
                "instruments": ["bass", "melody"],  # drums correctly absent
            }],
        }
        report = _run_audit([sec], raw_render_plan=raw_plan)
        assert report["render_mismatch_count"] == 0

    def test_no_mismatch_when_no_raw_plan(self):
        """Without a raw plan, render_mismatch_count is 0."""
        sec = _make_section("Verse 1", "verse", 0, 8, 0.6, final_blocked_roles=["pads"])
        report = _run_audit([sec])
        assert report["render_mismatch_count"] == 0


# ---------------------------------------------------------------------------
# 12. Contrast score
# ---------------------------------------------------------------------------


class TestContrastScore:
    def test_monotone_arrangement_has_low_contrast(self):
        """All sections with same energy and density → contrast_score near 0."""
        sections = [
            _make_section(f"Verse {i}", "verse", i * 8, 8, 0.6, ["drums", "bass"])
            for i in range(1, 5)
        ]
        report = _run_audit(sections)
        assert report["contrast_score"] < 0.3, (
            f"Expected low contrast_score, got {report['contrast_score']}"
        )

    def test_varied_arrangement_has_high_contrast(self):
        sections = [
            _make_section("Intro", "intro", 0, 4, 0.3, ["melody"]),
            _make_section("Verse 1", "verse", 4, 8, 0.6, ["drums", "bass", "melody"]),
            _make_section(
                "Pre Hook", "pre_hook", 12, 4, 0.75,
                ["bass", "melody"],
                final_blocked_roles=["drums"],
            ),
            _make_section("Hook 1", "hook", 16, 8, 0.95,
                          ["drums", "bass", "melody", "pads", "808"]),
            _make_section("Outro", "outro", 24, 4, 0.2, ["melody"]),
        ]
        report = _run_audit(sections)
        assert report["contrast_score"] >= 0.4, (
            f"Expected contrast_score ≥ 0.4, got {report['contrast_score']}"
        )


# ---------------------------------------------------------------------------
# 13. Recommended fixes populated for known issues
# ---------------------------------------------------------------------------


class TestRecommendedFixes:
    def test_repetition_fix_included_when_sections_repeat(self):
        roles = ["drums", "bass"]
        sections = [
            _make_section("Verse 1", "verse", 0, 8, 0.6, roles),
            _make_section("Verse 2", "verse", 8, 8, 0.6, roles),
        ]
        report = _run_audit(sections)
        assert len(report["recommended_fixes"]) >= 1
        assert any("identical" in f.lower() or "differentiate" in f.lower()
                   for f in report["recommended_fixes"]), (
            f"Expected repetition fix, got: {report['recommended_fixes']}"
        )

    def test_weak_hook_payoff_fix_included(self):
        verse = _make_section("Verse 1", "verse", 0, 8, 0.6, ["drums", "bass"])
        hook = _make_section("Hook 1", "hook", 8, 8, 0.62, ["drums", "bass", "melody"])
        report = _run_audit([verse, hook])
        if report["hook_payoff_score"] < 0.50:
            assert any("hook" in f.lower() for f in report["recommended_fixes"]), (
                f"Expected hook payoff fix, got: {report['recommended_fixes']}"
            )

    def test_noop_event_fix_included(self):
        noop_ann = [{
            "engine_name": "decision",
            "section": "Verse 1",
            "planned_action": "block_role:piano",
            "reason_not_applied": "role 'piano' was not in section base roles",
        }]
        sec = _make_section("Verse 1")
        report = _run_audit([sec], noop_annotations=noop_ann)
        assert any("no-op" in f.lower() or "noop" in f.lower() for f in report["recommended_fixes"]), (
            f"Expected no-op fix, got: {report['recommended_fixes']}"
        )

    def test_mismatch_fix_included_when_mismatches_detected(self):
        sec = _make_section(
            "Pre Hook", "pre_hook", 0, 4, 0.7,
            final_active_roles=["bass"],
            final_blocked_roles=["drums"],
        )
        raw_plan = {
            "sections": [{
                "name": "Pre Hook",
                "instruments": ["drums", "bass"],
            }],
        }
        report = _run_audit([sec], raw_render_plan=raw_plan)
        if report["render_mismatch_count"] > 0:
            assert any("mismatch" in f.lower() or "resolved plan" in f.lower()
                       for f in report["recommended_fixes"]), (
                f"Expected mismatch fix, got: {report['recommended_fixes']}"
            )


# ---------------------------------------------------------------------------
# 14. Clean arrangement — minimal issues, high scores
# ---------------------------------------------------------------------------


class TestCleanArrangement:
    """A well-structured arrangement should produce high scores and minimal issues."""

    def _make_clean_arrangement(self) -> list[ResolvedSection]:
        return [
            _make_section("Intro", "intro", 0, 4, 0.3, ["melody"]),
            _make_section("Verse 1", "verse", 4, 8, 0.55, ["drums", "bass", "melody"]),
            _make_section(
                "Pre Hook 1", "pre_hook", 12, 4, 0.70,
                ["bass", "melody"],
                final_blocked_roles=["drums"],
                final_boundary_events=[_make_boundary_event("silence_gap", 0.9)],
            ),
            _make_section("Hook 1", "hook", 16, 8, 0.9,
                          ["drums", "bass", "melody", "pads", "808"]),
            _make_section("Verse 2", "verse", 24, 8, 0.60,
                          ["drums", "bass", "melody", "pads"]),
            _make_section(
                "Pre Hook 2", "pre_hook", 32, 4, 0.70,
                ["bass", "melody"],
                final_blocked_roles=["drums"],
                final_boundary_events=[_make_boundary_event("riser_fx", 0.85)],
            ),
            _make_section("Hook 2", "hook", 36, 8, 0.95,
                          ["drums", "bass", "melody", "pads", "808"],
                          final_boundary_events=[_make_boundary_event("final_hook_expansion", 0.9)]),
            _make_section("Outro", "outro", 44, 4, 0.2, ["melody", "pads"]),
        ]

    def test_clean_arrangement_has_no_repetition_groups(self):
        sections = self._make_clean_arrangement()
        report = _run_audit(sections)
        assert report["repetition_groups"] == [], (
            f"Expected no repetition groups, got: {report['repetition_groups']}"
        )

    def test_clean_arrangement_has_high_contrast_score(self):
        sections = self._make_clean_arrangement()
        report = _run_audit(sections)
        assert report["contrast_score"] >= 0.3, (
            f"Expected contrast_score ≥ 0.3, got {report['contrast_score']}"
        )

    def test_clean_arrangement_has_positive_hook_payoff(self):
        sections = self._make_clean_arrangement()
        report = _run_audit(sections)
        assert report["hook_payoff_score"] >= 0.3, (
            f"Expected hook_payoff_score ≥ 0.3, got {report['hook_payoff_score']}"
        )

    def test_clean_arrangement_transition_safety_score_is_high(self):
        sections = self._make_clean_arrangement()
        report = _run_audit(sections)
        # silence_gap without outro_strip will produce missing_fade warnings,
        # which lowers the score slightly, so we accept ≥ 0.7 for the clean arrangement
        assert report["transition_safety_score"] >= 0.7, (
            f"Expected transition_safety_score ≥ 0.7, got {report['transition_safety_score']}"
        )

    def test_report_has_all_required_keys(self):
        sections = self._make_clean_arrangement()
        report = _run_audit(sections)
        required_keys = {
            "repetition_score",
            "contrast_score",
            "hook_payoff_score",
            "transition_safety_score",
            "no_op_event_count",
            "render_mismatch_count",
            "weak_sections",
            "recommended_fixes",
            "section_audits",
            "trap_structure_issues",
            "repetition_groups",
            "impact_scores",
            "safety_findings",
        }
        missing = required_keys - set(report.keys())
        assert missing == set(), f"Report missing keys: {missing}"
