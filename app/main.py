"""FastAPI application entry point with auto-discovery of routes."""

from contextlib import asynccontextmanager
import os
import logging
import threading

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

    try:
        from app.queue import is_redis_available

        if not is_redis_available():
            logger.warning("Embedded RQ worker not started: Redis unavailable at startup")
            return
    except Exception as exc:
        logger.warning("Embedded RQ worker precheck failed: %s", exc)
        return

    def _worker_target() -> None:
        try:
            from app.workers.main import run_worker

            run_worker()
        except Exception:
            logger.exception("Embedded RQ worker exited unexpectedly")

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




def create_tables_if_missing():
    """Create required tables if they don't exist in the database.
    
    This is a fallback approach when migrations are skipped (e.g., due to
    existing table locking issues). Uses IF NOT EXISTS to safely handle
    repeated calls.
    """
    try:
        import sqlalchemy as sa
        from sqlalchemy import text
        
        # Create a connection to the database
        engine = sa.create_engine(settings.database_url)
        
        with engine.begin() as connection:
            # Create loops table with all required columns
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS loops (
                    id SERIAL PRIMARY KEY,
                    title VARCHAR NOT NULL,
                    artist_name VARCHAR NOT NULL,
                    duration_seconds FLOAT NOT NULL,
                    file_path VARCHAR NOT NULL UNIQUE,
                    s3_key VARCHAR,
                    waveform_data TEXT,
                    status VARCHAR DEFAULT 'pending',
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # ADD COLUMN IF NOT EXISTS (PostgreSQL 9.6+) -- idempotent, no inspector needed
            for col_name, col_type in [
                ("name",                 "VARCHAR"),
                ("tempo",                "FLOAT"),
                ("key",                  "VARCHAR"),
                ("filename",             "VARCHAR"),
                ("file_url",             "VARCHAR"),
                ("file_key",             "VARCHAR"),
                ("bpm",                  "INTEGER"),
                ("bars",                 "INTEGER"),
                ("musical_key",          "VARCHAR"),
                ("genre",                "VARCHAR"),
                ("processed_file_url",   "VARCHAR"),
                ("analysis_json",        "TEXT"),
                ("created_at",           "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
                ("is_stem_pack",         "VARCHAR DEFAULT 'false'"),
                ("stem_roles_json",      "TEXT"),
                ("stem_files_json",      "TEXT"),
                ("stem_validation_json", "TEXT"),
            ]:
                connection.execute(text(f"ALTER TABLE loops ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            logger.info("✅ loops column guard complete")

            # Create arrangements table with all required columns
            connection.execute(text("""
                CREATE TABLE IF NOT EXISTS arrangements (
                    id SERIAL PRIMARY KEY,
                    loop_id INTEGER NOT NULL,
                    status VARCHAR DEFAULT 'queued',
                    target_seconds INTEGER NOT NULL,
                    genre VARCHAR,
                    intensity VARCHAR,
                    include_stems BOOLEAN DEFAULT false,
                    output_file_url VARCHAR,
                    stems_zip_url VARCHAR,
                    arrangement_json TEXT,
                    error_message TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))

            # ADD COLUMN IF NOT EXISTS for arrangements -- idempotent
            for col_name, col_type in [
                ("style_profile_json",        "TEXT"),
                ("ai_parsing_used",           "BOOLEAN DEFAULT false"),
                ("producer_arrangement_json", "TEXT"),
                ("render_plan_json",          "TEXT"),
                ("stem_arrangement_json",     "TEXT"),
                ("stem_render_path",          "VARCHAR"),
                ("rendered_from_stems",       "BOOLEAN DEFAULT false"),
                ("progress",                  "FLOAT DEFAULT 0.0"),
                ("progress_message",          "VARCHAR(256)"),
                ("output_s3_key",             "VARCHAR"),
                ("output_url",               "VARCHAR"),
            ]:
                connection.execute(text(f"ALTER TABLE arrangements ADD COLUMN IF NOT EXISTS {col_name} {col_type}"))
            logger.info("✅ arrangements column guard complete")

            # Indexes
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_loops_id ON loops(id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_arrangements_id ON arrangements(id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS ix_arrangements_loop_id ON arrangements(loop_id)"))
            connection.execute(text("CREATE INDEX IF NOT EXISTS idx_arrangement_loop_status ON arrangements(loop_id, status)"))

        engine.dispose()
        logger.info("✅ Database tables verified/created successfully")

        # Foreign key runs in its own separate transaction.
        # A duplicate-constraint error CANNOT roll back the column additions above.
        try:
            fk_engine = sa.create_engine(settings.database_url)
            with fk_engine.begin() as fk_conn:
                fk_conn.execute(text("""
                    ALTER TABLE arrangements
                    ADD CONSTRAINT fk_arrangements_loop_id
                    FOREIGN KEY (loop_id) REFERENCES loops(id)
                """))
            fk_engine.dispose()
        except Exception:
            pass  # Constraint already exists -- fine
    except Exception as e:
        logger.exception("❌ Failed to create database tables")
        raise RuntimeError("Failed to create required database tables") from e


def run_migrations():
    """Run Alembic migrations to update database schema."""
    try:
        from alembic.config import Config
        from alembic import command
        
        alembic_cfg = Config(os.path.join(os.path.dirname(os.path.dirname(__file__)), "alembic.ini"))
        alembic_cfg.set_main_option("sqlalchemy.url", settings.database_url)
        
        command.upgrade(alembic_cfg, "head")
        logger.info("✅ Database migrations completed successfully")
    except Exception as e:
        logger.exception("❌ Database migrations failed during startup")
        raise RuntimeError("Database migration failed during startup") from e


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
    


    # Create tables if they don't exist (application-level fallback)
    # Non-fatal: log errors but don't prevent the app from starting
    try:
        create_tables_if_missing()
    except Exception as _tbl_err:
        logger.error("⚠️  Startup table-init error (non-fatal): %s", _tbl_err)

    # Run Alembic migrations to apply any pending schema changes (idempotent)
    # Non-fatal: log errors but don't prevent the app from starting
    try:
        run_migrations()
    except Exception as _mig_err:
        logger.error("⚠️  Startup migration error (non-fatal): %s", _mig_err)

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


# Create uploads and renders directories if they don't exist
os.makedirs("uploads", exist_ok=True)
os.makedirs("renders", exist_ok=True)
os.makedirs("renders/arrangements", exist_ok=True)

# Mount static files directory for uploads
from pathlib import Path
from fastapi.staticfiles import StaticFiles

UPLOADS_DIR = Path(__file__).resolve().parent.parent / "uploads"
app.mount("/uploads", StaticFiles(directory=str(UPLOADS_DIR)), name="uploads")

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
