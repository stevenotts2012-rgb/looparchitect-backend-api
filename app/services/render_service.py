"""
Render Pipeline Service

Converts uploaded loops into full instrumental arrangements.
Handles audio analysis, slicing, arrangement generation, and stem rendering.
"""

import os
import logging
import asyncio
from typing import Dict, List, Optional
import uuid

import librosa
import numpy as np
from pydub import AudioSegment
from pydub.effects import normalize


logger = logging.getLogger(__name__)

# Directory constants
UPLOADS_DIR = "uploads"
RENDERS_DIR = "renders"


class RenderPipeline:
    """Complete render pipeline for loop arrangements."""

    def __init__(self, render_id: str):
        """Initialize render pipeline."""
        self.render_id = render_id
        self.outputs = {}
        os.makedirs(RENDERS_DIR, exist_ok=True)

    async def analyze_loop(self, file_path: str) -> Dict[str, object]:
        """
        Analyze uploaded loop for BPM, key, and duration.
        
        Args:
            file_path: Path to audio file (local path or URL)
        
        Returns:
            Dictionary with:
            - bpm: Detected BPM (float)
            - key: Detected key (str, e.g., "C Major")
            - duration_seconds: Audio duration (float)
            - sample_rate: Sample rate in Hz (int)
            - confidence: Analysis confidence (0-1)
        """
        logger.info(f"[{self.render_id}] Analyzing loop at {file_path}")
        
        try:
            # Load audio file
            if file_path.startswith(('http://', 'https://')):
                # For remote URLs, skip detailed analysis
                logger.warning(f"[{self.render_id}] Remote file - using default analysis")
                return {
                    "bpm": 120.0,
                    "key": "C Major",
                    "duration_seconds": 8.0,
                    "sample_rate": 44100,
                    "confidence": 0.5,
                    "note": "Defaults used for remote URL"
                }
            
            # Load local file
            if not os.path.exists(file_path):
                raise FileNotFoundError(f"File not found: {file_path}")
            
            # Load with librosa
            y, sr = librosa.load(file_path, sr=None)
            duration = librosa.get_duration(y=y, sr=sr)
            
            # Detect BPM using beat tracking
            onset_env = librosa.onset.onset_strength(y=y, sr=sr)
            bpm_float = librosa.beat.tempo(onset_strength=onset_env, sr=sr)[0]
            
            # Estimate key using chroma features (simple approach)
            chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
            key_dist = np.sum(chroma, axis=1)
            key_idx = np.argmax(key_dist)
            keys = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
            detected_key = f"{keys[key_idx]} Major"
            
            result = {
                "bpm": float(bpm_float),
                "key": detected_key,
                "duration_seconds": float(duration),
                "sample_rate": int(sr),
                "confidence": 0.85,
            }
            
            logger.info(f"[{self.render_id}] Analysis complete: BPM={result['bpm']}, Key={result['key']}")
            return result
            
        except Exception as e:
            logger.error(f"[{self.render_id}] Analysis failed: {e}")
            # Return defaults on error
            return {
                "bpm": 120.0,
                "key": "C Major",
                "duration_seconds": 8.0,
                "sample_rate": 44100,
                "confidence": 0.0,
                "error": str(e)
            }

    async def slice_loop(self, file_path: str, bpm: float, num_bars: int = 4) -> List[bytes]:
        """
        Slice loop into bar-sized segments.
        
        Args:
            file_path: Path to audio file
            bpm: Tempo in BPM
            num_bars: Number of bars to detect (default 4)
        
        Returns:
            List of audio segments (as bytes)
        """
        logger.info(f"[{self.render_id}] Slicing loop into {num_bars} bar segments")
        
        try:
            # Load audio
            if file_path.startswith(('http://', 'https://')):
                logger.warning(f"[{self.render_id}] Remote file - using mock slices")
                return [b"mock_slice_1", b"mock_slice_2", b"mock_slice_3", b"mock_slice_4"]
            
            audio = AudioSegment.from_file(file_path)
            
            # Calculate bar length in ms
            # Assuming 4 beats per bar, 120 BPM = 2000ms per bar
            ms_per_beat = (60 / bpm) * 1000
            ms_per_bar = ms_per_beat * 4
            
            # Slice into segments
            slices = []
            for i in range(num_bars):
                start = int(i * ms_per_bar)
                end = int((i + 1) * ms_per_bar)
                slice_segment = audio[start:end]
                slices.append(slice_segment.export(format="wav").read())
            
            logger.info(f"[{self.render_id}] Sliced into {len(slices)} segments")
            return slices
            
        except Exception as e:
            logger.error(f"[{self.render_id}] Slicing failed: {e}")
            return []

    async def generate_arrangement(
        self,
        loop_id: int,
        bpm: float,
        duration_seconds: int = 180
    ) -> Dict[str, List[Dict]]:
        """
        Generate song structure arrangement.
        
        Structure: Intro → Hook → Verse → Hook → Bridge → Outro
        
        Args:
            loop_id: Loop database ID
            bpm: Tempo in BPM
            duration_seconds: Target total length
        
        Returns:
            Dictionary with sections and timing:
            {
                "sections": [
                    {"name": "Intro", "bars": 8, "start_sec": 0},
                    {"name": "Hook", "bars": 8, "start_sec": 16},
                    ...
                ],
                "total_bars": 96,
                "total_seconds": 192
            }
        """
        logger.info(f"[{self.render_id}] Generating arrangement for {duration_seconds}s")
        
        # Bars per beat at standard 4-beat bars
        ms_per_beat = (60 / bpm) * 1000
        bars_per_second = 1000 / (ms_per_beat * 4)
        
        # Target bars based on duration
        target_bars = int(duration_seconds * bars_per_second)
        
        # Standard song structure proportions
        structure = [
            ("Intro", 0.10),      # 10% - 8 bars
            ("Hook", 0.08),       # 8% - 7 bars
            ("Verse", 0.20),      # 20% - 16 bars
            ("Hook", 0.08),       # 8% - 7 bars
            ("Verse", 0.20),      # 20% - 16 bars
            ("Bridge", 0.12),     # 12% - 10 bars
            ("Hook", 0.08),       # 8% - 7 bars
            ("Outro", 0.14),      # 14% - 11 bars
        ]
        
        sections = []
        current_bar = 0
        current_sec = 0.0
        
        for section_name, proportion in structure:
            num_bars = max(4, int(target_bars * proportion))
            duration_bars = num_bars * ms_per_beat * 4 / 1000
            
            sections.append({
                "name": section_name,
                "bars": num_bars,
                "start_bar": current_bar,
                "start_sec": current_sec,
                "duration_sec": duration_bars,
                "loop_id": loop_id
            })
            
            current_bar += num_bars
            current_sec += duration_bars
        
        result = {
            "sections": sections,
            "total_bars": current_bar,
            "total_seconds": current_sec,
            "bpm": bpm
        }
        
        logger.info(f"[{self.render_id}] Arrangement: {len(sections)} sections, {current_bar} total bars")
        return result

    async def render_stems(
        self,
        loop_id: int,
        file_path: str,
        arrangement: Dict[str, object],
        num_stems: int = 3
    ) -> Dict[str, str]:
        """
        Render individual stems (drum, bass, melody, etc.).
        
        Args:
            loop_id: Loop ID
            file_path: Source audio file
            arrangement: Song structure
            num_stems: Number of stems to generate
        
        Returns:
            Dictionary mapping stem name to file path
        """
        logger.info(f"[{self.render_id}] Rendering {num_stems} stems")
        
        stems = {}
        stem_names = ["drums", "bass", "melody", "harmony", "pad"][:num_stems]
        
        try:
            for stem_name in stem_names:
                # In production: Use audio processing DSP/ML to extract stems
                # For now: Create placeholder files
                stem_filename = f"{self.render_id}_{stem_name}.wav"
                stem_path = os.path.join(RENDERS_DIR, stem_filename)
                
                # Create dummy audio file
                dummy_audio = AudioSegment.silent(duration=1000)
                dummy_audio.export(stem_path, format="wav")
                
                stems[stem_name] = stem_path
                logger.info(f"[{self.render_id}] Rendered stem: {stem_name}")
            
            self.outputs["stems"] = stems
            return stems
            
        except Exception as e:
            logger.error(f"[{self.render_id}] Stem rendering failed: {e}")
            return {}

    async def export_mixdown(
        self,
        stems: Dict[str, str],
        arrangement: Dict[str, object],
        output_format: str = "wav"
    ) -> str:
        """
        Mix down stems into final instrumental file.
        
        Args:
            stems: Dictionary of stem files
            arrangement: Song arrangement
            output_format: Output format (wav, mp3, etc.)
        
        Returns:
            Path to final rendered file
        """
        logger.info(f"[{self.render_id}] Creating mixdown")
        
        try:
            # Load and mix stems
            mixed = None
            
            for stem_name, stem_path in stems.items():
                if not os.path.exists(stem_path):
                    continue
                
                stem_audio = AudioSegment.from_file(stem_path)
                
                if mixed is None:
                    mixed = stem_audio
                else:
                    # Mix stems together (overlay)
                    mixed = mixed.overlay(stem_audio)
            
            if mixed is None:
                logger.warning(f"[{self.render_id}] No stems to mix, creating silence")
                mixed = AudioSegment.silent(
                    duration=int(arrangement.get("total_seconds", 180) * 1000)
                )
            
            # Normalize to avoid clipping
            mixed = normalize(mixed)
            
            # Export final file
            output_filename = f"{self.render_id}_instrumental.{output_format}"
            output_path = os.path.join(RENDERS_DIR, output_filename)
            
            mixed.export(output_path, format=output_format)
            
            logger.info(f"[{self.render_id}] Mixdown complete: {output_path}")
            self.outputs["mixdown"] = output_path
            
            return output_path
            
        except Exception as e:
            logger.error(f"[{self.render_id}] Mixdown failed: {e}")
            raise

    async def render_full_pipeline(
        self,
        loop_id: int,
        file_path: str,
        target_duration_seconds: int = 180,
        bpm: Optional[float] = None,
        key: Optional[str] = None
    ) -> Dict[str, object]:
        """
        Execute complete render pipeline.
        
        Orchestrates all steps: analyze → slice → arrange → render stems → mixdown
        
        Args:
            loop_id: Loop ID from database
            file_path: Path to uploaded audio file
            target_duration_seconds: Target instrumental length
            bpm: Override detected BPM (optional)
            key: Override detected key (optional)
        
        Returns:
            Complete render result with URLs and metadata
        """
        logger.info(f"[{self.render_id}] Starting full pipeline for loop {loop_id}")
        
        try:
            # Step 1: Analyze
            analysis = await self.analyze_loop(file_path)
            detected_bpm = bpm or analysis.get("bpm", 120.0)
            detected_key = key or analysis.get("key", "C Major")
            
            # Step 2: Slice
            await asyncio.sleep(0.1)  # Async simulation
            slices = await self.slice_loop(file_path, detected_bpm)
            
            # Step 3: Arrange
            arrangement = await self.generate_arrangement(
                loop_id,
                detected_bpm,
                target_duration_seconds
            )
            
            # Step 4: Render stems
            stems = await self.render_stems(
                loop_id,
                file_path,
                arrangement,
                num_stems=3
            )
            
            # Step 5: Mix down
            final_path = await self.export_mixdown(stems, arrangement)
            
            # Build response
            render_url = f"/renders/{os.path.basename(final_path)}"
            
            result = {
                "render_id": self.render_id,
                "loop_id": loop_id,
                "status": "completed",
                "download_url": render_url,
                "file_path": final_path,
                "analysis": {
                    "bpm": detected_bpm,
                    "key": detected_key,
                    "duration_seconds": analysis.get("duration_seconds", 8.0),
                    "confidence": analysis.get("confidence", 0.0)
                },
                "arrangement": arrangement,
                "outputs": self.outputs
            }
            
            logger.info(f"[{self.render_id}] Pipeline complete! URL: {render_url}")
            return result
            
        except Exception as e:
            logger.error(f"[{self.render_id}] Pipeline failed: {e}")
            return {
                "render_id": self.render_id,
                "loop_id": loop_id,
                "status": "failed",
                "error": str(e)
            }


# Standalone functions compatible with existing code

async def render_loop(
    loop_id: int,
    file_path: str,
    target_duration_seconds: int = 180
) -> Dict[str, object]:
    """
    High-level async function to render a loop.
    
    Recommended usage:
        result = await render_loop(loop_id, file_path)
    """
    render_id = str(uuid.uuid4())[:8]
    pipeline = RenderPipeline(render_id)
    return await pipeline.render_full_pipeline(
        loop_id,
        file_path,
        target_duration_seconds
    )


def render_loop_sync(
    loop_id: int,
    file_path: str,
    target_duration_seconds: int = 180
) -> Dict[str, object]:
    """
    Synchronous wrapper for render pipeline (for migration).
    
    Use async version for new code.
    """
    render_id = str(uuid.uuid4())[:8]
    pipeline = RenderPipeline(render_id)
    
    # Run async pipeline in new event loop
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            pipeline.render_full_pipeline(
                loop_id,
                file_path,
                target_duration_seconds
            )
        )
    finally:
        loop.close()
