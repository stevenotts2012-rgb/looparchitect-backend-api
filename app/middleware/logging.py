"""
Request logging middleware.

Logs all incoming HTTP requests with timing information.
"""

import logging
import time
import uuid
from fastapi import Request, Response

logger = logging.getLogger(__name__)


def add_request_logging(app):
    """
    Add request logging middleware to app.

    Args:
        app: FastAPI application instance
    """
    @app.middleware("http")
    async def request_logging_middleware(request: Request, call_next) -> Response:
        start_time = time.time()
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id

        logger.info(
            f"→ {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'} "
            f"cid={correlation_id}"
        )

        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000
            logger.info(
                f"← {request.method} {request.url.path} "
                f"→ {response.status_code} ({duration_ms:.1f}ms) cid={correlation_id}"
            )
            response.headers["x-correlation-id"] = correlation_id
            return response
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            logger.error(
                f"✗ {request.method} {request.url.path} "
                f"failed after {duration_ms:.1f}ms: {str(e)} cid={correlation_id}"
            )
            raise

    logger.info("✅ Request logging middleware enabled")
