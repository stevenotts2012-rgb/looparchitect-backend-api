"""
STEM-BASED RENDER EXECUTOR

Renders full arrangements by mixing stems according to a stem arrangement plan.
Replaces the old loop-replication approach with true stem mixing.
"""

import json
import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from pydub import AudioSegment
from app.services.stem_arrangement_engine import (
    StemArrangementEngine,
    StemRole,
    SectionConfig,
    StemState,
)
from app.services.mastering import apply_mastering

logger = logging.getLogger(__name__)


class StemRenderError(Exception):
    """Exception during stem rendering."""
    pass


class StemRenderExecutor:
    """
    Renders audio by mixing stems according to arrangement.
    
    Workflow:
    1. Load all stem audio files
    2. For each section in arrangement:
        - Identify active stems
        - Mix active stems together
        - Apply stem-level processing (gain, pan, filter)
        - Apply section transitions
        - Append to output
    3. Apply master processing
    """
    
    def __init__(self, target_sample_rate: int = 44100):
        """Initialize render executor."""
        self.target_sample_rate = target_sample_rate
        self.stems_cache: Dict[StemRole, AudioSegment] = {}
    
    def render_from_stems(
        self,
        stem_files: Dict[StemRole, Path],
        sections: List[SectionConfig],
        apply_master: bool = True,
    ) -> AudioSegment:
        """
        Render a full arrangement from stem files.
        
        Args:
            stem_files: Dict mapping StemRole to audio file path
            sections: List of SectionConfig objects defining arrangement
            apply_master: Whether to apply mastering
        
        Returns:
            Rendered AudioSegment
        """
        # Load all stem audio files
        self._load_stems(stem_files)
        
        # Verify stem compatibility
        self._validate_stem_compatibility()
        
        # Render section by section
        output = AudioSegment.empty()
        
        for section in sections:
            section_audio = self._render_section(section)
            output += section_audio
        
        # Apply mastering
        if apply_master:
            output = apply_mastering(output)
        
        logger.info(f"Rendered arrangement: {len(output) / 1000:.1f}s")
        
        return output
    
    def _load_stems(self, stem_files: Dict[StemRole, Path]) -> None:
        """Load all stem audio files into memory."""
        logger.info(f"Loading {len(stem_files)} stems...")
        
        for role, file_path in stem_files.items():
            if not Path(file_path).exists():
                raise StemRenderError(f"Stem file not found: {file_path}")
            
            try:
                audio = AudioSegment.from_file(str(file_path))
                # Resample to target if needed
                if audio.frame_rate != self.target_sample_rate:
                    audio = audio.set_frame_rate(self.target_sample_rate)
                self.stems_cache[role] = audio
                logger.info(f"Loaded {role.value}: {len(audio) / 1000:.1f}s")
            except Exception as e:
                raise StemRenderError(f"Failed to load stem {role.value}: {e}")
    
    def _validate_stem_compatibility(self) -> None:
        """Verify all stems have same length and sample rate."""
        if not self.stems_cache:
            raise StemRenderError("No stems loaded")
        
        lengths = [len(audio) for audio in self.stems_cache.values()]
        if len(set(lengths)) > 1:
            logger.warning(
                f"Stems have different lengths: {set(lengths)} ms. "
                f"Using longest: {max(lengths)}ms"
            )
        
        rates = [audio.frame_rate for audio in self.stems_cache.values()]
        if len(set(rates)) > 1:
            raise StemRenderError(
                f"Stems have different sample rates: {set(rates)}. "
                f"All stems must have same sample rate."
            )
    
    def _render_section(self, section: SectionConfig) -> AudioSegment:
        """Render a single section by mixing active stems."""
        logger.debug(
            f"Rendering section '{section.name}' ({section.bars} bars, "
            f"active={len(section.active_stems)} stems)"
        )
        
        # Determine duration of section in milliseconds
        # Assuming 4 beats per bar at the tempo
        ms_per_bar = (60000 * 4) / section.bpm
        section_duration_ms = int(ms_per_bar * section.bars)
        
        # Start with silence at section duration
        mixed = AudioSegment.silent(duration=section_duration_ms)
        mixed = mixed.set_frame_rate(self.target_sample_rate)
        
        # Mix active stems
        for role in section.active_stems:
            if role not in self.stems_cache:
                logger.warning(f"Stem {role.value} not loaded, skipping")
                continue
            
            stem_audio = self.stems_cache[role]
            stem_state = section.stem_states.get(role)
            
            # Extract the section slice from stem
            # (assumes stems are loop-based, cycle through them)
            stem_slice = self._extract_stem_slice(stem_audio, section_duration_ms)
            
            # Apply stem-level processing
            if stem_state:
                stem_slice = self._apply_stem_processing(stem_slice, stem_state)
            
            # Mix
            mixed = self._mix_audio(mixed, stem_slice)
        
        # Apply producer moves (transitions, fills, etc.)
        if section.producer_moves:
            mixed = self._apply_producer_moves(mixed, section)
        
        return mixed
    
    def _extract_stem_slice(self, stem: AudioSegment, duration_ms: int) -> AudioSegment:
        """
        Extract a slice of stem audio at specified duration.
        For loop-based stems, cycles through the audio.
        """
        if len(stem) >= duration_ms:
            # Stem is long enough, just take a slice
            return stem[:duration_ms]
        else:
            # Loop the stem to fill duration
            repetitions = (duration_ms // len(stem)) + 1
            looped = stem * repetitions
            return looped[:duration_ms]
    
    def _apply_stem_processing(self, audio: AudioSegment, state: StemState) -> AudioSegment:
        """Apply gain, pan, and filtering to stem."""
        # Apply gain
        if state.gain_db != 0.0:
            audio = audio + state.gain_db
        
        # Apply pan (simple split-based pan)
        if state.pan != 0.0:
            audio = self._apply_pan(audio, state.pan)
        
        # Apply filter
        if state.filter_cutoff is not None:
            audio = audio.low_pass_filter(int(state.filter_cutoff))
        
        return audio
    
    def _apply_pan(self, audio: AudioSegment, pan: float) -> AudioSegment:
        """
        Apply panning to audio.
        pan: -1.0 (full left) to 1.0 (full right), 0.0 = center
        """
        if audio.channels == 1:
            # Convert mono to stereo first
            audio = audio.set_channels(2)
        
        if audio.channels == 2:
            # Pan by modulating left/right channels
            # Negative pan: reduce right, keep/boost left
            # Positive pan: reduce left, keep/boost right
            
            left_gain = max(0.0, 1.0 - pan)  # 0.0 to 1.0
            right_gain = max(0.0, 1.0 + pan)  # 0.0 to 1.0
            
            # Get raw data
            data = np.array(audio.get_array_of_samples())
            if audio.sample_width == 2:
                data = data.astype(np.int16)
            
            # Reshape to stereo
            data = data.reshape((-1, 2))
            data[..., 0] = (data[..., 0] * left_gain).astype(data.dtype)
            data[..., 1] = (data[..., 1] * right_gain).astype(data.dtype)
            data = data.flatten()
            
            audio = audio._spawn(data.tobytes())
        
        return audio
    
    def _mix_audio(self, base: AudioSegment, to_add: AudioSegment) -> AudioSegment:
        """Mix two audio segments by overlaying them."""
        # Ensure same duration
        if len(to_add) < len(base):
            to_add = to_add + AudioSegment.silent(duration=len(base) - len(to_add))
        elif len(to_add) > len(base):
            to_add = to_add[:len(base)]
        
        # Ensure same channels
        if base.channels != to_add.channels:
            if base.channels == 1:
                base = base.set_channels(2)
            if to_add.channels == 1:
                to_add = to_add.set_channels(2)
        
        # Mix at reduced levels to avoid clipping
        # Standard mixing: reduce each by -3dB (-0.7x)
        return (base - 3) + (to_add - 3)
    
    def _apply_producer_moves(self, section_audio: AudioSegment, section: SectionConfig) -> AudioSegment:
        """Apply producer-style effects and transitions to section."""
        if not section.producer_moves:
            return section_audio
        
        for move in section.producer_moves:
            move_value = move.value
            
            if move_value == "drum_fill":
                # Add emphasis to last bar: boost drums/percussion
                bar_duration_ms = int((60000 * 4) / section.bpm)
                fill_start = len(section_audio) - bar_duration_ms
                if fill_start >= 0:
                    # Boost last bar slightly
                    section_audio = (section_audio[:fill_start] + 
                                    (section_audio[fill_start:] + 2))
            
            elif move_value == "pre_hook_silence":
                # Create brief silence just before section for impact
                silence_duration_ms = int((60000 * 4) / section.bpm / 2)  # Half bar
                audio_without_end = section_audio[:-silence_duration_ms]
                silence = AudioSegment.silent(duration=silence_duration_ms)
                section_audio = audio_without_end + silence
            
            elif move_value == "riser_fx":
                # Add slight pitch rise effect (high-pass filter sweep)
                # This is subtle - just raise upper mids
                pass  # Implemented via stem-level filters
            
            elif move_value == "crash_hit":
                # Brief peak at start
                bar_duration_ms = int((60000 * 4) / section.bpm / 4)
                if bar_duration_ms > 0:
                    peak = section_audio[: min(bar_duration_ms, len(section_audio))] + 4
                    section_audio = peak + section_audio[bar_duration_ms:]
            
            elif move_value == "bass_pause":
                # Reduce bass stem for transition
                # This would need to be applied at stem level, not post-mix
                pass
        
        return section_audio
    
    def render_to_file(
        self,
        stem_files: Dict[StemRole, Path],
        sections: List[SectionConfig],
        output_path: Path,
        format: str = "wav",
    ) -> Path:
        """Render and save to file."""
        audio = self.render_from_stems(stem_files, sections)
        audio.export(str(output_path), format=format)
        logger.info(f"Rendered to {output_path}")
        return output_path
