"""FastAPI application entry point with auto-discovery of routes."""

from contextlib import asynccontextmanager
import os
import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import settings
from app.db import init_db
from app.middleware.cors import add_cors_middleware
from app.middleware.logging import add_request_logging
from app.routes import register_routers

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


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
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    
    # Run migrations on startup
    run_migrations()
    
    # Initialize database tables
    init_db()
    
    logger.info("✅ Application startup complete")
    
    yield
    
    # Shutdown
    logger.info("👋 Shutting down LoopArchitect API")


# Determine server list for OpenAPI docs
_servers = []
_render_url = os.getenv("RENDER_EXTERNAL_URL")
if _render_url:
    _servers.append({"url": _render_url, "description": "Production (Render)"})
_servers.append({"url": "http://localhost:8000", "description": "Local development"})

# Create FastAPI application
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
    servers=_servers,
)

# Add middleware
add_cors_middleware(app)
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
