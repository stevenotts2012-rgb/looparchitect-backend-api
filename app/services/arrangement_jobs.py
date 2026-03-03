"""
Background job processing for arrangement generation.

Handles the async workflow of generating arrangements and updating database records.
"""

import io
import logging
import os
import tempfile
import wave
from pathlib import Path

import httpx
from pydub import AudioSegment

from app.db import SessionLocal
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.arrangement_engine import render_phase_b_arrangement
from app.services.storage import storage

logger = logging.getLogger(__name__)


def _load_audio_segment_from_wav_bytes(wav_bytes: bytes) -> AudioSegment:
    """Load WAV bytes without requiring ffmpeg/ffprobe."""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wav_file:
            channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            pcm_data = wav_file.readframes(wav_file.getnframes())

        return AudioSegment(
            data=pcm_data,
            sample_width=sample_width,
            frame_rate=frame_rate,
            channels=channels,
        )
    except Exception as decode_error:
        logger.warning("Failed to decode WAV bytes, falling back to silence: %s", decode_error)
        return AudioSegment.silent(duration=1000)


def run_arrangement_job(arrangement_id: int):
    """
    Background job to generate an arrangement.

    This runs asynchronously in a BackgroundTask and:
    1. Loads the Arrangement and Loop records
    2. Downloads the loop audio from S3 via presigned URL
    3. Builds the arrangement timeline and audio
    4. Uploads the output WAV to S3
    5. Updates the Arrangement with results
    6. Handles errors gracefully

    Args:
        arrangement_id: ID of the Arrangement record to process
    """
    db = SessionLocal()

    try:
        arrangement = (
            db.query(Arrangement)
            .filter(Arrangement.id == arrangement_id)
            .first()
        )

        if not arrangement:
            logger.error(f"Arrangement {arrangement_id} not found")
            return

        logger.info(f"Starting arrangement generation for ID {arrangement_id}")

        arrangement.status = "processing"
        db.commit()

        loop = db.query(Loop).filter(Loop.id == arrangement.loop_id).first()
        if not loop:
            raise ValueError(f"Loop {arrangement.loop_id} not found")
        if not loop.file_key:
            raise ValueError(f"Loop {arrangement.loop_id} missing file_key")

        if storage.use_s3:
            # Create presigned URL to fetch the loop audio
            input_url = storage.create_presigned_get_url(loop.file_key, expires_seconds=3600)

            # Download audio from S3
            with httpx.Client(timeout=60.0) as client:
                response = client.get(input_url)
                response.raise_for_status()
                input_bytes = response.content

            # Load WAV audio bytes without relying on ffmpeg
            loop_audio = _load_audio_segment_from_wav_bytes(input_bytes)
        else:
            # Local fallback for development
            filename = loop.file_key.split("/")[-1]
            local_path = Path.cwd() / "uploads" / filename
            if not local_path.exists():
                raise FileNotFoundError(f"Loop file not found: {local_path}")
            with open(local_path, "rb") as local_audio_file:
                loop_audio = _load_audio_segment_from_wav_bytes(local_audio_file.read())

        # Render arrangement
        bpm = float(loop.bpm or loop.tempo or 120.0)
        target_seconds = int(arrangement.target_seconds or 180)
        arranged_audio, timeline_json = render_phase_b_arrangement(
            loop_audio=loop_audio,
            bpm=bpm,
            target_seconds=target_seconds,
        )

        # Export to temp WAV and upload to S3
        fd, temp_wav_path = tempfile.mkstemp(suffix=".wav")
        os.close(fd)
        try:
            arranged_audio.export(temp_wav_path, format="wav")
            with open(temp_wav_path, "rb") as temp_audio_file:
                output_bytes = temp_audio_file.read()
        finally:
            try:
                Path(temp_wav_path).unlink(missing_ok=True)
            except PermissionError:
                logger.warning("Could not remove temporary file: %s", temp_wav_path)

        output_key = f"arrangements/{arrangement_id}.wav"
        storage.upload_file(
            file_bytes=output_bytes,
            content_type="audio/wav",
            key=output_key,
        )

        output_url = storage.create_presigned_get_url(
            output_key,
            expires_seconds=3600,
            download_filename=f"arrangement_{arrangement_id}.wav",
        )

        arrangement.status = "done"
        arrangement.output_s3_key = output_key
        arrangement.output_url = output_url
        arrangement.arrangement_json = timeline_json
        arrangement.error_message = None
        db.commit()

        logger.info(f"Successfully completed arrangement {arrangement_id}")

    except Exception as e:
        logger.exception("Error generating arrangement %s", arrangement_id)

        try:
            arrangement.status = "failed"
            arrangement.error_message = str(e)
            db.commit()
        except Exception as db_error:
            logger.error(f"Failed to update arrangement error status: {str(db_error)}")

    finally:
        db.close()
