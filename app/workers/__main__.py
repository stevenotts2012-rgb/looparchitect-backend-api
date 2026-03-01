"""Worker module entrypoint."""

from app.workers.main import run_worker


if __name__ == "__main__":
    run_worker()
