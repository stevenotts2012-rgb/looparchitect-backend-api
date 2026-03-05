"""Async render worker: pulls jobs from Redis queue and processes them."""

import logging
import os
import tempfile
import traceback
from datetime import datetime
from pathlib import Path
from typing import Dict, List

from tenacity import retry, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, engine
from app.models.job import RenderJob
from app.models.loop import Loop
from app.services.job_service import update_job_status
from app.services.storage import storage
from app.schemas.job import OutputFile

logger = logging.getLogger(__name__)

# Job module imports
MODELS_TO_REGISTER = [
    "app.models.loop",
    "app.models.arrangement",
    "app.models.job",
]


def _ensure_db_models():
    """Ensure all models are registered with Base.metadata."""
    from app.models.base import Base
    
    for module_name in MODELS_TO_REGISTER:
        try:
            __import__(module_name)
        except Exception as e:
            logger.warning(f"Failed to import {module_name}: {e}")
    
    Base.metadata.create_all(bind=engine)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _download_loop_audio(loop: Loop, temp_dir: Path) -> Path:
    """Download loop audio from S3 to local temp file."""
    if not (loop.file_key or loop.file_url):
        raise ValueError(f"Loop {loop.id} has no audio file")
    
    import boto3
    
    audio_key = loop.file_key or loop.file_url
    temp_file = temp_dir / f"input_{loop.id}.wav"
    
    if loop.file_key:
        # Download from S3
        try:
            region = settings.aws_region
            bucket = settings.aws_s3_bucket
            if not region or not bucket:
                raise ValueError("Missing AWS_REGION or AWS_S3_BUCKET for S3 download")
            s3_client = boto3.client(
                's3',
                aws_access_key_id=settings.aws_access_key_id,
                aws_secret_access_key=settings.aws_secret_access_key,
                region_name=region,
            )
            s3_client.download_file(bucket, audio_key, str(temp_file))
            logger.info(f"Downloaded S3:{bucket}/{audio_key} to {temp_file}")
        except Exception as e:
            logger.error(f"S3 download failed: {e}")
            raise
    else:
        # Local fallback: read from uploads
        upload_path = Path("uploads") / audio_key.split("/")[-1]
        if upload_path.exists():
            import shutil
            shutil.copy(upload_path, temp_file)
            logger.info(f"Copied local file {upload_path} to {temp_file}")
        else:
            raise FileNotFoundError(f"Audio file not found: {upload_path}")
    
    return temp_file


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def _upload_render_output(job_id: str, filename: str, file_path: Path) -> tuple[str, str]:
    """Upload render output to S3, return (s3_key, content_type)."""
    s3_key = f"renders/{job_id}/{filename}"
    content_type = "audio/wav"
    
    with open(file_path, "rb") as f:
        file_bytes = f.read()
    
    storage.upload_file(file_bytes, content_type, s3_key)
    logger.info(f"Uploaded render to S3: {s3_key}")
    
    return s3_key, content_type


def render_loop_worker(job_id: str, loop_id: int, params: Dict) -> None:
    """
    Worker function: process a single render job.
    
    Called by RQ when job is dequeued.
    """
    _ensure_db_models()
    db = SessionLocal()
    
    try:
        # Load job and loop
        job = db.query(RenderJob).filter(RenderJob.id == job_id).first()
        if not job:
            logger.error(f"Job {job_id} not found in database")
            return
        
        loop = db.query(Loop).filter(Loop.id == loop_id).first()
        if not loop:
            logger.error(f"Loop {loop_id} not found for job {job_id}")
            update_job_status(
                db,
                job_id,
                "failed",
                error_message=f"Loop {loop_id} not found",
            )
            return
        
        # Load arrangement with producer data (if available)
        from app.models.arrangement import Arrangement
        
        arrangement = db.query(Arrangement).filter(
            Arrangement.loop_id == loop_id
        ).order_by(Arrangement.created_at.desc()).first()
        
        logger.info(
            f"[{job_id}] Starting render for loop {loop_id} "
            f"(producer_data={'YES' if arrangement and arrangement.producer_arrangement_json else 'NO'})"
        )
        
        # Mark as processing
        update_job_status(db, job_id, "processing", progress=10.0)
        
        # Create temporary working directory
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)
            
            # Download audio
            update_job_status(db, job_id, "processing", progress=20.0, progress_message="Downloading audio")
            input_file = _download_loop_audio(loop, temp_dir)
            
            # Load and prepare audio
            update_job_status(db, job_id, "processing", progress=30.0, progress_message="Loading audio")
            from pydub import AudioSegment
            
            try:
                audio = AudioSegment.from_file(str(input_file))
            except Exception as e:
                raise ValueError(f"Failed to load audio: {e}")
            
            # Check if we have ProducerEngine arrangement data
            if arrangement and arrangement.producer_arrangement_json:
                # ========================================
                # ProducerEngine Path (Structured Render)
                # ========================================
                logger.info(f"[{job_id}] Using ProducerEngine arrangement for structured render")
                
                import json
                from app.services.producer_models import ProducerArrangement, Section, InstrumentType
                from app.services.audio_renderer import render_arrangement
                
                # Parse ProducerArrangement from JSON
                try:
                    wrapper_data = json.loads(arrangement.producer_arrangement_json)
                    
                    # Handle nested structure: {"version": "2.0", "producer_arrangement": {...}}
                    if "producer_arrangement" in wrapper_data:
                        producer_data = wrapper_data["producer_arrangement"]
                    else:
                        producer_data = wrapper_data
                    
                    # Reconstruct ProducerArrangement object
                    # Note: JSON doesn't preserve dataclass types, need to reconstruct
                    sections = []
                    for s_data in producer_data.get("sections", []):
                        from app.services.producer_models import SectionType
                        section = Section(
                            name=s_data.get("name", ""),
                            section_type=SectionType(s_data.get("type", "Verse")),
                            bar_start=s_data.get("bar_start", 0),
                            bars=s_data.get("bars", 8),
                            energy_level=s_data.get("energy", 0.5),
                            instruments=[InstrumentType(i) for i in s_data.get("instruments", [])],
                        )
                        sections.append(section)
                    
                    # Reconstruct energy curve
                    from app.services.producer_models import EnergyPoint
                    energy_curve = [
                        EnergyPoint(bar=ep["bar"], energy=ep["energy"])
                        for ep in producer_data.get("energy_curve", [])
                    ]
                    
                    # Create ProducerArrangement
                    producer_arrangement = ProducerArrangement(
                        tempo=producer_data.get("tempo", loop.bpm or 120.0),
                        total_bars=producer_data.get("total_bars", 64),
                        total_seconds=producer_data.get("total_seconds", 60.0),
                        sections=sections,
                        energy_curve=energy_curve,
                        genre=producer_data.get("genre", "generic"),
                    )
                    
                    logger.info(
                        f"[{job_id}] Parsed ProducerArrangement: "
                        f"{len(sections)} sections, {producer_arrangement.total_bars} bars"
                    )
                    
                except Exception as e:
                    logger.error(f"[{job_id}] Failed to parse producer_arrangement_json: {e}")
                    raise ValueError(f"Invalid producer arrangement data: {e}")
                
                # Render using ProducerEngine structure
                update_job_status(
                    db,
                    job_id,
                    "processing",
                    progress=60.0,
                    progress_message="Rendering structured arrangement",
                )
                
                try:
                    output_audio = render_arrangement(
                        audio,
                        producer_arrangement,
                        loop.bpm or 120.0
                    )
                except Exception as e:
                    logger.error(f"[{job_id}] Render failed: {e}")
                    raise ValueError(f"Audio rendering failed: {e}")
                
                # Export single arrangement file
                filename = "arrangement.wav"
                output_path = temp_dir / filename
                
                try:
                    output_audio.export(str(output_path), format="wav")
                    logger.info(f"[{job_id}] Exported arrangement: {filename}")
                except Exception as e:
                    raise ValueError(f"Failed to export arrangement: {e}")
                
                # Upload to S3
                update_job_status(db, job_id, "processing", progress=90.0, progress_message="Uploading")
                s3_key, content_type = _upload_render_output(job_id, filename, output_path)
                output_files = [
                    OutputFile(
                        name="Producer Arrangement",
                        s3_key=s3_key,
                        content_type=content_type,
                    )
                ]
                
            else:
                # ========================================
                # Legacy Path (Simple Variations)
                # ========================================
                logger.info(f"[{job_id}] No producer data, using legacy variation rendering")
                
                # Build variation profiles from params
                from app.routes.render import _compute_variation_profiles, _build_variation
            
                profiles = _compute_variation_profiles(type('RenderConfig', (), params)())
                output_files: List[OutputFile] = []
                
                # Render variations
                for i, profile in enumerate(profiles):
                    progress = 40.0 + (50.0 / len(profiles)) * i
                    update_job_status(
                        db,
                        job_id,
                        "processing",
                        progress=progress,
                        progress_message=f"Rendering {profile['name']} ({i+1}/{len(profiles)})",
                    )
                    
                    variation_audio = _build_variation(audio, profile["transformations"])
                    filename = f"{profile['name'].replace(' ', '_')}.wav"
                    output_path = temp_dir / filename
                    
                    try:
                        variation_audio.export(str(output_path), format="wav")
                        logger.info(f"[{job_id}] Exported variation: {filename}")
                    except Exception as e:
                        raise ValueError(f"Failed to export variation {profile['name']}: {e}")
                    
                    # Upload to S3
                    s3_key, content_type = _upload_render_output(job_id, filename, output_path)
                    output_files.append(
                        OutputFile(
                            name=profile["name"],
                            s3_key=s3_key,
                            content_type=content_type,
                        )
                    )
            
            # Mark as succeeded
            update_job_status(
                db,
                job_id,
                "succeeded",
                progress=100.0,
                output_files=output_files,
            )
            logger.info(f"[{job_id}] Render completed successfully")
    
    except Exception as e:
        logger.error(f"[{job_id}] Worker failed: {e}\n{traceback.format_exc()}")
        try:
            job = db.query(RenderJob).filter(RenderJob.id == job_id).first()
            if job:
                job.retry_count = (job.retry_count or 0) + 1
                update_job_status(
                    db,
                    job_id,
                    "failed",
                    error_message=f"{str(e)[:500]}",
                )
        except Exception as db_err:
            logger.error(f"Failed to update job status: {db_err}")
    
    finally:
        db.close()
