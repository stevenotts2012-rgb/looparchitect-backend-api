"""
Background job processing for arrangement generation.

Handles the async workflow of generating arrangements and updating database records.
"""

import logging
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.arrangement_engine import generate_arrangement

logger = logging.getLogger(__name__)


def run_arrangement_job(arrangement_id: int):
    """
    Background job to generate an arrangement.

    This runs asynchronously in a BackgroundTask and:
    1. Loads the Arrangement and Loop records
    2. Resolves the input file path
    3. Calls the generation engine
    4. Updates the Arrangement with results
    5. Handles errors gracefully

    Args:
        arrangement_id: ID of the Arrangement record to process
    """
    # Create a new session for this background task
    engine = create_engine(settings.database_url)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        # Load the arrangement
        arrangement = (
            db.query(Arrangement)
            .filter(Arrangement.id == arrangement_id)
            .first()
        )

        if not arrangement:
            logger.error(f"Arrangement {arrangement_id} not found")
            return

        logger.info(f"Starting arrangement generation for ID {arrangement_id}")

        # Update status to processing
        arrangement.status = "processing"
        db.commit()

        # Load the source loop
        loop = db.query(Loop).filter(Loop.id == arrangement.loop_id).first()

        if not loop:
            raise ValueError(f"Loop {arrangement.loop_id} not found")

        logger.info(f"Processing loop: {loop.name}")

        # Resolve input file path
        input_file_path = _resolve_uploads_path(loop.file_url)

        if not Path(input_file_path).exists():
            raise FileNotFoundError(f"Loop file not found: {input_file_path}")

        # Generate the arrangement
        output_url, timeline_json = generate_arrangement(
            input_wav_path=input_file_path,
            target_seconds=arrangement.target_seconds,
            bpm=loop.bpm or 120.0,  # Default to 120 if not set
            genre=arrangement.genre or "generic",
            intensity=arrangement.intensity or "medium",
        )

        # Update arrangement with results
        arrangement.status = "complete"
        arrangement.output_file_url = output_url
        arrangement.arrangement_json = timeline_json
        arrangement.error_message = None
        db.commit()

        logger.info(f"Successfully completed arrangement {arrangement_id}")

    except Exception as e:
        logger.error(f"Error generating arrangement {arrangement_id}: {str(e)}")

        # Update arrangement with error
        try:
            arrangement.status = "failed"
            arrangement.error_message = str(e)
            db.commit()
        except Exception as db_error:
            logger.error(f"Failed to update arrangement error status: {str(db_error)}")

    finally:
        db.close()


def _resolve_uploads_path(file_url: str) -> str:
    """
    Resolve a file URL to a local disk path.

    Handles URLs like:
    - /uploads/loop_123.wav
    - uploads/loop_123.wav
    - loop_123.wav

    Args:
        file_url: File URL or relative path

    Returns:
        Full path to file on disk
    """
    # Remove leading separator if present
    clean_url = file_url.lstrip("/")

    # If it starts with "uploads/", construct full path
    if clean_url.startswith("uploads/"):
        return str(Path.cwd() / clean_url)

    # If it's just a filename, put it in /uploads
    if "/" not in clean_url:
        return str(Path.cwd() / "uploads" / clean_url)

    # Otherwise assume it's already a relative path
    return str(Path.cwd() / clean_url)
