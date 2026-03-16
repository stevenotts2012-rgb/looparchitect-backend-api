from contextlib import asynccontextmanager
import os
import shutil
import logging
import threading
import time
import traceback

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.config import settings
from app.db import init_db, engine, SessionLocal
from app.middleware.cors import add_cors_middleware
from app.middleware.logging import add_request_logging
from app.routes import api, health, db_health, loops, render, arrange, arrangements, audio, styles
from app.services.audio_runtime import configure_audio_binaries
from app.queue import is_redis_available

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
_embedded_worker_threads: list[threading.Thread] = []


def _start_embedded_rq_worker_if_enabled() -> None:
    """Start embedded RQ worker threads when enabled.

    This prevents jobs from remaining queued in environments running only the web process.
    """
    global _embedded_worker_threads

    enabled = os.getenv("ENABLE_EMBEDDED_RQ_WORKER", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    if not enabled:
        logger.info("Embedded RQ worker disabled via ENABLE_EMBEDDED_RQ_WORKER")
        return

    worker_count_raw = os.getenv("EMBEDDED_RQ_WORKER_COUNT", "2").strip()
    try:
        worker_count = max(1, int(worker_count_raw))
    except ValueError:
        worker_count = 2

    alive_workers = [thread for thread in _embedded_worker_threads if thread.is_alive()]
    if len(alive_workers) >= worker_count:
        logger.info("Embedded RQ workers already running: count=%s", len(alive_workers))
        _embedded_worker_threads = alive_workers
        return

    _embedded_worker_threads = alive_workers

    def _worker_target() -> None:
        from app.workers.main import run_worker

        while True:
            try:
                run_worker()
                logger.warning("Embedded RQ worker exited; restarting in 10s")
            except Exception:
                logger.exception("Embedded RQ worker failed; restarting in 10s")
            time.sleep(10)

    workers_to_start = worker_count - len(_embedded_worker_threads)
    for _ in range(workers_to_start):
        worker_number = len(_embedded_worker_threads) + 1
        thread = threading.Thread(
            target=_worker_target,
            name=f"embedded-rq-worker-{worker_number}",
            daemon=True,
        )
        thread.start()
        _embedded_worker_threads.append(thread)
        logger.info("Embedded RQ worker thread started: name=%s", thread.name)

    logger.info("Embedded RQ workers active: count=%s", len(_embedded_worker_threads))

def run_migrations():
    """Run Alembic migrations to update database schema."""
    try:
        from alembic.config import Config
        from alembic.runtime.migration import MigrationContext
        from alembic.operations import Operations
        import sys
        
        alembic_cfg = Config(os.path.join(os.path.dirname(__file__), "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        
        # Run migrations
        from alembic import command
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Database migrations completed successfully")
    except Exception as e:
        logger.warning(f"⚠️  Migration warning (may be expected on first run): {e}")
        # Don't fail startup if migrations have issues - the schema fix script handles it

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("🚀 Starting LoopArchitect API...")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")

    # Validate startup configuration and runtime prerequisites
    settings.validate_startup()
    configure_audio_binaries(
        ffmpeg_binary=settings.ffmpeg_binary or None,
        ffprobe_binary=settings.ffprobe_binary or None,
        raise_if_missing=settings.should_enforce_audio_binaries,
    )

    ffmpeg_detected = bool(settings.ffmpeg_binary or shutil.which("ffmpeg"))
    ffprobe_detected = bool(settings.ffprobe_binary or shutil.which("ffprobe"))
    logger.info("FFmpeg detected: %s (ffprobe: %s)", ffmpeg_detected, ffprobe_detected)

    redis_connected = is_redis_available()
    if redis_connected:
        logger.info("Redis connection status: connected")
    elif settings.is_production:
        logger.warning("Redis connection status: unavailable (production mode)")
    else:
        logger.warning("Redis connection status: unavailable (development mode, non-blocking)")
    
    # Run migrations on startup
    run_migrations()
    
    # Initialize database tables
    init_db()

    # Start embedded queue workers so queued render jobs are processed
    _start_embedded_rq_worker_if_enabled()
    
    logger.info("✅ Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("👋 Shutting down LoopArchitect API")

# Determine server list for OpenAPI docs (used by Swagger UI as the base URL)
_servers = []
_render_url = os.getenv("RENDER_EXTERNAL_URL")
if _render_url:
    _servers.append({"url": _render_url, "description": "Production (Render)"})
_servers.append({"url": "http://localhost:8000", "description": "Local development"})

app = FastAPI(
    title=settings.app_name,
    debug=settings.debug,
    lifespan=lifespan,
    servers=_servers,
)

# Add middleware
add_cors_middleware(app)
add_request_logging(app)

# Configure maximum request body size
# This is handled by Starlette's internal processing
# For file uploads, we validate size in the endpoint handlers
app.state.max_body_size = settings.max_request_body_size_mb * 1024 * 1024

# Global exception handlers
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle Pydantic validation errors."""
    logger.error(f"Validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "detail": exc.errors(),
            "path": str(request.url.path)
        }
    )


@app.exception_handler(ValidationError)
async def pydantic_exception_handler(request: Request, exc: ValidationError):
    """Handle Pydantic validation errors."""
    logger.error(f"Pydantic validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "error": "Validation Error",
            "detail": exc.errors(),
            "path": str(request.url.path)
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    logger.error(
        f"Unhandled exception on {request.method} {request.url.path}: {str(exc)}\n"
        f"{traceback.format_exc()}"
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "error": "Internal Server Error",
            "detail": "An unexpected error occurred. Please try again later.",
            "path": str(request.url.path)
        }
    )


# Root health check endpoint
@app.get("/")
async def root():
    """
    Root endpoint.
    
    Returns API status and basic information.
    
    Returns:
        {"status": "ok", "message": "LoopArchitect API"}
    """
    return {
        "status": "ok",
        "message": "LoopArchitect API",
        "version": settings.app_version,
        "docs": "/docs"
    }


@app.get("/health")
async def root_health():
    """
    Simple root-level health check.
    
    Returns immediately without dependencies.
    Used for load balancers and basic health monitoring.
    
    Returns:
        {"ok": true}
    """
    return {"ok": True}


@app.get("/health/worker")
async def worker_health():
    """Report embedded worker thread status for queue diagnostics."""
    alive_workers = [thread for thread in _embedded_worker_threads if thread.is_alive()]
    enabled = os.getenv("ENABLE_EMBEDDED_RQ_WORKER", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    worker_count_raw = os.getenv("EMBEDDED_RQ_WORKER_COUNT", "2").strip()
    try:
        target_count = max(1, int(worker_count_raw))
    except ValueError:
        target_count = 2

    return {
        "embedded_worker_enabled": enabled,
        "target_worker_count": target_count,
        "active_worker_count": len(alive_workers),
        "active_workers": [thread.name for thread in alive_workers],
    }


# Create uploads and renders directories if they don't exist
os.makedirs("uploads", exist_ok=True)
os.makedirs("renders", exist_ok=True)
os.makedirs("renders/arrangements", exist_ok=True)

# Mount static files directory for uploads
from pathlib import Path
from fastapi.staticfiles import StaticFiles

UPLOADS_DIR = Path(__file__).resolve().parent / "uploads"
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

# Note: /renders files are served via secure endpoint in render.py (GET /api/v1/renders/{filename})

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(db_health.router, prefix="/api/v1", tags=["database"])
app.include_router(api.router, prefix="/api/v1", tags=["api"])
app.include_router(loops.router, prefix="/api/v1", tags=["loops"])
app.include_router(audio.router, prefix="/api/v1", tags=["audio"])
app.include_router(render.router, prefix="/api/v1", tags=["render"])
app.include_router(arrange.router, prefix="/api/v1", tags=["arrange"])
app.include_router(arrangements.router, prefix="/api/v1/arrangements", tags=["arrangements"])
app.include_router(styles.router, prefix="/api/v1", tags=["styles"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=settings.debug,
        log_level="info",
    )
