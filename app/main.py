"""FastAPI application entry point with auto-discovery of routes."""

from contextlib import asynccontextmanager
import os
import logging
import threading
import time

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import settings
from app.db import init_db
from app.middleware.logging import add_request_logging
from app.routes import register_routers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)
_embedded_worker_threads: list[threading.Thread] = []


def _start_embedded_rq_worker_if_enabled() -> None:
    """Start RQ worker in a daemon thread when enabled.

    This is a deployment-safe fallback for environments that only launch the web process.
    """
    global _embedded_worker_threads

    enabled = settings.enable_embedded_rq_worker
    if not enabled:
        logger.info("Embedded RQ worker disabled via ENABLE_EMBEDDED_RQ_WORKER")
        return

    worker_count = max(1, settings.embedded_rq_worker_count)

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
    for index in range(workers_to_start):
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


def _is_railway_environment() -> bool:
    """Detect Railway runtime using Railway metadata or PORT availability."""
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("PORT"))


def _normalize_origin(origin: str) -> str:
    """Normalize origin values for consistent CORS/server configuration."""
    return origin.strip().rstrip("/")


def _to_absolute_url(value: str) -> str:
    """Ensure URL has a scheme and no trailing slash."""
    normalized = value.strip().rstrip("/")
    if normalized.startswith("http://") or normalized.startswith("https://"):
        return normalized
    return f"https://{normalized}"


def _get_public_base_url() -> str | None:
    """Resolve the public deployment URL from common hosting environment variables."""
    railway_public_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if railway_public_domain:
        return _to_absolute_url(railway_public_domain)

    for env_var in (
        "RAILWAY_PUBLIC_URL",
        "RAILWAY_STATIC_URL",
        "RENDER_EXTERNAL_URL",
    ):
        value = os.getenv(env_var)
        if value:
            return _to_absolute_url(value)

    return None


def _build_openapi_servers() -> list[dict[str, str]]:
    """Build OpenAPI servers for production and local development."""
    servers: list[dict[str, str]] = []
    public_url = _get_public_base_url()
    local_port = os.getenv("PORT", "8000")

    if public_url:
        servers.append(
            {
                "url": public_url,
                "description": "Production (Railway)" if _is_railway_environment() else "Public",
            }
        )

    servers.extend(
        [
            {"url": f"http://localhost:{local_port}", "description": "Local development"},
            {"url": f"http://127.0.0.1:{local_port}", "description": "Local loopback"},
        ]
    )
    return servers




def _run_dev_migrations() -> None:
    """Run Alembic migrations in-process for local development convenience.

    This is intentionally called only when ``settings.is_production`` is
    ``False``.  In production, migrations MUST be applied as a dedicated
    pre-start step (``alembic upgrade head`` in the ``release`` Procfile
    phase or Dockerfile entrypoint) so that:

    * All replicas share a single, atomic migration run.
    * A bad migration fails the deploy rather than partially degrading live
      traffic.
    * The web process has no DDL authority at runtime.
    """
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)

        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Dev database migrations applied successfully")
    except Exception as e:
        logger.exception("❌ Dev database migrations failed")
        raise RuntimeError("Dev database migration failed") from e


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan (startup and shutdown)."""
    # Startup
    logger.info("🚀 Starting LoopArchitect API...")
    settings.validate_startup()
    
    # Log CORS origins for verification
    cors_origins = settings.allowed_origins
    logger.info(f"🔒 CORS Configuration:")
    logger.info(f"   Allowed origins: {cors_origins}")
    logger.info(f"   Credentials: True")
    logger.info(f"   Methods: all")
    logger.info(f"   Headers: all")
    
    # Verify localhost is present
    if "http://localhost:3000" not in cors_origins:
        logger.error("❌ CRITICAL: http://localhost:3000 is NOT in allowed CORS origins!")
    else:
        logger.info("✅ http://localhost:3000 is allowed")
    
    # Log feature flags
    logger.info(f"Feature flags: producer_engine={settings.feature_producer_engine}, style_engine={settings.feature_style_engine}, llm_parsing={settings.feature_llm_style_parsing}")
    
    # Log environment
    logger.info(
        "Startup configuration: environment=%s debug=%s storage_backend=%s railway=%s port=%s db_configured=%s redis_configured=%s",
        settings.environment,
        settings.debug,
        settings.get_storage_backend(),
        _is_railway_environment(),
        os.getenv("PORT", "8000"),
        bool(settings.database_url),
        bool(settings.redis_url),
    )

    if settings.get_storage_backend() == "s3":
        logger.info(
            "Storage backend: s3 (bucket=%s, region=%s)",
            settings.get_s3_bucket(),
            settings.aws_region,
        )
    else:
        logger.info("Storage backend: local")
    


    # Schema management strategy:
    #
    # Production: schema is owned exclusively by Alembic, applied before
    #   the web process starts (Procfile `release` phase / Dockerfile
    #   entrypoint `scripts/prestart.sh`).  The web process performs NO DDL.
    #
    # Development (non-production / SQLite): run `init_db()` to create
    #   tables from ORM metadata for a fast local-dev loop, then apply any
    #   pending Alembic migrations for full fidelity.
    if settings.is_production:
        logger.info(
            "Production mode: schema DDL is managed by Alembic pre-start migrations. "
            "The web process will not mutate the schema."
        )
    else:
        # Local dev / test: bootstrap schema, then bring it up to the latest
        # Alembic revision so devs always work against a fully migrated schema.
        try:
            init_db()
            logger.info("✅ Dev tables bootstrapped via SQLAlchemy metadata (init_db)")
        except Exception as _tbl_err:
            logger.error("⚠️  Dev table-init error (non-fatal): %s", _tbl_err)

        try:
            _run_dev_migrations()
        except Exception as _mig_err:
            logger.error("⚠️  Dev migration error (non-fatal): %s", _mig_err)

    _start_embedded_rq_worker_if_enabled()
    
    logger.info("✅ Application startup complete")
    yield
    
    # Shutdown
    logger.info("👋 Shutting down LoopArchitect API")


# Determine server list for OpenAPI docs
_servers = _build_openapi_servers()

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
    servers=_servers,
)

# *** CRITICAL: CORS middleware MUST be first ***
# Get allowed origins from config
_cors_origins = settings.allowed_origins
logger.info(f"📋 CORS allowed origins: {_cors_origins}")

# Add CORS middleware FIRST and BEFORE all other middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add request logging AFTER CORS
add_request_logging(app)


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
    import traceback
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
    Root endpoint - API status and information.
    
    Returns:
        dict: API status, version, and docs URL
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
        dict: {"ok": true}
    """
    return {"ok": True}


@app.get("/health/worker")
async def worker_health():
    """Report embedded worker thread status for queue diagnostics."""
    alive_workers = [thread for thread in _embedded_worker_threads if thread.is_alive()]
    enabled = settings.enable_embedded_rq_worker
    target_count = max(1, settings.embedded_rq_worker_count)

    return {
        "embedded_worker_enabled": enabled,
        "target_worker_count": target_count,
        "active_worker_count": len(alive_workers),
        "active_workers": [thread.name for thread in alive_workers],
    }


# Create local directories for uploads and renders.
# In production with S3 storage these directories are still created because
# temporary files may be written during processing, but files are NOT served
# from the local disk — S3 presigned URLs are used instead.
os.makedirs("uploads", exist_ok=True)
os.makedirs("renders", exist_ok=True)
os.makedirs("renders/arrangements", exist_ok=True)

# Mount /uploads as a static file directory ONLY when using local storage.
# In production (S3 backend) files live in S3; serving from local disk would
# return stale or empty responses.
from pathlib import Path
from fastapi.staticfiles import StaticFiles

if settings.get_storage_backend() == "local":
    UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
    app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")
    logger.info("Static file mount: /uploads → %s (local storage)", UPLOADS_DIR)
else:
    logger.info("Static file mount skipped: storage backend is '%s' (files served via presigned URLs)", settings.get_storage_backend())

# Auto-discover and register all routers from app.routes
register_routers(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=settings.debug,
    )
