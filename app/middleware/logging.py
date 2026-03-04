"""
Request logging middleware.

Logs all incoming HTTP requests with timing information.
"""

import logging
import time
import uuid
from typing import Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to log all HTTP requests."""

    async def dispatch(
        self, 
        request: Request, 
        call_next: Callable
    ) -> Response:
        """
        Process request and log details.

        Args:
            request: Incoming HTTP request
            call_next: Next middleware/handler

        Returns:
            HTTP response
        """
        # Start timing
        start_time = time.time()
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        request.state.correlation_id = correlation_id
        
        # Log request
        logger.info(
            f"→ {request.method} {request.url.path} "
            f"from {request.client.host if request.client else 'unknown'} "
            f"cid={correlation_id}"
        )
        
        # Process request
        try:
            response = await call_next(request)
            
            # Calculate duration
            duration_ms = (time.time() - start_time) * 1000
            
            # Log response
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


def add_request_logging(app):
    """
    Add request logging middleware to app.

    Args:
        app: FastAPI application instance
    """
    app.add_middleware(RequestLoggingMiddleware)
    logger.info("✅ Request logging middleware enabled")
