"""Unit tests for audit_logging helpers."""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, call

from app.services.audit_logging import log_feature_event


class TestLogFeatureEvent:
    def test_calls_logger_info(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "test_event")
        assert logger.info.called

    def test_event_name_in_payload(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "arrangement_started")
        args, _ = logger.info.call_args
        assert "arrangement_started" in str(args)

    def test_correlation_id_in_payload(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "render_completed", correlation_id="abc-123")
        args, _ = logger.info.call_args
        assert "abc-123" in str(args)

    def test_missing_correlation_id_defaults_to_unknown(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "render_completed")
        args, _ = logger.info.call_args
        assert "unknown" in str(args)

    def test_extra_fields_included_in_payload(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "job_queued", correlation_id="x", job_id=42, status="ok")
        args, _ = logger.info.call_args
        payload_str = str(args)
        assert "job_id" in payload_str
        assert "42" in payload_str
        assert "status" in payload_str
        assert "ok" in payload_str

    def test_no_extra_fields_does_not_crash(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "ping")
        assert logger.info.call_count == 1

    def test_log_level_is_info_not_debug_or_error(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "test_event")
        assert logger.info.called
        assert not logger.debug.called
        assert not logger.error.called

    def test_event_key_present_in_payload(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "my_event")
        args, _ = logger.info.call_args
        # The second positional arg to logger.info should be the payload dict
        payload = args[1]
        assert isinstance(payload, dict)
        assert payload["event"] == "my_event"

    def test_correlation_id_key_in_payload(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "my_event", correlation_id="cid-999")
        args, _ = logger.info.call_args
        payload = args[1]
        assert payload["correlation_id"] == "cid-999"

    def test_none_correlation_id_treated_as_unknown(self):
        logger = MagicMock(spec=logging.Logger)
        log_feature_event(logger, "event", correlation_id=None)
        args, _ = logger.info.call_args
        payload = args[1]
        assert payload["correlation_id"] == "unknown"
