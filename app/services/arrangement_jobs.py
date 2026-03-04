"""
Background job processing for arrangement generation.

Handles the async workflow of generating arrangements and updating database records.
"""

import io
import logging
import os
import tempfile
import json
import time
import uuid
from pathlib import Path

import httpx
from pydub import AudioSegment

from app.db import SessionLocal
from app.config import settings
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.arrangement_engine import render_phase_b_arrangement
from app.services.audit_logging import log_feature_event
from app.services.storage import storage

logger = logging.getLogger(__name__)


def _parse_style_sections(raw_json: str | None) -> list[dict] | None:
    """
    Parse style sections from arrangement_json.
    Supports both legacy format (array) and new format (object with seed + sections).
    Returns sections list only.
    """
    if not raw_json:
        return None

    try:
        payload = json.loads(raw_json)
    except Exception:
        return None

    # Handle new format: {"seed": 123, "sections": [...]}
    if isinstance(payload, dict):
        sections_data = payload.get("sections")
        if not isinstance(sections_data, list):
            return None
        payload = sections_data

    # Handle legacy format: [...]
    if not isinstance(payload, list):
        return None

    sections: list[dict] = []
    current_bar = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        bars = int(item.get("bars", 0) or 0)
        if bars <= 0:
            continue
        name = str(item.get("name", "section"))
        energy = float(item.get("energy", 0.6) or 0.6)
        sections.append(
            {
                "name": name,
                "bars": bars,
                "energy": max(0.0, min(1.0, energy)),
                "start_bar": current_bar,
                "end_bar": current_bar + bars - 1,
            }
        )
        current_bar += bars

    return sections or None


def _parse_seed_from_json(raw_json: str | None) -> int | None:
    """Extract seed from arrangement_json if present."""
    if not raw_json:
        return None

    try:
        payload = json.loads(raw_json)
        if isinstance(payload, dict):
            seed = payload.get("seed")
            if seed is not None:
                return int(seed)
    except Exception:
        pass

    return None


def _parse_style_profile(style_profile_json: str | None) -> dict | None:
    """
    Parse StyleProfile from JSON.
    Returns dict with resolved_params (style parameters for rendering).
    """
    if not style_profile_json:
        return None

    try:
        profile = json.loads(style_profile_json)
        return profile
    except Exception as e:
        logger.warning("Failed to parse style_profile_json: %s", e)
        return None


def _extract_correlation_id(arrangement_json: str | None) -> str | None:
    """Extract correlation id from arrangement JSON payload if present."""
    if not arrangement_json:
        return None
    try:
        payload = json.loads(arrangement_json)
        if isinstance(payload, dict):
            correlation_id = payload.get("correlation_id")
            if correlation_id:
                return str(correlation_id)
    except Exception:
        return None
    return None


def _build_render_plan_artifact(
    arrangement_id: int,
    bpm: float,
    target_seconds: int,
    timeline_json: str,
) -> dict:
    """Build a normalized render plan artifact for debug and acceptance checks."""
    timeline = {}
    try:
        timeline = json.loads(timeline_json) if timeline_json else {}
    except Exception:
        timeline = {}

    sections = timeline.get("sections") if isinstance(timeline, dict) else []
    events = timeline.get("events") if isinstance(timeline, dict) else []
    render_profile = timeline.get("render_profile") if isinstance(timeline, dict) else {}

    return {
        "arrangement_id": arrangement_id,
        "bpm": bpm,
        "target_seconds": target_seconds,
        "sections": sections or [],
        "events": events or [],
        "sections_count": len(sections or []),
        "events_count": len(events or []),
        "render_profile": render_profile or {},
    }


def _load_audio_segment_from_wav_bytes(wav_bytes: bytes) -> AudioSegment:
    """Load WAV/audio bytes with multiple fallback strategies."""
    if not wav_bytes or len(wav_bytes) < 44:
        raise ValueError(f"Audio file too small: {len(wav_bytes)} bytes")
    
    # Strategy 1: Try pydub with automatic format detection (works for most files)
    try:
        logger.info("Attempting audio load with format auto-detection...")
        # Don't specify format - let pydub auto-detect
        return AudioSegment.from_file(io.BytesIO(wav_bytes))
    except Exception as e1:
        logger.warning("Auto-detection failed: %s. Trying explicit WAV format...", str(e1)[:100])
    
    # Strategy 2: Try explicit WAV format with codec handling
    try:
        logger.info("Attempting audio load with explicit WAV format...")
        # Try with explicit WAV format specification
        return AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
    except Exception as e2:
        logger.warning("Explicit WAV format failed: %s. Trying MP3 format...", str(e2)[:100])
    
    # Strategy 3: Try MP3 format (sometimes files are mislabeled)
    try:
        logger.info("Attempting audio load with MP3 format...")
        return AudioSegment.from_file(io.BytesIO(wav_bytes), format="mp3")
    except Exception as e3:
        logger.warning("MP3 format failed: %s", str(e3)[:100])
    
    # Strategy 4: Try OGG format
    try:
        logger.info("Attempting audio load with OGG format...")
        return AudioSegment.from_file(io.BytesIO(wav_bytes), format="ogg")
    except Exception as e4:
        logger.warning("OGG format failed: %s", str(e4)[:100])
    
    # All strategies failed - provide detailed error
    error_details = f"Auto-detect: {str(e1)[:80]} | WAV: {str(e2)[:80]} | MP3: {str(e3)[:80]} | OGG: {str(e4)[:80]}"
    logger.error("Audio decoding failed after all strategies. Details: %s", error_details)
    
    # Log file signature for debugging
    sig = wav_bytes[:4].hex() if len(wav_bytes) >= 4 else "???"
    logger.error("Audio file signature (first 4 bytes): %s", sig)
    
    raise ValueError(f"Cannot decode audio file in any supported format. File signature: {sig}. Errors: {error_details}")


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
        correlation_id = _extract_correlation_id(arrangement.arrangement_json) or str(uuid.uuid4())
        started_at = time.time()
        log_feature_event(
            logger,
            event="render_started",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            loop_id=arrangement.loop_id,
        )

        arrangement.status = "processing"
        arrangement.progress = 0.0
        arrangement.progress_message = "Starting generation..."
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

            logger.info(
                "Downloaded audio from S3: key=%s, size=%d bytes, first 4 bytes (hex)=%s",
                loop.file_key,
                len(input_bytes),
                input_bytes[:4].hex() if len(input_bytes) >= 4 else "???"
            )

            # Load audio with multi-strategy decoder
            try:
                loop_audio = _load_audio_segment_from_wav_bytes(input_bytes)
            except ValueError as decode_error:
                logger.error("All decoding strategies failed for loop %s: %s", arrangement.loop_id, decode_error)
                raise ValueError(f"Cannot decode loop audio: {decode_error}") from decode_error
        else:
            # Local fallback for development
            filename = loop.file_key.split("/")[-1]
            local_path = Path.cwd() / "uploads" / filename
            if not local_path.exists():
                raise FileNotFoundError(f"Loop file not found: {local_path}")
            with open(local_path, "rb") as local_audio_file:
                input_bytes = local_audio_file.read()
            logger.info(
                "Loaded audio from local file: path=%s, size=%d bytes",
                local_path,
                len(input_bytes)
            )
            loop_audio = _load_audio_segment_from_wav_bytes(input_bytes)

        # Render arrangement
        bpm = float(loop.bpm or loop.tempo or 120.0)
        target_seconds = int(arrangement.target_seconds or 180)
        style_sections = None
        seed = None
        style_params = None
        
        # V2: Parse style profile if using LLM-based styling
        if arrangement.ai_parsing_used and arrangement.style_profile_json:
            try:
                style_profile = _parse_style_profile(arrangement.style_profile_json)
                if style_profile:
                    style_params = style_profile.get("resolved_params")
                    if style_params is None:
                        style_params = {}
                    else:
                        style_params = dict(style_params)

                    intent = style_profile.get("intent") or {}
                    style_params["__archetype"] = intent.get("archetype")
                    style_params["__raw_input"] = intent.get("raw_input")

                    genre_hint = arrangement.genre or loop.genre
                    if genre_hint:
                        style_params["__genre_hint"] = genre_hint

                    seed = style_profile.get("seed")
                    style_sections = style_profile.get("sections")
                    logger.info(
                        "Using V2 style profile for arrangement %s (archetype: %s, confidence: %.2f)",
                        arrangement_id,
                        style_profile.get("intent", {}).get("archetype", "unknown"),
                        style_profile.get("intent", {}).get("confidence", 0.0),
                    )
            except Exception as style_error:
                logger.warning("Failed to load V2 style profile: %s", style_error)
                # Fall through to V1 parsing
        
        # V1: Parse style from arrangement_json (fallback)
        if settings.feature_style_engine and not style_sections:
            style_sections = _parse_style_sections(arrangement.arrangement_json)
            if not seed:
                seed = _parse_seed_from_json(arrangement.arrangement_json)
            if style_sections:
                logger.info("Applying V1 style section plan for arrangement %s", arrangement_id)
            if seed is not None:
                logger.info("Using seed %s for pattern generation in arrangement %s", seed, arrangement_id)

        try:
            arranged_audio, timeline_json = render_phase_b_arrangement(
                loop_audio=loop_audio,
                bpm=bpm,
                target_seconds=target_seconds,
                sections_override=style_sections,
                seed=seed,
                style_params=style_params,
            )
        except Exception as render_error:
            if settings.dev_fallback_loop_only and not settings.is_production:
                logger.warning(
                    "DEV_FALLBACK_LOOP_ONLY enabled - using loop-only fallback for arrangement %s: %s",
                    arrangement_id,
                    render_error,
                )
                log_feature_event(
                    logger,
                    event="fallback_loop_only_used",
                    correlation_id=correlation_id,
                    arrangement_id=arrangement_id,
                    reason=str(render_error),
                )
                target_ms = target_seconds * 1000
                repeats = (target_ms // len(loop_audio)) + 1
                arranged_audio = (loop_audio * repeats)[:target_ms]
                bar_duration_seconds = (60.0 / bpm) * 4.0
                bars = max(1, int(round(target_seconds / bar_duration_seconds)))
                events = [
                    {
                        "type": "fallback_loop_bar",
                        "bar": idx,
                        "time_seconds": round(idx * bar_duration_seconds, 3),
                        "genre_profile": "fallback_loop_only",
                    }
                    for idx in range(bars)
                ]
                timeline_json = json.dumps(
                    {
                        "bpm": bpm,
                        "render_profile": {
                            "genre_profile": "fallback_loop_only",
                            "fallback_used": True,
                        },
                        "events": events,
                        "sections": [
                            {
                                "name": "fallback_loop",
                                "bars": bars,
                                "energy": 0.5,
                                "start_bar": 0,
                                "end_bar": bars - 1,
                                "start_seconds": 0.0,
                                "end_seconds": round(target_seconds, 3),
                            }
                        ],
                    }
                )
            else:
                raise

        render_plan = _build_render_plan_artifact(
            arrangement_id=arrangement_id,
            bpm=bpm,
            target_seconds=target_seconds,
            timeline_json=timeline_json,
        )
        log_feature_event(
            logger,
            event="render_plan_built",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            sections_count=render_plan.get("sections_count", 0),
            events_count=render_plan.get("events_count", 0),
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
        log_feature_event(
            logger,
            event="storage_uploaded",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            storage_backend="s3" if storage.use_s3 else "local",
            output_key=output_key,
        )

        if not storage.use_s3:
            debug_plan_path = Path.cwd() / "uploads" / f"{arrangement_id}_render_plan.json"
            debug_plan_path.parent.mkdir(parents=True, exist_ok=True)
            debug_plan_path.write_text(json.dumps(render_plan, indent=2), encoding="utf-8")
            logger.info("Wrote local render plan artifact: %s", debug_plan_path)

        output_url = storage.create_presigned_get_url(
            output_key,
            expires_seconds=3600,
            download_filename=f"arrangement_{arrangement_id}.wav",
        )

        arrangement.status = "done"
        arrangement.progress = 100.0
        arrangement.progress_message = "Generation complete"
        arrangement.output_s3_key = output_key
        arrangement.output_url = output_url
        arrangement.arrangement_json = timeline_json
        arrangement.error_message = None
        db.commit()

        logger.info(f"Successfully completed arrangement {arrangement_id}")
        log_feature_event(
            logger,
            event="render_finished",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            duration_sec=round(time.time() - started_at, 3),
        )

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
