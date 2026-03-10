"""
Stem audio loading and management service.

Loads separated stem audio files from storage and provides them to the renderer
for real layer-based arrangement instead of DSP-only processing.
"""

import io
import logging
from pathlib import Path
from typing import Dict, Optional

import httpx
from pydub import AudioSegment

from app.config import settings
from app.services.storage import storage

logger = logging.getLogger(__name__)


class StemLoadError(Exception):
    """Raised when stem audio files cannot be loaded."""
    pass


def load_stems_from_metadata(
    stem_metadata: dict,
    timeout_seconds: float = 60.0,
) -> Dict[str, AudioSegment]:
    """
    Load stem audio files from storage based on stem metadata.
    
    Args:
        stem_metadata: Dict from loop.analysis_json["stem_separation"]
            Expected format:
            {
                "enabled": true,
                "succeeded": true,
                "stems": {
                    "drums": "loops/123_drums.wav",
                    "bass": "loops/123_bass.wav",
                    "melody": "loops/123_other.wav",
                    "vocal": "loops/123_vocals.wav"
                }
            }
        timeout_seconds: HTTP timeout for S3 downloads
    
    Returns:
        Dict mapping stem names to AudioSegment objects
        Example: {"drums": AudioSegment(...), "bass": AudioSegment(...)}
    
    Raises:
        StemLoadError: If stems cannot be loaded or are invalid
    """
    if not stem_metadata:
        raise StemLoadError("stem_metadata is None or empty")
    
    if not stem_metadata.get("enabled"):
        raise StemLoadError("Stem separation not enabled")
    
    if not stem_metadata.get("succeeded"):
        raise StemLoadError("Stem separation did not succeed")
    
    stems_dict = stem_metadata.get("stem_s3_keys") or stem_metadata.get("stems")
    if not stems_dict or not isinstance(stems_dict, dict):
        raise StemLoadError("No stems dict in metadata")
    
    loaded_stems: Dict[str, AudioSegment] = {}
    errors: Dict[str, str] = {}
    
    for stem_name, stem_key in stems_dict.items():
        if not stem_key:
            logger.warning(f"Stem '{stem_name}' has no file key, skipping")
            continue
        
        try:
            stem_audio = _load_stem_audio_from_storage(stem_key, timeout_seconds)
            
            # Validate stem audio
            if len(stem_audio) == 0:
                raise ValueError("Stem audio is empty")
            if stem_audio.channels not in {1, 2}:
                raise ValueError(f"Invalid channel count: {stem_audio.channels}")
            if stem_audio.frame_rate not in range(22050, 192001):
                raise ValueError(f"Invalid sample rate: {stem_audio.frame_rate}")
            
            loaded_stems[stem_name] = stem_audio
            logger.info(
                f"Loaded stem '{stem_name}': {len(stem_audio)}ms, "
                f"{stem_audio.channels}ch, {stem_audio.frame_rate}Hz"
            )
        
        except Exception as e:
            error_msg = f"Failed to load stem '{stem_name}' from {stem_key}: {e}"
            logger.warning(error_msg)
            errors[stem_name] = str(e)
    
    if not loaded_stems:
        raise StemLoadError(
            f"No stems could be loaded. Errors: {errors}"
        )
    
    logger.info(
        f"Successfully loaded {len(loaded_stems)}/{len(stems_dict)} stems: "
        f"{list(loaded_stems.keys())}"
    )
    
    return loaded_stems


def _load_stem_audio_from_storage(
    stem_key: str,
    timeout_seconds: float,
) -> AudioSegment:
    """Load a single stem audio file from S3 or local storage."""
    if storage.use_s3:
        # S3 path
        presigned_url = storage.create_presigned_get_url(stem_key, expires_seconds=3600)
        
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.get(presigned_url)
            response.raise_for_status()
            stem_bytes = response.content
        
        logger.debug(f"Downloaded stem from S3: {stem_key} ({len(stem_bytes)} bytes)")
        
        # Try WAV first, then fallback to other formats
        try:
            return AudioSegment.from_wav(io.BytesIO(stem_bytes))
        except Exception:
            # Try generic loader
            return AudioSegment.from_file(io.BytesIO(stem_bytes))
    
    else:
        # Local storage path
        filename = stem_key.split("/")[-1]
        local_path = storage.upload_dir / filename
        
        if not local_path.exists():
            raise FileNotFoundError(f"Stem file not found: {local_path}")
        
        logger.debug(f"Loading stem from local: {local_path}")
        
        try:
            return AudioSegment.from_wav(str(local_path))
        except Exception:
            return AudioSegment.from_file(str(local_path))


def validate_stem_sync(
    stems: Dict[str, AudioSegment],
    tolerance_ms: int = 100,
) -> bool:
    """
    Validate that all stems have similar durations (are in sync).
    
    Args:
        stems: Dict of stem name to AudioSegment
        tolerance_ms: Maximum allowed duration difference in milliseconds
    
    Returns:
        True if all stems are within tolerance, False otherwise
    """
    if not stems:
        return False
    
    durations = [len(audio) for audio in stems.values()]
    min_duration = min(durations)
    max_duration = max(durations)
    
    duration_diff = max_duration - min_duration
    
    if duration_diff > tolerance_ms:
        logger.warning(
            f"Stem duration mismatch: {min_duration}ms to {max_duration}ms "
            f"(diff: {duration_diff}ms, tolerance: {tolerance_ms}ms)"
        )
        return False
    
    logger.info(f"Stem sync validation passed: {min_duration}ms to {max_duration}ms")
    return True


def normalize_stem_durations(
    stems: Dict[str, AudioSegment],
) -> Dict[str, AudioSegment]:
    """
    Normalize all stems to the same duration (trim to shortest).
    
    Args:
        stems: Dict of stem name to AudioSegment
    
    Returns:
        Dict with all stems trimmed to same length
    """
    if not stems:
        return stems
    
    min_duration = min(len(audio) for audio in stems.values())
    
    normalized: Dict[str, AudioSegment] = {}
    for name, audio in stems.items():
        if len(audio) > min_duration:
            normalized[name] = audio[:min_duration]
            logger.debug(f"Trimmed stem '{name}' from {len(audio)}ms to {min_duration}ms")
        else:
            normalized[name] = audio
    
    return normalized


def map_instruments_to_stems(
    instruments: list[str],
    available_stems: Dict[str, AudioSegment],
) -> Dict[str, AudioSegment]:
    """
    Map section instrument list to available stems.
    
    Args:
        instruments: List like ["kick", "snare", "bass", "melody"]
        available_stems: Dict like {"drums": AudioSegment, "bass": AudioSegment}
    
    Returns:
        Dict of stems that should be enabled for this section
    
    Example:
        instruments = ["kick", "snare", "bass"]
        available_stems = {"drums", "bass", "melody", "vocal"}
        → returns {"drums": AudioSegment, "bass": AudioSegment}
    """
    enabled_stems: Dict[str, AudioSegment] = {}
    
    # Build mapping rules
    instrument_to_stem_map = {
        "kick": "drums",
        "snare": "drums",
        "drums": "drums",
        "percussion": "drums",
        "hats": "drums",
        "hi-hat": "drums",
        "bass": "bass",
        "sub": "bass",
        "melody": "melody",
        "lead": "melody",
        "synth": "melody",
        "keys": "melody",
        "pad": "harmony",
        "pads": "harmony",
        "chord": "harmony",
        "chords": "harmony",
        "harmony": "harmony",
        "strings": "harmony",
        "other": "melody",
        "fx": "fx",
        "sfx": "fx",
        "riser": "fx",
        "impact": "fx",
        "vocal": "vocal",
        "vocals": "vocal",
        "voice": "vocal",
    }
    
    # If no instruments specified, enable all stems
    if not instruments:
        return dict(available_stems)
    
    # Map instruments to stem names
    requested_stem_names = set()
    for instrument in instruments:
        instrument_lower = instrument.lower().strip()
        stem_name = instrument_to_stem_map.get(instrument_lower)
        if stem_name:
            requested_stem_names.add(stem_name)
    
    # Return matching stems
    for stem_name in requested_stem_names:
        if stem_name in available_stems:
            enabled_stems[stem_name] = available_stems[stem_name]
    
    logger.debug(
        f"Mapped instruments {instruments} → stems {list(enabled_stems.keys())} "
        f"(available: {list(available_stems.keys())})"
    )
    
    return enabled_stems
