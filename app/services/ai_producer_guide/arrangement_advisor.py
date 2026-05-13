from __future__ import annotations

import logging
import os
from typing import Any, Dict

from app.config import settings

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
        raw = os.getenv("AI_PRODUCER_GUIDE_ENABLED")
        remote_enabled = (
            bool(getattr(settings, "feature_ai_producer_assist", True))
            if raw is None
            else str(raw).strip().lower() in {"1", "true", "yes", "on"}
        )

        cached = _CACHE.get(guide_input)
        if cached:
            return cached

        logger.info("AI_PRODUCER_GUIDE_REQUESTED")
        if not remote_enabled:
            local = GuideClient()._rules_response(build_prompt(guide_input))
            validated = validate_guide_schema(local)
            _CACHE.set(guide_input, validated)
            logger.info("AI_PRODUCER_GUIDE_LOCAL_ADVISOR_USED")
            logger.info("AI_PRODUCER_GUIDE_APPLIED")
            return validated
        try:
            timeout = int(os.getenv("AI_PRODUCER_GUIDE_TIMEOUT_SECONDS", "20"))
            response = self.client.request(build_prompt(guide_input), timeout_seconds=timeout)
            reject_unsafe_guidance(response)
            validated = validate_guide_schema(response)
            _CACHE.set(guide_input, validated)
            logger.info("AI_PRODUCER_GUIDE_RESPONSE_RECEIVED")
            logger.info("AI_PRODUCER_GUIDE_APPLIED")
            return validated
        except Exception:
            logger.exception("AI_PRODUCER_GUIDE_REMOTE_FAILED_LOCAL_USED")
            local = GuideClient()._rules_response(build_prompt(guide_input))
            validated = validate_guide_schema(local)
            _CACHE.set(guide_input, validated)
            logger.info("AI_PRODUCER_GUIDE_APPLIED")
            return validated
