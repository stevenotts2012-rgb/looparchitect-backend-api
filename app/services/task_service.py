"""
Background task service for async audio processing.

Handles:
- Task queueing
- Status tracking
- Background job execution
"""

import logging
import traceback

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import settings
from app.models.loop import Loop
from app.services.audio_service import audio_service
from app.services.storage_service import storage_service

logger = logging.getLogger(__name__)


class TaskService:
    """Service for managing background audio processing tasks."""

    def __init__(self):
        """Initialize task service."""
        logger.info("TaskService initialized")

    def analyze_loop_task(self, loop_id: int) -> None:
        """
        Background task to analyze a loop.

        Args:
            loop_id: ID of the loop to analyze

        This function runs in a background task and updates the database.
        """
        # Create a new database session for this background task
        engine = create_engine(settings.database_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            logger.info(f"Starting analysis task for loop {loop_id}")

            # Get loop from database
            loop = db.query(Loop).filter(Loop.id == loop_id).first()
            if not loop:
                logger.error(f"Loop {loop_id} not found")
                return

            # Update status to processing
            loop.status = "processing"
            db.commit()

            # Get file path for analysis
            file_path = storage_service.get_file_path(loop.file_url)

            if file_path is None:
                # S3 storage - need to download file first
                # For now, mark as failed (S3 download can be added later)
                raise Exception("S3 file analysis not yet implemented")

            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            # Perform analysis
            analysis = audio_service.analyze_loop(str(file_path))

            # Update loop with analysis results
            loop.bpm = analysis.get("bpm")
            loop.musical_key = analysis.get("key")
            loop.duration_seconds = analysis.get("duration_seconds")
            loop.analysis_json = str(analysis)  # Store full analysis
            loop.status = "complete"

            db.commit()

            logger.info(f"Analysis complete for loop {loop_id}")

        except Exception as e:
            logger.error(f"Analysis failed for loop {loop_id}: {e}")
            logger.error(traceback.format_exc())

            # Update status to failed
            try:
                loop = db.query(Loop).filter(Loop.id == loop_id).first()
                if loop:
                    loop.status = "failed"
                    db.commit()
            except:
                pass

        finally:
            db.close()

    def generate_beat_task(
        self,
        loop_id: int,
        target_length_seconds: int,
        output_filename: str
    ) -> None:
        """
        Background task to generate a full beat from a loop.

        Args:
            loop_id: ID of the source loop
            target_length_seconds: Desired beat length
            output_filename: Name for the output file

        This function runs in a background task and updates the database.
        """
        # Create a new database session for this background task
        engine = create_engine(settings.database_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            logger.info(
                f"Starting beat generation for loop {loop_id}, "
                f"length={target_length_seconds}s"
            )

            # Get loop from database
            loop = db.query(Loop).filter(Loop.id == loop_id).first()
            if not loop:
                logger.error(f"Loop {loop_id} not found")
                return

            # Update status to processing
            loop.status = "processing"
            db.commit()

            # Get source file path
            source_path = storage_service.get_file_path(loop.file_url)

            if source_path is None:
                raise Exception("S3 file processing not yet implemented")

            if not source_path.exists():
                raise FileNotFoundError(f"Source file not found: {source_path}")

            # Generate output path
            output_path = f"renders/{output_filename}"

            # Generate beat
            result_path, metadata = audio_service.generate_full_beat(
                audio_path=str(source_path),
                output_path=output_path,
                target_length_seconds=target_length_seconds,
                bpm=loop.bpm
            )

            # Upload generated file to storage
            with open(result_path, "rb") as f:
                file_content = f.read()

            file_url = storage_service.upload_file(
                file_content=file_content,
                filename=output_filename,
                content_type="audio/wav"
            )

            # Update loop with generated file
            loop.processed_file_url = file_url
            loop.analysis_json = str(metadata)
            loop.status = "complete"

            db.commit()

            logger.info(f"Beat generation complete for loop {loop_id}")

        except Exception as e:
            logger.error(f"Beat generation failed for loop {loop_id}: {e}")
            logger.error(traceback.format_exc())

            # Update status to failed
            try:
                loop = db.query(Loop).filter(Loop.id == loop_id).first()
                if loop:
                    loop.status = "failed"
                    db.commit()
            except:
                pass

        finally:
            db.close()

    def extend_loop_task(
        self,
        loop_id: int,
        bars: int,
        output_filename: str
    ) -> None:
        """
        Background task to extend a loop to a specific number of bars.

        Args:
            loop_id: ID of the source loop
            bars: Number of bars to extend to
            output_filename: Name for the output file

        This function runs in a background task and updates the database.
        """
        # Create a new database session for this background task
        engine = create_engine(settings.database_url)
        SessionLocal = sessionmaker(bind=engine)
        db = SessionLocal()

        try:
            logger.info(f"Starting loop extension for loop {loop_id}, bars={bars}")

            # Get loop from database
            loop = db.query(Loop).filter(Loop.id == loop_id).first()
            if not loop:
                logger.error(f"Loop {loop_id} not found")
                return

            # Update status to processing
            loop.status = "processing"
            db.commit()

            # Get source file path
            source_path = storage_service.get_file_path(loop.file_url)

            if source_path is None:
                raise Exception("S3 file processing not yet implemented")

            if not source_path.exists():
                raise FileNotFoundError(f"Source file not found: {source_path}")

            # Generate output path
            output_path = f"renders/{output_filename}"

            # Extend loop
            result_path, metadata = audio_service.extend_loop(
                audio_path=str(source_path),
                output_path=output_path,
                bars=bars,
                bpm=loop.bpm
            )

            # Upload extended file to storage
            with open(result_path, "rb") as f:
                file_content = f.read()

            file_url = storage_service.upload_file(
                file_content=file_content,
                filename=output_filename,
                content_type="audio/wav"
            )

            # Update loop with extended file
            loop.processed_file_url = file_url
            loop.analysis_json = str(metadata)
            loop.status = "complete"

            db.commit()

            logger.info(f"Loop extension complete for loop {loop_id}")

        except Exception as e:
            logger.error(f"Loop extension failed for loop {loop_id}: {e}")
            logger.error(traceback.format_exc())

            # Update status to failed
            try:
                loop = db.query(Loop).filter(Loop.id == loop_id).first()
                if loop:
                    loop.status = "failed"
                    db.commit()
            except:
                pass

        finally:
            db.close()


# Global task service instance
task_service = TaskService()
