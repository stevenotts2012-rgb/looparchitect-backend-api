"""
Production-Ready Loop Analyzer Service for LoopArchitect

Analyzes audio loops from S3 storage with comprehensive feature detection:
- BPM/tempo detection via librosa
- Musical key detection
- Duration and bar calculation
- Async-compatible for FastAPI
- Safe temporary file handling
"""

import asyncio
import logging
import os
import tempfile
from pathlib import Path
from typing import Dict
import boto3
from botocore.exceptions import ClientError
import librosa
import numpy as np
import httpx

from app.config import settings
from app.services.storage import storage

logger = logging.getLogger(__name__)


class LoopAnalyzer:
    """Production-ready service for analyzing audio loop files from S3."""

    def __init__(self):
        """Initialize the loop analyzer with S3 client."""
        self.sample_rate = 44100  # Standard sample rate for analysis
        self.s3_client = None
        
        # Initialize S3 client if credentials available
        if storage.use_s3:
            try:
                self.s3_client = boto3.client(
                    's3',
                    aws_access_key_id=settings.aws_access_key_id,
                    aws_secret_access_key=settings.aws_secret_access_key,
                    region_name=settings.aws_region
                )
                self.bucket_name = settings.get_s3_bucket()
                logger.info("S3 client initialized for loop analysis")
            except Exception as e:
                logger.warning(f"S3 client initialization failed: {e}")
                self.s3_client = None

    async def analyze_from_s3(self, file_key: str) -> Dict:
        """
        Analyze audio loop from S3 storage (async-compatible).

        Downloads file temporarily, performs analysis, and cleans up.

        Args:
            file_key: S3 key (e.g., "uploads/abc123.wav")

        Returns:
            Dictionary with analysis results:
            {
                'bpm': float,
                'key': str,
                'duration': float,
                'bars': int
            }

        Raises:
            Exception: If download or analysis fails
        """
        temp_file = None
        try:
            logger.info(f"Starting analysis for S3 key: {file_key}")

            # Download file to temporary location
            temp_file = await self._download_from_s3_async(file_key)

            # Perform analysis (CPU-bound, run in executor)
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(None, self._analyze_file, temp_file)

            logger.info(f"Analysis complete for {file_key}: {result}")
            return result

        except Exception as e:
            logger.error(f"Analysis failed for {file_key}: {e}")
            raise

        finally:
            # Clean up temporary file (only if it's actually a temp file, not the original upload)
            if temp_file and os.path.exists(temp_file):
                # Only delete if it's in the system temp directory, not in uploads/
                if tempfile.gettempdir() in temp_file:
                    try:
                        os.unlink(temp_file)
                        logger.debug(f"Cleaned up temp file: {temp_file}")
                    except Exception as e:
                        logger.warning(f"Failed to clean up temp file {temp_file}: {e}")
                else:
                    logger.debug(f"Skipping cleanup of non-temp file: {temp_file}")

    def analyze_from_file(self, file_path: str) -> Dict:
        """
        Analyze audio loop from local file path (sync version).

        Args:
            file_path: Path to local audio file

        Returns:
            Dictionary with analysis results:
            {
                'bpm': float,
                'key': str,
                'duration': float,
                'bars': int
            }

        Raises:
            Exception: If analysis fails
        """
        try:
            logger.info(f"Starting analysis for local file: {file_path}")
            result = self._analyze_file(file_path)
            logger.info(f"Analysis complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Analysis failed for {file_path}: {e}")
            raise

    async def _download_from_s3_async(self, file_key: str) -> str:
        """
        Download file from S3 to temporary location (async).

        Args:
            file_key: S3 key

        Returns:
            Path to temporary file

        Raises:
            Exception: If download fails
        """
        if storage.use_s3 and self.s3_client:
            # S3 mode: Download using boto3
            try:
                # Create temporary file
                suffix = Path(file_key).suffix or '.wav'
                fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix='loop_analysis_')
                os.close(fd)  # Close file descriptor, we'll write via boto3

                # Download from S3
                logger.debug(f"Downloading {file_key} from S3 to {temp_path}")
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(
                    None,
                    self.s3_client.download_file,
                    self.bucket_name,
                    file_key,
                    temp_path
                )

                logger.info(f"Downloaded {file_key} to temporary file")
                return temp_path

            except ClientError as e:
                logger.error(f"S3 download failed for {file_key}: {e}")
                raise Exception(f"Failed to download from S3: {e}")

        else:
            # Local mode: Use presigned URL or direct file path
            try:
                # Get presigned URL (or local path)
                url = storage.create_presigned_get_url(file_key)

                if url.startswith('http'):
                    # Download via HTTP
                    suffix = Path(file_key).suffix or '.wav'
                    fd, temp_path = tempfile.mkstemp(suffix=suffix, prefix='loop_analysis_')
                    os.close(fd)

                    async with httpx.AsyncClient(timeout=60.0) as client:
                        response = await client.get(url)
                        response.raise_for_status()

                        with open(temp_path, 'wb') as f:
                            f.write(response.content)

                    logger.info(f"Downloaded {file_key} via HTTP to temporary file")
                    return temp_path
                else:
                    # Local file path - return as is
                    local_path = f"uploads/{file_key.split('/')[-1]}"
                    if os.path.exists(local_path):
                        return local_path
                    else:
                        raise FileNotFoundError(f"Local file not found: {local_path}")

            except Exception as e:
                logger.error(f"Local download failed for {file_key}: {e}")
                raise

    def _analyze_file(self, file_path: str) -> Dict:
        """
        Perform audio analysis on a file (sync, CPU-bound).

        Args:
            file_path: Path to audio file

        Returns:
            Dictionary with bpm, key, duration, bars
        """
        try:
            # Load audio file with librosa
            y, sr = librosa.load(file_path, sr=self.sample_rate, mono=True)

            # Detect BPM
            bpm = self._detect_bpm(y, sr)

            # Detect musical key
            key = self._detect_key(y, sr)

            # Calculate duration
            duration = float(len(y)) / float(sr)

            # Estimate bars (4/4 time signature)
            bars = self._estimate_bars(duration, bpm)

            # Return in requested format
            return {
                'bpm': round(bpm, 2),
                'key': key,
                'duration': round(duration, 2),
                'bars': bars
            }

        except Exception as e:
            logger.error(f"File analysis failed for {file_path}: {e}")
            raise Exception(f"Audio analysis failed: {e}")
            raise Exception(f"Audio analysis failed: {e}")

    def _detect_bpm(self, y: np.ndarray, sr: int) -> float:
        """
        Detect BPM/tempo using librosa beat tracking.

        Includes validation and edge case handling for production use.

        Args:
            y: Audio time series
            sr: Sample rate

        Returns:
            BPM as float (validated range: 60-200)
        """
        try:
            # Use librosa beat tracking with onset envelope
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            tempo = librosa.beat.tempo(onset_envelope=onset_env, sr=sr)
            
            # Extract float from numpy array
            if isinstance(tempo, np.ndarray):
                tempo = float(tempo[0]) if len(tempo) > 0 else 120.0
            else:
                tempo = float(tempo)

            # Validate and correct tempo range (typical music: 60-200 BPM)
            if tempo < 60:
                tempo = tempo * 2  # Double time correction
            elif tempo > 200:
                tempo = tempo / 2  # Half time correction
            
            # Final bounds check
            tempo = max(60.0, min(200.0, tempo))

            logger.debug(f"Detected BPM: {tempo}")
            return tempo

        except Exception as e:
            logger.warning(f"BPM detection failed: {e}, using default 120 BPM")
            return 120.0

    def _detect_key(self, y: np.ndarray, sr: int) -> str:
        """
        Detect musical key using chromagram analysis.

        Uses CQT (Constant-Q Transform) for better frequency resolution.

        Args:
            y: Audio time series
            sr: Sample rate

        Returns:
            Musical key as string (e.g., 'C', 'Dm', 'F#')
        """
        try:
            # Compute chromagram with CQT for better accuracy
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr, n_chroma=12)

            # Average over time to get overall pitch class distribution
            chroma_mean = np.mean(chroma, axis=1)

            # Find dominant pitch class
            key_idx = int(np.argmax(chroma_mean))

            # Note names (chromatic scale)
            notes = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            key = notes[key_idx]

            # Simple major/minor detection based on third interval
            # Minor third is 3 semitones, major third is 4 semitones
            minor_third_strength = chroma_mean[(key_idx + 3) % 12]
            major_third_strength = chroma_mean[(key_idx + 4) % 12]
            
            if minor_third_strength > major_third_strength:
                key += 'm'  # Minor key

            logger.debug(f"Detected key: {key}")
            return key

        except Exception as e:
            logger.warning(f"Key detection failed: {e}, using default 'C'")
            return 'C'

    def _estimate_bars(self, duration_seconds: float, bpm: float) -> int:
        """
        Estimate number of bars assuming 4/4 time signature.

        Args:
            duration_seconds: Duration in seconds
            bpm: Beats per minute

        Returns:
            Estimated number of bars (minimum 1)
        """
        if bpm <= 0:
            logger.warning("Invalid BPM for bar estimation, using default 4 bars")
            return 4

        try:
            # Calculate beats per second
            beats_per_second = bpm / 60.0

            # Total beats in the loop
            total_beats = duration_seconds * beats_per_second

            # Bars in 4/4 time (4 beats per bar)
            bars = total_beats / 4.0

            # Round to nearest integer
            bars_int = round(bars)

            # Ensure minimum of 1 bar
            bars_int = max(1, bars_int)

            logger.debug(f"Estimated bars: {bars_int} (duration={duration_seconds}s, bpm={bpm})")
            return bars_int

        except Exception as e:
            logger.warning(f"Bar estimation failed: {e}, using default 4 bars")
            return 4


# Singleton instance for easy import
loop_analyzer = LoopAnalyzer()
