from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.test_model import Base
from app.models.loop import Loop  # noqa: F401 – registers Loop with Base.metadata

# Get DATABASE_URL from settings (loaded from .env with default fallback)
DATABASE_URL = settings.database_url

# Render (and older Heroku) provides postgres:// URLs; SQLAlchemy 1.4+ requires postgresql://
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

engine = create_engine(DATABASE_URL, pool_pre_ping=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
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
