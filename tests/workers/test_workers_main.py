"""Tests for app/workers/main.py — heartbeat, run_worker, _run_rq_worker."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, call, patch

import pytest


# ===========================================================================
# _heartbeat_loop
# ===========================================================================


class TestHeartbeatLoop:
    def test_logs_heartbeat_after_one_iteration(self):
        """Verify heartbeat loop logs at least once (stop after first sleep completes)."""
        import app.workers.main as workers_main

        call_count = [0]

        def _fake_sleep(seconds):
            call_count[0] += 1
            if call_count[0] >= 2:
                raise StopIteration("stop test")

        log_calls = []
        original_info = workers_main.logger.info

        def _capture_log(msg, *args, **kwargs):
            log_calls.append(msg)

        workers_main.logger.info = _capture_log
        try:
            with patch("app.workers.main.time.sleep", side_effect=_fake_sleep):
                with pytest.raises(StopIteration):
                    workers_main._heartbeat_loop()
        finally:
            workers_main.logger.info = original_info

        assert any("heartbeat" in str(m).lower() or "alive" in str(m).lower() for m in log_calls)


# ===========================================================================
# _run_rq_worker
# ===========================================================================


class TestRunRqWorker:
    def test_calls_ensure_db_models(self):
        import app.workers.main as workers_main

        mock_worker = MagicMock()
        mock_queue = MagicMock()
        mock_queue.name = "render"

        with (
            patch("app.workers.render_worker._ensure_db_models") as mock_ensure,
            patch("app.queue.get_redis_conn", return_value=MagicMock()),
            patch("app.queue.get_queue", return_value=mock_queue),
            patch("rq.SimpleWorker", return_value=mock_worker),
        ):
            workers_main._run_rq_worker()

        mock_ensure.assert_called_once()

    def test_worker_work_called(self):
        import app.workers.main as workers_main

        mock_worker = MagicMock()
        mock_queue = MagicMock()
        mock_queue.name = "render"

        with (
            patch("app.workers.render_worker._ensure_db_models"),
            patch("app.queue.get_redis_conn", return_value=MagicMock()),
            patch("app.queue.get_queue", return_value=mock_queue),
            patch("rq.SimpleWorker", return_value=mock_worker),
        ):
            workers_main._run_rq_worker()

        mock_worker.work.assert_called_once_with(with_scheduler=False)


# ===========================================================================
# run_worker
# ===========================================================================


class TestRunWorker:
    def test_calls_validate_startup(self):
        import app.workers.main as workers_main

        mock_rq_worker = MagicMock()

        with (
            patch.object(workers_main.settings, "validate_startup") as mock_validate,
            patch("app.workers.main._run_rq_worker", mock_rq_worker),
        ):
            workers_main.run_worker()

        mock_validate.assert_called_once()

    def test_starts_heartbeat_thread(self):
        import app.workers.main as workers_main

        started_threads = []
        original_start = threading.Thread.start

        def _fake_start(self):
            started_threads.append(self)

        with (
            patch.object(workers_main.settings, "validate_startup"),
            patch("app.workers.main._run_rq_worker"),
            patch.object(threading.Thread, "start", _fake_start),
        ):
            workers_main.run_worker()

        assert len(started_threads) >= 1

    def test_propagates_rq_worker_exception(self):
        import app.workers.main as workers_main

        with (
            patch.object(workers_main.settings, "validate_startup"),
            patch("app.workers.main._run_rq_worker", side_effect=RuntimeError("Redis unavailable")),
        ):
            with pytest.raises(RuntimeError, match="Redis unavailable"):
                workers_main.run_worker()
