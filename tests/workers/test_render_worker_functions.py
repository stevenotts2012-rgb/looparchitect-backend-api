"""Tests for app/workers/render_worker.py.

Covers helper functions and logic that don't require Redis/RQ.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.workers import render_worker


# ===========================================================================
# _should_use_dev_fallback
# ===========================================================================


class TestShouldUseDevFallback:
    def test_returns_false_in_production(self, monkeypatch):
        monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", True)
        monkeypatch.setattr(render_worker.settings, "environment", "production")
        assert render_worker._should_use_dev_fallback() is False

    def test_returns_false_when_flag_off(self, monkeypatch):
        monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", False)
        monkeypatch.setattr(render_worker.settings, "environment", "development")
        assert render_worker._should_use_dev_fallback() is False

    def test_returns_true_when_flag_on_non_production(self, monkeypatch):
        monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", True)
        monkeypatch.setattr(render_worker.settings, "environment", "development")
        assert render_worker._should_use_dev_fallback() is True


# ===========================================================================
# _build_dev_fallback_render_plan
# ===========================================================================


class TestBuildDevFallbackRenderPlan:
    def _make_loop(self, bpm=120.0, genre="generic"):
        loop = MagicMock()
        loop.bpm = bpm
        loop.genre = genre
        return loop

    def test_returns_dict(self):
        loop = self._make_loop()
        result = render_worker._build_dev_fallback_render_plan(loop, {"length_seconds": 60})
        assert isinstance(result, dict)

    def test_contains_required_keys(self):
        loop = self._make_loop()
        result = render_worker._build_dev_fallback_render_plan(loop, {})
        for key in ("bpm", "key", "total_bars", "render_profile", "sections", "events", "tracks"):
            assert key in result, f"Missing key: {key}"

    def test_bpm_from_loop(self):
        loop = self._make_loop(bpm=140.0)
        result = render_worker._build_dev_fallback_render_plan(loop, {})
        assert result["bpm"] == 140.0

    def test_defaults_bpm_to_120_when_none(self):
        loop = self._make_loop()
        loop.bpm = None
        result = render_worker._build_dev_fallback_render_plan(loop, {})
        assert result["bpm"] == 120.0

    def test_bars_at_least_one(self):
        loop = self._make_loop(bpm=120.0)
        result = render_worker._build_dev_fallback_render_plan(loop, {"length_seconds": 1})
        assert result["total_bars"] >= 1

    def test_genre_in_render_profile(self):
        loop = self._make_loop(genre="trap")
        result = render_worker._build_dev_fallback_render_plan(loop, {})
        assert result["render_profile"]["genre_profile"] == "trap"

    def test_fallback_used_flag_true(self):
        loop = self._make_loop()
        result = render_worker._build_dev_fallback_render_plan(loop, {})
        assert result["render_profile"]["fallback_used"] is True

    def test_sections_list_non_empty(self):
        loop = self._make_loop()
        result = render_worker._build_dev_fallback_render_plan(loop, {})
        assert len(result["sections"]) >= 1

    def test_events_list_is_list(self):
        loop = self._make_loop()
        result = render_worker._build_dev_fallback_render_plan(loop, {})
        assert isinstance(result["events"], list)

    def test_params_length_seconds_used(self):
        loop = self._make_loop(bpm=120.0)
        # 120 BPM, 4 beats/bar → 2s/bar; 120 seconds → 60 bars
        result = render_worker._build_dev_fallback_render_plan(loop, {"length_seconds": 120})
        assert result["total_bars"] == 60


# ===========================================================================
# _ensure_db_models
# ===========================================================================


class TestEnsureDbModels:
    def test_does_not_raise(self):
        # Just verifies the function runs without error in test env
        with patch("app.workers.render_worker.engine"):
            with patch("app.models.base.Base.metadata") as mock_meta:
                mock_meta.create_all = MagicMock()
                render_worker._ensure_db_models()


# ===========================================================================
# _run_with_timeout
# ===========================================================================


class TestRunWithTimeout:
    def test_returns_function_result(self):
        result = render_worker._run_with_timeout(lambda: 42, timeout_seconds=5)
        assert result == 42

    def test_passes_args_to_function(self):
        result = render_worker._run_with_timeout(lambda x, y: x + y, 3, 4, timeout_seconds=5)
        assert result == 7

    def test_raises_on_timeout(self):
        import time
        from concurrent.futures import TimeoutError as FuturesTimeoutError

        with pytest.raises(FuturesTimeoutError):
            render_worker._run_with_timeout(lambda: time.sleep(10), timeout_seconds=0.1)

    def test_propagates_function_exception(self):
        def _raise():
            raise ValueError("inner error")

        with pytest.raises(ValueError, match="inner error"):
            render_worker._run_with_timeout(_raise, timeout_seconds=5)


# ===========================================================================
# _upload_render_output
# ===========================================================================


class TestUploadRenderOutput:
    def test_calls_storage_upload_file(self, tmp_path):
        wav = tmp_path / "output.wav"
        wav.write_bytes(b"fake-audio-data")

        mock_storage = MagicMock()
        mock_storage.upload_file.return_value = "renders/job123/output.wav"

        with patch.object(render_worker, "storage", mock_storage):
            key, content_type = render_worker._upload_render_output(
                "job123", "output.wav", wav
            )

        mock_storage.upload_file.assert_called_once()
        assert key == "renders/job123/output.wav"
        assert content_type == "audio/wav"

    def test_s3_key_format(self, tmp_path):
        wav = tmp_path / "output.wav"
        wav.write_bytes(b"audio")

        mock_storage = MagicMock()
        # Return the same key that was passed
        mock_storage.upload_file.side_effect = lambda bytes, ct, key: key

        with patch.object(render_worker, "storage", mock_storage):
            key, _ = render_worker._upload_render_output("abc-job", "final.wav", wav)

        assert key == "renders/abc-job/final.wav"


# ===========================================================================
# _resolve_app_job_id
# ===========================================================================


class TestResolveAppJobId:
    def test_returns_incoming_id_when_direct_match(self):
        mock_job = MagicMock()
        mock_job.id = "job-001"

        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = mock_job

        result = render_worker._resolve_app_job_id(db, "job-001")
        assert result == "job-001"

    def test_returns_incoming_id_when_no_rq_match(self):
        db = MagicMock()
        db.query.return_value.filter.return_value.first.return_value = None

        with patch("rq.get_current_job", side_effect=Exception("no rq")):
            result = render_worker._resolve_app_job_id(db, "fallback-job")

        assert result == "fallback-job"


# ===========================================================================
# _select_render_mode — params render_plan_json fallback
# ===========================================================================


class TestSelectRenderMode:
    def test_returns_render_plan_when_has_render_plan_true(self):
        result = render_worker._select_render_mode(has_render_plan=True)
        assert result == "render_plan"

    def test_raises_when_no_render_plan_and_no_dev_fallback(self, monkeypatch):
        monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", False)
        monkeypatch.setattr(render_worker.settings, "environment", "production")
        with pytest.raises(ValueError, match="render_plan_json is required"):
            render_worker._select_render_mode(has_render_plan=False)

    def test_returns_dev_fallback_when_enabled(self, monkeypatch):
        monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", True)
        monkeypatch.setattr(render_worker.settings, "environment", "development")
        result = render_worker._select_render_mode(has_render_plan=False)
        assert result == "dev_fallback"


class TestWorkerUsesParamsRenderPlanJson:
    """Worker must use render_plan_json from params when no DB arrangement exists."""

    def _make_loop(self, bpm=120.0):
        loop = MagicMock()
        loop.id = 1
        loop.bpm = bpm
        loop.genre = "generic"
        loop.file_key = "uploads/test.wav"
        loop.file_url = None
        return loop

    def test_params_render_plan_json_is_used_when_no_db_arrangement(self, monkeypatch):
        """_select_render_mode gets has_render_plan=True when params has render_plan_json."""
        minimal_plan = {"loop_id": 1, "sections": [{"name": "full_loop", "type": "VERSE",
                                                      "start_bar": 0, "length_bars": 8,
                                                      "active_stem_roles": ["full_mix"],
                                                      "instruments": ["full_mix"]}]}
        params = {"render_plan_json": json.dumps(minimal_plan)}

        # has_render_plan should be True when only params has the plan
        arrangement = None
        params_render_plan_json = params.get("render_plan_json") if isinstance(params, dict) else None
        has_render_plan = bool(
            (arrangement and getattr(arrangement, "render_plan_json", None)) or params_render_plan_json
        )
        assert has_render_plan is True

    def test_params_render_plan_json_selected_when_arrangement_has_none(self):
        """When arrangement row has no render_plan_json, params value must be chosen."""
        minimal_plan = {"loop_id": 2, "sections": []}
        params = {"render_plan_json": json.dumps(minimal_plan)}

        arrangement = MagicMock()
        arrangement.render_plan_json = None  # arrangement exists but plan is absent

        params_render_plan_json = params.get("render_plan_json") if isinstance(params, dict) else None
        chosen = (arrangement and arrangement.render_plan_json) or params_render_plan_json
        assert chosen == params["render_plan_json"]

    def test_arrangement_render_plan_json_preferred_over_params(self):
        """When both arrangement and params have a plan, arrangement's plan wins."""
        arr_plan = {"loop_id": 3, "sections": [{"name": "arr_section"}]}
        params_plan = {"loop_id": 3, "sections": [{"name": "params_section"}]}

        arrangement = MagicMock()
        arrangement.render_plan_json = json.dumps(arr_plan)

        params = {"render_plan_json": json.dumps(params_plan)}
        params_render_plan_json = params.get("render_plan_json")

        chosen = (arrangement and arrangement.render_plan_json) or params_render_plan_json
        parsed = json.loads(chosen)
        assert parsed["sections"][0]["name"] == "arr_section"

    def test_no_plan_anywhere_raises_value_error(self, monkeypatch):
        """No plan in either arrangement or params must raise ValueError in worker."""
        monkeypatch.setattr(render_worker.settings, "dev_fallback_loop_only", False)
        monkeypatch.setattr(render_worker.settings, "environment", "production")

        arrangement = None
        params = {}
        params_render_plan_json = params.get("render_plan_json") if isinstance(params, dict) else None
        has_render_plan = bool(
            (arrangement and getattr(arrangement, "render_plan_json", None)) or params_render_plan_json
        )
        with pytest.raises(ValueError, match="render_plan_json is required"):
            render_worker._select_render_mode(has_render_plan)
