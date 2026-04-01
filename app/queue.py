"""Redis queue configuration and entrypoint."""

import logging
from typing import TYPE_CHECKING

import redis

if TYPE_CHECKING:
    from rq import Queue

logger = logging.getLogger(__name__)

DEFAULT_RENDER_QUEUE_NAME = "render"


def is_redis_available() -> bool:
    """Check if Redis is available without raising exception."""
    try:
        from app.config import settings

        redis_url = settings.redis_url
        if not redis_url:
            logger.warning("⚠️  REDIS_URL not configured")
            return False
        conn = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
        conn.ping()
        return True
    except Exception as e:
        logger.warning(f"⚠️  Redis unavailable: {e}")
        return False


def get_redis_conn() -> redis.Redis:
    """Get or create redis connection.

    Uses ``settings.redis_url`` (populated from the ``REDIS_URL`` environment
    variable via Pydantic Settings).  Falls back to ``redis://localhost:6379/0``
    only when the variable is completely absent, which is the correct behaviour
    for local development.
    """
    from app.config import settings

    redis_url = settings.redis_url or "redis://localhost:6379/0"
    try:
        conn = redis.from_url(redis_url)
        conn.ping()
        logger.info("✅ Redis connection established")
        return conn
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise


def get_queue(conn: redis.Redis = None, name: str = DEFAULT_RENDER_QUEUE_NAME) -> "Queue":
    """Get or create the render job queue."""
    from rq import Queue

    if conn is None:
        conn = get_redis_conn()
    return Queue(name, connection=conn, is_async=True)
