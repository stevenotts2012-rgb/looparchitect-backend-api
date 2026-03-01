"""LoopArchitect background worker entrypoint."""

import logging
import threading
import time


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("app.workers.main")


def _heartbeat_loop() -> None:
    """Background heartbeat to show worker is alive (logs once per minute)."""
    tick_count = 0
    while True:
        time.sleep(10)  # Check every 10s
        tick_count += 1
        # Only log every 6th tick (once per minute)
        if tick_count % 6 == 0:
            logger.info("Worker heartbeat - alive and processing jobs")
            tick_count = 0  # Reset to prevent overflow


def _run_rq_worker() -> None:
    from app.queue import get_redis_conn, get_queue
    from app.workers.render_worker import _ensure_db_models

    _ensure_db_models()
    redis_conn = get_redis_conn()
    queue = get_queue(redis_conn)

    from rq import Worker

    logger.info("Connected to Redis queue: %s", queue.name)
    worker = Worker([queue], connection=redis_conn, log_job_description=True)
    worker.work(with_scheduler=False)


def run_worker() -> None:
    logger.info("LoopArchitect Worker Started")

    heartbeat = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat.start()

    try:
        _run_rq_worker()
    except Exception as exc:
        logger.warning("Queue wiring unavailable, running heartbeat-only mode: %s", exc)
        logger.warning("TODO: Configure REDIS_URL and queue workers in this environment.")
        while True:
            time.sleep(60)


if __name__ == "__main__":
    run_worker()
