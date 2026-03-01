"""Redis queue configuration and entrypoint."""

import logging
import os

import redis
from rq import Queue

logger = logging.getLogger(__name__)


def get_redis_conn() -> redis.Redis:
    """Get or create redis connection."""
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    try:
        conn = redis.from_url(redis_url, decode_responses=True)
        conn.ping()
        logger.info(f"✅ Redis connected: {redis_url}")
        return conn
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        raise


def get_queue(conn: redis.Redis = None, name: str = "render") -> Queue:
    """Get or create the render job queue."""
    if conn is None:
        conn = get_redis_conn()
    return Queue(name, connection=conn, is_async=True)
