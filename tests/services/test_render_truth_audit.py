"""
Tests for RenderTruthAudit and TransitionSafetyAuditor
(app/services/render_truth_audit.py).

Covers:
- audit records correct engine summaries
- applied/skipped events classified correctly
- no-op actions are surfaced
- role subtraction actually changes final active role map (audit records it)
- repeated sections differ in resolved plan (audit shows different role maps)
- boundary events applied exactly once per section (safety auditor)
- distorted transition regressions: duplicate boundary events flagged as critical
- conflicting event pairs flagged as warning
- post-reentry clipping risk flagged as warning
- hard cuts flagged for hook/pre_hook sections with blocked roles but no transition
- renderer consumes resolved plan: roles injected back into raw sections
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app.services.final_plan_resolver import FinalPlanResolver
from app.services.render_truth_audit import RenderTruthAudit, TransitionSafetyAuditor
from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)


# ---------------------------------------------------------------------------
# Helpers (shared with test_final_plan_resolver where needed)
# ---------------------------------------------------------------------------


def _make_section(
    name: str = "Verse 1",
    section_type: str = "verse",
    bar_start: int = 0,
    bars: int = 8,
    energy: float = 0.6,
    instruments: list | None = None,
    boundary_events: list | None = None,
) -> dict:
    return {
        "name": name,
        "type": section_type,
        "bar_start": bar_start,
        "bars": bars,
        "energy": energy,
        "instruments": instruments or ["drums", "bass"],
        "active_stem_roles": instruments or ["drums", "bass"],
        "boundary_events": boundary_events or [],
        "timeline_events": [],
        "variations": [],
    }


def _make_render_plan(
    sections: list | None = None,
    events: list | None = None,
    decision_plan: dict | None = None,
    drop_plan: dict | None = None,
    timeline_plan: dict | None = None,
) -> dict:
    return {
        "bpm": 120.0,
        "key": "C",
        "total_bars": sum(s.get("bars", 8) for s in (sections or [])),
        "sections": sections or [],
        "events": events or [],
        "_decision_plan": decision_plan,
        "_drop_plan": drop_plan,
        "_timeline_plan": timeline_plan,
        "render_profile": {"genre_profile": "generic"},
    }


def _simple_resolved_section(
    name: str = "Verse 1",
    section_type: str = "verse",
    active_roles: list | None = None,
    blocked_roles: list | None = None,
    reentries: list | None = None,
    boundary_events: list | None = None,
    bar_start: int = 0,
    bars: int = 8,
) -> ResolvedSection:
    return ResolvedSection(
        section_name=name,
        section_type=section_type,
        bar_start=bar_start,
        bars=bars,
        energy=0.6,
        final_active_roles=list(active_roles or ["drums", "bass"]),
        final_blocked_roles=list(blocked_roles or []),
        final_reentries=list(reentries or []),
        final_boundary_events=list(boundary_events or []),
    )


def _simple_resolved_plan(
    sections: list | None = None,
    available_roles: list | None = None,
    noops: list | None = None,
) -> ResolvedRenderPlan:
    return ResolvedRenderPlan(
        resolved_sections=list(sections or [_simple_resolved_section()]),
        bpm=120.0,
        key="C",
        total_bars=8,
        source_quality="stereo_fallback",
        available_roles=list(available_roles or ["drums", "bass"]),
        noop_annotations=list(noops or []),
    )


def _boundary_event(
    event_type: str = "drum_fill",
    source_engine: str = "section",
    intensity: float = 0.7,
    bar: int = 8,
) -> ResolvedBoundaryEvent:
    return ResolvedBoundaryEvent(
        event_type=event_type,
        source_engine=source_engine,
        placement="boundary",
        intensity=intensity,
        bar=bar,
    )


# ===========================================================================
# RenderTruthAudit.build()
# ===========================================================================


class TestRenderTruthAuditBuild:
    def test_build_returns_audit_instance(self):
        raw = _make_render_plan(sections=[_make_section()])
        resolved = _simple_resolved_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert isinstance(audit, RenderTruthAudit)

    def test_arrangement_id_set(self):
        raw = _make_render_plan()
        resolved = _simple_resolved_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=42,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert audit.arrangement_id == 42

    def test_final_section_role_map_correct(self):
        sections = [
            _simple_resolved_section("Verse 1", active_roles=["drums", "bass"]),
            _simple_resolved_section("Hook 1", "hook", active_roles=["drums", "bass", "melody"]),
        ]
        resolved = _simple_resolved_plan(sections=sections)
        raw = _make_render_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert set(audit.final_section_role_map["Verse 1"]) == {"drums", "bass"}
        assert set(audit.final_section_role_map["Hook 1"]) == {"drums", "bass", "melody"}

    def test_role_mutes_recorded(self):
        sections = [
            _simple_resolved_section(
                "Pre Hook", "pre_hook",
                active_roles=["bass"],
                blocked_roles=["drums", "melody"],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        raw = _make_render_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        muted_roles = {m["role"] for m in audit.applied_role_mutes}
        assert "drums" in muted_roles
        assert "melody" in muted_roles

    def test_reintroductions_recorded(self):
        sections = [
            _simple_resolved_section(
                "Hook 1", "hook",
                active_roles=["drums", "bass", "melody"],
                reentries=["melody"],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        raw = _make_render_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        reentry_roles = {r["role"] for r in audit.applied_reintroductions}
        assert "melody" in reentry_roles

    def test_noop_annotations_from_resolver(self):
        noops = [
            {
                "engine_name": "decision",
                "section": "Verse 1",
                "planned_action": "block_role:phantom",
                "reason_not_applied": "role not in base roles",
            }
        ]
        resolved = _simple_resolved_plan(noops=noops)
        raw = _make_render_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert len(audit.noop_annotations) == 1
        assert audit.noop_annotations[0]["planned_action"] == "block_role:phantom"

    def test_engine_summaries_extracted(self):
        decision_plan = {
            "section_decisions": [
                {
                    "section_name": "Verse 1",
                    "occurrence_index": 0,
                    "target_fullness": "medium",
                    "allow_full_stack": True,
                    "required_subtractions": [],
                    "required_reentries": [],
                    "blocked_roles": [],
                    "protected_roles": [],
                    "decision_score": 0.7,
                    "rationale": [],
                }
            ],
            "global_contrast_score": 0.72,
            "payoff_readiness_score": 0.65,
            "fallback_used": False,
        }
        raw = _make_render_plan(
            sections=[_make_section()],
            decision_plan=decision_plan,
        )
        resolved = _simple_resolved_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert "decision" in audit.engine_summaries
        assert audit.engine_summaries["decision"]["section_count"] == 1
        assert audit.engine_summaries["decision"]["global_contrast_score"] == pytest.approx(0.72)

    def test_timeline_summary_extracted(self):
        timeline_plan = {
            "sections": [
                {"name": "verse", "bars": 8, "events": [{"action": "drum_fill"}]},
            ],
            "total_bars": 8,
            "energy_curve": [0.6],
        }
        raw = _make_render_plan(sections=[_make_section()], timeline_plan=timeline_plan)
        resolved = _simple_resolved_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert "timeline" in audit.engine_summaries
        assert audit.engine_summaries["timeline"]["total_events"] == 1

    def test_to_dict_contains_all_keys(self):
        raw = _make_render_plan(sections=[_make_section()])
        resolved = _simple_resolved_plan()
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        d = audit.to_dict()
        for key in (
            "arrangement_id",
            "engine_summaries",
            "resolved_plan_summary",
            "applied_events",
            "skipped_events",
            "skipped_reasons",
            "noop_annotations",
            "applied_role_mutes",
            "applied_reintroductions",
            "final_section_role_map",
            "transition_safety_findings",
        ):
            assert key in d, f"Missing key: {key}"


# ===========================================================================
# Applied / skipped event classification
# ===========================================================================


class TestEventClassification:
    def test_events_with_valid_type_marked_applied(self):
        raw = _make_render_plan(
            sections=[_make_section()],
            events=[{"type": "drum_fill", "section_name": "Verse 1", "bar": 0}],
        )
        resolved = _simple_resolved_plan(
            sections=[_simple_resolved_section("Verse 1")]
        )
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert any(e.get("type") == "drum_fill" for e in audit.applied_events)

    def test_events_with_unknown_section_marked_skipped(self):
        raw = _make_render_plan(
            sections=[_make_section()],
            events=[{"type": "drum_fill", "section_name": "Ghost Section", "bar": 0}],
        )
        resolved = _simple_resolved_plan(
            sections=[_simple_resolved_section("Verse 1")]
        )
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert any(e.get("section_name") == "Ghost Section" for e in audit.skipped_events)
        assert any("Ghost Section" in r for r in audit.skipped_reasons)

    def test_events_without_type_marked_skipped(self):
        raw = _make_render_plan(
            sections=[_make_section()],
            events=[{"section_name": "Verse 1", "bar": 0}],
        )
        resolved = _simple_resolved_plan(
            sections=[_simple_resolved_section("Verse 1")]
        )
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=raw,
            resolved_plan=resolved,
        )
        assert len(audit.skipped_events) >= 1


# ===========================================================================
# TransitionSafetyAuditor
# ===========================================================================


class TestTransitionSafetyAuditorDuplicates:
    def test_no_findings_for_clean_plan(self):
        resolved = _simple_resolved_plan(sections=[
            _simple_resolved_section(
                "Hook 1", "hook",
                boundary_events=[_boundary_event("drum_fill")],
            )
        ])
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        duplicate_findings = [f for f in findings if f["check"] == "duplicate_boundary_event"]
        assert duplicate_findings == []

    def test_duplicate_boundary_event_flagged_critical(self):
        """Two events with same event_type on a section → critical finding."""
        evt1 = _boundary_event("drum_fill")
        evt2 = _boundary_event("drum_fill", intensity=0.9)
        # Both have same type — create them directly
        resolved = _simple_resolved_plan(sections=[
            _simple_resolved_section(
                "Hook 1", "hook",
                boundary_events=[evt1, evt2],
            )
        ])
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        critical = [f for f in findings if f["check"] == "duplicate_boundary_event"]
        assert len(critical) >= 1
        assert all(f["severity"] == "critical" for f in critical)
        assert all(f["event_type"] == "drum_fill" for f in critical)

    def test_duplicate_finding_contains_section_name(self):
        evt1 = _boundary_event("crash_hit")
        evt2 = _boundary_event("crash_hit")
        resolved = _simple_resolved_plan(sections=[
            _simple_resolved_section(
                "Hook 2", "hook",
                boundary_events=[evt1, evt2],
            )
        ])
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        duplicate_findings = [f for f in findings if f["check"] == "duplicate_boundary_event"]
        assert any(f["section"] == "Hook 2" for f in duplicate_findings)


class TestTransitionSafetyAuditorConflicts:
    def test_conflicting_event_pair_flagged(self):
        """silence_gap + drum_fill on same section boundary → warning."""
        events = [
            _boundary_event("silence_gap"),
            _boundary_event("drum_fill"),
        ]
        resolved = _simple_resolved_plan(sections=[
            _simple_resolved_section("Hook 1", "hook", boundary_events=events)
        ])
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        conflict_findings = [f for f in findings if f["check"] == "conflicting_boundary_events"]
        assert len(conflict_findings) >= 1
        assert all(f["severity"] == "warning" for f in conflict_findings)

    def test_non_conflicting_events_not_flagged(self):
        events = [
            _boundary_event("drum_fill"),
            _boundary_event("snare_pickup"),
        ]
        resolved = _simple_resolved_plan(sections=[
            _simple_resolved_section("Hook 1", "hook", boundary_events=events)
        ])
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        conflict_findings = [f for f in findings if f["check"] == "conflicting_boundary_events"]
        assert conflict_findings == []


class TestTransitionSafetyAuditorPostReentryClipping:
    def test_high_intensity_reentry_accent_after_reentry_flagged(self):
        """re_entry_accent at intensity >= 0.8 with role reentries → clipping warning."""
        sections = [
            _simple_resolved_section(
                "Hook 1", "hook",
                active_roles=["drums", "bass", "melody"],
                reentries=["melody"],
                boundary_events=[_boundary_event("re_entry_accent", intensity=0.9)],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        clipping_findings = [f for f in findings if f["check"] == "post_reentry_clipping_risk"]
        assert len(clipping_findings) >= 1
        assert all(f["severity"] == "warning" for f in clipping_findings)

    def test_low_intensity_reentry_accent_not_flagged(self):
        """re_entry_accent at intensity < 0.8 is safe."""
        sections = [
            _simple_resolved_section(
                "Hook 1", "hook",
                reentries=["melody"],
                boundary_events=[_boundary_event("re_entry_accent", intensity=0.5)],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        clipping_findings = [f for f in findings if f["check"] == "post_reentry_clipping_risk"]
        assert clipping_findings == []

    def test_no_reentries_no_clipping_warning(self):
        sections = [
            _simple_resolved_section(
                "Hook 1", "hook",
                reentries=[],
                boundary_events=[_boundary_event("re_entry_accent", intensity=0.95)],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        clipping_findings = [f for f in findings if f["check"] == "post_reentry_clipping_risk"]
        assert clipping_findings == []


class TestTransitionSafetyAuditorHardCuts:
    def test_hook_with_blocked_roles_no_transition_flagged(self):
        sections = [
            _simple_resolved_section(
                "Hook 1", "hook",
                blocked_roles=["drums"],
                boundary_events=[],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        hard_cut_findings = [f for f in findings if f["check"] == "hard_cut_no_transition"]
        assert len(hard_cut_findings) >= 1
        assert all(f["severity"] == "warning" for f in hard_cut_findings)

    def test_hook_with_blocked_roles_and_transition_not_flagged(self):
        sections = [
            _simple_resolved_section(
                "Hook 1", "hook",
                blocked_roles=["drums"],
                boundary_events=[_boundary_event("drum_fill")],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        hard_cut_findings = [f for f in findings if f["check"] == "hard_cut_no_transition"]
        assert hard_cut_findings == []

    def test_verse_with_blocked_roles_no_transition_not_flagged(self):
        """Verse sections don't require a transition event."""
        sections = [
            _simple_resolved_section(
                "Verse 1", "verse",
                blocked_roles=["melody"],
                boundary_events=[],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        hard_cut_findings = [f for f in findings if f["check"] == "hard_cut_no_transition"]
        assert hard_cut_findings == []

    def test_pre_hook_with_blocked_roles_no_transition_flagged(self):
        sections = [
            _simple_resolved_section(
                "Pre Hook", "pre_hook",
                blocked_roles=["bass"],
                boundary_events=[],
            )
        ]
        resolved = _simple_resolved_plan(sections=sections)
        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        hard_cut_findings = [f for f in findings if f["check"] == "hard_cut_no_transition"]
        assert len(hard_cut_findings) >= 1


# ===========================================================================
# Distorted transition regression prevention
# ===========================================================================


class TestDistortedTransitionRegression:
    def test_no_duplicate_events_in_resolved_plan_from_resolver(self):
        """End-to-end: FinalPlanResolver → TransitionSafetyAuditor finds no duplicates."""
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            bar_start=8,
            instruments=["drums", "bass", "melody"],
            boundary_events=[
                {"type": "drum_fill", "placement": "boundary", "intensity": 0.7}
            ],
        )
        plan = _make_render_plan(sections=[section])
        resolver = FinalPlanResolver(plan, available_roles=["drums", "bass", "melody"])
        resolved = resolver.resolve()

        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        duplicate_findings = [f for f in findings if f["check"] == "duplicate_boundary_event"]
        assert duplicate_findings == [], f"Unexpected duplicates: {duplicate_findings}"

    def test_crash_hit_plus_silence_conflict_detected_end_to_end(self):
        """Adding silence_gap + crash_hit via section boundary_events is caught."""
        section = _make_section(
            name="Hook 1",
            section_type="hook",
            bar_start=8,
            boundary_events=[
                {"type": "silence_gap", "placement": "pre_boundary", "intensity": 0.8},
                {"type": "crash_hit", "placement": "boundary", "intensity": 0.9},
            ],
        )
        plan = _make_render_plan(sections=[section])
        resolver = FinalPlanResolver(plan)
        resolved = resolver.resolve()

        auditor = TransitionSafetyAuditor(resolved)
        findings = auditor.audit()
        conflict_findings = [f for f in findings if f["check"] == "conflicting_boundary_events"]
        assert len(conflict_findings) >= 1


# ===========================================================================
# Renderer consumes resolved plan — role injection into raw sections
# ===========================================================================


class TestRendererConsumesResolvedPlan:
    def test_resolved_plan_roles_injected_into_raw_sections(self):
        """render_executor.render_from_plan patches raw sections with resolved roles."""
        from pydub import AudioSegment

        raw_section = {
            "name": "Verse 1",
            "type": "verse",
            "bar_start": 0,
            "bars": 4,
            "energy": 0.6,
            "instruments": ["drums", "bass", "melody"],
            "active_stem_roles": ["drums", "bass", "melody"],
            "boundary_events": [],
            "timeline_events": [],
            "variations": [],
        }
        render_plan = {
            "bpm": 120.0,
            "key": "C",
            "total_bars": 4,
            "sections": [raw_section],
            "events": [],
            "render_profile": {},
            "_resolved_render_plan": {
                "resolved_sections": [
                    {
                        "section_name": "Verse 1",
                        "final_active_roles": ["drums", "bass"],
                        "final_blocked_roles": ["melody"],
                        "final_reentries": [],
                        "final_boundary_events": [],
                    }
                ]
            },
        }

        import tempfile, os
        from pathlib import Path
        from app.services.render_executor import render_from_plan

        audio_source = AudioSegment.silent(duration=4000)
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with patch("app.services.arrangement_jobs._render_producer_arrangement") as mock_render:
                mock_render.return_value = (audio_source, json.dumps({"sections": []}))
                with patch("app.services.mastering.apply_mastering") as mock_master:
                    from app.services.mastering import MasteringResult
                    mock_master.return_value = MasteringResult(
                        audio=audio_source,
                        applied=False,
                        profile="none",
                        peak_dbfs_before=-12.0,
                        peak_dbfs_after=-12.0,
                    )
                    render_from_plan(
                        render_plan_json=render_plan,
                        audio_source=audio_source,
                        output_path=tmp_path,
                    )
            # The section's instruments should now be the resolved roles
            called_arrangement = mock_render.call_args[1]["producer_arrangement"]
            # sections are from the normalised plan built from the raw plan
            # which was patched before _build_producer_arrangement was called
            injected_section = render_plan["sections"][0]
            assert injected_section["instruments"] == ["drums", "bass"]
            assert injected_section["active_stem_roles"] == ["drums", "bass"]
        finally:
            Path(tmp_path).unlink(missing_ok=True)

    def test_mismatched_section_count_skips_injection(self):
        """When resolved_sections length differs from raw sections, injection is skipped."""
        raw_sections = [
            {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8,
             "instruments": ["drums", "bass", "melody"], "active_stem_roles": ["drums", "bass", "melody"],
             "energy": 0.6, "boundary_events": [], "timeline_events": [], "variations": []},
        ]
        render_plan = {
            "bpm": 120.0,
            "key": "C",
            "total_bars": 8,
            "sections": raw_sections,
            "events": [],
            "render_profile": {},
            "_resolved_render_plan": {
                "resolved_sections": [
                    {"section_name": "Verse 1", "final_active_roles": ["drums"]},
                    {"section_name": "Extra Section", "final_active_roles": ["bass"]},
                ]
            },
        }

        import tempfile, os
        from pathlib import Path
        from pydub import AudioSegment
        from app.services.render_executor import render_from_plan

        audio_source = AudioSegment.silent(duration=8000)
        fd, tmp_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            with patch("app.services.arrangement_jobs._render_producer_arrangement") as mock_render:
                mock_render.return_value = (audio_source, json.dumps({"sections": []}))
                with patch("app.services.mastering.apply_mastering") as mock_master:
                    from app.services.mastering import MasteringResult
                    mock_master.return_value = MasteringResult(
                        audio=audio_source,
                        applied=False,
                        profile="none",
                        peak_dbfs_before=-12.0,
                        peak_dbfs_after=-12.0,
                    )
                    render_from_plan(
                        render_plan_json=render_plan,
                        audio_source=audio_source,
                        output_path=tmp_path,
                    )
            # Section should NOT be patched (lengths differ)
            assert raw_sections[0]["instruments"] == ["drums", "bass", "melody"]
        finally:
            Path(tmp_path).unlink(missing_ok=True)


# ===========================================================================
# Integration: resolver + audit together
# ===========================================================================


class TestResolverAndAuditIntegration:
    def test_full_pipeline_produces_consistent_data(self):
        """Full resolver → audit pipeline on a realistic multi-section plan."""
        sections = [
            _make_section("Intro", "intro", bar_start=0, bars=8,
                          instruments=["melody", "pads"]),
            _make_section("Verse 1", "verse", bar_start=8, bars=16,
                          instruments=["drums", "bass", "melody"]),
            _make_section("Pre Hook", "pre_hook", bar_start=24, bars=4,
                          instruments=["drums", "bass"]),
            _make_section("Hook 1", "hook", bar_start=28, bars=16,
                          instruments=["drums", "bass", "melody", "pads"],
                          boundary_events=[
                              {"type": "drum_fill", "placement": "boundary", "intensity": 0.8}
                          ]),
        ]
        decision_plan = {
            "section_decisions": [
                {
                    "section_name": "Intro",
                    "occurrence_index": 0,
                    "target_fullness": "sparse",
                    "allow_full_stack": False,
                    "required_subtractions": [],
                    "required_reentries": [],
                    "blocked_roles": [],
                    "protected_roles": ["melody"],
                    "decision_score": 0.6,
                    "rationale": [],
                },
                {
                    "section_name": "Pre Hook",
                    "occurrence_index": 0,
                    "target_fullness": "medium",
                    "allow_full_stack": False,
                    "required_subtractions": [
                        {
                            "section_name": "Pre Hook",
                            "occurrence_index": 0,
                            "action_type": "hold_back_role",
                            "target_role": "melody",
                            "bar_start": None,
                            "bar_end": None,
                            "intensity": 0.8,
                            "reason": "tension",
                        }
                    ],
                    "required_reentries": [],
                    "blocked_roles": [],
                    "protected_roles": [],
                    "decision_score": 0.75,
                    "rationale": [],
                },
            ],
            "global_contrast_score": 0.8,
            "payoff_readiness_score": 0.75,
            "fallback_used": False,
        }
        raw_plan = _make_render_plan(
            sections=sections,
            decision_plan=decision_plan,
        )

        resolver = FinalPlanResolver(
            raw_plan,
            available_roles=["drums", "bass", "melody", "pads"],
            source_quality="true_stems",
            arrangement_id=99,
        )
        resolved = resolver.resolve()

        audit = RenderTruthAudit.build(
            arrangement_id=99,
            raw_render_plan=raw_plan,
            resolved_plan=resolved,
        )

        # Pre Hook should have melody held back
        pre_hook = next(s for s in resolved.resolved_sections if "pre_hook" in s.section_type or "Pre Hook" in s.section_name)
        assert "melody" not in pre_hook.final_active_roles

        # Hook should be fully active (no subtractions in decision for Hook 1)
        hook = next(s for s in resolved.resolved_sections if "Hook" in s.section_name)
        assert "drums" in hook.final_active_roles
        assert "bass" in hook.final_active_roles

        # Mutes recorded in audit
        muted = {m["role"] for m in audit.applied_role_mutes}
        assert "melody" in muted

        # No critical safety findings
        critical = [f for f in audit.transition_safety_findings if f["severity"] == "critical"]
        assert critical == []

        # section role map correct
        assert "melody" not in audit.final_section_role_map["Pre Hook"]
