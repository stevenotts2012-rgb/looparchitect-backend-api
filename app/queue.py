"""Redis queue configuration and entrypoint."""

import logging
import os
from typing import TYPE_CHECKING

import redis

if TYPE_CHECKING:
    from rq import Queue

logger = logging.getLogger(__name__)


def is_redis_available() -> bool:
    """Check if Redis is available without raising exception."""
    try:
        redis_url = os.getenv("REDIS_URL")
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
    """Get or create redis connection."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        conn = redis.from_url(redis_url)
        conn.ping()
        logger.info("✅ Redis connection established")
        return conn
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise


def get_queue(conn: redis.Redis = None, name: str = "render") -> "Queue":
    """Get or create the render job queue."""
    from rq import Queue

    if conn is None:
        conn = get_redis_conn()
    return Queue(name, connection=conn, is_async=True)
