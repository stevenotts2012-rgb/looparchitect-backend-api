"""
Tests for app/queue.py – previously-untested paths.

Covers:
- is_redis_available() → True when Redis is reachable
- is_redis_available() → False when REDIS_URL not configured
- is_redis_available() → False when connection fails
- get_redis_conn() raises RuntimeError when REDIS_URL absent
- get_redis_conn() logs and re-raises on connection failure
- get_queue() calls get_redis_conn() when conn=None
- get_queue() uses supplied conn without calling get_redis_conn()
- DEFAULT_RENDER_QUEUE_NAME constant value
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.queue import (
    DEFAULT_RENDER_QUEUE_NAME,
    get_queue,
    get_redis_conn,
    is_redis_available,
)


# ---------------------------------------------------------------------------
# DEFAULT_RENDER_QUEUE_NAME
# ---------------------------------------------------------------------------


def test_default_render_queue_name_is_render():
    assert DEFAULT_RENDER_QUEUE_NAME == "render"


# ---------------------------------------------------------------------------
# is_redis_available
# ---------------------------------------------------------------------------


class TestIsRedisAvailable:
    @patch("app.queue.redis.from_url")
    def test_returns_true_when_ping_succeeds(self, mock_from_url):
        mock_conn = MagicMock()
        mock_from_url.return_value = mock_conn
        mock_conn.ping.return_value = True

        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = is_redis_available()

        assert result is True
        mock_conn.ping.assert_called_once()

    def test_returns_false_when_redis_url_not_configured(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = None
            result = is_redis_available()

        assert result is False

    def test_returns_false_when_redis_url_empty_string(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = ""
            result = is_redis_available()

        assert result is False

    @patch("app.queue.redis.from_url")
    def test_returns_false_when_connection_raises(self, mock_from_url):
        mock_from_url.side_effect = Exception("connection refused")

        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = is_redis_available()

        assert result is False

    @patch("app.queue.redis.from_url")
    def test_returns_false_when_ping_raises(self, mock_from_url):
        mock_conn = MagicMock()
        mock_conn.ping.side_effect = Exception("ping failed")
        mock_from_url.return_value = mock_conn

        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            result = is_redis_available()

        assert result is False


# ---------------------------------------------------------------------------
# get_redis_conn
# ---------------------------------------------------------------------------


class TestGetRedisConn:
    def test_raises_runtime_error_when_no_redis_url(self):
        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = None
            with pytest.raises(RuntimeError, match="REDIS_URL is not configured"):
                get_redis_conn()

    @patch("app.queue.redis.from_url")
    def test_returns_connection_when_ping_succeeds(self, mock_from_url):
        mock_conn = MagicMock()
        mock_from_url.return_value = mock_conn

        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            conn = get_redis_conn()

        assert conn is mock_conn
        mock_from_url.assert_called_once_with("redis://localhost:6379/0")

    @patch("app.queue.redis.from_url")
    def test_re_raises_on_connection_failure(self, mock_from_url):
        mock_from_url.side_effect = ConnectionError("refused")

        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            with pytest.raises(ConnectionError, match="refused"):
                get_redis_conn()

    @patch("app.queue.redis.from_url")
    def test_logs_info_on_success(self, mock_from_url, caplog):
        import logging

        mock_conn = MagicMock()
        mock_from_url.return_value = mock_conn

        with patch("app.config.settings") as mock_settings:
            mock_settings.redis_url = "redis://localhost:6379/0"
            with caplog.at_level(logging.INFO, logger="app.queue"):
                get_redis_conn()

        assert any("Redis connection established" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# get_queue
# ---------------------------------------------------------------------------


class TestGetQueue:
    @patch("rq.Queue")
    def test_uses_supplied_conn_without_calling_get_redis_conn(self, mock_queue_cls):
        mock_conn = MagicMock()
        mock_queue_instance = MagicMock()
        mock_queue_cls.return_value = mock_queue_instance

        result = get_queue(conn=mock_conn, name="render")

        mock_queue_cls.assert_called_once_with("render", connection=mock_conn, is_async=True)
        assert result is mock_queue_instance

    @patch("rq.Queue")
    @patch("app.queue.get_redis_conn")
    def test_calls_get_redis_conn_when_conn_is_none(self, mock_get_redis_conn, mock_queue_cls):
        mock_conn = MagicMock()
        mock_get_redis_conn.return_value = mock_conn
        mock_queue_instance = MagicMock()
        mock_queue_cls.return_value = mock_queue_instance

        result = get_queue(conn=None)

        mock_get_redis_conn.assert_called_once()
        mock_queue_cls.assert_called_once_with(
            DEFAULT_RENDER_QUEUE_NAME, connection=mock_conn, is_async=True
        )
        assert result is mock_queue_instance

    @patch("rq.Queue")
    def test_default_queue_name_is_render(self, mock_queue_cls):
        mock_conn = MagicMock()
        get_queue(conn=mock_conn)
        args, kwargs = mock_queue_cls.call_args
        assert args[0] == DEFAULT_RENDER_QUEUE_NAME

    @patch("rq.Queue")
    def test_custom_queue_name_is_passed_through(self, mock_queue_cls):
        mock_conn = MagicMock()
        get_queue(conn=mock_conn, name="custom_queue")
        args, kwargs = mock_queue_cls.call_args
        assert args[0] == "custom_queue"
