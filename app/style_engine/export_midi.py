from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def maybe_export_midi(feature_enabled: bool) -> str | None:
    if not feature_enabled:
        logger.info("style_engine midi export skipped (feature disabled)")
        return None
    logger.info("style_engine midi export placeholder executed")
    return None
