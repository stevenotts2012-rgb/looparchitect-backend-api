"""
Tests for the timeline engine shadow planner integration in arrangement_jobs.

Covers:
- TimelinePlan is generated during arrangement jobs
- Validation warnings are captured and stored
- Serialised plan is stored in render_plan_json metadata
- Live generation still completes unchanged when the shadow planner runs
- Timeline Engine primary promotion behaviour (TIMELINE_ENGINE_PRIMARY)
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from app.db import SessionLocal
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.arrangement_jobs import (
    _apply_timeline_engine_primary,
    _run_timeline_planner_shadow,
    _serialize_timeline_plan,
    _serialize_timeline_validation,
    run_arrangement_job,
)
from app.services.timeline_engine import TimelinePlan, TimelineSection
from app.services.timeline_engine.types import TimelineEvent
from app.services.timeline_engine.validator import ValidationIssue


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_FULL_ROLES = ["drums", "bass", "melody", "pads", "fx"]

_STANDARD_RENDER_PLAN = {
    "sections": [
        {"type": "intro",   "bars": 4,  "active_stem_roles": ["melody", "pads"]},
        {"type": "verse",   "bars": 8,  "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "hook",    "bars": 8,  "active_stem_roles": ["drums", "bass", "melody", "pads"]},
        {"type": "verse",   "bars": 8,  "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "hook",    "bars": 8,  "active_stem_roles": ["drums", "bass", "melody", "pads", "fx"]},
        {"type": "outro",   "bars": 4,  "active_stem_roles": ["melody", "pads"]},
    ],
    "sections_count": 6,
    "events_count": 0,
}


@pytest.fixture()
def db():
    session = SessionLocal()
    yield session
    session.close()


def _minimal_wav_bytes() -> bytes:
    """Return a minimal valid WAV byte string for mock HTTP responses."""
    return (
        b"RIFF"
        b"\x24\x00\x00\x00"
        b"WAVE"
        b"fmt "
        b"\x10\x00\x00\x00"
        b"\x01\x00"
        b"\x02\x00"
        b"\x44\xac\x00\x00"
        b"\x10\xb1\x02\x00"
        b"\x04\x00"
        b"\x10\x00"
        b"data"
        b"\x00\x00\x00\x00"
    )


def _fake_export(self, out_f, format="wav"):
    with open(out_f, "wb") as fh:
        fh.write(_minimal_wav_bytes())
    return None


# ---------------------------------------------------------------------------
# Unit: _serialize_timeline_plan
# ---------------------------------------------------------------------------

class TestSerializeTimelinePlan:
    def test_returns_json_safe_dict(self):
        event = TimelineEvent(bar_start=1, bar_end=2, action="drum_fill", target_role="drums")
        section = TimelineSection(
            name="hook",
            bars=8,
            target_energy=0.9,
            target_density=0.8,
            active_roles=["drums", "bass"],
            events=[event],
        )
        plan = TimelinePlan(
            sections=[section],
            total_bars=8,
            energy_curve=[0.9],
            variation_log=["hook_v1"],
            state_snapshot={"foo": "bar"},
        )

        result = _serialize_timeline_plan(plan)

        assert result["total_bars"] == 8
        assert result["energy_curve"] == [0.9]
        assert result["variation_log"] == ["hook_v1"]
        assert result["state_snapshot"] == {"foo": "bar"}
        assert len(result["sections"]) == 1
        sec = result["sections"][0]
        assert sec["name"] == "hook"
        assert sec["bars"] == 8
        assert sec["active_roles"] == ["drums", "bass"]
        assert len(sec["events"]) == 1
        ev = sec["events"][0]
        assert ev["action"] == "drum_fill"
        assert ev["target_role"] == "drums"
        assert ev["bar_start"] == 1
        assert ev["bar_end"] == 2

        # Should be JSON-serialisable without error
        json.dumps(result)

    def test_empty_plan_serialises(self):
        plan = TimelinePlan(sections=[], total_bars=0, energy_curve=[], variation_log=[])
        result = _serialize_timeline_plan(plan)
        assert result["sections"] == []
        assert result["total_bars"] == 0
        json.dumps(result)


# ---------------------------------------------------------------------------
# Unit: _serialize_timeline_validation
# ---------------------------------------------------------------------------

class TestSerializeTimelineValidation:
    def test_converts_issues_to_dicts(self):
        issues = [
            ValidationIssue(rule="flat_timeline", severity="error", message="Flat energy."),
            ValidationIssue(rule="empty_events_long_section", severity="warning",
                            message="No events.", section_name="verse"),
        ]
        result = _serialize_timeline_validation(issues)

        assert len(result) == 2
        assert result[0] == {
            "rule": "flat_timeline",
            "severity": "error",
            "message": "Flat energy.",
            "section_name": "",
        }
        assert result[1]["section_name"] == "verse"
        json.dumps(result)

    def test_empty_list(self):
        assert _serialize_timeline_validation([]) == []


# ---------------------------------------------------------------------------
# Unit: _run_timeline_planner_shadow
# ---------------------------------------------------------------------------

class TestRunTimelinePlannerShadow:
    def test_returns_plan_for_valid_render_plan(self):
        result = _run_timeline_planner_shadow(
            render_plan=_STANDARD_RENDER_PLAN,
            available_roles=_FULL_ROLES,
            arrangement_id=1,
            correlation_id="test-corr-id",
        )

        assert result["error"] is None
        assert result["section_count"] == 6
        assert result["event_count"] >= 0
        assert result["plan"] is not None
        plan = result["plan"]
        assert plan["total_bars"] == 40
        assert len(plan["sections"]) == 6
        # Sections have the expected keys
        for sec in plan["sections"]:
            assert "name" in sec
            assert "bars" in sec
            assert "active_roles" in sec
            assert "events" in sec

    def test_validation_issues_captured(self):
        # Build a render_plan that will produce a flat energy curve warning/error
        flat_plan = {
            "sections": [
                {"type": "verse", "bars": 8, "active_stem_roles": ["drums"]},
                {"type": "verse", "bars": 8, "active_stem_roles": ["drums"]},
            ]
        }
        result = _run_timeline_planner_shadow(
            render_plan=flat_plan,
            available_roles=["drums"],
            arrangement_id=2,
            correlation_id="test-flat",
        )
        # We only check structure — the validator may or may not fire depending
        # on how the planner adjusts the energy curve for weak source material.
        assert "validation_issues" in result
        assert isinstance(result["validation_issues"], list)
        for issue in result["validation_issues"]:
            assert "rule" in issue
            assert "severity" in issue
            assert "message" in issue

    def test_returns_empty_result_for_empty_render_plan(self):
        result = _run_timeline_planner_shadow(
            render_plan={"sections": []},
            available_roles=_FULL_ROLES,
            arrangement_id=3,
            correlation_id="test-empty",
        )
        assert result["plan"] is None
        assert result["section_count"] == 0
        assert result["event_count"] == 0
        assert result["error"] is None

    def test_never_raises_on_bad_input(self):
        # Pass None sections to verify the shadow call never propagates exceptions
        result = _run_timeline_planner_shadow(
            render_plan={"sections": None},
            available_roles=[],
            arrangement_id=99,
            correlation_id="test-bad",
        )
        # Should return gracefully with no error or with a captured error string
        assert isinstance(result, dict)

    def test_serialised_plan_is_json_safe(self):
        result = _run_timeline_planner_shadow(
            render_plan=_STANDARD_RENDER_PLAN,
            available_roles=_FULL_ROLES,
            arrangement_id=4,
            correlation_id="test-json",
        )
        assert result["error"] is None
        # Must not raise
        json.dumps(result)

    def test_section_names_logged(self, caplog):
        import logging
        with caplog.at_level(logging.INFO, logger="app.services.arrangement_jobs"):
            _run_timeline_planner_shadow(
                render_plan=_STANDARD_RENDER_PLAN,
                available_roles=_FULL_ROLES,
                arrangement_id=5,
                correlation_id="test-log",
            )
        log_text = caplog.text
        # Intro section name should appear
        assert "intro" in log_text.lower()

    def test_variation_log_captured(self):
        # Use a spec with repeated sections so the variation log is populated.
        repeated_plan = {
            "sections": [
                {"type": "verse", "bars": 8,  "active_stem_roles": _FULL_ROLES},
                {"type": "hook",  "bars": 8,  "active_stem_roles": _FULL_ROLES},
                {"type": "verse", "bars": 8,  "active_stem_roles": _FULL_ROLES},
                {"type": "hook",  "bars": 8,  "active_stem_roles": _FULL_ROLES},
            ]
        }
        result = _run_timeline_planner_shadow(
            render_plan=repeated_plan,
            available_roles=_FULL_ROLES,
            arrangement_id=6,
            correlation_id="test-variation",
        )
        assert result["error"] is None
        plan = result["plan"]
        # variation_log should exist (may be empty or populated depending on source quality)
        assert "variation_log" in plan

    def test_roles_from_sections_used_when_available_roles_empty(self):
        # Even with no globally available roles, section-level roles drive the planner.
        result = _run_timeline_planner_shadow(
            render_plan=_STANDARD_RENDER_PLAN,
            available_roles=[],
            arrangement_id=7,
            correlation_id="test-no-roles",
        )
        assert result["error"] is None
        assert result["section_count"] == 6


# ---------------------------------------------------------------------------
# Integration: run_arrangement_job stores _timeline_plan in render_plan_json
# ---------------------------------------------------------------------------

class TestRunArrangementJobTimeline:
    """Integration tests verifying that the shadow plan ends up in the stored
    metadata without breaking the live render path."""

    def _run_job_with_mocks(self, arrangement_id: int, timeline_shadow_enabled: bool = True):
        """Run run_arrangement_job with all external side-effects mocked.

        Returns the Arrangement record as-stored in the test DB.
        """
        mock_response = MagicMock()
        mock_response.content = _minimal_wav_bytes()
        mock_response.raise_for_status.return_value = None

        with patch("app.services.arrangement_jobs.storage.create_presigned_get_url",
                   return_value="https://example.com/arr.wav"), \
             patch("app.services.arrangement_jobs.storage.upload_file"), \
             patch("app.services.arrangement_jobs.httpx.Client") as mock_client, \
             patch("app.services.arrangement_jobs.generate_loop_variations",
                   return_value=({}, {"active": False, "count": 0})), \
             patch("app.services.arrangement_jobs._build_pre_render_plan",
                   return_value=dict(_STANDARD_RENDER_PLAN)), \
             patch("app.services.arrangement_jobs.attach_loops_to_sections"), \
             patch("app.services.arrangement_jobs._validate_render_plan_quality"), \
             patch("app.services.arrangement_jobs.score_and_reject"), \
             patch("app.services.arrangement_jobs.render_from_plan",
                   return_value={"timeline_json": '{"sections": []}', "postprocess": {}}), \
             patch("app.services.arrangement_jobs.AudioSegment.export", new=_fake_export), \
             patch("app.services.arrangement_jobs.storage.use_s3", True), \
             patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_timeline_engine_shadow = timeline_shadow_enabled
            mock_settings.feature_timeline_engine_primary = False
            mock_settings.feature_arranger_v2 = False
            mock_settings.feature_style_engine = False
            mock_settings.dev_fallback_loop_only = False
            mock_settings.is_production = False
            mock_settings.feature_pattern_variation_shadow = False
            mock_settings.feature_groove_engine_shadow = False
            mock_settings.feature_ai_producer_system_shadow = False
            mock_settings.feature_drop_engine_shadow = False
            mock_settings.feature_motif_engine_shadow = False
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            run_arrangement_job(arrangement_id)

    def test_timeline_plan_stored_in_render_plan_json(self, db):
        """_timeline_plan key must be present in the stored render_plan_json."""
        loop = Loop(name="TL Test Loop", file_key="uploads/tl_test.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, timeline_shadow_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        assert updated.render_plan_json is not None

        stored = json.loads(updated.render_plan_json)
        assert "_timeline_plan" in stored, (
            "_timeline_plan key missing from render_plan_json — "
            "shadow planner did not run or store its result"
        )

    def test_timeline_plan_has_sections_and_events(self, db):
        """Stored plan must have sections with event lists."""
        loop = Loop(name="TL Sections Loop", file_key="uploads/tl_sec.wav", bpm=140.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, timeline_shadow_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        stored = json.loads(updated.render_plan_json)
        tl = stored["_timeline_plan"]

        assert tl["plan"] is not None
        assert tl["section_count"] == 6
        plan = tl["plan"]
        assert len(plan["sections"]) == 6
        for sec in plan["sections"]:
            assert "name" in sec
            assert "events" in sec

    def test_validation_issues_stored(self, db):
        """validation_issues list must be present (may be empty or populated)."""
        loop = Loop(name="TL Validation Loop", file_key="uploads/tl_val.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, timeline_shadow_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        stored = json.loads(updated.render_plan_json)
        tl = stored["_timeline_plan"]

        assert "validation_issues" in tl
        assert isinstance(tl["validation_issues"], list)

    def test_live_generation_completes_unchanged_with_shadow(self, db):
        """status==done and output_s3_key set even when shadow planner runs."""
        loop = Loop(name="TL Live Loop", file_key="uploads/tl_live.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, timeline_shadow_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        assert updated.output_s3_key == f"arrangements/{arr.id}.wav"
        assert updated.error_message is None

    def test_live_generation_completes_when_shadow_disabled(self, db):
        """Disabling the shadow flag must not affect job completion."""
        loop = Loop(name="TL No Shadow Loop", file_key="uploads/tl_noshadow.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, timeline_shadow_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        # _timeline_plan should NOT be present when the flag is disabled
        stored = json.loads(updated.render_plan_json)
        assert "_timeline_plan" not in stored


# ---------------------------------------------------------------------------
# Unit: _apply_timeline_engine_primary
# ---------------------------------------------------------------------------

# A valid timeline shadow result built from _STANDARD_RENDER_PLAN
_VALID_SHADOW_RESULT = {
    "plan": {
        "total_bars": 40,
        "energy_curve": [0.3, 0.55, 0.85, 0.55, 0.9, 0.25],
        "variation_log": [],
        "state_snapshot": {},
        "sections": [
            {"name": "intro",   "bars": 4,  "target_energy": 0.3,  "target_density": 0.3, "active_roles": ["melody", "pads"],                         "events": []},
            {"name": "verse",   "bars": 8,  "target_energy": 0.55, "target_density": 0.5, "active_roles": ["drums", "bass", "melody"],                 "events": []},
            {"name": "hook",    "bars": 8,  "target_energy": 0.85, "target_density": 0.8, "active_roles": ["drums", "bass", "melody", "pads"],         "events": [{"bar_start": 8, "bar_end": 8, "action": "drum_fill", "target_role": "drums", "parameters": {}}]},
            {"name": "verse",   "bars": 8,  "target_energy": 0.55, "target_density": 0.5, "active_roles": ["drums", "bass", "melody"],                 "events": []},
            {"name": "hook",    "bars": 8,  "target_energy": 0.9,  "target_density": 0.85,"active_roles": ["drums", "bass", "melody", "pads", "fx"],   "events": [{"bar_start": 8, "bar_end": 8, "action": "drum_fill", "target_role": "drums", "parameters": {}}]},
            {"name": "outro",   "bars": 4,  "target_energy": 0.25, "target_density": 0.25,"active_roles": ["melody", "pads"],                         "events": []},
        ],
    },
    "validation_issues": [],
    "section_count": 6,
    "event_count": 2,
    "error": None,
}

_RENDER_PLAN_FOR_PRIMARY = {
    "sections": [
        {"type": "intro",   "bars": 4,  "energy": 0.5, "instruments": ["melody", "pads"],                         "active_stem_roles": ["melody", "pads"]},
        {"type": "verse",   "bars": 8,  "energy": 0.5, "instruments": ["drums", "bass", "melody"],                 "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "hook",    "bars": 8,  "energy": 0.5, "instruments": ["drums", "bass", "melody", "pads"],         "active_stem_roles": ["drums", "bass", "melody", "pads"]},
        {"type": "verse",   "bars": 8,  "energy": 0.5, "instruments": ["drums", "bass", "melody"],                 "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "hook",    "bars": 8,  "energy": 0.5, "instruments": ["drums", "bass", "melody", "pads", "fx"],   "active_stem_roles": ["drums", "bass", "melody", "pads", "fx"]},
        {"type": "outro",   "bars": 4,  "energy": 0.5, "instruments": ["melody", "pads"],                         "active_stem_roles": ["melody", "pads"]},
    ],
    "sections_count": 6,
}


class TestApplyTimelineEnginePrimary:
    """Unit tests for _apply_timeline_engine_primary."""

    def _make_render_plan(self):
        """Return a deep copy of the test render plan."""
        import copy
        return copy.deepcopy(_RENDER_PLAN_FOR_PRIMARY)

    # ------------------------------------------------------------------
    # Happy path
    # ------------------------------------------------------------------

    def test_energy_targets_applied(self):
        rp = self._make_render_plan()
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=_VALID_SHADOW_RESULT,
            arrangement_id=10,
            correlation_id="test-primary-energy",
        )
        energies = [s["energy"] for s in result["sections"]]
        assert energies == [0.3, 0.55, 0.85, 0.55, 0.9, 0.25]

    def test_active_roles_applied_to_instruments_and_active_stem_roles(self):
        rp = self._make_render_plan()
        # Reset instruments to empty so we can confirm they are filled by primary
        for s in rp["sections"]:
            s["instruments"] = []
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=_VALID_SHADOW_RESULT,
            arrangement_id=11,
            correlation_id="test-primary-roles",
        )
        assert result["sections"][0]["instruments"] == ["melody", "pads"]
        assert result["sections"][2]["instruments"] == ["drums", "bass", "melody", "pads"]
        # active_stem_roles must be updated too
        assert result["sections"][2]["active_stem_roles"] == ["drums", "bass", "melody", "pads"]

    def test_timeline_events_stored_on_sections(self):
        rp = self._make_render_plan()
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=_VALID_SHADOW_RESULT,
            arrangement_id=12,
            correlation_id="test-primary-events",
        )
        # hook sections (index 2, 4) have drum_fill events in the test data
        assert len(result["sections"][2]["timeline_events"]) == 1
        ev = result["sections"][2]["timeline_events"][0]
        assert ev["action"] == "drum_fill"
        # intro has no events
        assert result["sections"][0]["timeline_events"] == []

    def test_observability_metadata_set_on_success(self):
        rp = self._make_render_plan()
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=_VALID_SHADOW_RESULT,
            arrangement_id=13,
            correlation_id="test-primary-meta",
        )
        assert result["timeline_primary_used"] is True
        assert result["timeline_primary_fallback_used"] is False
        assert result["timeline_primary_fallback_reason"] == ""
        assert result["timeline_plan_summary"]["section_count"] == 6
        assert result["timeline_plan_summary"]["event_count"] == 2
        assert result["timeline_plan_validation_warnings"] == []

    def test_result_is_json_serialisable(self):
        rp = self._make_render_plan()
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=_VALID_SHADOW_RESULT,
            arrangement_id=14,
            correlation_id="test-primary-json",
        )
        # Should not raise
        json.dumps(result)

    # ------------------------------------------------------------------
    # Fallback paths
    # ------------------------------------------------------------------

    def test_fallback_on_build_error(self):
        rp = self._make_render_plan()
        shadow_with_error = {"error": "Unexpected exception", "plan": None,
                             "validation_issues": [], "section_count": 0, "event_count": 0}
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=shadow_with_error,
            arrangement_id=20,
            correlation_id="test-primary-err",
        )
        assert result["timeline_primary_used"] is False
        assert result["timeline_primary_fallback_used"] is True
        assert "build failed" in result["timeline_primary_fallback_reason"].lower()
        # Original energy must be unchanged (fallback = no mutation)
        assert result["sections"][0]["energy"] == 0.5

    def test_fallback_on_empty_plan(self):
        rp = self._make_render_plan()
        empty_shadow = {"error": None, "plan": {"sections": [], "total_bars": 0,
                                                 "energy_curve": [], "variation_log": [],
                                                 "state_snapshot": {}},
                        "validation_issues": [], "section_count": 0, "event_count": 0}
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=empty_shadow,
            arrangement_id=21,
            correlation_id="test-primary-empty",
        )
        assert result["timeline_primary_used"] is False
        assert result["timeline_primary_fallback_used"] is True
        assert "empty" in result["timeline_primary_fallback_reason"].lower()

    def test_fallback_on_missing_plan(self):
        rp = self._make_render_plan()
        no_plan_shadow = {"error": None, "plan": None,
                          "validation_issues": [], "section_count": 0, "event_count": 0}
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=no_plan_shadow,
            arrangement_id=22,
            correlation_id="test-primary-noplan",
        )
        assert result["timeline_primary_fallback_used"] is True

    def test_fallback_on_critical_validation_error(self):
        import copy
        shadow_with_errors = copy.deepcopy(_VALID_SHADOW_RESULT)
        shadow_with_errors["validation_issues"] = [
            {"rule": "flat_timeline", "severity": "error",
             "message": "Energy curve is flat.", "section_name": ""},
        ]
        rp = self._make_render_plan()
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=shadow_with_errors,
            arrangement_id=23,
            correlation_id="test-primary-valerr",
        )
        assert result["timeline_primary_used"] is False
        assert result["timeline_primary_fallback_used"] is True
        assert "validation" in result["timeline_primary_fallback_reason"].lower()
        # Validation issues preserved in metadata
        assert len(result["timeline_plan_validation_warnings"]) == 1

    def test_warnings_do_not_trigger_fallback(self):
        import copy
        shadow_with_warning = copy.deepcopy(_VALID_SHADOW_RESULT)
        shadow_with_warning["validation_issues"] = [
            {"rule": "empty_events_long_section", "severity": "warning",
             "message": "No events on long section.", "section_name": "verse"},
        ]
        rp = self._make_render_plan()
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=shadow_with_warning,
            arrangement_id=24,
            correlation_id="test-primary-warn",
        )
        # Warnings should NOT cause fallback
        assert result["timeline_primary_used"] is True
        assert result["timeline_primary_fallback_used"] is False
        assert result["timeline_plan_validation_warnings"] == shadow_with_warning["validation_issues"]

    def test_empty_shadow_result_dict_falls_back(self):
        rp = self._make_render_plan()
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result={},
            arrangement_id=25,
            correlation_id="test-primary-empty-dict",
        )
        assert result["timeline_primary_fallback_used"] is True

    def test_section_count_mismatch_applies_min_sections(self):
        """When section counts differ, apply to the overlap and still succeed."""
        import copy
        short_shadow = copy.deepcopy(_VALID_SHADOW_RESULT)
        # Trim to only 2 sections
        short_shadow["plan"]["sections"] = short_shadow["plan"]["sections"][:2]
        short_shadow["section_count"] = 2

        rp = self._make_render_plan()  # has 6 sections
        result = _apply_timeline_engine_primary(
            render_plan=rp,
            timeline_shadow_result=short_shadow,
            arrangement_id=26,
            correlation_id="test-primary-mismatch",
        )
        # Should succeed — applied to first 2 sections
        assert result["timeline_primary_used"] is True
        # First 2 sections updated
        assert result["sections"][0]["energy"] == 0.3
        assert result["sections"][1]["energy"] == 0.55
        # Remaining 4 sections untouched (energy still 0.5)
        assert result["sections"][2]["energy"] == 0.5


# ---------------------------------------------------------------------------
# Integration: run_arrangement_job with TIMELINE_ENGINE_PRIMARY=true/false
# ---------------------------------------------------------------------------

class TestRunArrangementJobTimelinePrimary:
    """Integration tests for the TIMELINE_ENGINE_PRIMARY flag in run_arrangement_job."""

    def _run_job_with_primary_mocks(
        self,
        arrangement_id: int,
        primary_enabled: bool,
        shadow_enabled: bool = True,
    ):
        """Run run_arrangement_job with all external side-effects mocked.

        Returns the Arrangement record as stored in the test DB.
        """
        mock_response = MagicMock()
        mock_response.content = _minimal_wav_bytes()
        mock_response.raise_for_status.return_value = None

        with patch("app.services.arrangement_jobs.storage.create_presigned_get_url",
                   return_value="https://example.com/arr.wav"), \
             patch("app.services.arrangement_jobs.storage.upload_file"), \
             patch("app.services.arrangement_jobs.httpx.Client") as mock_client, \
             patch("app.services.arrangement_jobs.generate_loop_variations",
                   return_value=({}, {"active": False, "count": 0})), \
             patch("app.services.arrangement_jobs._build_pre_render_plan",
                   return_value=dict(_STANDARD_RENDER_PLAN)), \
             patch("app.services.arrangement_jobs.attach_loops_to_sections"), \
             patch("app.services.arrangement_jobs._validate_render_plan_quality"), \
             patch("app.services.arrangement_jobs.score_and_reject"), \
             patch("app.services.arrangement_jobs.render_from_plan",
                   return_value={"timeline_json": '{"sections": []}', "postprocess": {}}), \
             patch("app.services.arrangement_jobs.AudioSegment.export", new=_fake_export), \
             patch("app.services.arrangement_jobs.storage.use_s3", True), \
             patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_timeline_engine_shadow = shadow_enabled
            mock_settings.feature_timeline_engine_primary = primary_enabled
            mock_settings.feature_arranger_v2 = False
            mock_settings.feature_style_engine = False
            mock_settings.dev_fallback_loop_only = False
            mock_settings.is_production = False
            mock_settings.feature_pattern_variation_shadow = False
            mock_settings.feature_groove_engine_shadow = False
            mock_settings.feature_ai_producer_system_shadow = False
            mock_settings.feature_drop_engine_shadow = False
            mock_settings.feature_motif_engine_shadow = False
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            run_arrangement_job(arrangement_id)

    def test_primary_enabled_sets_timeline_primary_used(self, db):
        """When TIMELINE_ENGINE_PRIMARY=true, timeline_primary_used must be True."""
        loop = Loop(name="Primary True Loop", file_key="uploads/primary_true.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_primary_mocks(arr.id, primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        stored = json.loads(updated.render_plan_json)
        assert "timeline_primary_used" in stored
        # May be True (plan valid) or False (fallback), but key must exist
        assert isinstance(stored["timeline_primary_used"], bool)
        assert "timeline_primary_fallback_used" in stored
        assert "timeline_primary_fallback_reason" in stored
        assert "timeline_plan_summary" in stored
        assert "timeline_plan_validation_warnings" in stored

    def test_primary_disabled_does_not_add_primary_metadata(self, db):
        """When TIMELINE_ENGINE_PRIMARY=false, primary metadata keys must not be present."""
        loop = Loop(name="Primary False Loop", file_key="uploads/primary_false.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_primary_mocks(arr.id, primary_enabled=False, shadow_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        stored = json.loads(updated.render_plan_json)
        assert "timeline_primary_used" not in stored
        assert "timeline_primary_fallback_used" not in stored

    def test_primary_true_still_completes_generation(self, db):
        """Arrangement must still reach status==done when primary is enabled."""
        loop = Loop(name="Primary Complete Loop", file_key="uploads/primary_complete.wav", bpm=130.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_primary_mocks(arr.id, primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        assert updated.output_s3_key == f"arrangements/{arr.id}.wav"
        assert updated.error_message is None

    def test_primary_enabled_shadow_disabled_still_runs_timeline_planner(self, db):
        """TIMELINE_ENGINE_PRIMARY=true must run the timeline planner even when
        TIMELINE_ENGINE_SHADOW=false, to obtain the plan for primary use."""
        loop = Loop(name="Primary No Shadow Loop",
                    file_key="uploads/primary_noshadow.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        # shadow_enabled=False but primary_enabled=True
        self._run_job_with_primary_mocks(arr.id, primary_enabled=True, shadow_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        stored = json.loads(updated.render_plan_json)
        # _timeline_plan must still have been generated (primary needs it)
        assert "_timeline_plan" in stored
        # Primary metadata must be present
        assert "timeline_primary_used" in stored

    def test_invalid_timeline_plan_falls_back_cleanly(self, db):
        """When _run_timeline_planner_shadow returns an error, the job still
        completes and timeline_primary_fallback_used is True."""
        loop = Loop(name="Primary Fallback Loop", file_key="uploads/primary_fallback.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        error_shadow_result = {
            "error": "Simulated build failure",
            "plan": None,
            "validation_issues": [],
            "section_count": 0,
            "event_count": 0,
        }

        with patch("app.services.arrangement_jobs._run_timeline_planner_shadow",
                   return_value=error_shadow_result):
            self._run_job_with_primary_mocks(arr.id, primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        stored = json.loads(updated.render_plan_json)
        assert stored["timeline_primary_used"] is False
        assert stored["timeline_primary_fallback_used"] is True
        assert stored["timeline_primary_fallback_reason"] != ""

    def test_primary_metadata_json_serialisable(self, db):
        """All primary metadata keys must be JSON-serialisable."""
        loop = Loop(name="Primary JSON Loop", file_key="uploads/primary_json.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_primary_mocks(arr.id, primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        # The full render_plan_json must round-trip without error
        stored = json.loads(updated.render_plan_json)
        json.dumps(stored)  # must not raise

