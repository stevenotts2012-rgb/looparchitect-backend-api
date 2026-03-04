"""Structured feature audit logging helpers."""

from __future__ import annotations

import logging
from typing import Any


def log_feature_event(
    logger: logging.Logger,
    event: str,
    correlation_id: str | None = None,
    **fields: Any,
) -> None:
    """Emit a structured feature/integration event log line."""
    payload = {
        "event": event,
        "correlation_id": correlation_id or "unknown",
        **fields,
    }
    logger.info("feature_event %s", payload)
