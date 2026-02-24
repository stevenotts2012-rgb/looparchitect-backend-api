from contextlib import asynccontextmanager
import os
import logging

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db import init_db, engine, SessionLocal
from app.middleware.cors import add_cors_middleware
from app.routes import api, health, db_health, loops, render, arrange

logger = logging.getLogger(__name__)

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
    # Run migrations on startup
    run_migrations()
    # Initialize database tables
    init_db()
    yield

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

add_cors_middleware(app)

# Create uploads and renders directories if they don't exist
os.makedirs("uploads", exist_ok=True)
os.makedirs("renders", exist_ok=True)

# Mount static files directory for uploads
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Note: /renders files are served via secure endpoint in render.py (GET /api/v1/renders/{filename})

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(db_health.router, prefix="/api/v1", tags=["database"])
app.include_router(api.router, prefix="/api/v1", tags=["api"])
app.include_router(loops.router, prefix="/api/v1", tags=["loops"])
app.include_router(render.router, prefix="/api/v1", tags=["render"])
app.include_router(arrange.router, prefix="/api/v1", tags=["arrange"])
