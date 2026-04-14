"""
Tests for Phase 3 render truthfulness and observability.

Covers:
1. success_truthful (stems, no fallback)
2. success_with_fallbacks (stem fallback triggered)
3. failure with failure_stage
4. mastering_applied recorded correctly
5. render_metadata present in job status response
6. section_execution_report correctness
7. deterministic render_signatures
8. worker_mode accuracy
9. backward compatibility (old jobs without render_metadata)
10. planned vs actual stem map comparison
"""
from __future__ import annotations

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment

from app.services.render_observability import (
    assemble_render_metadata,
    determine_job_terminal_state,
    extract_observability_from_arrangement,
    get_worker_mode,
    resolve_feature_flags_snapshot,
)
from app.services.render_executor import (
    _build_render_observability,
    _derive_source_quality_mode,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_silent(ms: int = 500) -> AudioSegment:
    """Create a short silent AudioSegment for testing."""
    return AudioSegment.silent(duration=ms)


def _make_mock_mastering_result(applied: bool, profile: str = "transparent"):
    result = MagicMock()
    result.applied = applied
    result.profile = profile
    result.peak_dbfs_before = -6.0
    result.peak_dbfs_after = -1.5
    result.audio = _make_silent()
    return result


def _timeline_with_sections(sections: list[dict]) -> str:
    """Build a minimal timeline JSON with render_spec_summary."""
    phrase_splits = sum(1 for s in sections if s.get("phrase_plan_used"))
    stem_sets = [frozenset(s.get("runtime_active_stems") or []) for s in sections]
    from collections import Counter
    counts = Counter(stem_sets)
    return json.dumps({
        "sections": sections,
        "render_spec_summary": {
            "sections_count": len(sections),
            "phrase_split_count": phrase_splits,
            "distinct_stem_set_count": len(counts),
            "most_reused_stem_set_count": max(counts.values()) if counts else 0,
            "hook_stages": [
                s.get("hook_evolution", {}).get("stage")
                for s in sections
                if s.get("hook_evolution")
            ],
            "transition_event_count": sum(len(s.get("applied_events") or []) for s in sections),
        },
    })


# ---------------------------------------------------------------------------
# 1. success_truthful state
# ---------------------------------------------------------------------------

class TestJobTerminalState:
    def test_success_truthful_no_fallbacks(self):
        state = determine_job_terminal_state(
            success=True,
            fallback_triggered_count=0,
            failure_stage=None,
            error_message=None,
        )
        assert state == "success_truthful"

    def test_success_with_fallbacks(self):
        state = determine_job_terminal_state(
            success=True,
            fallback_triggered_count=3,
            failure_stage=None,
            error_message=None,
        )
        assert state == "success_with_fallbacks"

    def test_failed_storage(self):
        state = determine_job_terminal_state(
            success=False,
            fallback_triggered_count=0,
            failure_stage="storage",
            error_message=None,
        )
        assert state == "failed_storage"

    def test_failed_executor(self):
        state = determine_job_terminal_state(
            success=False,
            fallback_triggered_count=0,
            failure_stage="execution",
            error_message=None,
        )
        assert state == "failed_executor"

    def test_failed_mastering(self):
        state = determine_job_terminal_state(
            success=False,
            fallback_triggered_count=0,
            failure_stage="mastering",
            error_message=None,
        )
        assert state == "failed_mastering"

    def test_failed_plan_validation(self):
        state = determine_job_terminal_state(
            success=False,
            fallback_triggered_count=0,
            failure_stage="render_plan",
            error_message=None,
        )
        assert state == "failed_plan_validation"

    def test_failed_timeout_via_message(self):
        state = determine_job_terminal_state(
            success=False,
            fallback_triggered_count=0,
            failure_stage=None,
            error_message="Render pipeline exceeded timeout of 900s",
        )
        assert state == "failed_timeout"

    def test_failed_unknown_fallback(self):
        state = determine_job_terminal_state(
            success=False,
            fallback_triggered_count=0,
            failure_stage=None,
            error_message="unexpected database error",
        )
        assert state == "failed_unknown"


# ---------------------------------------------------------------------------
# 2. worker_mode
# ---------------------------------------------------------------------------

class TestWorkerMode:
    def test_embedded_mode(self):
        with patch("app.services.render_observability.settings") as mock_settings:
            mock_settings.enable_embedded_rq_worker = True
            assert get_worker_mode() == "embedded"

    def test_external_mode(self):
        with patch("app.services.render_observability.settings") as mock_settings:
            mock_settings.enable_embedded_rq_worker = False
            assert get_worker_mode() == "external"

    def test_unknown_mode_on_error(self):
        with patch(
            "app.services.render_observability.settings",
            new_callable=lambda: type("S", (), {"enable_embedded_rq_worker": property(lambda s: (_ for _ in ()).throw(Exception("broken")))}),
        ):
            # If accessing the setting raises an exception, return "unknown"
            # Re-implement inline to test the try/except in get_worker_mode
            import app.services.render_observability as mod
            original = mod.settings
            try:

                class _BrokenSettings:
                    @property
                    def enable_embedded_rq_worker(self):
                        raise RuntimeError("no settings")

                mod.settings = _BrokenSettings()
                result = get_worker_mode()
                assert result == "unknown"
            finally:
                mod.settings = original


# ---------------------------------------------------------------------------
# 3. source_quality_mode
# ---------------------------------------------------------------------------

class TestSourceQualityMode:
    def test_stereo_fallback_no_stems(self):
        mode = _derive_source_quality_mode({}, None, {})
        assert mode == "stereo_fallback"

    def test_true_stems(self):
        stems = {"drums": _make_silent(), "bass": _make_silent()}
        mode = _derive_source_quality_mode({}, stems, {})
        assert mode == "true_stems"

    def test_ai_separated_demucs(self):
        stems = {"drums": _make_silent()}
        mode = _derive_source_quality_mode({}, stems, {"backend": "demucs"})
        assert mode == "ai_separated"

    def test_zip_stems(self):
        stems = {"drums": _make_silent()}
        render_plan = {"loop_variations": {"stems_used": True}}
        mode = _derive_source_quality_mode(render_plan, stems, {})
        assert mode == "zip_stems"


# ---------------------------------------------------------------------------
# 4. _build_render_observability
# ---------------------------------------------------------------------------

class TestBuildRenderObservability:
    def _planned_sections(self):
        return [
            {"type": "intro", "instruments": ["melody", "pads"]},
            {"type": "verse", "instruments": ["drums", "bass"]},
            {"type": "hook", "instruments": ["drums", "bass", "melody"]},
            {"type": "outro", "instruments": ["melody"]},
        ]

    def _timeline_sections(self, fallback: bool = False):
        secs = [
            {
                "type": "intro",
                "active_stem_roles": ["melody", "pads"],
                "runtime_active_stems": ["melody", "pads"],
                "phrase_plan_used": False,
                "applied_events": [],
                "_stem_fallback_all": False,
            },
            {
                "type": "verse",
                "active_stem_roles": ["drums", "bass"],
                "runtime_active_stems": ["drums", "bass"],
                "phrase_plan_used": False,
                "applied_events": ["bridge_strip"],
                "_stem_fallback_all": fallback,
            },
            {
                "type": "hook",
                "active_stem_roles": ["drums", "bass", "melody"],
                "runtime_active_stems": ["drums", "bass", "melody"],
                "phrase_plan_used": True,
                "applied_events": [],
                "_stem_fallback_all": False,
                "hook_evolution": {"stage": "hook1"},
            },
            {
                "type": "outro",
                "active_stem_roles": ["melody"],
                "runtime_active_stems": ["melody"],
                "phrase_plan_used": False,
                "applied_events": [],
                "_stem_fallback_all": False,
            },
        ]
        return secs

    def test_no_fallback(self):
        timeline = _timeline_with_sections(self._timeline_sections())
        mastering = _make_mock_mastering_result(applied=True)
        obs = _build_render_observability(
            timeline_json=timeline,
            render_path_used="stem_render_executor",
            source_quality_mode_used="true_stems",
            mastering_result=mastering,
            render_plan_sections=self._planned_sections(),
        )
        assert obs["render_path_used"] == "stem_render_executor"
        assert obs["fallback_triggered_count"] == 0
        assert obs["fallback_reasons"] == []
        assert obs["mastering_applied"] is True
        assert obs["mastering_profile"] == "transparent"
        assert obs["phrase_split_count"] == 1  # one section has phrase_plan_used=True
        assert len(obs["section_execution_report"]) == 4
        assert len(obs["render_signatures"]) == 4

    def test_fallback_section_detected(self):
        secs = self._timeline_sections(fallback=True)
        timeline = _timeline_with_sections(secs)
        mastering = _make_mock_mastering_result(applied=False)
        obs = _build_render_observability(
            timeline_json=timeline,
            render_path_used="stem_render_executor",
            source_quality_mode_used="true_stems",
            mastering_result=mastering,
            render_plan_sections=self._planned_sections(),
        )
        assert obs["fallback_triggered_count"] == 1
        assert "missing_required_stem_role" in obs["fallback_reasons"]
        assert obs["mastering_applied"] is False

    def test_stereo_fallback_path(self):
        timeline = _timeline_with_sections(self._timeline_sections())
        mastering = _make_mock_mastering_result(applied=False)
        obs = _build_render_observability(
            timeline_json=timeline,
            render_path_used="stereo_fallback",
            source_quality_mode_used="stereo_fallback",
            mastering_result=mastering,
            render_plan_sections=self._planned_sections(),
        )
        assert obs["render_path_used"] == "stereo_fallback"
        assert "full_mix_only_available" in obs["fallback_reasons"]

    def test_planned_vs_actual_maps_present(self):
        timeline = _timeline_with_sections(self._timeline_sections())
        mastering = _make_mock_mastering_result(applied=True)
        obs = _build_render_observability(
            timeline_json=timeline,
            render_path_used="stem_render_executor",
            source_quality_mode_used="true_stems",
            mastering_result=mastering,
            render_plan_sections=self._planned_sections(),
        )
        assert len(obs["planned_stem_map_by_section"]) == 4
        assert len(obs["actual_stem_map_by_section"]) == 4
        # Planned intro should list melody and pads
        intro_planned = next(s for s in obs["planned_stem_map_by_section"] if s["section_type"] == "intro")
        assert set(intro_planned["roles"]) == {"melody", "pads"}

    def test_section_execution_report_fields(self):
        timeline = _timeline_with_sections(self._timeline_sections())
        mastering = _make_mock_mastering_result(applied=True)
        obs = _build_render_observability(
            timeline_json=timeline,
            render_path_used="stem_render_executor",
            source_quality_mode_used="true_stems",
            mastering_result=mastering,
            render_plan_sections=self._planned_sections(),
        )
        for row in obs["section_execution_report"]:
            assert "section_index" in row
            assert "section_type" in row
            assert "planned_roles" in row
            assert "actual_roles" in row
            assert "dropped_roles" in row
            assert "fallback_used" in row
            assert "render_signature" in row
            assert len(row["render_signature"]) == 12


# ---------------------------------------------------------------------------
# 5. Deterministic render_signatures
# ---------------------------------------------------------------------------

class TestRenderSignatures:
    def _make_obs_for_roles(self, roles_list: list[list[str]]) -> dict:
        """Build observability for sections with given roles."""
        sections = [
            {
                "type": "verse",
                "active_stem_roles": roles,
                "runtime_active_stems": roles,
                "phrase_plan_used": False,
                "applied_events": [],
                "_stem_fallback_all": False,
            }
            for roles in roles_list
        ]
        timeline = _timeline_with_sections(sections)
        mastering = _make_mock_mastering_result(applied=False)
        return _build_render_observability(
            timeline_json=timeline,
            render_path_used="stem_render_executor",
            source_quality_mode_used="true_stems",
            mastering_result=mastering,
            render_plan_sections=[{"type": "verse", "instruments": r} for r in roles_list],
        )

    def test_same_roles_same_signature(self):
        obs1 = self._make_obs_for_roles([["drums", "bass"]])
        obs2 = self._make_obs_for_roles([["drums", "bass"]])
        assert obs1["render_signatures"][0] == obs2["render_signatures"][0]

    def test_different_roles_different_signature(self):
        obs1 = self._make_obs_for_roles([["drums", "bass"]])
        obs2 = self._make_obs_for_roles([["melody", "pads"]])
        assert obs1["render_signatures"][0] != obs2["render_signatures"][0]

    def test_identical_sections_detected(self):
        """If two sections have the same role set, unique_render_signature_count < total."""
        obs = self._make_obs_for_roles([["drums", "bass"], ["drums", "bass"], ["melody"]])
        # two identical sections → only 2 unique signatures
        assert obs["unique_render_signature_count"] == 2

    def test_all_different_signatures(self):
        obs = self._make_obs_for_roles([["drums"], ["bass"], ["melody"], ["pads"]])
        assert obs["unique_render_signature_count"] == 4


# ---------------------------------------------------------------------------
# 6. assemble_render_metadata
# ---------------------------------------------------------------------------

class TestAssembleRenderMetadata:
    def test_all_fields_present(self):
        obs = {
            "fallback_triggered_count": 1,
            "fallback_sections_count": 1,
            "fallback_reasons": ["missing_required_stem_role"],
            "planned_stem_map_by_section": [],
            "actual_stem_map_by_section": [],
            "section_execution_report": [],
            "render_signatures": ["abc123"],
            "unique_render_signature_count": 1,
            "phrase_split_count": 2,
            "distinct_stem_set_count": 1,
            "hook_stages_rendered": ["hook1"],
            "transition_event_count": 5,
            "mastering_applied": True,
            "mastering_profile": "transparent",
        }
        mastering_info = {
            "applied": True,
            "profile": "transparent",
            "peak_dbfs_before": -6.0,
            "peak_dbfs_after": -1.5,
        }
        metadata = assemble_render_metadata(
            worker_mode="external",
            job_terminal_state="success_with_fallbacks",
            failure_stage=None,
            render_path_used="stem_render_executor",
            source_quality_mode_used="true_stems",
            observability=obs,
            mastering_info=mastering_info,
            feature_flags_snapshot={"feature_mastering_stage": True},
        )
        assert metadata["worker_mode"] == "external"
        assert metadata["job_terminal_state"] == "success_with_fallbacks"
        assert metadata["failure_stage"] is None
        assert metadata["render_path_used"] == "stem_render_executor"
        assert metadata["source_quality_mode_used"] == "true_stems"
        assert metadata["fallback_triggered_count"] == 1
        assert metadata["fallback_reasons"] == ["missing_required_stem_role"]
        assert metadata["mastering_applied"] is True
        assert metadata["mastering_profile"] == "transparent"
        assert metadata["mastering_peak_dbfs_before"] == -6.0
        assert metadata["mastering_peak_dbfs_after"] == -1.5
        assert metadata["feature_flags_snapshot"]["feature_mastering_stage"] is True
        assert metadata["phrase_split_count"] == 2
        assert metadata["hook_stages_rendered"] == ["hook1"]

    def test_failure_metadata(self):
        metadata = assemble_render_metadata(
            worker_mode="embedded",
            job_terminal_state="failed_executor",
            failure_stage="execution",
            render_path_used="unknown",
            source_quality_mode_used="unknown",
            observability={},
        )
        assert metadata["job_terminal_state"] == "failed_executor"
        assert metadata["failure_stage"] == "execution"
        assert metadata["fallback_triggered_count"] == 0


# ---------------------------------------------------------------------------
# 7. extract_observability_from_arrangement
# ---------------------------------------------------------------------------

class TestExtractObservabilityFromArrangement:
    def _make_arrangement(self, timeline_sections, render_plan_sections):
        row = MagicMock()
        row.arrangement_json = _timeline_with_sections(timeline_sections)
        row.render_plan_json = json.dumps({
            "bpm": 120,
            "sections": render_plan_sections,
        })
        return row

    def test_basic_extraction(self):
        timeline_secs = [
            {
                "type": "intro",
                "active_stem_roles": ["melody"],
                "runtime_active_stems": ["melody"],
                "phrase_plan_used": False,
                "applied_events": [],
                "_stem_fallback_all": False,
            },
            {
                "type": "hook",
                "active_stem_roles": ["drums", "bass"],
                "runtime_active_stems": ["drums", "bass"],
                "phrase_plan_used": True,
                "applied_events": ["crash_hit"],
                "_stem_fallback_all": False,
                "hook_evolution": {"stage": "hook1"},
            },
        ]
        planned_secs = [
            {"type": "intro", "instruments": ["melody"]},
            {"type": "hook", "instruments": ["drums", "bass"]},
        ]
        row = self._make_arrangement(timeline_secs, planned_secs)
        obs = extract_observability_from_arrangement(row)

        assert obs["fallback_triggered_count"] == 0
        assert obs["phrase_split_count"] == 1
        assert len(obs["planned_stem_map_by_section"]) == 2
        assert len(obs["actual_stem_map_by_section"]) == 2
        assert len(obs["section_execution_report"]) == 2
        assert obs["unique_render_signature_count"] == 2

    def test_fallback_section_counted(self):
        timeline_secs = [
            {
                "type": "verse",
                "active_stem_roles": ["drums"],
                "runtime_active_stems": ["drums", "bass", "melody", "pads"],
                "phrase_plan_used": False,
                "applied_events": [],
                "_stem_fallback_all": True,
            },
        ]
        planned_secs = [{"type": "verse", "instruments": ["drums"]}]
        row = self._make_arrangement(timeline_secs, planned_secs)
        obs = extract_observability_from_arrangement(row)

        assert obs["fallback_triggered_count"] == 1
        assert "missing_required_stem_role" in obs["fallback_reasons"]

    def test_handles_missing_arrangement_json(self):
        row = MagicMock()
        row.arrangement_json = None
        row.render_plan_json = None
        obs = extract_observability_from_arrangement(row)
        assert obs["fallback_triggered_count"] == 0
        assert obs["planned_stem_map_by_section"] == []


# ---------------------------------------------------------------------------
# 8. job_service render_metadata persistence (unit)
# ---------------------------------------------------------------------------

class TestJobServiceRenderMetadata:
    def test_update_job_status_persists_render_metadata(self):
        """update_job_status should serialize render_metadata to render_metadata_json."""
        from app.services.job_service import update_job_status

        mock_job = MagicMock()
        mock_job.id = "test-job-id"
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        render_meta = {
            "render_path_used": "stem_render_executor",
            "job_terminal_state": "success_truthful",
            "worker_mode": "external",
        }

        update_job_status(
            mock_db,
            "test-job-id",
            "succeeded",
            render_metadata=render_meta,
        )

        # render_metadata_json should have been set
        assert mock_job.render_metadata_json == json.dumps(render_meta)

    def test_get_job_status_includes_render_metadata(self):
        """get_job_status should parse and surface render_metadata."""
        from app.services.job_service import get_job_status

        render_meta = {
            "render_path_used": "stereo_fallback",
            "job_terminal_state": "success_with_fallbacks",
            "worker_mode": "embedded",
            "fallback_triggered_count": 2,
        }

        mock_job = MagicMock()
        mock_job.id = "job-123"
        mock_job.loop_id = 1
        mock_job.job_type = "render_arrangement"
        mock_job.status = "succeeded"
        mock_job.progress = 100.0
        mock_job.progress_message = None
        mock_job.created_at = __import__("datetime").datetime.utcnow()
        mock_job.started_at = None
        mock_job.finished_at = None
        mock_job.output_files_json = None
        mock_job.error_message = None
        mock_job.retry_count = 0
        mock_job.render_metadata_json = json.dumps(render_meta)

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        response = get_job_status(mock_db, "job-123")

        assert response.render_metadata is not None
        assert response.render_metadata["render_path_used"] == "stereo_fallback"
        assert response.render_metadata["fallback_triggered_count"] == 2

    def test_backward_compat_no_render_metadata(self):
        """Jobs without render_metadata_json should return render_metadata=None."""
        from app.services.job_service import get_job_status

        mock_job = MagicMock()
        mock_job.id = "old-job"
        mock_job.loop_id = 1
        mock_job.job_type = "render_arrangement"
        mock_job.status = "succeeded"
        mock_job.progress = 100.0
        mock_job.progress_message = None
        mock_job.created_at = __import__("datetime").datetime.utcnow()
        mock_job.started_at = None
        mock_job.finished_at = None
        mock_job.output_files_json = None
        mock_job.error_message = None
        mock_job.retry_count = 0
        mock_job.render_metadata_json = None

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_job

        response = get_job_status(mock_db, "old-job")
        # Backward compatible: must not raise, render_metadata should be None
        assert response.render_metadata is None


# ---------------------------------------------------------------------------
# 9. feature_flags snapshot
# ---------------------------------------------------------------------------

class TestFeatureFlagsSnapshot:
    def test_snapshot_contains_mastering_flag(self):
        snapshot = resolve_feature_flags_snapshot()
        assert "feature_mastering_stage" in snapshot

    def test_snapshot_contains_all_expected_flags(self):
        snapshot = resolve_feature_flags_snapshot()
        expected_keys = [
            "feature_producer_section_identity_v2",
            "feature_section_choreography_v2",
            "feature_stem_separation",
            "feature_mastering_stage",
            "enable_embedded_rq_worker",
        ]
        for key in expected_keys:
            assert key in snapshot, f"Missing flag: {key}"


# ---------------------------------------------------------------------------
# 10. RenderJobStatusResponse schema backward compat
# ---------------------------------------------------------------------------

class TestSchemaBackwardCompat:
    def test_render_metadata_is_optional(self):
        """RenderJobStatusResponse must be creatable without render_metadata."""
        from datetime import datetime
        from app.schemas.job import RenderJobStatusResponse

        resp = RenderJobStatusResponse(
            job_id="test",
            loop_id=1,
            job_type="render_arrangement",
            status="succeeded",
            progress=100.0,
            created_at=datetime.utcnow(),
        )
        assert resp.render_metadata is None

    def test_render_metadata_field_accepted(self):
        """RenderJobStatusResponse must accept render_metadata dict."""
        from datetime import datetime
        from app.schemas.job import RenderJobStatusResponse

        resp = RenderJobStatusResponse(
            job_id="test",
            loop_id=1,
            job_type="render_arrangement",
            status="succeeded",
            progress=100.0,
            created_at=datetime.utcnow(),
            render_metadata={
                "render_path_used": "stem_render_executor",
                "job_terminal_state": "success_truthful",
            },
        )
        assert resp.render_metadata["render_path_used"] == "stem_render_executor"
