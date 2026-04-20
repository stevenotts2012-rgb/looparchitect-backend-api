"""
Tests for the timeline engine shadow planner integration in arrangement_jobs.

Covers:
- TimelinePlan is generated during arrangement jobs
- Validation warnings are captured and stored
- Serialised plan is stored in render_plan_json metadata
- Live generation still completes unchanged when the shadow planner runs
"""

import json
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from app.db import SessionLocal
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.arrangement_jobs import (
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
            mock_settings.feature_arranger_v2 = False
            mock_settings.feature_style_engine = False
            mock_settings.dev_fallback_loop_only = False
            mock_settings.is_production = False
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
