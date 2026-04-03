"""reconcile_db.py — Safe one-time Alembic state reconciliation.

Run this BEFORE ``alembic upgrade head`` in the release/prestart phase.

Problem it solves
-----------------
Production databases that were created before Alembic tracking began may have
all tables present but no ``alembic_version`` row (or a stale revision).
Calling ``alembic upgrade head`` against such a database fails because Alembic
tries to run every migration from scratch, hitting "table already exists" errors.

What this script does
---------------------
1. Connects to the database using the same URL as the application.
2. Checks the current Alembic revision via the Python API (no shell).
3. If **no revision is recorded** AND **production tables already exist**, it
   stamps the database to the latest migration head so that ``alembic upgrade
   head`` becomes a no-op.
4. If a valid revision already exists it does nothing — it will NOT overwrite
   an existing ``alembic_version`` value.

Safety guarantees
-----------------
* Only mutates state when ``ENVIRONMENT=production``.
* Idempotent: safe to run on every deploy; repeated runs are no-ops once the
  version has been stamped or migrations have run normally.
* Does not run DDL — it only writes to the ``alembic_version`` table.
* Alembic remains the single source of truth for schema changes going forward.
"""

import logging
import os
import sys

# ---------------------------------------------------------------------------
# Ensure the project root is on sys.path so we can import app.* modules.
# This script lives in scripts/ which is one level below the project root.
# ---------------------------------------------------------------------------
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from sqlalchemy import inspect, text  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from alembic.runtime.migration import MigrationContext  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.session import engine  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("reconcile_db")

# Tables that must exist for us to consider the production schema "already set up".
# These are the core tables introduced by the first batch of migrations.
_SENTINEL_TABLES = {"loops", "arrangements", "render_jobs"}

# Path to alembic.ini relative to the project root.
_ALEMBIC_INI = os.path.join(PROJECT_ROOT, "alembic.ini")


def _get_current_revision() -> str | None:
    """Return the current Alembic revision stored in the database, or None."""
    try:
        with engine.connect() as conn:
            context = MigrationContext.configure(conn)
            return context.get_current_revision()
    except Exception as exc:
        logger.error(
            "Failed to query Alembic revision from the database: %s. "
            "Check DATABASE_URL and that the database is reachable.",
            exc,
        )
        raise


def _tables_exist() -> bool:
    """Return True if all sentinel tables are present in the database."""
    with engine.connect() as conn:
        inspector = inspect(conn)
        existing = set(inspector.get_table_names())
    missing = _SENTINEL_TABLES - existing
    if missing:
        logger.info("Sentinel tables not yet present: %s", missing)
    return not missing


def _alembic_version_table_exists() -> bool:
    """Return True if the alembic_version table itself is present."""
    with engine.connect() as conn:
        inspector = inspect(conn)
        return "alembic_version" in inspector.get_table_names()


def reconcile() -> None:
    """Run the reconciliation check and stamp if required."""
    if not settings.is_production:
        logger.info(
            "ENVIRONMENT=%s — reconciliation only runs in production. Skipping.",
            settings.environment,
        )
        return

    logger.info("==> Starting production DB reconciliation (ENVIRONMENT=production)")

    # Step 1: determine current revision.
    current_rev = _get_current_revision()
    logger.info("Current Alembic revision: %s", current_rev or "<none>")

    if current_rev is not None:
        # A valid revision is already tracked — nothing to do.
        logger.info(
            "Alembic version is already set to '%s'. No stamp needed. "
            "alembic upgrade head will apply any pending migrations.",
            current_rev,
        )
        return

    # Step 2: no revision recorded — check whether tables exist.
    logger.info(
        "No Alembic revision found. Checking whether production tables exist..."
    )

    if not _tables_exist():
        logger.info(
            "Sentinel tables are absent — this looks like a fresh database. "
            "Skipping stamp; alembic upgrade head will create all tables from scratch."
        )
        return

    # Step 3: tables exist but no revision is tracked — stamp to head.
    logger.warning(
        "Production tables exist but alembic_version is empty. "
        "This indicates the database was created before Alembic tracking. "
        "Stamping database to head revision to reconcile state."
    )

    alembic_cfg = Config(_ALEMBIC_INI)
    try:
        command.stamp(alembic_cfg, "head")
    except Exception as exc:
        logger.error(
            "Stamp operation failed during reconciliation. "
            "Check alembic.ini path (%s) and database connectivity. Error: %s",
            _ALEMBIC_INI,
            exc,
        )
        raise
    logger.info("Stamp applied.")

    # Step 4: log the new revision for confirmation.
    new_rev = _get_current_revision()
    logger.info("Reconciliation complete. Alembic revision is now: %s", new_rev)


if __name__ == "__main__":
    reconcile()
