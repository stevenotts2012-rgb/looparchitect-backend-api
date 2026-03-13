from __future__ import annotations

from pathlib import Path
import sys

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker


@pytest.fixture(scope="module")
def fresh_sqlite_integration_db(tmp_path_factory: pytest.TempPathFactory):
    """Create a fresh temp SQLite DB, initialize schema, and clean up after tests."""
    import app.db as db_exports
    import app.db.session as db_session
    from app.config import settings
    from app.models.base import Base

    tmp_dir = tmp_path_factory.mktemp("integration_db")
    db_path = tmp_dir / "integration.sqlite"
    db_url = f"sqlite:///{db_path.as_posix()}"

    old_settings_db_url = settings.database_url
    old_exports_db_url = db_exports.DATABASE_URL
    old_exports_engine = db_exports.engine
    old_exports_session_local = db_exports.SessionLocal

    old_session_db_url = db_session.DATABASE_URL
    old_session_engine = db_session.engine
    old_session_session_local = db_session.SessionLocal

    settings.database_url = db_url

    engine = create_engine(db_url, pool_pre_ping=True, connect_args={"check_same_thread": False})
    session_local = sessionmaker(autocommit=False, autoflush=False, bind=engine)

    db_exports.DATABASE_URL = db_url
    db_exports.engine = engine
    db_exports.SessionLocal = session_local

    db_session.DATABASE_URL = db_url
    db_session.engine = engine
    db_session.SessionLocal = session_local

    patched_modules: dict[str, object] = {}
    for module_name in [
        "app.services.arrangement_jobs",
        "app.services.job_service",
        "app.routes.arrangements",
        "app.routes.loops",
    ]:
        module = sys.modules.get(module_name)
        if module is not None and hasattr(module, "SessionLocal"):
            patched_modules[module_name] = getattr(module, "SessionLocal")
            setattr(module, "SessionLocal", session_local)

    Base.metadata.create_all(bind=engine)

    try:
        yield db_path
    finally:
        try:
            engine.dispose()
        finally:
            for module_name, original in patched_modules.items():
                module = sys.modules.get(module_name)
                if module is not None:
                    setattr(module, "SessionLocal", original)

            db_exports.DATABASE_URL = old_exports_db_url
            db_exports.engine = old_exports_engine
            db_exports.SessionLocal = old_exports_session_local

            db_session.DATABASE_URL = old_session_db_url
            db_session.engine = old_session_engine
            db_session.SessionLocal = old_session_session_local

            settings.database_url = old_settings_db_url

            db_file = Path(db_path)
            if db_file.exists():
                db_file.unlink(missing_ok=True)
