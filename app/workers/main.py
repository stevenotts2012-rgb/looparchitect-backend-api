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
    from app.queue import DEFAULT_RENDER_QUEUE_NAME, get_redis_conn, get_queue
    from app.workers.render_worker import _ensure_db_models

    _ensure_db_models()
    redis_conn = get_redis_conn()
    queue_name = DEFAULT_RENDER_QUEUE_NAME
    queue = get_queue(redis_conn, name=queue_name)

    from rq import SimpleWorker

    # Use a Windows-safe death-penalty class so the worker never touches
    # signal.SIGALRM, which does not exist on Windows.
    #
    # Preference order:
    #  1. rq.timeouts.TimerDeathPenalty  – available in RQ ≥ 1.16; uses a
    #     threading.Timer, works on all platforms.
    #  2. A local no-op subclass – silently disables RQ's timeout mechanism;
    #     safe because application-level timeouts are already enforced inside
    #     render_loop_worker via concurrent.futures.ThreadPoolExecutor
    #     (_run_with_timeout).
    try:
        from rq.timeouts import TimerDeathPenalty as _SafeDeathPenalty
    except ImportError:
        from rq.timeouts import BaseDeathPenalty as _BaseDP  # type: ignore[assignment]

        class _SafeDeathPenalty(_BaseDP):  # type: ignore[no-redef]
            """No-op death penalty for environments where TimerDeathPenalty is
            unavailable (older RQ).  Timeout is managed at the application
            level via ThreadPoolExecutor in render_worker._run_with_timeout()."""

            def setup_death_penalty(self) -> None:
                pass

            def cancel_death_penalty(self) -> None:
                pass

    logger.info("Connected to Redis queue: %s", queue.name)
    logger.info("Listening on queue(s): %s", queue_name)

    worker = SimpleWorker([queue], connection=redis_conn, log_job_description=True,
                          default_result_ttl=500)
    # Override at the instance level so the class-level default
    # (UnixSignalDeathPenalty on older RQ) is never used.
    worker.death_penalty_class = _SafeDeathPenalty
    logger.info("🚀 Worker starting to listen for jobs...")
    worker.work(with_scheduler=False)


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
