from __future__ import annotations

import logging
import os
from typing import Any, Dict

from .cache import GuideCache
from .decision_schema import validate_guide_schema
from .guide_client import GuideClient
from .prompt_builder import build_prompt
from .safety import reject_unsafe_guidance

logger = logging.getLogger(__name__)
_CACHE = GuideCache()


class AIProducerGuideAdvisor:
    def __init__(self, client: GuideClient | None = None) -> None:
        self.client = client or GuideClient()

    def get_guide(self, guide_input: Dict[str, Any]) -> Dict[str, Any] | None:
        enabled = os.getenv("AI_PRODUCER_GUIDE_ENABLED", "false").lower() == "true"
        if not enabled:
            logger.info("AI_PRODUCER_GUIDE_FALLBACK_USED reason=disabled")
            return None

        cached = _CACHE.get(guide_input)
        if cached:
            return cached

        logger.info("AI_PRODUCER_GUIDE_REQUESTED")
        try:
            timeout = int(os.getenv("AI_PRODUCER_GUIDE_TIMEOUT_SECONDS", "20"))
            response = self.client.request(build_prompt(guide_input), timeout_seconds=timeout)
            reject_unsafe_guidance(response)
            validated = validate_guide_schema(response)
            _CACHE.set(guide_input, validated)
            logger.info("AI_PRODUCER_GUIDE_RESPONSE_RECEIVED")
            return validated
        except Exception:
            logger.exception("AI_PRODUCER_GUIDE_FALLBACK_USED reason=exception")
            return None
