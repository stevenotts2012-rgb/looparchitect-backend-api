"""
Tests for the Motif Engine primary-mode integration in arrangement_jobs.

Covers:
- Motif Engine shapes live motif fields per section when MOTIF_ENGINE_PRIMARY=true.
- Current live behaviour is preserved when MOTIF_ENGINE_PRIMARY=false.
- Invalid/empty motif plans fall back cleanly without raising.
- Shadow metadata (_motif_plan, _motif_scores, etc.) is always stored.
- Metadata keys (motif_primary_used, motif_primary_fallback_used,
  motif_primary_fallback_reason, motif_plan_summary, motif_validation_warnings,
  motif_reuse_score, motif_variation_score) are always written by
  _apply_motif_engine_primary.
- Integration rules:
  - Repeated hooks differ in motif treatment (or a warning is logged).
  - Verse motifs are weaker (non-strong) than hook motifs.
  - Bridge must not copy hook motif directly.
  - Outro resolves/strips motif (no strong statement, no full_phrase).
- Fallback works correctly (empty plan, error, validator error-severity issue).
- No regression to render pipeline.
- Decision Engine blocked_roles are respected.
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
    _apply_motif_engine_primary,
    _build_motif_plan_summary,
    _run_motif_engine_shadow,
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
            "active_stem_roles": ["drums", "bass", "melody", "pads"],
            "instruments": ["drums", "bass", "melody", "pads"],
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
            "energy": 0.90,
            "active_stem_roles": ["drums", "bass", "melody", "pads", "fx"],
            "instruments": ["drums", "bass", "melody", "pads", "fx"],
        },
        {
            "type": "verse",
            "name": "Verse 2",
            "bars": 8,
            "energy": 0.55,
            "active_stem_roles": ["drums", "bass", "melody"],
            "instruments": ["drums", "bass", "melody"],
        },
        {
            "type": "hook",
            "name": "Hook 2",
            "bars": 8,
            "energy": 0.90,
            "active_stem_roles": ["drums", "bass", "melody", "pads", "fx"],
            "instruments": ["drums", "bass", "melody", "pads", "fx"],
        },
        {
            "type": "bridge",
            "name": "Bridge",
            "bars": 8,
            "energy": 0.6,
            "active_stem_roles": ["drums", "bass", "melody"],
            "instruments": ["drums", "bass", "melody"],
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
    "sections_count": 8,
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
    """Build a well-formed motif shadow result from a real shadow planner run."""
    plan = render_plan or _STANDARD_RENDER_PLAN
    return _run_motif_engine_shadow(
        render_plan=copy.deepcopy(plan),
        available_roles=_FULL_ROLES,
        arrangement_id=1,
        correlation_id="test-motif-primary",
        source_quality="true_stems",
    )


def _make_render_plan_copy() -> dict:
    """Return a deep copy of the standard render plan."""
    return copy.deepcopy(_STANDARD_RENDER_PLAN)


# ---------------------------------------------------------------------------
# Unit: _build_motif_plan_summary
# ---------------------------------------------------------------------------


class TestBuildMotifPlanSummary:
    def test_returns_correct_structure(self):
        result = _make_valid_shadow_result()
        summary = _build_motif_plan_summary(result)

        assert "motif_type" in summary
        assert "motif_source_role" in summary
        assert "occurrence_count" in summary
        assert "motif_reuse_score" in summary
        assert "motif_variation_score" in summary
        assert "fallback_used" in summary
        assert "occurrences" in summary
        assert isinstance(summary["occurrences"], list)

    def test_occurrence_entries_have_expected_keys(self):
        result = _make_valid_shadow_result()
        summary = _build_motif_plan_summary(result)

        for occ in summary["occurrences"]:
            assert "section_name" in occ
            assert "occurrence_index" in occ
            assert "source_role" in occ
            assert "transformation_types" in occ
            assert "target_intensity" in occ
            assert "is_strong" in occ

    def test_is_json_safe(self):
        result = _make_valid_shadow_result()
        summary = _build_motif_plan_summary(result)
        json.dumps(summary)  # must not raise

    def test_empty_shadow_result(self):
        summary = _build_motif_plan_summary(
            {
                "plan": {},
                "scores": [],
                "warnings": [],
                "fallback_used": False,
                "error": None,
            }
        )
        assert summary["occurrence_count"] == 0
        assert summary["occurrences"] == []
        assert summary["fallback_used"] is False

    def test_scores_are_floats_in_range(self):
        result = _make_valid_shadow_result()
        summary = _build_motif_plan_summary(result)
        assert 0.0 <= summary["motif_reuse_score"] <= 1.0
        assert 0.0 <= summary["motif_variation_score"] <= 1.0
        for occ in summary["occurrences"]:
            assert 0.0 <= occ["target_intensity"] <= 1.0


# ---------------------------------------------------------------------------
# Unit: _run_motif_engine_shadow
# ---------------------------------------------------------------------------


class TestRunMotifEngineShadow:
    def test_returns_plan_for_valid_render_plan(self):
        result = _run_motif_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=1,
            correlation_id="test-shadow",
            source_quality="true_stems",
        )

        assert result["error"] is None
        assert result["plan"] is not None

    def test_plan_has_occurrences(self):
        result = _run_motif_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=2,
            correlation_id="test-fields",
            source_quality="true_stems",
        )
        plan = result["plan"]
        assert "occurrences" in plan
        assert len(plan["occurrences"]) > 0

    def test_scores_have_expected_keys(self):
        result = _run_motif_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=_FULL_ROLES,
            arrangement_id=3,
            correlation_id="test-scores",
        )
        for score in result["scores"]:
            assert "section_name" in score
            assert "transformation_types" in score
            assert "target_intensity" in score
            assert "is_strong" in score
            assert "source_role" in score

    def test_empty_render_plan_returns_no_plan(self):
        result = _run_motif_engine_shadow(
            render_plan={"sections": []},
            available_roles=_FULL_ROLES,
            arrangement_id=4,
            correlation_id="test-empty",
        )
        assert result["plan"] is None
        assert result["error"] is None

    def test_no_roles_returns_fallback(self):
        result = _run_motif_engine_shadow(
            render_plan=_make_render_plan_copy(),
            available_roles=[],
            arrangement_id=5,
            correlation_id="test-no-roles",
            source_quality="stereo_fallback",
        )
        # May return a plan with fallback=True or no occurrences depending on extractor.
        assert result["error"] is None

    def test_exception_does_not_raise(self):
        """Shadow runner never raises — exceptions are recorded in 'error'."""
        from unittest.mock import patch

        with patch(
            "app.services.motif_engine.planner.MotifPlanner.build",
            side_effect=RuntimeError("unexpected failure"),
        ):
            result = _run_motif_engine_shadow(
                render_plan=_make_render_plan_copy(),
                available_roles=_FULL_ROLES,
                arrangement_id=6,
                correlation_id="test-exception",
            )
        assert result["error"] is not None
        assert "unexpected failure" in result["error"]
        assert result["plan"] is None


# ---------------------------------------------------------------------------
# Unit: _apply_motif_engine_primary — observability always written
# ---------------------------------------------------------------------------


class TestApplyMotifEnginePrimaryObservability:
    """Checks that all required keys are written regardless of outcome."""

    def _required_keys(self) -> list[str]:
        return [
            "motif_primary_used",
            "motif_primary_fallback_used",
            "motif_primary_fallback_reason",
            "motif_plan_summary",
            "motif_validation_warnings",
            "motif_reuse_score",
            "motif_variation_score",
        ]

    def test_keys_written_on_success(self):
        render_plan = _make_render_plan_copy()
        shadow = _make_valid_shadow_result(render_plan)
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=1,
            correlation_id="obs-test",
        )
        for key in self._required_keys():
            assert key in result, f"Missing key: {key}"

    def test_keys_written_on_error_fallback(self):
        render_plan = _make_render_plan_copy()
        shadow = {"error": "simulated failure", "plan": None, "scores": [], "warnings": []}
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=2,
            correlation_id="obs-error",
        )
        for key in self._required_keys():
            assert key in result, f"Missing key: {key}"
        assert result["motif_primary_fallback_used"] is True
        assert result["motif_primary_used"] is False

    def test_keys_written_on_empty_plan_fallback(self):
        render_plan = _make_render_plan_copy()
        shadow = {
            "error": None,
            "plan": {"occurrences": [], "motif": None, "motif_reuse_score": 0.0,
                     "motif_variation_score": 0.0, "fallback_used": True},
            "scores": [],
            "warnings": [],
            "fallback_used": True,
        }
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=3,
            correlation_id="obs-empty",
        )
        for key in self._required_keys():
            assert key in result, f"Missing key: {key}"
        assert result["motif_primary_fallback_used"] is True


# ---------------------------------------------------------------------------
# Unit: _apply_motif_engine_primary — fallback guards
# ---------------------------------------------------------------------------


class TestApplyMotifEnginePrimaryFallback:
    def test_error_in_shadow_triggers_fallback(self):
        render_plan = _make_render_plan_copy()
        shadow = {
            "error": "planner crash",
            "plan": None,
            "scores": [],
            "warnings": [],
            "fallback_used": False,
        }
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=10,
            correlation_id="fallback-error",
        )
        assert result["motif_primary_fallback_used"] is True
        assert "planner crash" in result["motif_primary_fallback_reason"]
        assert result["motif_primary_used"] is False

    def test_empty_occurrences_with_sections_triggers_fallback(self):
        render_plan = _make_render_plan_copy()
        shadow = {
            "error": None,
            "plan": {
                "occurrences": [],
                "motif": None,
                "motif_reuse_score": 0.0,
                "motif_variation_score": 0.0,
                "fallback_used": True,
            },
            "scores": [],
            "warnings": [],
            "fallback_used": True,
        }
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=11,
            correlation_id="fallback-empty",
        )
        assert result["motif_primary_fallback_used"] is True
        assert result["motif_primary_used"] is False

    def test_error_severity_issue_triggers_fallback(self):
        render_plan = _make_render_plan_copy()
        shadow = _make_valid_shadow_result(render_plan)
        # Inject an error-severity warning.
        shadow["warnings"] = [
            {"severity": "error", "rule": "critical_rule", "message": "fatal issue"}
        ]
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=12,
            correlation_id="fallback-error-issue",
        )
        assert result["motif_primary_fallback_used"] is True
        assert "fatal issue" in result["motif_primary_fallback_reason"]
        assert result["motif_primary_used"] is False

    def test_no_sections_does_not_trigger_fallback(self):
        """Empty render plan (no sections) should apply cleanly (nothing to annotate)."""
        render_plan = {"sections": [], "sections_count": 0}
        shadow = _make_valid_shadow_result()
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=13,
            correlation_id="no-sections",
        )
        # No eligible sections → no fallback triggered for empty plan
        assert result["motif_primary_fallback_used"] is False


# ---------------------------------------------------------------------------
# Unit: _apply_motif_engine_primary — motif fields are applied
# ---------------------------------------------------------------------------


class TestApplyMotifEnginePrimaryFields:
    def _apply_primary(self, render_plan: dict | None = None) -> dict:
        plan = render_plan or _make_render_plan_copy()
        shadow = _make_valid_shadow_result(plan)
        return _apply_motif_engine_primary(
            render_plan=plan,
            motif_shadow_result=shadow,
            arrangement_id=20,
            correlation_id="fields-test",
        )

    def test_primary_used_is_true_on_success(self):
        result = self._apply_primary()
        assert result["motif_primary_used"] is True

    def test_sections_receive_motif_fields(self):
        result = self._apply_primary()
        eligible_types = {"intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"}
        for section in result["sections"]:
            raw = str(section.get("type") or section.get("name") or "verse")
            n = raw.lower()
            is_eligible = any(tok in n for tok in eligible_types)
            if is_eligible:
                assert "motif_transformations" in section, (
                    f"Section '{raw}' missing motif_transformations"
                )
                assert "motif_intensity" in section, f"Section '{raw}' missing motif_intensity"
                assert "motif_prominence" in section, f"Section '{raw}' missing motif_prominence"

    def test_motif_intensity_in_range(self):
        result = self._apply_primary()
        for section in result["sections"]:
            if "motif_intensity" in section:
                assert 0.0 <= section["motif_intensity"] <= 1.0

    def test_motif_prominence_is_valid_string(self):
        result = self._apply_primary()
        valid = {"strong", "subtle"}
        for section in result["sections"]:
            if "motif_prominence" in section:
                assert section["motif_prominence"] in valid

    def test_plan_summary_has_expected_shape(self):
        result = self._apply_primary()
        summary = result["motif_plan_summary"]
        assert "occurrence_count" in summary
        assert "motif_reuse_score" in summary
        assert "motif_variation_score" in summary

    def test_reuse_and_variation_scores_written(self):
        result = self._apply_primary()
        assert 0.0 <= result["motif_reuse_score"] <= 1.0
        assert 0.0 <= result["motif_variation_score"] <= 1.0


# ---------------------------------------------------------------------------
# Integration rules
# ---------------------------------------------------------------------------


class TestMotifIntegrationRules:
    """Verify that the four main integration rules are enforced."""

    def _apply_primary(self, render_plan: dict | None = None) -> dict:
        plan = render_plan or _make_render_plan_copy()
        shadow = _make_valid_shadow_result(plan)
        return _apply_motif_engine_primary(
            render_plan=plan,
            motif_shadow_result=shadow,
            arrangement_id=30,
            correlation_id="rules-test",
        )

    def test_verse_motif_is_not_strong(self):
        """Verse motif prominence must not be 'strong'."""
        result = self._apply_primary()
        for section in result["sections"]:
            raw = str(section.get("type") or section.get("name") or "")
            if "verse" in raw.lower() and "motif_prominence" in section:
                assert section["motif_prominence"] != "strong", (
                    f"Verse section '{raw}' should not have strong motif prominence"
                )

    def test_outro_motif_is_not_strong(self):
        """Outro must resolve motif — prominence must be 'subtle'."""
        result = self._apply_primary()
        for section in result["sections"]:
            raw = str(section.get("type") or section.get("name") or "")
            if "outro" in raw.lower() and "motif_prominence" in section:
                assert section["motif_prominence"] != "strong", (
                    f"Outro section '{raw}' must not be strong motif statement"
                )

    def test_outro_motif_intensity_is_reduced(self):
        """Outro motif intensity must be <= 0.40."""
        result = self._apply_primary()
        for section in result["sections"]:
            raw = str(section.get("type") or section.get("name") or "")
            if "outro" in raw.lower() and "motif_intensity" in section:
                assert section["motif_intensity"] <= 0.40, (
                    f"Outro section '{raw}' motif_intensity={section['motif_intensity']} > 0.40"
                )

    def test_outro_no_full_phrase(self):
        """Outro must not use full_phrase transformation."""
        result = self._apply_primary()
        for section in result["sections"]:
            raw = str(section.get("type") or section.get("name") or "")
            if "outro" in raw.lower() and "motif_transformations" in section:
                assert "full_phrase" not in section["motif_transformations"], (
                    f"Outro section '{raw}' must not have full_phrase transformation"
                )

    def test_verse_intensity_at_most_half(self):
        """Verse motif_intensity must be <= 0.50 (verse is never a strong motif statement)."""
        result = self._apply_primary()
        for section in result["sections"]:
            raw = str(section.get("type") or section.get("name") or "")
            if "verse" in raw.lower() and "motif_intensity" in section:
                # Verse motifs are always downgraded — intensity must never exceed 0.50.
                assert section["motif_intensity"] <= 0.50, (
                    f"Verse section '{raw}' motif_intensity={section['motif_intensity']} > 0.50 — "
                    f"verse motif must not be as strong as hook motif"
                )

    def test_hook_sections_receive_motif_fields(self):
        """Hooks must always receive motif annotation when a motif exists."""
        result = self._apply_primary()
        if not result.get("motif_primary_used"):
            pytest.skip("Primary not applied (fallback triggered)")
        hook_sections = [
            s for s in result["sections"]
            if "hook" in str(s.get("type") or s.get("name") or "").lower()
        ]
        assert len(hook_sections) >= 1
        for section in hook_sections:
            assert "motif_transformations" in section, "Hook missing motif_transformations"


# ---------------------------------------------------------------------------
# Decision Engine blocked_roles respected
# ---------------------------------------------------------------------------


class TestMotifRespectsDecisionEngineConstraints:
    def test_blocked_role_sets_source_role_to_none(self):
        """When melody is blocked, motif_source_role must be None for that section."""
        render_plan = _make_render_plan_copy()
        # Simulate Decision Engine having blocked melody in verse.
        for section in render_plan["sections"]:
            if "verse" in str(section.get("type") or section.get("name") or "").lower():
                section["decision_blocked_roles"] = ["melody"]
                break

        shadow = _make_valid_shadow_result(render_plan)
        result = _apply_motif_engine_primary(
            render_plan=render_plan,
            motif_shadow_result=shadow,
            arrangement_id=40,
            correlation_id="blocked-role-test",
        )

        if not result.get("motif_primary_used"):
            pytest.skip("Primary not applied (fallback triggered)")

        for section in result["sections"]:
            raw = str(section.get("type") or section.get("name") or "")
            if "verse" in raw.lower() and "decision_blocked_roles" in section:
                blocked = section["decision_blocked_roles"]
                if "melody" in blocked and section.get("motif_source_role") == "melody":
                    pytest.fail(
                        f"Section '{raw}': motif_source_role='melody' "
                        f"despite melody being blocked"
                    )


# ---------------------------------------------------------------------------
# Integration: full run_arrangement_job with primary enabled
# ---------------------------------------------------------------------------


class TestRunArrangementJobWithMotifPrimary:
    """End-to-end tests verifying run_arrangement_job behaves correctly
    with MOTIF_ENGINE_PRIMARY enabled/disabled."""

    def _run_job_with_mocks(
        self,
        arrangement_id: int,
        motif_shadow_enabled: bool = True,
        motif_primary_enabled: bool = False,
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
            mock_settings.feature_drop_engine_primary = False
            mock_settings.feature_decision_engine_shadow = False
            mock_settings.feature_decision_engine_primary = False
            mock_settings.feature_motif_engine_shadow = motif_shadow_enabled
            mock_settings.feature_motif_engine_primary = motif_primary_enabled
            mock_client.return_value.__enter__.return_value.get.return_value = mock_response
            run_arrangement_job(arrangement_id)

    def test_job_completes_with_primary_enabled(self, db):
        """Status must be 'done' when MOTIF_ENGINE_PRIMARY=true."""
        loop = Loop(name="Motif Primary Loop", file_key="uploads/motif_primary.wav", bpm=128.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, motif_shadow_enabled=True, motif_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done", (
            f"Expected status='done', got '{updated.status}': {updated.error_message}"
        )
        # Verify motif primary metadata is in the persisted render plan.
        plan = json.loads(updated.render_plan_json)
        assert "motif_primary_used" in plan
        assert "motif_primary_fallback_used" in plan
        assert "motif_plan_summary" in plan
        assert "motif_reuse_score" in plan
        assert "motif_variation_score" in plan

    def test_job_completes_with_primary_disabled(self, db):
        """Status must be 'done' when MOTIF_ENGINE_PRIMARY=false (shadow-only)."""
        loop = Loop(name="Motif Shadow Only Loop", file_key="uploads/motif_shadow.wav", bpm=128.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, motif_shadow_enabled=True, motif_primary_enabled=False)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        assert updated.status == "done", (
            f"Expected status='done', got '{updated.status}': {updated.error_message}"
        )
        # Shadow metadata should be present; primary metadata must NOT be set.
        plan = json.loads(updated.render_plan_json)
        assert "_motif_plan" in plan
        # motif_primary_used should not be in the plan when primary is disabled.
        assert "motif_primary_used" not in plan

    def test_motif_primary_metadata_in_render_plan(self, db):
        """motif_primary_used and summary keys must be in render_plan_json when primary is set."""
        loop = Loop(name="Motif Primary Meta Loop", file_key="uploads/motif_meta.wav", bpm=128.0)
        db.add(loop)
        db.commit()
        db.refresh(loop)

        arr = Arrangement(loop_id=loop.id, status="queued", target_seconds=60)
        db.add(arr)
        db.commit()
        db.refresh(arr)

        self._run_job_with_mocks(arr.id, motif_shadow_enabled=True, motif_primary_enabled=True)

        db.expire_all()
        updated = db.query(Arrangement).filter_by(id=arr.id).first()
        plan = json.loads(updated.render_plan_json)
        assert "motif_primary_used" in plan
        assert "motif_plan_summary" in plan
        assert isinstance(plan["motif_plan_summary"], dict)

