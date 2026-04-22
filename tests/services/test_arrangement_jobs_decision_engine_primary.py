"""
Tests for the Decision Engine primary-mode integration in arrangement_jobs.

Covers:
- Decision Engine shapes live roles/fullness when DECISION_ENGINE_PRIMARY=true.
- Current live behaviour is preserved when DECISION_ENGINE_PRIMARY=false.
- Invalid/empty decision plans fall back cleanly without raising.
- Shadow metadata (_decision_plan, _decision_scores, etc.) is always stored.
- Metadata keys (decision_primary_used, decision_primary_fallback_used,
  decision_primary_fallback_reason, decision_plan_summary,
  decision_validation_warnings) are always written by _apply_decision_engine_primary.
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
    _apply_decision_engine_primary,
    _build_decision_plan_summary,
    _run_decision_engine_shadow,
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
            "active_stem_roles": ["drums", "bass", "melody", "pads", "fx"],
            "instruments": ["drums", "bass", "melody", "pads", "fx"],
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
            "energy": 0.6,
            "active_stem_roles": ["drums", "bass", "melody", "pads", "fx"],
            "instruments": ["drums", "bass", "melody", "pads", "fx"],
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
    """Build a well-formed decision shadow result from a real shadow planner run."""
    plan = render_plan or _STANDARD_RENDER_PLAN
    return _run_decision_engine_shadow(
        render_plan=copy.deepcopy(plan),
        available_roles=_FULL_ROLES,
        arrangement_id=1,
        correlation_id="test-decision-primary",
        source_quality="true_stems",
    )


def _make_render_plan_copy() -> dict:
    """Return a deep copy of the standard render plan."""
    return copy.deepcopy(_STANDARD_RENDER_PLAN)


# ---------------------------------------------------------------------------
# Unit: _build_decision_plan_summary
# ---------------------------------------------------------------------------


class TestBuildDecisionPlanSummary:
    def test_returns_correct_structure(self):
        result = _make_valid_shadow_result()
        summary = _build_decision_plan_summary(result)

        assert "section_count" in summary
        assert "global_contrast_score" in summary
        assert "payoff_readiness_score" in summary
        assert "fallback_used" in summary
        assert "sections" in summary
        assert isinstance(summary["sections"], list)

    def test_section_entries_have_expected_keys(self):
        result = _make_valid_shadow_result()
        summary = _build_decision_plan_summary(result)

        for sec in summary["sections"]:
            assert "section_name" in sec
            assert "target_fullness" in sec
            assert "allow_full_stack" in sec
            assert "blocked_roles" in sec
            assert "protected_roles" in sec
            assert "subtraction_count" in sec
            assert "reentry_count" in sec
            assert "decision_score" in sec

    def test_is_json_safe(self):
        result = _make_valid_shadow_result()
        summary = _build_decision_plan_summary(result)
        json.dumps(summary)  # must not raise

    def test_empty_shadow_result(self):
        summary = _build_decision_plan_summary(
            {
                "plan": {},
                "scores": [],
                "warnings": [],
                "fallback_used": False,
                "error": None,
            }
        )
        assert summary["section_count"] == 0
        assert summary["sections"] == []

    def test_section_count_matches(self):
        result = _make_valid_shadow_result()
        summary = _build_decision_plan_summary(result)
        assert summary["section_count"] == 6
        assert len(summary["sections"]) == 6

    def test_scores_are_floats_in_range(self):
        result = _make_valid_shadow_result()
        summary = _build_decision_plan_summary(result)
        assert 0.0 <= summary["global_contrast_score"] <= 1.0
        assert 0.0 <= summary["payoff_readiness_score"] <= 1.0
        for sec in summary["sections"]:
            assert 0.0 <= sec["decision_score"] <= 1.0


# ---------------------------------------------------------------------------
# Unit: _run_decision_engine_shadow
# ---------------------------------------------------------------------------


class TestRunDecisionEngineShadow:
    def test_returns_plan_for_valid_render_plan(self):
        result = _run_decision_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=1,
            correlation_id="test-shadow",
            source_quality="true_stems",
        )

        assert result["error"] is None
        assert result["plan"] is not None
        assert len(result["scores"]) == 6

    def test_plan_has_section_decisions(self):
        result = _run_decision_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=2,
            correlation_id="test-fields",
            source_quality="true_stems",
        )
        plan = result["plan"]
        assert "section_decisions" in plan
        assert len(plan["section_decisions"]) == 6

    def test_scores_have_expected_keys(self):
        result = _run_decision_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=3,
            correlation_id="test-scores",
        )
        for score in result["scores"]:
            assert "section_name" in score
            assert "target_fullness" in score
            assert "allow_full_stack" in score
            assert "blocked_roles" in score
            assert "decision_score" in score

    def test_is_json_safe(self):
        result = _run_decision_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=4,
            correlation_id="test-json",
        )
        json.dumps(result)  # must not raise

    def test_empty_render_plan_returns_empty_result(self):
        result = _run_decision_engine_shadow(
            render_plan={"sections": []},
            available_roles=_FULL_ROLES,
            arrangement_id=5,
            correlation_id="test-empty",
        )
        assert result["plan"] is None
        assert result["error"] is None

    def test_never_raises(self):
        result = _run_decision_engine_shadow(
            render_plan={"sections": None},
            available_roles=[],
            arrangement_id=99,
            correlation_id="test-bad",
        )
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# Unit: _apply_decision_engine_primary
# ---------------------------------------------------------------------------


class TestApplyDecisionEnginePrimary:
    """Unit tests for _apply_decision_engine_primary."""

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
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=1,
            correlation_id="test",
        )
        assert "decision_primary_used" in result
        assert "decision_primary_fallback_used" in result
        assert "decision_primary_fallback_reason" in result
        assert "decision_plan_summary" in result
        assert "decision_validation_warnings" in result

    def test_observability_keys_always_present_on_fallback(self):
        render_plan = self._render_plan()
        bad_shadow = {
            "error": "DecisionEngine exploded",
            "plan": None,
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=bad_shadow,
            arrangement_id=2,
            correlation_id="test",
        )
        assert "decision_primary_used" in result
        assert "decision_primary_fallback_used" in result
        assert "decision_primary_fallback_reason" in result
        assert "decision_plan_summary" in result
        assert "decision_validation_warnings" in result

    # ---------------------------------------------------------------
    # Primary applied when valid plan exists
    # ---------------------------------------------------------------

    def test_primary_used_is_true_when_plan_applied(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=3,
            correlation_id="test",
        )
        assert result["decision_primary_used"] is True
        assert result["decision_primary_fallback_used"] is False

    def test_decision_metadata_fields_injected_into_sections(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=4,
            correlation_id="test",
        )
        for sec in result["sections"]:
            assert "decision_target_fullness" in sec
            assert sec["decision_target_fullness"] in ("sparse", "medium", "full")
            assert "decision_allow_full_stack" in sec
            assert isinstance(sec["decision_allow_full_stack"], bool)
            assert "decision_blocked_roles" in sec
            assert isinstance(sec["decision_blocked_roles"], list)
            assert "decision_protected_roles" in sec
            assert isinstance(sec["decision_protected_roles"], list)

    def test_instruments_field_updated(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=5,
            correlation_id="test",
        )
        for sec in result["sections"]:
            assert "instruments" in sec
            assert isinstance(sec["instruments"], list)

    def test_active_stem_roles_matches_instruments(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=6,
            correlation_id="test",
        )
        for sec in result["sections"]:
            assert sec["instruments"] == sec["active_stem_roles"]

    def test_decision_plan_summary_populated(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=7,
            correlation_id="test",
        )
        summary = result["decision_plan_summary"]
        assert summary["section_count"] == 6
        assert len(summary["sections"]) == 6

    def test_result_is_json_safe_after_primary_applied(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=8,
            correlation_id="test",
        )
        json.dumps(result)  # must not raise

    # ---------------------------------------------------------------
    # Verse 1: full stack suppressed unless allow_full_stack=True
    # ---------------------------------------------------------------

    def test_verse1_blocked_roles_removed_from_instruments(self):
        """Blocked roles must not appear in the verse 1 instruments list."""
        render_plan = _make_render_plan_copy()
        # Verse 1 starts with full stack ["drums","bass","melody","pads","fx"]
        verse1 = render_plan["sections"][1]
        assert "fx" in verse1["instruments"]

        shadow = self._valid_shadow(render_plan)

        # Inject a synthetic decision that blocks "fx" in verse 1
        plan = shadow["plan"]
        for sec_dec in plan["section_decisions"]:
            if "verse" in sec_dec["section_name"].lower() and sec_dec["occurrence_index"] == 0:
                sec_dec["blocked_roles"] = ["fx"]
                sec_dec["allow_full_stack"] = False
                break

        # Rebuild scores to match the mutated plan
        shadow["scores"] = [
            {
                "section_name": d["section_name"],
                "occurrence_index": d["occurrence_index"],
                "target_fullness": d["target_fullness"],
                "allow_full_stack": d["allow_full_stack"],
                "blocked_roles": d["blocked_roles"],
                "protected_roles": d.get("protected_roles", []),
                "subtraction_count": len(d.get("required_subtractions", [])),
                "reentry_count": len(d.get("required_reentries", [])),
                "decision_score": d.get("decision_score", 0.5),
            }
            for d in plan["section_decisions"]
        ]

        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=9,
            correlation_id="test",
        )
        verse1_result = result["sections"][1]
        assert "fx" not in verse1_result["instruments"]

    def test_protected_roles_not_removed(self):
        """Protected roles must never be removed even when blocked."""
        render_plan = _make_render_plan_copy()
        shadow = self._valid_shadow(render_plan)

        plan = shadow["plan"]
        for sec_dec in plan["section_decisions"]:
            if "verse" in sec_dec["section_name"].lower() and sec_dec["occurrence_index"] == 0:
                sec_dec["blocked_roles"] = ["drums"]
                sec_dec["protected_roles"] = ["drums"]
                break

        shadow["scores"] = [
            {
                "section_name": d["section_name"],
                "occurrence_index": d["occurrence_index"],
                "target_fullness": d["target_fullness"],
                "allow_full_stack": d["allow_full_stack"],
                "blocked_roles": d["blocked_roles"],
                "protected_roles": d.get("protected_roles", []),
                "subtraction_count": len(d.get("required_subtractions", [])),
                "reentry_count": len(d.get("required_reentries", [])),
                "decision_score": d.get("decision_score", 0.5),
            }
            for d in plan["section_decisions"]
        ]

        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=10,
            correlation_id="test",
        )
        # drums is both blocked and protected → must remain
        verse1_result = result["sections"][1]
        assert "drums" in verse1_result["instruments"]

    # ---------------------------------------------------------------
    # Fullness cap when allow_full_stack=False
    # ---------------------------------------------------------------

    def test_fullness_cap_sparse_reduces_roles(self):
        """sparse + allow_full_stack=False must cap role count to ~40%."""
        render_plan = _make_render_plan_copy()
        # Give verse 1 5 roles
        render_plan["sections"][1]["instruments"] = ["drums", "bass", "melody", "pads", "fx"]
        render_plan["sections"][1]["active_stem_roles"] = ["drums", "bass", "melody", "pads", "fx"]

        shadow = self._valid_shadow(render_plan)
        plan = shadow["plan"]
        for sec_dec in plan["section_decisions"]:
            if "verse" in sec_dec["section_name"].lower() and sec_dec["occurrence_index"] == 0:
                sec_dec["target_fullness"] = "sparse"
                sec_dec["allow_full_stack"] = False
                sec_dec["blocked_roles"] = []
                break

        shadow["scores"] = [
            {
                "section_name": d["section_name"],
                "occurrence_index": d["occurrence_index"],
                "target_fullness": d["target_fullness"],
                "allow_full_stack": d["allow_full_stack"],
                "blocked_roles": d.get("blocked_roles", []),
                "protected_roles": d.get("protected_roles", []),
                "subtraction_count": len(d.get("required_subtractions", [])),
                "reentry_count": len(d.get("required_reentries", [])),
                "decision_score": d.get("decision_score", 0.5),
            }
            for d in plan["section_decisions"]
        ]

        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=11,
            correlation_id="test",
        )
        verse1_out = result["sections"][1]
        # sparse → max 40% of 5 = 2 roles
        assert len(verse1_out["instruments"]) <= 2

    # ---------------------------------------------------------------
    # Fallback: error in shadow result
    # ---------------------------------------------------------------

    def test_fallback_when_shadow_has_error(self):
        render_plan = self._render_plan()
        error_shadow = {
            "error": "DecisionEngine failed",
            "plan": None,
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=error_shadow,
            arrangement_id=12,
            correlation_id="test",
        )
        assert result["decision_primary_used"] is False
        assert result["decision_primary_fallback_used"] is True
        assert "failed" in result["decision_primary_fallback_reason"].lower()

    def test_sections_unchanged_on_error_fallback(self):
        render_plan = self._render_plan()
        original_sections = copy.deepcopy(render_plan["sections"])
        error_shadow = {
            "error": "boom",
            "plan": None,
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=error_shadow,
            arrangement_id=13,
            correlation_id="test",
        )
        for sec, orig_sec in zip(result["sections"], original_sections):
            assert "decision_target_fullness" not in sec
            assert sec.get("instruments") == orig_sec.get("instruments")

    # ---------------------------------------------------------------
    # Fallback: empty plan when sections exist
    # ---------------------------------------------------------------

    def test_fallback_when_plan_empty_but_sections_exist(self):
        render_plan = self._render_plan()
        empty_shadow = {
            "error": None,
            "plan": {"section_decisions": [], "global_contrast_score": 0.0, "payoff_readiness_score": 0.0},
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=empty_shadow,
            arrangement_id=14,
            correlation_id="test",
        )
        assert result["decision_primary_used"] is False
        assert result["decision_primary_fallback_used"] is True
        assert result["decision_primary_fallback_reason"] != ""

    def test_no_fallback_when_both_plan_and_sections_empty(self):
        """Empty plan with no sections is not a fallback — nothing to apply."""
        render_plan = {"sections": [], "sections_count": 0}
        empty_shadow = {
            "error": None,
            "plan": {"section_decisions": [], "global_contrast_score": 0.0, "payoff_readiness_score": 0.0},
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=empty_shadow,
            arrangement_id=15,
            correlation_id="test",
        )
        assert result["decision_primary_fallback_used"] is False

    # ---------------------------------------------------------------
    # Fallback: critical validation issues
    # ---------------------------------------------------------------

    def test_fallback_on_critical_validation_issue(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        shadow["warnings"] = [
            {
                "rule": "verse_1_full_stack",
                "severity": "critical",
                "message": "Critical: Verse 1 is full stack without fallback",
                "section_name": "Verse 1",
            }
        ]
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=16,
            correlation_id="test",
        )
        assert result["decision_primary_used"] is False
        assert result["decision_primary_fallback_used"] is True
        assert "critical" in result["decision_primary_fallback_reason"].lower()
        for sec in result["sections"]:
            assert "decision_target_fullness" not in sec

    def test_warning_issues_do_not_cause_fallback(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        shadow["warnings"] = [
            {
                "rule": "hook_no_reintroduction",
                "severity": "warning",
                "message": "Hook does not reintroduce anything",
                "section_name": "Hook 1",
            }
        ]
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=17,
            correlation_id="test",
        )
        assert result["decision_primary_used"] is True
        assert result["decision_primary_fallback_used"] is False
        assert len(result["decision_validation_warnings"]) == 1

    # ---------------------------------------------------------------
    # Legacy behaviour preserved when primary disabled
    # ---------------------------------------------------------------

    def test_sections_have_no_decision_fields_without_primary_call(self):
        """Without calling _apply_decision_engine_primary, sections are untouched."""
        render_plan = self._render_plan()
        for sec in render_plan["sections"]:
            assert "decision_target_fullness" not in sec
            assert "decision_blocked_roles" not in sec

    # ---------------------------------------------------------------
    # Validation warnings stored
    # ---------------------------------------------------------------

    def test_validation_warnings_stored(self):
        render_plan = self._render_plan()
        shadow = self._valid_shadow(render_plan)
        shadow["warnings"] = [
            {
                "rule": "pre_hook_no_subtraction",
                "severity": "warning",
                "message": "Pre-hook did not subtract any roles",
                "section_name": "Pre-Hook",
            }
        ]
        result = _apply_decision_engine_primary(
            render_plan=render_plan,
            dec_shadow_result=shadow,
            arrangement_id=18,
            correlation_id="test",
        )
        assert result["decision_validation_warnings"] != []
        assert result["decision_validation_warnings"][0]["rule"] == "pre_hook_no_subtraction"


# ---------------------------------------------------------------------------
# Integration: run_arrangement_job with Decision Engine primary
# ---------------------------------------------------------------------------


class TestRunArrangementJobDecisionEnginePrimary:
    """Integration-level tests verifying run_arrangement_job behaves correctly
    with DECISION_ENGINE_PRIMARY enabled/disabled."""

    def _run_job_with_mocks(
        self,
        arrangement_id: int,
        dec_shadow_enabled: bool = True,
        dec_primary_enabled: bool = False,
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
            mock_settings.feature_drop_engine_shadow = False
            mock_settings.feature_motif_engine_shadow = False
            mock_settings.feature_decision_engine_shadow = dec_shadow_enabled
            mock_settings.feature_decision_engine_primary = dec_primary_enabled
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            run_arrangement_job(arrangement_id)

    def test_live_generation_completes_with_primary_enabled(self, db):
        """Status must be 'done' when DECISION_ENGINE_PRIMARY=true."""
        loop = Loop(name="DE Primary Loop", file_key="uploads/de_primary.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, dec_shadow_enabled=True, dec_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"
        assert updated.error_message is None

    def test_decision_primary_used_stored_in_metadata_when_primary_enabled(self, db):
        """decision_primary_used must be present in render_plan_json when flag is set."""
        loop = Loop(name="DE Primary Meta Loop", file_key="uploads/de_meta.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, dec_shadow_enabled=True, dec_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "decision_primary_used" in plan

    def test_decision_plan_summary_stored_when_primary_enabled(self, db):
        """decision_plan_summary must be a dict in render_plan_json when primary is enabled."""
        loop = Loop(name="DE Summary Loop", file_key="uploads/de_summary.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, dec_shadow_enabled=True, dec_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "decision_plan_summary" in plan
        assert isinstance(plan["decision_plan_summary"], dict)

    def test_shadow_metadata_stored_when_shadow_only_enabled(self, db):
        """_decision_plan etc. must be stored when shadow-only mode is on."""
        loop = Loop(name="DE Shadow Only Loop", file_key="uploads/de_shadow_only.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, dec_shadow_enabled=True, dec_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "_decision_plan" in plan
        assert "_decision_scores" in plan
        assert "_decision_warnings" in plan
        assert "_decision_fallback_used" in plan

    def test_shadow_metadata_always_stored_when_primary_enabled(self, db):
        """_decision_plan must be stored even when only DECISION_ENGINE_PRIMARY=true."""
        loop = Loop(name="DE Primary Shadow Loop", file_key="uploads/de_both.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        # shadow=False but primary=True — shadow must still run
        self._run_job_with_mocks(arr.id, dec_shadow_enabled=False, dec_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "_decision_plan" in plan

    def test_legacy_behavior_when_primary_disabled(self, db):
        """decision_primary_used must not be set when DECISION_ENGINE_PRIMARY=false."""
        loop = Loop(name="DE Legacy Loop", file_key="uploads/de_legacy.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, dec_shadow_enabled=False, dec_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert not plan.get("decision_primary_used")

    def test_live_generation_completes_when_both_disabled(self, db):
        """Status must be 'done' when both shadow and primary are off."""
        loop = Loop(name="DE Both Off Loop", file_key="uploads/de_both_off.wav", bpm=120.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, dec_shadow_enabled=False, dec_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done"

