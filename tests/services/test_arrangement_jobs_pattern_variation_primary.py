"""
Tests for the Pattern Variation Engine primary-mode integration in arrangement_jobs.

Covers:
- Pattern Variation Engine plans are applied to render_plan sections when
  PATTERN_VARIATION_PRIMARY=true.
- Current live behaviour is preserved when PATTERN_VARIATION_PRIMARY=false.
- Invalid / empty variation plans fall back cleanly without raising.
- Shadow metadata is always stored regardless of primary mode.
- Metadata keys (pattern_primary_used, pattern_primary_fallback_used,
  pattern_primary_fallback_reason, pattern_variation_summary,
  pattern_variation_validation_warnings) are always written.
- Live generation still completes (status==done) when primary mode is active.
- No regression to existing uploads/jobs/render flow.
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
    _apply_pattern_variation_primary,
    _build_pattern_variation_summary,
    _run_pattern_variation_shadow,
    run_arrangement_job,
)


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

_FULL_ROLES = ["drums", "bass", "melody", "pads", "fx"]

_STANDARD_RENDER_PLAN = {
    "sections": [
        {"type": "intro",   "name": "Intro",   "bars": 4,  "energy": 0.3,  "active_stem_roles": ["melody", "pads"]},
        {"type": "verse",   "name": "Verse 1", "bars": 8,  "energy": 0.55, "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "hook",    "name": "Hook 1",  "bars": 8,  "energy": 0.85, "active_stem_roles": ["drums", "bass", "melody", "pads"]},
        {"type": "verse",   "name": "Verse 2", "bars": 8,  "energy": 0.55, "active_stem_roles": ["drums", "bass", "melody"]},
        {"type": "hook",    "name": "Hook 2",  "bars": 8,  "energy": 0.9,  "active_stem_roles": ["drums", "bass", "melody", "pads", "fx"]},
        {"type": "outro",   "name": "Outro",   "bars": 4,  "energy": 0.2,  "active_stem_roles": ["melody", "pads"]},
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
    """Build a well-formed shadow result from a real shadow planner run."""
    plan = render_plan or _STANDARD_RENDER_PLAN
    return _run_pattern_variation_shadow(
        render_plan=copy.deepcopy(plan),
        available_roles=_FULL_ROLES,
        arrangement_id=1,
        correlation_id="test-primary",
        source_quality="true_stems",
    )


def _make_render_plan_copy() -> dict:
    """Return a deep copy of the standard render plan."""
    return copy.deepcopy(_STANDARD_RENDER_PLAN)


# ---------------------------------------------------------------------------
# Unit: _build_pattern_variation_summary
# ---------------------------------------------------------------------------

class TestBuildPatternVariationSummary:
    def test_returns_correct_structure(self):
        result = _make_valid_shadow_result()
        summary = _build_pattern_variation_summary(result)

        assert "section_count" in summary
        assert "total_events" in summary
        assert "low_score_sections" in summary
        assert "sections" in summary
        assert isinstance(summary["sections"], list)

    def test_section_entries_have_expected_keys(self):
        result = _make_valid_shadow_result()
        summary = _build_pattern_variation_summary(result)

        for sec in summary["sections"]:
            assert "section" in sec
            assert "variation_density" in sec
            assert "repetition_score" in sec
            assert "event_count" in sec
            assert "applied_strategies" in sec

    def test_is_json_safe(self):
        result = _make_valid_shadow_result()
        summary = _build_pattern_variation_summary(result)
        json.dumps(summary)  # must not raise

    def test_empty_shadow_result(self):
        summary = _build_pattern_variation_summary({"plans": [], "section_count": 0, "total_events": 0})
        assert summary["section_count"] == 0
        assert summary["total_events"] == 0
        assert summary["sections"] == []

    def test_section_count_matches(self):
        result = _make_valid_shadow_result()
        summary = _build_pattern_variation_summary(result)
        assert summary["section_count"] == 6
        assert len(summary["sections"]) == 6


# ---------------------------------------------------------------------------
# Unit: _run_pattern_variation_shadow
# ---------------------------------------------------------------------------

class TestRunPatternVariationShadow:
    def test_returns_plans_for_valid_render_plan(self):
        result = _run_pattern_variation_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=1,
            correlation_id="test-shadow",
            source_quality="true_stems",
        )

        assert result["error"] is None
        assert result["section_count"] == 6
        assert len(result["plans"]) == 6

    def test_plan_entries_have_variation_fields(self):
        result = _run_pattern_variation_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=2,
            correlation_id="test-fields",
            source_quality="true_stems",
        )
        for plan in result["plans"]:
            assert "section" in plan
            assert "variations" in plan
            assert "variation_density" in plan
            assert "repetition_score" in plan
            assert "applied_strategies" in plan

    def test_is_json_safe(self):
        result = _run_pattern_variation_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=3,
            correlation_id="test-json",
        )
        json.dumps(result)  # must not raise

    def test_empty_render_plan_returns_empty_result(self):
        result = _run_pattern_variation_shadow(
            render_plan={"sections": []},
            available_roles=_FULL_ROLES,
            arrangement_id=4,
            correlation_id="test-empty",
        )
        assert result["plans"] == []
        assert result["section_count"] == 0
        assert result["error"] is None

    def test_never_raises(self):
        result = _run_pattern_variation_shadow(
            render_plan={"sections": None},
            available_roles=[],
            arrangement_id=99,
            correlation_id="test-bad",
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Unit: _apply_pattern_variation_primary
# ---------------------------------------------------------------------------

class TestApplyPatternVariationPrimary:
    """Unit tests for _apply_pattern_variation_primary."""

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
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=shadow,
            arrangement_id=1,
            correlation_id="test",
        )
        assert "pattern_primary_used" in result
        assert "pattern_primary_fallback_used" in result
        assert "pattern_primary_fallback_reason" in result
        assert "pattern_variation_summary" in result
        assert "pattern_variation_validation_warnings" in result

    def test_observability_keys_always_present_on_fallback(self):
        render_plan = self._render_plan()
        bad_shadow = {"error": "planner exploded", "plans": [], "section_count": 0, "total_events": 0}
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=bad_shadow,
            arrangement_id=2,
            correlation_id="test",
        )
        assert "pattern_primary_used" in result
        assert "pattern_primary_fallback_used" in result
        assert "pattern_primary_fallback_reason" in result
        assert "pattern_variation_summary" in result
        assert "pattern_variation_validation_warnings" in result

    # ---------------------------------------------------------------
    # Primary applied when valid plans exist
    # ---------------------------------------------------------------

    def test_primary_used_is_true_when_plans_applied(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=shadow,
            arrangement_id=3,
            correlation_id="test",
        )
        assert result["pattern_primary_used"] is True
        assert result["pattern_primary_fallback_used"] is False

    def test_pattern_variation_events_injected_into_sections(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=shadow,
            arrangement_id=4,
            correlation_id="test",
        )
        for sec in result["sections"]:
            assert "pattern_variation_events" in sec
            assert isinstance(sec["pattern_variation_events"], list)
            assert "pattern_variation_density" in sec
            assert "pattern_variation_score" in sec
            assert "pattern_variation_strategies" in sec

    def test_variation_summary_populated(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=shadow,
            arrangement_id=5,
            correlation_id="test",
        )
        summary = result["pattern_variation_summary"]
        assert summary["section_count"] == 6
        assert len(summary["sections"]) == 6

    def test_result_is_json_safe_after_primary_applied(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=shadow,
            arrangement_id=6,
            correlation_id="test",
        )
        json.dumps(result)  # must not raise

    # ---------------------------------------------------------------
    # Fallback: error in shadow result
    # ---------------------------------------------------------------

    def test_fallback_when_shadow_has_error(self):
        render_plan = self._render_plan()
        error_shadow = {
            "error": "PatternVariationEngine failed",
            "plans": [],
            "section_count": 0,
            "total_events": 0,
            "low_score_sections": [],
        }
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=error_shadow,
            arrangement_id=7,
            correlation_id="test",
        )
        assert result["pattern_primary_used"] is False
        assert result["pattern_primary_fallback_used"] is True
        assert "failed" in result["pattern_primary_fallback_reason"].lower()

    def test_sections_unchanged_on_error_fallback(self):
        render_plan = self._render_plan()
        original_sections = copy.deepcopy(render_plan["sections"])
        error_shadow = {"error": "boom", "plans": [], "section_count": 0, "total_events": 0}
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=error_shadow,
            arrangement_id=8,
            correlation_id="test",
        )
        # Sections must not have pattern_variation_events injected
        for sec, orig_sec in zip(result["sections"], original_sections):
            assert "pattern_variation_events" not in sec

    # ---------------------------------------------------------------
    # Fallback: empty plans when sections exist
    # ---------------------------------------------------------------

    def test_fallback_when_plans_empty_but_sections_exist(self):
        render_plan = self._render_plan()
        empty_shadow = {
            "error": None,
            "plans": [],
            "section_count": 0,
            "total_events": 0,
            "low_score_sections": [],
        }
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=empty_shadow,
            arrangement_id=9,
            correlation_id="test",
        )
        assert result["pattern_primary_used"] is False
        assert result["pattern_primary_fallback_used"] is True
        assert result["pattern_primary_fallback_reason"] != ""

    def test_no_fallback_when_both_plans_and_sections_empty(self):
        """Empty plans with no sections is not a fallback — nothing to apply."""
        render_plan = {"sections": [], "sections_count": 0}
        empty_shadow = {
            "error": None,
            "plans": [],
            "section_count": 0,
            "total_events": 0,
            "low_score_sections": [],
        }
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=empty_shadow,
            arrangement_id=10,
            correlation_id="test",
        )
        # No sections = nothing to inject; treated as success (no fallback)
        assert result["pattern_primary_fallback_used"] is False

    # ---------------------------------------------------------------
    # Legacy behaviour preserved when primary disabled
    # ---------------------------------------------------------------

    def test_sections_have_no_variation_events_without_primary_call(self):
        """Without calling _apply_pattern_variation_primary, sections are untouched."""
        render_plan = self._render_plan()
        for sec in render_plan["sections"]:
            assert "pattern_variation_events" not in sec

    # ---------------------------------------------------------------
    # Validation warnings stored for low-score sections
    # ---------------------------------------------------------------

    def test_low_score_sections_stored_as_warnings(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        # Manually inject low-score sections to simulate the warning path
        shadow["low_score_sections"] = ["Verse 1", "Hook 1"]
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=shadow,
            arrangement_id=11,
            correlation_id="test",
        )
        # Primary should still succeed
        assert result["pattern_primary_used"] is True
        assert result["pattern_variation_validation_warnings"] == ["Verse 1", "Hook 1"]

    def test_no_warnings_when_no_low_score_sections(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        shadow["low_score_sections"] = []
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=shadow,
            arrangement_id=12,
            correlation_id="test",
        )
        assert result["pattern_variation_validation_warnings"] == []


# ---------------------------------------------------------------------------
# Integration: run_arrangement_job with pattern variation primary enabled
# ---------------------------------------------------------------------------

class TestRunArrangementJobPatternVariationPrimary:
    """Integration tests verifying primary-mode end-to-end behaviour."""

    def _run_job_with_mocks(
        self,
        arrangement_id: int,
        pv_shadow_enabled: bool = True,
        pv_primary_enabled: bool = False,
    ):
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
                   return_value=copy.deepcopy(_STANDARD_RENDER_PLAN)), \
             patch("app.services.arrangement_jobs.attach_loops_to_sections"), \
             patch("app.services.arrangement_jobs._validate_render_plan_quality"), \
             patch("app.services.arrangement_jobs.score_and_reject"), \
             patch("app.services.arrangement_jobs.render_from_plan",
                   return_value={"timeline_json": '{"sections": []}', "postprocess": {}}), \
             patch("app.services.arrangement_jobs.AudioSegment.export", new=_fake_export), \
             patch("app.services.arrangement_jobs.storage.use_s3", True), \
             patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_timeline_engine_shadow = False
            mock_settings.feature_timeline_engine_primary = False
            mock_settings.feature_arranger_v2 = False
            mock_settings.feature_style_engine = False
            mock_settings.dev_fallback_loop_only = False
            mock_settings.is_production = False
            mock_settings.feature_pattern_variation_shadow = pv_shadow_enabled
            mock_settings.feature_pattern_variation_primary = pv_primary_enabled
            mock_settings.feature_groove_engine_shadow = False
            mock_settings.feature_ai_producer_system_shadow = False
            mock_settings.feature_drop_engine_shadow = False
            mock_settings.feature_motif_engine_shadow = False
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            run_arrangement_job(arrangement_id)

    def test_live_generation_completes_with_primary_enabled(self, db):
        """Status must be 'done' when PATTERN_VARIATION_PRIMARY=true."""
        loop = Loop(name="PV Primary Loop", file_key="uploads/pv_primary.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=True, pv_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        assert updated.error_message is None

    def test_pattern_primary_used_stored_in_metadata_when_primary_enabled(self, db):
        """pattern_primary_used must be True in render_plan_json when flag is set."""
        loop = Loop(name="PV Primary Meta Loop", file_key="uploads/pv_meta.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=True, pv_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.render_plan_json is not None
        stored = json.loads(updated.render_plan_json)
        assert stored.get("pattern_primary_used") is True
        assert stored.get("pattern_primary_fallback_used") is False

    def test_variation_summary_stored_when_primary_enabled(self, db):
        """pattern_variation_summary must be present and non-empty."""
        loop = Loop(name="PV Summary Loop", file_key="uploads/pv_summary.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=True, pv_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        stored = json.loads(updated.render_plan_json)
        summary = stored.get("pattern_variation_summary")
        assert summary is not None
        assert "section_count" in summary
        assert "total_events" in summary

    def test_pattern_variation_events_in_sections_when_primary_enabled(self, db):
        """Each section in stored render plan must have pattern_variation_events."""
        loop = Loop(name="PV Events Loop", file_key="uploads/pv_events.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=True, pv_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        stored = json.loads(updated.render_plan_json)
        sections = stored.get("sections") or []
        assert len(sections) > 0
        for sec in sections:
            assert "pattern_variation_events" in sec, (
                f"Section {sec.get('type') or sec.get('name')} missing pattern_variation_events"
            )

    def test_legacy_behavior_when_primary_disabled(self, db):
        """When PATTERN_VARIATION_PRIMARY=false, sections must NOT have variation events."""
        loop = Loop(name="PV Legacy Loop", file_key="uploads/pv_legacy.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=False, pv_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        stored = json.loads(updated.render_plan_json)
        # No primary metadata keys should be present
        assert "pattern_primary_used" not in stored

    def test_shadow_metadata_stored_when_shadow_only_enabled(self, db):
        """Shadow metadata (_pattern_variation_plans) should be present when shadow=true."""
        loop = Loop(name="PV Shadow Only Loop", file_key="uploads/pv_shadow_only.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=True, pv_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        stored = json.loads(updated.render_plan_json)
        assert "_pattern_variation_plans" in stored, (
            "_pattern_variation_plans key missing — shadow planner did not store its result"
        )
        pv = stored["_pattern_variation_plans"]
        assert "plans" in pv
        assert "section_count" in pv

    def test_shadow_metadata_always_stored_when_primary_enabled(self, db):
        """_pattern_variation_plans must also be present when primary mode runs."""
        loop = Loop(name="PV Primary Shadow Loop", file_key="uploads/pv_both.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=False, pv_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        stored = json.loads(updated.render_plan_json)
        # Shadow data stored even though feature_pattern_variation_shadow=False
        # because primary mode forces the shadow pass to run.
        assert "_pattern_variation_plans" in stored

    def test_live_generation_completes_when_both_disabled(self, db):
        """Both flags disabled: job must still complete successfully."""
        loop = Loop(name="PV Both Off Loop", file_key="uploads/pv_both_off.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, pv_shadow_enabled=False, pv_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        assert updated.output_s3_key == f"arrangements/{arr.id}.wav"
        assert updated.error_message is None


# ---------------------------------------------------------------------------
# Integration: fallback on invalid plan (simulated via mock)
# ---------------------------------------------------------------------------

class TestPatternVariationPrimaryFallback:
    """Verify clean fallback when the variation plan is invalid."""

    def test_fallback_recorded_when_shadow_raises(self):
        """If shadow planner fails at runtime, fallback metadata is written."""
        render_plan = copy.deepcopy(_STANDARD_RENDER_PLAN)
        error_shadow = {
            "error": "PatternVariationEngine: unexpected internal error",
            "plans": [],
            "section_count": 0,
            "total_events": 0,
            "low_score_sections": [],
        }
        result = _apply_pattern_variation_primary(
            render_plan=render_plan,
            pv_shadow_result=error_shadow,
            arrangement_id=50,
            correlation_id="test-fallback",
        )
        assert result["pattern_primary_used"] is False
        assert result["pattern_primary_fallback_used"] is True
        assert "PatternVariationEngine" in result["pattern_primary_fallback_reason"]
        # Sections must be untouched
        for sec in result["sections"]:
            assert "pattern_variation_events" not in sec

    def test_fallback_does_not_raise(self):
        """Fallback path must never raise regardless of shadow content."""
        render_plan = copy.deepcopy(_STANDARD_RENDER_PLAN)
        for bad_shadow in [
            {},
            {"error": "boom"},
            None,
        ]:
            # _apply_pattern_variation_primary accepts a dict; pass {} for None
            shadow = bad_shadow if bad_shadow is not None else {}
            result = _apply_pattern_variation_primary(
                render_plan=render_plan,
                pv_shadow_result=shadow,
                arrangement_id=51,
                correlation_id="test-no-raise",
            )
            assert isinstance(result, dict)
