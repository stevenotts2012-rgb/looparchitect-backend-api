"""
Tests for the Generative Producer Primary mode.

Covers (per problem statement):
1. primary flag off  → no audio plan changes
2. primary flag on   → supported events applied to resolved sections
3. unsupported events skipped with reason
4. duplicate events deduped (not added twice)
5. blocked roles respected (GP cannot unmute DE-blocked roles)
6. job does not crash on malformed events
7. metadata is JSON-safe
8. render truth check: mute_role mismatch detected
9. mute_role applied correctly (role removed from active_roles)
10. unmute_role applied correctly (role added to active_roles)
11. pattern events applied (filter_role, chop_role, add_hat_roll, etc.)
12. boundary events applied (add_fx_riser, add_impact, reverb_tail, etc.)
13. groove events applied (widen_role)
14. events for unavailable roles are skipped
15. events with missing required fields are skipped
16. no GP events available → fallback recorded
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services.final_plan_resolver import FinalPlanResolver
from app.services.resolved_render_plan import ResolvedRenderPlan, ResolvedSection
from app.services.render_truth_audit import RenderTruthAudit, _check_producer_mute_mismatches


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
) -> dict:
    roles = instruments or ["drums", "bass", "melody"]
    return {
        "name": name,
        "type": section_type,
        "bar_start": bar_start,
        "bars": bars,
        "energy": energy,
        "instruments": roles,
        "active_stem_roles": roles,
        "boundary_events": boundary_events or [],
        "timeline_events": timeline_events or [],
        "variations": [],
    }


def _make_render_plan(
    sections: list | None = None,
    gp_events: list | None = None,
    bpm: float = 120.0,
) -> dict:
    plan: dict = {
        "bpm": bpm,
        "key": "C major",
        "total_bars": sum(s.get("bars", 8) for s in (sections or [])),
        "sections": sections or [],
        "events": [],
        "render_profile": {"genre_profile": "trap"},
    }
    if gp_events is not None:
        plan["_generative_producer_events"] = gp_events
    return plan


def _make_gp_event(
    event_type: str,
    render_action: str,
    target_role: str,
    section_name: str = "Verse 1",
    bar_start: int = 0,
    bar_end: int = 8,
    intensity: float = 0.75,
    parameters: dict | None = None,
) -> dict:
    return {
        "event_id": str(uuid.uuid4()),
        "event_type": event_type,
        "render_action": render_action,
        "target_role": target_role,
        "section_name": section_name,
        "bar_start": bar_start,
        "bar_end": bar_end,
        "intensity": intensity,
        "parameters": parameters or {},
    }


def _resolve(
    plan: dict,
    available_roles: list | None = None,
    generative_producer_primary: bool = True,
) -> ResolvedRenderPlan:
    resolver = FinalPlanResolver(
        plan,
        available_roles=available_roles or ["drums", "bass", "melody", "pads", "fx"],
        generative_producer_primary=generative_producer_primary,
    )
    return resolver.resolve()


# ===========================================================================
# 1. Primary flag off → no audio plan changes
# ===========================================================================


class TestPrimaryFlagOff:
    def test_no_gp_events_applied_when_flag_off(self):
        """When flag=False the GP events in render_plan must not change anything."""
        evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass"])],
            gp_events=[evt],
        )
        result = _resolve(plan, generative_producer_primary=False)
        section = result.resolved_sections[0]
        # drums must still be active — GP did not run.
        assert "drums" in section.final_active_roles
        assert "drums" not in section.final_blocked_roles

    def test_gp_metadata_false_when_flag_off(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = _resolve(plan, generative_producer_primary=False)
        assert result.generative_producer_primary_used is False
        assert result.generative_producer_events_applied == 0
        assert result.generative_producer_events_skipped == 0

    def test_all_resolved_fields_unchanged_when_flag_off(self):
        """Boundary events, groove, pattern fields must be untouched."""
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[_make_gp_event("fx_riser", "add_fx_riser", "fx")],
        )
        result = _resolve(plan, generative_producer_primary=False)
        section = result.resolved_sections[0]
        assert section.final_boundary_events == []


# ===========================================================================
# 2. Primary flag on → supported events applied
# ===========================================================================


class TestPrimaryFlagOn:
    def test_mute_role_removes_role(self):
        evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass", "melody"])],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert "drums" not in section.final_active_roles
        assert "drums" in section.final_blocked_roles

    def test_unmute_role_adds_role(self):
        """unmute_role on a role absent from active should add it."""
        evt = _make_gp_event("pad_expose", "unmute_role", "pads")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass"])],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert "pads" in section.final_active_roles

    def test_pattern_event_added_for_filter_role(self):
        evt = _make_gp_event("melody_filter", "filter_role", "melody", section_name="Hook 1")
        plan = _make_render_plan(
            sections=[_make_section("Hook 1", section_type="hook", instruments=["drums", "melody"])],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(
            e.get("action") == "filter_role" and e.get("target_role") == "melody"
            for e in section.final_pattern_events
        )

    def test_pattern_event_added_for_chop_role(self):
        evt = _make_gp_event("melody_chop", "chop_role", "melody")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "melody"])],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(
            e.get("action") == "chop_role" and e.get("target_role") == "melody"
            for e in section.final_pattern_events
        )

    def test_pattern_event_added_for_add_hat_roll(self):
        evt = _make_gp_event("hat_roll", "add_hat_roll", "drums")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.get("action") == "add_hat_roll" for e in section.final_pattern_events)

    def test_pattern_event_added_for_add_drum_fill(self):
        evt = _make_gp_event("drum_fill", "add_drum_fill", "drums")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.get("action") == "add_drum_fill" for e in section.final_pattern_events)

    def test_pattern_event_added_for_bass_pattern_variation(self):
        evt = _make_gp_event("bass_pattern_variation", "bass_pattern_variation", "bass")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(
            e.get("action") == "bass_pattern_variation" for e in section.final_pattern_events
        )

    def test_boundary_event_added_for_add_fx_riser(self):
        evt = _make_gp_event("fx_riser", "add_fx_riser", "fx", section_name="Pre-Hook")
        plan = _make_render_plan(
            sections=[_make_section("Pre-Hook", section_type="pre_hook", instruments=["drums", "fx"])],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.event_type == "riser_fx" for e in section.final_boundary_events)

    def test_boundary_event_added_for_add_impact(self):
        evt = _make_gp_event("fx_impact", "add_impact", "fx", section_name="Hook 1")
        plan = _make_render_plan(
            sections=[_make_section("Hook 1", section_type="hook")],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.event_type == "crash_hit" for e in section.final_boundary_events)

    def test_boundary_event_added_for_reverb_tail(self):
        evt = _make_gp_event("automation_reverb", "reverb_tail", "melody", section_name="Outro")
        plan = _make_render_plan(
            sections=[_make_section("Outro", section_type="outro")],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.event_type == "reverse_fx" for e in section.final_boundary_events)

    def test_boundary_event_added_for_fade_role(self):
        evt = _make_gp_event("automation_fade", "fade_role", "melody", section_name="Outro")
        plan = _make_render_plan(
            sections=[_make_section("Outro", section_type="outro")],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.event_type == "outro_strip" for e in section.final_boundary_events)

    def test_boundary_event_added_for_reverse_slice(self):
        evt = _make_gp_event("melody_reverse", "reverse_slice", "melody")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.event_type == "reverse_fx" for e in section.final_boundary_events)

    def test_groove_event_added_for_widen_role(self):
        evt = _make_gp_event("automation_widen", "widen_role", "melody")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(
            e.get("action") == "widen_role" and e.get("target_role") == "melody"
            for e in section.final_groove_events
        )

    def test_pattern_event_added_for_delay_role(self):
        evt = _make_gp_event("automation_delay", "delay_role", "melody")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert any(e.get("action") == "delay_role" for e in section.final_pattern_events)

    def test_metadata_set_when_events_applied(self):
        evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        assert result.generative_producer_primary_used is True
        assert result.generative_producer_events_applied >= 1
        assert result.generative_producer_primary_fallback_used is False

    def test_source_engine_field_is_set(self):
        evt = _make_gp_event("fx_riser", "add_fx_riser", "fx")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        riser = next(e for e in section.final_boundary_events if e.event_type == "riser_fx")
        assert riser.source_engine == "generative_producer_primary"


# ===========================================================================
# 3. Unsupported events skipped
# ===========================================================================


class TestUnsupportedEventsSkipped:
    def test_unsupported_render_action_is_skipped(self):
        evt = _make_gp_event("custom_action", "totally_unsupported_action", "melody")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        assert result.generative_producer_events_skipped >= 1

    def test_unsupported_event_recorded_in_noop_annotations(self):
        evt = _make_gp_event("custom_action", "totally_unsupported_action", "melody")
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[evt],
        )
        result = _resolve(plan)
        # Unsupported events are surfaced as noop annotations.
        noops = [n for n in result.noop_annotations if n.get("engine_name") == "generative_producer_primary"]
        assert len(noops) >= 1

    def test_skipped_count_increases_for_each_unsupported_event(self):
        events = [
            _make_gp_event(f"custom_{i}", "bad_action", "melody")
            for i in range(3)
        ]
        plan = _make_render_plan(sections=[_make_section()], gp_events=events)
        result = _resolve(plan)
        assert result.generative_producer_events_skipped >= 3


# ===========================================================================
# 4. Duplicate events deduped
# ===========================================================================


class TestDuplicateEventsDeduped:
    def test_duplicate_mute_skipped(self):
        """Two mute_role events for the same role should only apply once."""
        evts = [
            _make_gp_event("drum_dropout", "mute_role", "drums"),
            _make_gp_event("drum_dropout_2", "mute_role", "drums"),
        ]
        plan = _make_render_plan(
            sections=[_make_section(instruments=["drums", "bass"])],
            gp_events=evts,
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        # drums appears exactly once in blocked
        assert section.final_blocked_roles.count("drums") == 1
        # One applied, one skipped (dedup)
        assert result.generative_producer_events_applied == 1
        assert result.generative_producer_events_skipped == 1

    def test_duplicate_boundary_event_type_deduped(self):
        evts = [
            _make_gp_event("fx_riser", "add_fx_riser", "fx"),
            _make_gp_event("fx_riser_2", "add_fx_riser", "fx"),
        ]
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=evts,
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        riser_count = sum(1 for e in section.final_boundary_events if e.event_type == "riser_fx")
        assert riser_count == 1

    def test_duplicate_pattern_event_deduped(self):
        evts = [
            _make_gp_event("hat_roll", "add_hat_roll", "drums"),
            _make_gp_event("hat_roll_2", "add_hat_roll", "drums"),
        ]
        plan = _make_render_plan(sections=[_make_section()], gp_events=evts)
        result = _resolve(plan)
        section = result.resolved_sections[0]
        count = sum(1 for e in section.final_pattern_events if e.get("action") == "add_hat_roll" and e.get("target_role") == "drums")
        assert count == 1

    def test_unmute_on_already_active_role_is_skipped(self):
        """Unmuting a role that is already active is a no-op."""
        evt = _make_gp_event("pad_expose", "unmute_role", "drums")  # drums already active
        plan = _make_render_plan(
            sections=[_make_section(instruments=["drums", "bass"])],
            gp_events=[evt],
        )
        result = _resolve(plan)
        assert result.generative_producer_events_skipped >= 1


# ===========================================================================
# 5. Blocked roles respected
# ===========================================================================


class TestBlockedRolesRespected:
    def test_gp_cannot_unmute_de_blocked_role(self):
        """Decision Engine blocked roles must not be overridden by GP unmute_role."""
        decision_plan = {
            "section_decisions": [
                {
                    "section_name": "Verse 1",
                    "occurrence_index": 0,
                    "target_fullness": "medium",
                    "allow_full_stack": True,
                    "required_subtractions": [
                        {"action_type": "remove_role", "target_role": "pads"}
                    ],
                    "required_reentries": [],
                    "blocked_roles": ["pads"],
                    "protected_roles": [],
                    "decision_score": 0.8,
                    "rationale": [],
                }
            ]
        }
        gp_evt = _make_gp_event("pad_expose", "unmute_role", "pads")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass", "pads"])],
            gp_events=[gp_evt],
        )
        plan["_decision_plan"] = decision_plan
        result = _resolve(plan)
        section = result.resolved_sections[0]
        # GP must not have re-added pads
        assert "pads" not in section.final_active_roles

    def test_gp_mute_respected_even_when_de_has_no_opinion(self):
        """GP mute_role should work when the Decision Engine hasn't blocked the role."""
        evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section(instruments=["drums", "bass"])],
            gp_events=[evt],
        )
        result = _resolve(plan)
        section = result.resolved_sections[0]
        assert "drums" not in section.final_active_roles
        assert "drums" in section.final_blocked_roles


# ===========================================================================
# 6. Job does not crash on malformed events
# ===========================================================================


class TestMalformedEventsHandled:
    def test_missing_render_action(self):
        evt = {
            "event_id": str(uuid.uuid4()),
            "event_type": "drum_dropout",
            "render_action": "",  # empty
            "target_role": "drums",
            "section_name": "Verse 1",
            "bar_start": 0,
            "bar_end": 8,
            "intensity": 0.75,
            "parameters": {},
        }
        plan = _make_render_plan(sections=[_make_section()], gp_events=[evt])
        result = _resolve(plan)
        assert isinstance(result, ResolvedRenderPlan)
        assert result.generative_producer_events_skipped >= 1

    def test_missing_target_role(self):
        evt = _make_gp_event("mute_role", "mute_role", "drums")
        evt["target_role"] = ""  # blank
        plan = _make_render_plan(sections=[_make_section()], gp_events=[evt])
        result = _resolve(plan)
        assert isinstance(result, ResolvedRenderPlan)

    def test_missing_section_name(self):
        evt = _make_gp_event("mute_role", "mute_role", "drums")
        evt["section_name"] = ""  # blank
        plan = _make_render_plan(sections=[_make_section()], gp_events=[evt])
        result = _resolve(plan)
        assert isinstance(result, ResolvedRenderPlan)

    def test_section_name_not_in_plan(self):
        evt = _make_gp_event("mute_role", "mute_role", "drums", section_name="NonExistentSection")
        plan = _make_render_plan(sections=[_make_section("Verse 1")], gp_events=[evt])
        result = _resolve(plan)
        assert isinstance(result, ResolvedRenderPlan)
        assert result.generative_producer_events_skipped >= 1

    def test_negative_intensity_no_crash(self):
        evt = _make_gp_event("drum_fill", "add_drum_fill", "drums", intensity=-0.5)
        plan = _make_render_plan(sections=[_make_section()], gp_events=[evt])
        result = _resolve(plan)
        assert isinstance(result, ResolvedRenderPlan)

    def test_entirely_malformed_event_dict(self):
        """A completely unexpected dict shape should not raise."""
        evt = {"garbage": True, "junk": None}
        plan = _make_render_plan(sections=[_make_section()], gp_events=[evt])
        result = _resolve(plan)
        assert isinstance(result, ResolvedRenderPlan)

    def test_none_gp_events_field_no_crash(self):
        """If _generative_producer_events is None the resolver must not crash."""
        plan = _make_render_plan(sections=[_make_section()], gp_events=None)
        plan["_generative_producer_events"] = None
        result = _resolve(plan)
        assert isinstance(result, ResolvedRenderPlan)

    def test_resolve_never_raises_on_exception_in_merge(self):
        """The public resolve() must never raise — always return a ResolvedRenderPlan."""
        plan = _make_render_plan(sections=[_make_section()], gp_events=[{"bad": object()}])
        resolver = FinalPlanResolver(
            plan,
            available_roles=["drums", "bass"],
            generative_producer_primary=True,
        )
        result = resolver.resolve()
        assert isinstance(result, ResolvedRenderPlan)


# ===========================================================================
# 7. Metadata JSON-safe
# ===========================================================================


class TestMetadataJsonSafe:
    def test_resolved_plan_to_dict_is_json_serialisable(self):
        evts = [
            _make_gp_event("drum_dropout", "mute_role", "drums"),
            _make_gp_event("melody_filter", "filter_role", "melody"),
            _make_gp_event("fx_riser", "add_fx_riser", "fx"),
        ]
        plan = _make_render_plan(
            sections=[
                _make_section("Verse 1"),
                _make_section("Hook 1", section_type="hook", bar_start=8),
            ],
            gp_events=evts,
        )
        result = _resolve(plan)
        d = result.to_dict()
        # Must not raise
        serialised = json.dumps(d)
        assert isinstance(serialised, str)

    def test_metadata_fields_have_correct_types(self):
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[_make_gp_event("drum_dropout", "mute_role", "drums")],
        )
        result = _resolve(plan)
        assert isinstance(result.generative_producer_primary_used, bool)
        assert isinstance(result.generative_producer_primary_fallback_used, bool)
        assert isinstance(result.generative_producer_primary_fallback_reason, str)
        assert isinstance(result.generative_producer_events_applied, int)
        assert isinstance(result.generative_producer_events_skipped, int)

    def test_to_dict_metadata_keys_present(self):
        plan = _make_render_plan(sections=[_make_section()])
        result = _resolve(plan, generative_producer_primary=False)
        d = result.to_dict()
        assert "generative_producer_primary_used" in d
        assert "generative_producer_primary_fallback_used" in d
        assert "generative_producer_primary_fallback_reason" in d
        assert "generative_producer_events_applied" in d
        assert "generative_producer_events_skipped" in d

    def test_noop_annotations_json_safe(self):
        """Skipped GP events appear as noop annotations and must be JSON-safe."""
        evt = _make_gp_event("custom", "unsupported_render_action", "melody")
        plan = _make_render_plan(sections=[_make_section()], gp_events=[evt])
        result = _resolve(plan)
        json.dumps(result.noop_annotations)  # must not raise


# ===========================================================================
# 8. Render truth check: mute_role mismatch detected
# ===========================================================================


class TestRenderTruthMuteMismatch:
    def test_mismatch_recorded_when_mute_not_applied(self):
        """
        When GP primary is OFF and the _generative_producer_events list contains
        a mute_role event, the role remains active → mismatch should be detected.
        """
        gp_evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass"])],
            gp_events=[gp_evt],
        )
        # Resolve WITHOUT GP primary so drums stays active.
        resolved = _resolve(plan, generative_producer_primary=False)
        mismatches = _check_producer_mute_mismatches(plan, resolved)
        # drums is still in active_roles → mismatch
        assert any(m["target_role"] == "drums" for m in mismatches)

    def test_no_mismatch_when_mute_applied(self):
        """When GP primary is ON and mute_role works, no mismatch."""
        gp_evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass"])],
            gp_events=[gp_evt],
        )
        resolved = _resolve(plan, generative_producer_primary=True)
        mismatches = _check_producer_mute_mismatches(plan, resolved)
        # drums was muted → no mismatch
        assert all(m["target_role"] != "drums" for m in mismatches)

    def test_no_mismatch_when_no_gp_events(self):
        plan = _make_render_plan(sections=[_make_section()])
        resolved = _resolve(plan, generative_producer_primary=False)
        mismatches = _check_producer_mute_mismatches(plan, resolved)
        assert mismatches == []

    def test_mismatch_fields_json_safe(self):
        gp_evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass"])],
            gp_events=[gp_evt],
        )
        resolved = _resolve(plan, generative_producer_primary=False)
        mismatches = _check_producer_mute_mismatches(plan, resolved)
        json.dumps(mismatches)  # must not raise

    def test_render_truth_audit_includes_producer_mute_mismatches(self):
        gp_evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass"])],
            gp_events=[gp_evt],
        )
        resolved = _resolve(plan, generative_producer_primary=False)
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=plan,
            resolved_plan=resolved,
        )
        # The audit must expose the field
        audit_dict = audit.to_dict()
        assert "producer_mute_mismatches" in audit_dict
        assert isinstance(audit_dict["producer_mute_mismatches"], list)

    def test_render_truth_audit_json_safe(self):
        gp_evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section("Verse 1", instruments=["drums", "bass"])],
            gp_events=[gp_evt],
        )
        resolved = _resolve(plan, generative_producer_primary=False)
        audit = RenderTruthAudit.build(
            arrangement_id=1,
            raw_render_plan=plan,
            resolved_plan=resolved,
        )
        json.dumps(audit.to_dict())  # must not raise


# ===========================================================================
# 9. Instrument Activation Rules (available_roles filter)
# ===========================================================================


class TestInstrumentActivationRules:
    def test_event_for_absent_role_is_skipped(self):
        """An event targeting a role not in available_roles must be skipped."""
        evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(
            sections=[_make_section(instruments=["bass", "melody"])],
            gp_events=[evt],
        )
        # available_roles does not include 'drums'
        result = _resolve(plan, available_roles=["bass", "melody"])
        assert result.generative_producer_events_skipped >= 1
        section = result.resolved_sections[0]
        assert "drums" not in section.final_blocked_roles

    def test_event_for_present_role_applied(self):
        evt = _make_gp_event("hat_roll", "add_hat_roll", "drums")
        plan = _make_render_plan(
            sections=[_make_section(instruments=["drums", "bass"])],
            gp_events=[evt],
        )
        result = _resolve(plan, available_roles=["drums", "bass"])
        section = result.resolved_sections[0]
        assert any(e.get("action") == "add_hat_roll" for e in section.final_pattern_events)


# ===========================================================================
# 10. No GP events → fallback recorded
# ===========================================================================


class TestNoGpEventsFallback:
    def test_fallback_used_when_no_events_present_with_sections(self):
        plan = _make_render_plan(
            sections=[_make_section()],
            gp_events=[],  # empty list
        )
        result = _resolve(plan)
        assert result.generative_producer_primary_fallback_used is True
        assert result.generative_producer_primary_used is False
        assert result.generative_producer_primary_fallback_reason != ""

    def test_no_fallback_when_events_present(self):
        evt = _make_gp_event("drum_dropout", "mute_role", "drums")
        plan = _make_render_plan(sections=[_make_section()], gp_events=[evt])
        result = _resolve(plan)
        assert result.generative_producer_primary_fallback_used is False


# ===========================================================================
# 11. Multi-section routing
# ===========================================================================


class TestMultiSectionRouting:
    def test_event_applied_to_correct_section_only(self):
        """An event for 'Hook 1' must not affect 'Verse 1'."""
        hook_evt = _make_gp_event("fx_riser", "add_fx_riser", "fx", section_name="Hook 1")
        plan = _make_render_plan(
            sections=[
                _make_section("Verse 1", section_type="verse", bar_start=0),
                _make_section("Hook 1", section_type="hook", bar_start=8),
            ],
            gp_events=[hook_evt],
        )
        result = _resolve(plan)
        verse_section = result.resolved_sections[0]
        hook_section = result.resolved_sections[1]
        assert verse_section.section_name == "Verse 1"
        assert hook_section.section_name == "Hook 1"
        assert not any(e.event_type == "riser_fx" for e in verse_section.final_boundary_events)
        assert any(e.event_type == "riser_fx" for e in hook_section.final_boundary_events)

    def test_multiple_events_multiple_sections(self):
        evts = [
            _make_gp_event("mute_role", "mute_role", "drums", section_name="Pre-Hook"),
            _make_gp_event("add_impact", "add_impact", "fx", section_name="Hook 1"),
        ]
        plan = _make_render_plan(
            sections=[
                _make_section("Verse 1", instruments=["drums", "bass"], bar_start=0),
                _make_section("Pre-Hook", section_type="pre_hook", instruments=["drums", "bass", "fx"], bar_start=8),
                _make_section("Hook 1", section_type="hook", instruments=["drums", "bass", "fx"], bar_start=16),
            ],
            gp_events=evts,
        )
        result = _resolve(plan)
        pre_hook = result.resolved_sections[1]
        hook = result.resolved_sections[2]
        assert "drums" not in pre_hook.final_active_roles
        assert any(e.event_type == "crash_hit" for e in hook.final_boundary_events)
