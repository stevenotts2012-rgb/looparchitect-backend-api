
"""LoopArchitect background worker entrypoint."""

import logging
import threading
import time
from app.config import settings

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app.workers.main")

def _heartbeat_loop() -> None:
    """Background heartbeat to show worker is alive (logs once per minute)."""
    while True:
        time.sleep(60)
        logger.info("Worker heartbeat - alive")

def _run_rq_worker() -> None:
    from app.queue import DEFAULT_RENDER_QUEUE_NAME, get_redis_conn
    from rq.queue import Queue
    from rq.worker import SimpleWorker
    from rq.connections import Connection
    from app.workers.render_worker import _ensure_db_models

    print("🚀 Windows-safe RQ worker starting...")
    _ensure_db_models()

    redis_conn = get_redis_conn()
    queue = Queue(DEFAULT_RENDER_QUEUE_NAME, connection=redis_conn)

    with Connection(redis_conn):
        worker = SimpleWorker([queue])
        print("✅ Worker running WITHOUT scheduler or fork")
        worker.work(burst=False)

def run_worker() -> None:
    logger.info("LoopArchitect Worker started")
    settings.validate_startup()

    heartbeat = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat.start()

    try:
        _run_rq_worker()
    except Exception as exc:
        logger.exception("Worker startup failed: %s", exc)
        raise

if __name__ == "__main__":
    run_worker()
