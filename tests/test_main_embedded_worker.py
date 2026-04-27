"""Tests for app/main.py — _start_embedded_rq_worker_if_enabled and related helpers."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _start_embedded_rq_worker_if_enabled
# ---------------------------------------------------------------------------


class TestStartEmbeddedRqWorkerIfEnabled:
    def test_does_nothing_when_disabled(self):
        """When enable_embedded_rq_worker is False, no threads are started."""
        import app.main as main_mod

        original_threads = main_mod._embedded_worker_threads[:]
        with patch.object(main_mod.settings, "enable_embedded_rq_worker", False):
            main_mod._start_embedded_rq_worker_if_enabled()

        # Thread list should be unchanged (no new threads added)
        assert main_mod._embedded_worker_threads == original_threads

    def test_starts_thread_when_enabled(self):
        """When enable_embedded_rq_worker is True, a daemon thread is started."""
        import app.main as main_mod

        started = []

        class FakeThread:
            def __init__(self, target, name, daemon):
                self.name = name
                self.daemon = daemon
                self._target = target
                self._alive = True

            def start(self):
                started.append(self)

            def is_alive(self):
                return False

        original_threads = main_mod._embedded_worker_threads[:]
        main_mod._embedded_worker_threads = []

        try:
            with (
                patch.object(main_mod.settings, "enable_embedded_rq_worker", True),
                patch.object(main_mod.settings, "embedded_rq_worker_count", 1),
                patch("app.main.threading.Thread", FakeThread),
            ):
                main_mod._start_embedded_rq_worker_if_enabled()
        finally:
            main_mod._embedded_worker_threads = original_threads

        assert len(started) == 1
        assert started[0].daemon is True

    def test_does_not_start_extra_threads_when_already_running(self):
        """Does not add more threads when alive count already meets worker_count."""
        import app.main as main_mod

        alive_thread = MagicMock()
        alive_thread.is_alive.return_value = True

        original_threads = main_mod._embedded_worker_threads[:]
        main_mod._embedded_worker_threads = [alive_thread]

        started = []

        class FakeThread:
            def __init__(self, target, name, daemon):
                pass

            def start(self):
                started.append(self)

            def is_alive(self):
                return False

        try:
            with (
                patch.object(main_mod.settings, "enable_embedded_rq_worker", True),
                patch.object(main_mod.settings, "embedded_rq_worker_count", 1),
                patch("app.main.threading.Thread", FakeThread),
            ):
                main_mod._start_embedded_rq_worker_if_enabled()
        finally:
            main_mod._embedded_worker_threads = original_threads

        assert len(started) == 0

    def test_starts_multiple_threads_when_worker_count_greater_than_one(self):
        """Starts the correct number of worker threads."""
        import app.main as main_mod

        started = []

        class FakeThread:
            def __init__(self, target, name, daemon):
                self.name = name
                self.daemon = daemon

            def start(self):
                started.append(self)

            def is_alive(self):
                return False

        original_threads = main_mod._embedded_worker_threads[:]
        main_mod._embedded_worker_threads = []

        try:
            with (
                patch.object(main_mod.settings, "enable_embedded_rq_worker", True),
                patch.object(main_mod.settings, "embedded_rq_worker_count", 3),
                patch("app.main.threading.Thread", FakeThread),
            ):
                main_mod._start_embedded_rq_worker_if_enabled()
        finally:
            main_mod._embedded_worker_threads = original_threads

        assert len(started) == 3

    def test_thread_names_include_embedded_rq_worker(self):
        """Thread names follow the expected naming pattern."""
        import app.main as main_mod

        names = []

        class FakeThread:
            def __init__(self, target, name, daemon):
                names.append(name)
                self.name = name
                self.daemon = daemon

            def start(self):
                pass

            def is_alive(self):
                return False

        original_threads = main_mod._embedded_worker_threads[:]
        main_mod._embedded_worker_threads = []

        try:
            with (
                patch.object(main_mod.settings, "enable_embedded_rq_worker", True),
                patch.object(main_mod.settings, "embedded_rq_worker_count", 2),
                patch("app.main.threading.Thread", FakeThread),
            ):
                main_mod._start_embedded_rq_worker_if_enabled()
        finally:
            main_mod._embedded_worker_threads = original_threads

        for name in names:
            assert "embedded-rq-worker" in name


# ---------------------------------------------------------------------------
# _run_dev_migrations
# ---------------------------------------------------------------------------


class TestRunDevMigrations:
    def test_calls_alembic_upgrade(self):
        from app.main import _run_dev_migrations

        mock_command = MagicMock()
        mock_config = MagicMock()

        with (
            patch("app.main.settings") as mock_settings,
            patch("alembic.config.Config", return_value=mock_config),
            patch("alembic.command.upgrade", mock_command),
        ):
            mock_settings.database_url = "sqlite:///test.db"
            _run_dev_migrations()

        mock_command.assert_called_once_with(mock_config, "head")

    def test_raises_runtime_error_on_alembic_failure(self):
        from app.main import _run_dev_migrations

        with patch("alembic.config.Config", side_effect=Exception("alembic error")):
            with pytest.raises(RuntimeError, match="Dev database migration failed"):
                _run_dev_migrations()
