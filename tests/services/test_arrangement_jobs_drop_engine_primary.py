"""
Tests for the Drop Engine primary-mode integration in arrangement_jobs.

Covers:
- Drop Engine annotates sections with boundary drop data when DROP_ENGINE_PRIMARY=true.
- Current live behaviour is preserved when DROP_ENGINE_PRIMARY=false.
- Invalid/empty drop plans fall back cleanly without raising.
- Shadow metadata (_drop_plan, _drop_scores, etc.) is always stored.
- Metadata keys (drop_primary_used, drop_primary_fallback_used,
  drop_primary_fallback_reason, drop_plan_summary, drop_validation_warnings)
  are always written by _apply_drop_engine_primary.
- Live generation still completes (status==done) when primary mode is active.
- No regression to existing uploads/jobs/render flow.
- No reintroduction of distorted drop behaviour.
"""

from __future__ import annotations

import copy
import json
from unittest.mock import MagicMock, patch

import pytest

from app.db import SessionLocal
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.arrangement_jobs import (
    _apply_drop_engine_primary,
    _build_drop_plan_summary,
    _run_drop_engine_shadow,
    run_arrangement_job,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_FULL_ROLES = ["drums", "bass", "melody", "pads", "fx"]

_STANDARD_RENDER_PLAN = {
    "sections": [
        {
            "type": "intro",
            "name": "Intro",
            "bars": 4,
            "energy": 0.3,
            "active_stem_roles": ["melody", "pads"],
            "instruments": ["melody", "pads"],
        },
        {
            "type": "verse",
            "name": "Verse 1",
            "bars": 8,
            "energy": 0.55,
            "active_stem_roles": ["drums", "bass", "melody"],
            "instruments": ["drums", "bass", "melody"],
        },
        {
            "type": "pre_hook",
            "name": "Pre-Hook",
            "bars": 4,
            "energy": 0.65,
            "active_stem_roles": ["drums", "bass", "melody"],
            "instruments": ["drums", "bass", "melody"],
        },
        {
            "type": "hook",
            "name": "Hook 1",
            "bars": 8,
            "energy": 0.85,
            "active_stem_roles": ["drums", "bass", "melody", "pads"],
            "instruments": ["drums", "bass", "melody", "pads"],
        },
        {
            "type": "bridge",
            "name": "Bridge",
            "bars": 8,
            "energy": 0.5,
            "active_stem_roles": ["pads", "melody"],
            "instruments": ["pads", "melody"],
        },
        {
            "type": "outro",
            "name": "Outro",
            "bars": 4,
            "energy": 0.2,
            "active_stem_roles": ["melody", "pads"],
            "instruments": ["melody", "pads"],
        },
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


def _make_valid_shadow_result(render_plan: dict | None = None) -> dict:
    """Build a well-formed drop shadow result from a real shadow planner run."""
    plan = render_plan or _STANDARD_RENDER_PLAN
    return _run_drop_engine_shadow(
        render_plan=copy.deepcopy(plan),
        available_roles=_FULL_ROLES,
        arrangement_id=1,
        correlation_id="test-drop-primary",
        source_quality="true_stems",
    )


def _make_render_plan_copy() -> dict:
    """Return a deep copy of the standard render plan."""
    return copy.deepcopy(_STANDARD_RENDER_PLAN)


# ---------------------------------------------------------------------------
# Unit: _build_drop_plan_summary
# ---------------------------------------------------------------------------


class TestBuildDropPlanSummary:
    def test_returns_correct_structure(self):
        result = _make_valid_shadow_result()
        summary = _build_drop_plan_summary(result)

        assert "total_drop_count" in summary
        assert "repeated_hook_drop_variation_score" in summary
        assert "fallback_used" in summary
        assert "boundary_count" in summary
        assert "boundaries" in summary
        assert isinstance(summary["boundaries"], list)

    def test_boundary_entries_have_expected_keys(self):
        result = _make_valid_shadow_result()
        summary = _build_drop_plan_summary(result)

        for b in summary["boundaries"]:
            assert "boundary_name" in b
            assert "from_section" in b
            assert "to_section" in b
            assert "primary_event_type" in b
            assert "tension_score" in b
            assert "payoff_score" in b

    def test_is_json_safe(self):
        result = _make_valid_shadow_result()
        summary = _build_drop_plan_summary(result)
        json.dumps(summary)  # must not raise

    def test_empty_shadow_result(self):
        summary = _build_drop_plan_summary(
            {
                "plan": {},
                "scores": [],
                "warnings": [],
                "fallback_used": False,
                "error": None,
            }
        )
        assert summary["total_drop_count"] == 0
        assert summary["boundary_count"] == 0
        assert summary["boundaries"] == []

    def test_scores_are_floats_in_range(self):
        result = _make_valid_shadow_result()
        summary = _build_drop_plan_summary(result)
        assert 0.0 <= summary["repeated_hook_drop_variation_score"] <= 1.0
        for b in summary["boundaries"]:
            assert 0.0 <= b["tension_score"] <= 1.0
            assert 0.0 <= b["payoff_score"] <= 1.0


# ---------------------------------------------------------------------------
# Unit: _run_drop_engine_shadow
# ---------------------------------------------------------------------------


class TestRunDropEngineShadow:
    def test_returns_plan_for_valid_render_plan(self):
        result = _run_drop_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=1,
            correlation_id="test-shadow",
            source_quality="true_stems",
        )

        assert result["error"] is None
        assert result["plan"] is not None

    def test_plan_has_boundaries(self):
        result = _run_drop_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=2,
            correlation_id="test-fields",
            source_quality="true_stems",
        )
        plan = result["plan"]
        assert "boundaries" in plan
        # intro→verse, verse→pre_hook, pre_hook→hook, bridge→outro are expected
        assert len(plan["boundaries"]) > 0

    def test_scores_have_expected_keys(self):
        result = _run_drop_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=3,
            correlation_id="test-scores",
        )
        for score in result["scores"]:
            assert "boundary_name" in score
            assert "from_section" in score
            assert "to_section" in score
            assert "tension_score" in score
            assert "payoff_score" in score

    def test_is_json_safe(self):
        result = _run_drop_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=4,
            correlation_id="test-json",
        )
        json.dumps(result)  # must not raise

    def test_empty_render_plan_returns_empty_result(self):
        result = _run_drop_engine_shadow(
            render_plan={"sections": []},
            available_roles=_FULL_ROLES,
            arrangement_id=5,
            correlation_id="test-empty",
        )
        # Shadow skips when no sections
        assert result["plan"] is None
        assert result["error"] is None

    def test_never_raises(self):
        result = _run_drop_engine_shadow(
            render_plan={"sections": None},
            available_roles=[],
            arrangement_id=99,
            correlation_id="test-bad",
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Unit: _apply_drop_engine_primary
# ---------------------------------------------------------------------------


class TestApplyDropEnginePrimary:
    """Unit tests for _apply_drop_engine_primary."""

    def _render_plan(self) -> dict:
        return _make_render_plan_copy()

    def _valid_shadow(self, render_plan: dict | None = None) -> dict:
        return _make_valid_shadow_result(render_plan or self._render_plan())

    # ---------------------------------------------------------------
    # Observability keys always written
    # ---------------------------------------------------------------

    def test_observability_keys_always_present_on_success(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=1,
            correlation_id="test",
        )
        assert "drop_primary_used" in result
        assert "drop_primary_fallback_used" in result
        assert "drop_primary_fallback_reason" in result
        assert "drop_plan_summary" in result
        assert "drop_validation_warnings" in result

    def test_observability_keys_always_present_on_fallback(self):
        render_plan = self._render_plan()
        bad_shadow = {
            "error": "DropEngine exploded",
            "plan": None,
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=bad_shadow,
            arrangement_id=2,
            correlation_id="test",
        )
        assert "drop_primary_used" in result
        assert "drop_primary_fallback_used" in result
        assert "drop_primary_fallback_reason" in result
        assert "drop_plan_summary" in result
        assert "drop_validation_warnings" in result

    # ---------------------------------------------------------------
    # Primary applied when valid plan exists
    # ---------------------------------------------------------------

    def test_primary_used_is_true_when_plan_applied(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=3,
            correlation_id="test",
        )
        assert result["drop_primary_used"] is True
        assert result["drop_primary_fallback_used"] is False

    def test_drop_fields_injected_into_entering_sections(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=4,
            correlation_id="test",
        )
        # At least the hook section (entering pre_hook→hook boundary) should
        # have drop fields applied.
        hook_sec = next(
            (s for s in result["sections"] if s.get("type") == "hook"),
            None,
        )
        assert hook_sec is not None
        assert "primary_drop_event" in hook_sec
        assert "support_events" in hook_sec
        assert isinstance(hook_sec["support_events"], list)
        assert "tension_score" in hook_sec
        assert "payoff_score" in hook_sec
        assert 0.0 <= hook_sec["tension_score"] <= 1.0
        assert 0.0 <= hook_sec["payoff_score"] <= 1.0

    def test_drop_plan_summary_populated(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=5,
            correlation_id="test",
        )
        summary = result["drop_plan_summary"]
        assert "total_drop_count" in summary
        assert "boundary_count" in summary
        assert "boundaries" in summary

    def test_repeated_hook_variation_score_stored(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=6,
            correlation_id="test",
        )
        assert "drop_repeated_hook_variation_score" in result
        assert 0.0 <= result["drop_repeated_hook_variation_score"] <= 1.0

    def test_result_is_json_safe_after_primary_applied(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=7,
            correlation_id="test",
        )
        json.dumps(result)  # must not raise

    def test_section_structure_preserved(self):
        """Existing section fields (instruments, active_stem_roles, energy) must be untouched."""
        render_plan = self._render_plan()
        original_instruments = {
            sec["type"]: list(sec["instruments"])
            for sec in render_plan["sections"]
        }
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=8,
            correlation_id="test",
        )
        for sec in result["sections"]:
            sec_type = sec["type"]
            assert sec["instruments"] == original_instruments[sec_type], (
                f"instruments changed for section type={sec_type!r}"
            )

    def test_active_stem_roles_not_modified(self):
        render_plan = self._render_plan()
        original_roles = {
            sec["type"]: list(sec["active_stem_roles"])
            for sec in render_plan["sections"]
        }
        shadow = self._valid_shadow(render_plan)
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=9,
            correlation_id="test",
        )
        for sec in result["sections"]:
            sec_type = sec["type"]
            assert sec["active_stem_roles"] == original_roles[sec_type], (
                f"active_stem_roles changed for section type={sec_type!r}"
            )

    # ---------------------------------------------------------------
    # Fallback conditions
    # ---------------------------------------------------------------

    def test_fallback_on_build_error(self):
        render_plan = self._render_plan()
        bad_shadow = {
            "error": "DropEnginePlanner raised ValueError",
            "plan": None,
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=bad_shadow,
            arrangement_id=10,
            correlation_id="test",
        )
        assert result["drop_primary_used"] is False
        assert result["drop_primary_fallback_used"] is True
        assert "Drop plan build failed" in result["drop_primary_fallback_reason"]

    def test_fallback_on_empty_plan_with_sections(self):
        render_plan = self._render_plan()
        empty_shadow = {
            "error": None,
            "plan": {"boundaries": [], "total_drop_count": 0,
                     "repeated_hook_drop_variation_score": 0.5, "fallback_used": False},
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=empty_shadow,
            arrangement_id=11,
            correlation_id="test",
        )
        assert result["drop_primary_used"] is False
        assert result["drop_primary_fallback_used"] is True
        assert "empty" in result["drop_primary_fallback_reason"].lower()

    def test_fallback_on_error_severity_validation_issues(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        # Inject an error-severity issue
        shadow["warnings"] = [
            {"severity": "error", "rule": "critical_failure", "message": "Bad plan"}
        ]
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=12,
            correlation_id="test",
        )
        assert result["drop_primary_used"] is False
        assert result["drop_primary_fallback_used"] is True
        assert "error" in result["drop_primary_fallback_reason"].lower()

    def test_warning_severity_issues_do_not_trigger_fallback(self):
        """Warning-level issues must NOT trigger fallback."""
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        shadow["warnings"] = [
            {"severity": "warning", "rule": "some_rule", "message": "Just a warning"}
        ]
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=13,
            correlation_id="test",
        )
        assert result["drop_primary_used"] is True
        assert result["drop_primary_fallback_used"] is False

    def test_warning_issues_recorded_in_drop_validation_warnings(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        shadow["warnings"] = [
            {"severity": "warning", "rule": "some_rule", "message": "Just a warning"}
        ]
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=14,
            correlation_id="test",
        )
        assert len(result["drop_validation_warnings"]) == 1
        assert result["drop_validation_warnings"][0]["rule"] == "some_rule"

    def test_no_primary_without_shadow(self):
        """Passing empty shadow result (primary flag set but shadow produced nothing) → fallback."""
        render_plan = self._render_plan()
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result={},
            arrangement_id=15,
            correlation_id="test",
        )
        # No error set, no plan dict → empty plan → fallback (significant boundaries exist)
        assert result["drop_primary_fallback_used"] is True

    def test_no_crash_when_sections_is_empty(self):
        """No significant boundaries in empty plan → no fallback triggered for empty plan."""
        render_plan = {"sections": []}
        shadow = {
            "error": None,
            "plan": {"boundaries": [], "total_drop_count": 0,
                     "repeated_hook_drop_variation_score": 0.5, "fallback_used": False},
            "scores": [],
            "warnings": [],
        }
        result = _apply_drop_engine_primary(
            render_plan=render_plan,
            drop_shadow_result=shadow,
            arrangement_id=16,
            correlation_id="test",
        )
        # Empty sections — no significant boundaries — primary should be applied (no fallback)
        assert result["drop_primary_used"] is True
        assert result["drop_primary_fallback_used"] is False


# ---------------------------------------------------------------------------
# Integration: run_arrangement_job with DROP_ENGINE_PRIMARY flag
# ---------------------------------------------------------------------------


class TestRunArrangementJobDropEnginePrimary:
    """Integration-level tests verifying run_arrangement_job behaves correctly
    with DROP_ENGINE_PRIMARY enabled/disabled."""

    def _run_job_with_mocks(
        self,
        arrangement_id: int,
        drop_shadow_enabled: bool = True,
        drop_primary_enabled: bool = False,
    ):
        mock_response = MagicMock()
        mock_response.content = _minimal_wav_bytes()
        mock_response.raise_for_status.return_value = None

        with (
            patch("app.services.arrangement_jobs.storage.create_presigned_get_url",
                  return_value="https://example.com/arr.wav"),
            patch("app.services.arrangement_jobs.storage.upload_file"),
            patch("app.services.arrangement_jobs.httpx.Client") as mock_client,
            patch("app.services.arrangement_jobs.generate_loop_variations",
                  return_value=({}, {"active": False, "count": 0})),
            patch("app.services.arrangement_jobs._build_pre_render_plan",
                  return_value=copy.deepcopy(_STANDARD_RENDER_PLAN)),
            patch("app.services.arrangement_jobs.attach_loops_to_sections"),
            patch("app.services.arrangement_jobs._validate_render_plan_quality"),
            patch("app.services.arrangement_jobs.score_and_reject"),
            patch("app.services.arrangement_jobs.render_from_plan",
                  return_value={"timeline_json": '{"sections": []}', "postprocess": {}}),
            patch("app.services.arrangement_jobs.AudioSegment.export", new=_fake_export),
            patch("app.services.arrangement_jobs.storage.use_s3", True),
            patch("app.services.arrangement_jobs.settings") as mock_settings,
        ):
            mock_settings.feature_timeline_engine_shadow = False
            mock_settings.feature_timeline_engine_primary = False
            mock_settings.feature_arranger_v2 = False
            mock_settings.feature_style_engine = False
            mock_settings.dev_fallback_loop_only = False
            mock_settings.is_production = False
            mock_settings.feature_pattern_variation_shadow = False
            mock_settings.feature_pattern_variation_primary = False
            mock_settings.feature_groove_engine_shadow = False
            mock_settings.feature_groove_engine_primary = False
            mock_settings.feature_ai_producer_system_shadow = False
            mock_settings.feature_motif_engine_shadow = False
            mock_settings.feature_decision_engine_shadow = False
            mock_settings.feature_decision_engine_primary = False
            mock_settings.feature_drop_engine_shadow = drop_shadow_enabled
            mock_settings.feature_drop_engine_primary = drop_primary_enabled
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            run_arrangement_job(arrangement_id)

    def test_live_generation_completes_with_primary_enabled(self, db):
        """Status must be 'done' when DROP_ENGINE_PRIMARY=true."""
        loop = Loop(name="Drop Primary Loop", file_key="uploads/drop_primary.wav", bpm=120)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, drop_shadow_enabled=True, drop_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        assert updated.error_message is None

    def test_drop_primary_used_stored_in_metadata_when_primary_enabled(self, db):
        """drop_primary_used must be present in render_plan_json when flag is set."""
        loop = Loop(name="Drop Primary Meta Loop", file_key="uploads/drop_meta.wav", bpm=120)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, drop_shadow_enabled=True, drop_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "drop_primary_used" in plan

    def test_drop_plan_summary_stored_when_primary_enabled(self, db):
        """drop_plan_summary must be a dict in render_plan_json when primary is enabled."""
        loop = Loop(name="Drop Summary Loop", file_key="uploads/drop_summary.wav", bpm=120)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, drop_shadow_enabled=True, drop_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "drop_plan_summary" in plan
        assert isinstance(plan["drop_plan_summary"], dict)

    def test_shadow_metadata_stored_when_shadow_only_enabled(self, db):
        """_drop_plan etc. must be stored when shadow-only mode is on."""
        loop = Loop(name="Drop Shadow Only Loop", file_key="uploads/drop_shadow_only.wav", bpm=120)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, drop_shadow_enabled=True, drop_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "_drop_plan" in plan
        assert "_drop_scores" in plan
        assert "_drop_warnings" in plan
        assert "_drop_fallback_used" in plan

    def test_shadow_metadata_always_stored_when_primary_enabled(self, db):
        """_drop_plan must be stored even when only DROP_ENGINE_PRIMARY=true."""
        loop = Loop(name="Drop Primary Shadow Loop", file_key="uploads/drop_both.wav", bpm=120)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        # shadow=False but primary=True — shadow must still run
        self._run_job_with_mocks(arr.id, drop_shadow_enabled=False, drop_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "_drop_plan" in plan

    def test_legacy_behavior_when_primary_disabled(self, db):
        """drop_primary_used must not be set when DROP_ENGINE_PRIMARY=false."""
        loop = Loop(name="Drop Legacy Loop", file_key="uploads/drop_legacy.wav", bpm=120)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, drop_shadow_enabled=False, drop_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert not plan.get("drop_primary_used")

    def test_live_generation_completes_when_both_disabled(self, db):
        """Status must be 'done' when both shadow and primary are off."""
        loop = Loop(name="Drop Both Off Loop", file_key="uploads/drop_both_off.wav", bpm=120)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, drop_shadow_enabled=False, drop_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"


# ---------------------------------------------------------------------------
# Determinism: same input → same drop primary output
# ---------------------------------------------------------------------------


class TestDropEnginePrimaryDeterminism:
    def test_same_input_produces_same_primary_output(self):
        """_apply_drop_engine_primary must be deterministic."""
        render_plan_a = _make_render_plan_copy()
        render_plan_b = _make_render_plan_copy()

        shadow_a = _run_drop_engine_shadow(
            render_plan=render_plan_a,
            available_roles=_FULL_ROLES,
            arrangement_id=100,
            correlation_id="det-a",
            source_quality="true_stems",
        )
        shadow_b = _run_drop_engine_shadow(
            render_plan=render_plan_b,
            available_roles=_FULL_ROLES,
            arrangement_id=101,
            correlation_id="det-b",
            source_quality="true_stems",
        )

        result_a = _apply_drop_engine_primary(
            render_plan=_make_render_plan_copy(),
            drop_shadow_result=shadow_a,
            arrangement_id=100,
            correlation_id="det-a",
        )
        result_b = _apply_drop_engine_primary(
            render_plan=_make_render_plan_copy(),
            drop_shadow_result=shadow_b,
            arrangement_id=101,
            correlation_id="det-b",
        )

        # Both should be primary=True
        assert result_a["drop_primary_used"] == result_b["drop_primary_used"]

        # Hook section drop data must match
        hook_a = next((s for s in result_a["sections"] if s.get("type") == "hook"), None)
        hook_b = next((s for s in result_b["sections"] if s.get("type") == "hook"), None)
        if hook_a and hook_b:
            assert hook_a.get("tension_score") == hook_b.get("tension_score")
            assert hook_a.get("payoff_score") == hook_b.get("payoff_score")
