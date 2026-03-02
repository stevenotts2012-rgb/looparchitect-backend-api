"""FastAPI application entry point with auto-discovery of routes."""

from contextlib import asynccontextmanager
import os
import logging

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


def _build_cors_origins() -> list[str]:
    """Build CORS origins - only allow specified frontend origins."""
    return list(settings.allowed_origins)


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
        logger.warning(f"⚠️  Migration warning (may be expected on first run): {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage application lifespan (startup and shutdown)."""
    # Startup
    logger.info("🚀 Starting LoopArchitect API...")
    settings.validate_startup()
    logger.info(
        "Startup configuration: environment=%s debug=%s storage_backend=%s railway=%s port=%s",
        settings.environment,
        settings.debug,
        settings.storage_backend,
        _is_railway_environment(),
        os.getenv("PORT", "8000"),
    )
    
    # Run migrations on startup
    run_migrations()
    
    # Initialize database tables
    init_db()
    
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

# Add CORS middleware - must be added before routes
_cors_origins = _build_cors_origins()
logger.info(f"✅ CORS configured for origins: {_cors_origins}")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
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
