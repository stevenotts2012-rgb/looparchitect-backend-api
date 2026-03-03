"""
Loop business logic service.

Separates business logic from HTTP route handlers.
"""

import logging
import os
import uuid
from pathlib import Path
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopUpdate
from app.services.storage import storage

logger = logging.getLogger(__name__)


class LoopService:
    """Service layer for loop operations."""

    @staticmethod
    def create_loop(
        db: Session,
        loop_data: LoopCreate
    ) -> Loop:
        """
        Create a new loop record.

        Args:
            db: Database session
            loop_data: Loop creation data

        Returns:
            Created loop record

        Raises:
            Exception: If database operation fails
        """
        try:
            loop = Loop(**loop_data.model_dump())
            db.add(loop)
            db.commit()
            db.refresh(loop)
            logger.info(f"Loop created: {loop.id}")
            return loop
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to create loop: {e}")
            raise

    @staticmethod
    def list_loops(
        db: Session,
        status: Optional[str] = None,
        genre: Optional[str] = None,
        limit: int = 100,
        offset: int = 0
    ) -> List[Loop]:
        """
        List loops with optional filters.

        Args:
            db: Database session
            status: Filter by status (pending/processing/complete/failed)
            genre: Filter by genre
            limit: Maximum number of results
            offset: Pagination offset

        Returns:
            List of loop records
        """
        query = db.query(Loop)
        
        if status:
            query = query.filter(Loop.status == status)
        
        if genre:
            query = query.filter(Loop.genre == genre)
        
        loops = query.offset(offset).limit(limit).all()
        logger.info(f"Listed {len(loops)} loops (filters: status={status}, genre={genre})")
        return loops

    @staticmethod
    def get_loop(db: Session, loop_id: int) -> Optional[Loop]:
        """
        Get a single loop by ID.

        Args:
            db: Database session
            loop_id: Loop ID

        Returns:
            Loop record or None if not found
        """
        loop = db.query(Loop).filter(Loop.id == loop_id).first()
        if loop:
            logger.info(f"Loop retrieved: {loop_id}")
        else:
            logger.warning(f"Loop not found: {loop_id}")
        return loop

    @staticmethod
    def update_loop(
        db: Session,
        loop_id: int,
        update_data: LoopUpdate
    ) -> Optional[Loop]:
        """
        Update a loop record.

        Args:
            db: Database session
            loop_id: Loop ID
            update_data: Partial update data

        Returns:
            Updated loop record or None if not found

        Raises:
            Exception: If database operation fails
        """
        loop = db.query(Loop).filter(Loop.id == loop_id).first()
        
        if not loop:
            logger.warning(f"Cannot update - loop not found: {loop_id}")
            return None
        
        try:
            update_dict = update_data.model_dump(exclude_unset=True)
            for field, value in update_dict.items():
                setattr(loop, field, value)
            
            db.commit()
            db.refresh(loop)
            logger.info(f"Loop updated: {loop_id}")
            return loop
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to update loop {loop_id}: {e}")
            raise

    @staticmethod
    def delete_loop(
        db: Session,
        loop_id: int,
        delete_file: bool = True
    ) -> bool:
        """
        Delete a loop record and optionally its file.

        Args:
            db: Database session
            loop_id: Loop ID
            delete_file: Whether to delete the associated file

        Returns:
            True if deleted, False if not found

        Raises:
            Exception: If database operation fails
        """
        loop = db.query(Loop).filter(Loop.id == loop_id).first()
        
        if not loop:
            logger.warning(f"Cannot delete - loop not found: {loop_id}")
            return False
        
        try:
            # Delete file if requested
            if delete_file and loop.file_key:
                try:
                    storage.delete_file(loop.file_key)
                    logger.info(f"Deleted file for loop {loop_id}: {loop.file_key}")
                except Exception as e:
                    logger.error(f"Failed to delete file for loop {loop_id}: {e}")
                    # Continue with database deletion even if file deletion fails
            
            # Delete database record
            db.delete(loop)
            db.commit()
            logger.info(f"Loop deleted: {loop_id}")
            return True
        except Exception as e:
            db.rollback()
            logger.error(f"Failed to delete loop {loop_id}: {e}")
            raise

    @staticmethod
    def upload_loop_file(
        file_content: bytes,
        filename: str,
        content_type: str
    ) -> Tuple[str, str]:
        """
        Upload a loop file to storage (S3 or local).

        Args:
            file_content: Raw file bytes
            filename: Original filename
            content_type: MIME type

        Returns:
            Tuple of (file_key, file_url)
            - file_key: S3 key like "uploads/{uuid}.wav"
            - file_url: Backward-compatible local-style URL (e.g., /uploads/{uuid}.wav)

        Raises:
            Exception: If upload fails
        """
        # Generate unique S3 key with uploads/ prefix
        ext = Path(filename).suffix or ".wav"
        file_key = f"uploads/{uuid.uuid4()}{ext}"
        
        try:
            # Upload to S3 or local storage
            storage.upload_file(
                file_bytes=file_content,
                key=file_key,
                content_type=content_type
            )
            logger.info(f"File uploaded with key: {file_key}")
            file_url = f"/uploads/{Path(file_key).name}"
            return file_key, file_url
        except Exception as e:
            logger.error(f"Failed to upload file: {e}")
            raise

    @staticmethod
    def validate_audio_file(
        filename: str,
        content_type: str,
        file_size: int,
        max_size_mb: int = 50
    ) -> Tuple[bool, Optional[str]]:
        """
        Validate audio file before upload.

        Args:
            filename: Original filename
            content_type: MIME type
            file_size: File size in bytes
            max_size_mb: Maximum allowed size in MB

        Returns:
            Tuple of (is_valid, error_message)
        """
        # Validate file type
        allowed_types = {
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
            "audio/vnd.wave",
            "audio/mpeg",
            "audio/mp3"
        }
        
        if content_type not in allowed_types:
            return False, f"Invalid file type: {content_type}. Only WAV and MP3 files are allowed."
        
        # Validate extension
        ext = Path(filename).suffix.lower()
        allowed_extensions = {".wav", ".mp3"}
        
        if ext not in allowed_extensions:
            return False, f"Invalid file extension: {ext}. Only .wav and .mp3 files are allowed."
        
        # Validate file size
        max_size_bytes = max_size_mb * 1024 * 1024
        if file_size > max_size_bytes:
            return False, f"File too large: {file_size / 1024 / 1024:.1f}MB. Maximum: {max_size_mb}MB."
        
        if file_size == 0:
            return False, "File is empty."
        
        return True, None

    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """
        Sanitize filename to prevent path traversal and other security issues.

        Args:
            filename: Original filename

        Returns:
            Sanitized filename
        """
        # Get just the filename, no path components
        filename = os.path.basename(filename)
        
        # Remove any non-alphanumeric characters except dots, dashes, underscores
        safe_chars = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-_")
        filename = "".join(c if c in safe_chars else "_" for c in filename)
        
        # Limit length
        max_length = 255
        if len(filename) > max_length:
            ext = Path(filename).suffix
            filename = filename[:max_length - len(ext)] + ext
        
        return filename


# Global instance
loop_service = LoopService()
