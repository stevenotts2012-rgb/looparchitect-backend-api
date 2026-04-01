"""SQLAlchemy engine, session factory and FastAPI dependency for DB access."""

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.base import Base  # noqa: F401
from app.models.loop import Loop  # noqa: F401 - register Loop with Base.metadata
from app.models.arrangement import Arrangement  # noqa: F401 - register Arrangement with Base.metadata
from app.models.job import RenderJob  # noqa: F401 - register RenderJob with Base.metadata so init_db() creates render_jobs

logger = logging.getLogger(__name__)

# Get DATABASE_URL from settings (loaded from .env with default fallback)
DATABASE_URL: str = settings.database_url

# Render (and older Heroku) provides postgres:// URLs; SQLAlchemy 1.4+ requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# Configure SQLite-specific connection args if using SQLite
connect_args: dict = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(DATABASE_URL, pool_pre_ping=True, connect_args=connect_args)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables that are registered with the SQLAlchemy Base metadata."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Yield a database session for use as a FastAPI dependency.

    Usage in a route::

        @router.get("/items")
        def read_items(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
