"""
Variation Engine: Add fills, dropouts, and beat patterns to prevent loop repetition.

Variation types:
- Fill: Add drum pattern intensification (hi-hat roll, snare flam)
- Dropout: Mute kick/bass/drums for 1-2 bars before re-entry
- Chop: Stutter effect (short muting pulses)
- Filter Sweep: Low-pass filter sweep rising into section
- Reverse: Reverse cymbal or sound effect
- Halt: Brief silence for tension
"""

import logging
from typing import List, Optional, Tuple
import numpy as np
from pydub import AudioSegment
from enum import Enum

from app.services.producer_models import Section, Variation, VariationType

logger = logging.getLogger(__name__)


class VariationEngine:
    """Create beat variations to prevent loop repetition."""
    
    @staticmethod
    def add_section_variations(
        audio: AudioSegment,
        section: Section,
        bpm: float = 120,
    ) -> AudioSegment:
        """
        Insert variations (fills, dropouts) within a section.
        
        Strategy:
        - For 8-bar sections: Add fill at bars 6-7 (before final bar)
        - For 16-bar sections: Add fill at bars 14-15
        - Add dropout 1 bar before section transition
        
        Args:
            audio: Input section audio (already looped to section length)
            section: Section metadata (name, bars, variations)
            bpm: Tempo for calculating bar/beat durations
        
        Returns:
            Audio with variations applied
        """
        try:
            ms_per_beat = (60.0 / bpm) * 1000  # milliseconds per beat
            ms_per_bar = ms_per_beat * 4  # assume 4/4 time
            
            result = audio
            
            # Process each variation in the section
            for variation in section.variations:
                variation_ms = int(variation.bar * ms_per_bar)
                
                logger.debug(
                    f"Applying {variation.variation_type.value} "
                    f"to {section.name} at bar {variation.bar}"
                )
                
                if variation.variation_type == VariationType.FILL:
                    # Add drum fill at specific bar
                    result = VariationEngine._add_fill(
                        result,
                        position_ms=variation_ms,
                        duration_ms=int(2 * ms_per_bar),  # 2-bar fill
                        intensity=variation.intensity,
                        bpm=bpm,
                    )
                
                elif variation.variation_type == VariationType.DROPOUT:
                    # Mute kick/drums for 1 bar
                    result = VariationEngine._add_dropout(
                        result,
                        position_ms=variation_ms,
                        duration_ms=int(ms_per_bar),
                    )
                
                elif variation.variation_type == VariationType.CHOP:
                    # Stutter effect
                    result = VariationEngine._add_chop(
                        result,
                        position_ms=variation_ms,
                        duration_ms=int(ms_per_bar),
                        intensity=variation.intensity,
                    )
                
                elif variation.variation_type == VariationType.FILTER_SWEEP:
                    # Low-pass filter sweep
                    result = VariationEngine._add_filter_sweep(
                        result,
                        position_ms=variation_ms,
                        duration_ms=int(2 * ms_per_bar),
                        sweep_direction="rising",
                    )
                
                elif variation.variation_type == VariationType.REVERSE:
                    # Reverse cymbal or effect
                    result = VariationEngine._add_reverse_effect(
                        result,
                        position_ms=variation_ms,
                        duration_ms=int(ms_per_bar),
                    )
            
            return result
        
        except Exception as e:
            logger.warning(f"Variation application failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _add_fill(
        audio: AudioSegment,
        position_ms: int,
        duration_ms: int = 2000,
        intensity: float = 0.8,
        bpm: float = 120,
    ) -> AudioSegment:
        """
        Add a drum fill at a specific position.
        
        Strategy:
        - Extract a portion of the audio at the fill position
        - Increase playback speed to create "urgency"
        - Add parametric variation to make it different from original
        """
        try:
            # Clamp position to valid range
            position_ms = max(0, min(len(audio) - duration_ms, position_ms))
            
            # Get the portion at fill position
            fill_segment = audio[position_ms:position_ms + duration_ms]
            
            if len(fill_segment) < duration_ms:
                # Pad with repetition if too short
                fill_segment = fill_segment + audio[:(duration_ms - len(fill_segment))]
            
            # 1. Speed up slightly (create "urgency")
            # Increase speed by 10-20% based on intensity
            speed_multiplier = 1.0 + (intensity * 0.1)  # 1.0 to 1.1x speed
            fill_segment_fast = fill_segment.speedup(speed_multiplier)
            
            # 2. Add emphasis by increasing volume
            emphasis_db = 3.0 + (intensity * 3.0)  # 3 to 6 dB boost
            fill_segment_fast = fill_segment_fast.apply_gain(emphasis_db)
            
            # 3. Trim back to original duration
            if len(fill_segment_fast) > duration_ms:
                fill_segment_fast = fill_segment_fast[:duration_ms]
            elif len(fill_segment_fast) < duration_ms:
                fill_segment_fast = fill_segment_fast + AudioSegment.silent(
                    duration=duration_ms - len(fill_segment_fast)
                )
            
            # Replace the fill position with the enhanced version
            before = audio[:position_ms]
            after = audio[position_ms + duration_ms:]
            result = before + fill_segment_fast + after
            
            logger.debug(
                f"Added fill at {position_ms}ms: "
                f"speed={speed_multiplier:.2f}x, emphasis={emphasis_db:.1f}dB"
            )
            
            return result
        
        except Exception as e:
            logger.debug(f"Fill creation failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _add_dropout(
        audio: AudioSegment,
        position_ms: int,
        duration_ms: int = 1000,
    ) -> AudioSegment:
        """
        Add a dropout (silence or heavily reduced level) to create tension.
        
        Strategy:
        - Reduce volume to minimum (simulate instruments stopping)
        - Or create brief silence for dramatic effect
        """
        try:
            position_ms = max(0, min(len(audio) - duration_ms, position_ms))
            
            # Get the portion to dropout
            dropout_segment = audio[position_ms:position_ms + duration_ms]
            
            # Options:
            # 1. Reduce volume dramatically (say to -24dB for near-silence)
            # 2. Or apply quick fade out/in
            
            # Create a very quiet version (but not complete silence - allows punch back in)
            dropout_segment = dropout_segment.apply_gain(-24)  # -24dB = very quiet
            
            # Apply fade in/out at boundaries for smoothness
            fade_duration_ms = 50
            dropout_segment = dropout_segment.fade_in(fade_duration_ms).fade_out(fade_duration_ms)
            
            # Replace dropout section
            before = audio[:position_ms]
            after = audio[position_ms + duration_ms:]
            result = before + dropout_segment + after
            
            logger.debug(f"Added dropout at {position_ms}ms for {duration_ms}ms")
            
            return result
        
        except Exception as e:
            logger.debug(f"Dropout creation failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _add_chop(
        audio: AudioSegment,
        position_ms: int,
        duration_ms: int = 1000,
        intensity: float = 0.5,
    ) -> AudioSegment:
        """
        Add a chop/stutter effect (rapid muting) for rhythmic variation.
        
        Creates effect like: "ch-ch-ch-chop" by rapidly muting and unmuting
        """
        try:
            position_ms = max(0, min(len(audio) - duration_ms, position_ms))
            
            # Get the portion to chop
            chop_segment = audio[position_ms:position_ms + duration_ms]
            
            # Determine chop rate based on intensity
            # 0.5 intensity: 8 chops per second
            # 1.0 intensity: 16 chops per second
            chops_per_sec = 8.0 + (intensity * 8.0)  # 8 to 16 chops/sec
            chop_period_ms = 1000.0 / chops_per_sec  # milliseconds per chop period
            
            # Create chopped version by rapid gain modulation
            chop_segment_array = np.array(chop_segment.get_array_of_samples())
            chop_segment_array = chop_segment_array.astype(np.float32) / 32768.0
            
            # Apply gain envelope at chop rate
            sample_rate = audio.frame_rate
            samples_per_chop_period = int(chop_period_ms * sample_rate / 1000.0)
            
            # Create envelope: on for first half, off for second half of each period
            envelope = np.zeros_like(chop_segment_array)
            for i in range(len(envelope)):
                period_position = i % samples_per_chop_period
                if period_position < samples_per_chop_period / 2:
                    # Keep sound
                    envelope[i] = 1.0
                else:
                    # Mute
                    envelope[i] = 0.1  # 0.1 = very quiet but not complete silence
            
            # Apply envelope
            chopped = chop_segment_array * envelope
            chopped = np.int16(np.clip(chopped * 32768.0, -32768, 32767))
            
            chop_segment = AudioSegment(
                chopped.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
            
            # Also reduce volume of chop section overall
            chop_segment = chop_segment.apply_gain(-3)
            
            # Replace chop section
            before = audio[:position_ms]
            after = audio[position_ms + duration_ms:]
            result = before + chop_segment + after
            
            logger.debug(
                f"Added chop at {position_ms}ms: "
                f"rate={chops_per_sec:.0f} chops/sec"
            )
            
            return result
        
        except Exception as e:
            logger.debug(f"Chop creation failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _add_filter_sweep(
        audio: AudioSegment,
        position_ms: int,
        duration_ms: int = 2000,
        sweep_direction: str = "rising",  # "rising" or "falling"
    ) -> AudioSegment:
        """
        Add a filter sweep (low-pass cutoff rising or falling).
        
        Creates sweeping effect like a riser or downlifter.
        """
        try:
            from scipy import signal
            
            position_ms = max(0, min(len(audio) - duration_ms, position_ms))
            
            # Get the portion to filter
            sweep_segment = audio[position_ms:position_ms + duration_ms]
            
            # Get samples
            samples = np.array(sweep_segment.get_array_of_samples())
            samples = samples.astype(np.float32) / 32768.0
            
            sample_rate = audio.frame_rate
            num_samples = len(samples) if audio.channels == 1 else len(samples) // 2
            
            # Create time-varying low-pass filter
            # Start: ~500Hz (dark)
            # End: ~8kHz (bright) for rising sweep, reverse for falling
            
            if sweep_direction == "rising":
                start_hz = 500.0
                end_hz = 8000.0
            else:
                start_hz = 8000.0
                end_hz = 500.0
            
            # Create frequency trajectory
            freqs = np.linspace(start_hz, end_hz, num_samples)
            
            # Apply time-varying low-pass filter
            # Simple approach: apply series of fixed filters, increasing resolution
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                for ch in range(2):
                    samples[:, ch] = VariationEngine._apply_filter_sweep_mono(
                        samples[:, ch],
                        freqs,
                        sample_rate,
                    )
            else:
                samples = VariationEngine._apply_filter_sweep_mono(
                    samples,
                    freqs,
                    sample_rate,
                )
            
            # Clip and convert back
            samples = np.int16(np.clip(samples * 32768.0, -32768, 32767))
            
            sweep_segment = AudioSegment(
                samples.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
            
            # Replace sweep section
            before = audio[:position_ms]
            after = audio[position_ms + duration_ms:]
            result = before + sweep_segment + after
            
            logger.debug(
                f"Added {sweep_direction} filter sweep at {position_ms}ms: "
                f"{start_hz:.0f}Hz → {end_hz:.0f}Hz"
            )
            
            return result
        
        except Exception as e:
            logger.debug(f"Filter sweep failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _apply_filter_sweep_mono(
        samples: np.ndarray,
        cutoff_hz: np.ndarray,  # Time-varying cutoff frequencies
        sample_rate: float,
    ) -> np.ndarray:
        """Apply time-varying low-pass filter to mono samples."""
        try:
            from scipy import signal
            
            # Apply low-pass filter with slowly changing cutoff
            # Divide into chunks and apply fixed filter to each
            num_chunks = max(2, len(samples) // 1000)  # At least one per 1000 samples
            chunk_size = len(samples) // num_chunks
            
            filtered = np.copy(samples)
            
            for chunk_idx in range(num_chunks):
                start_idx = chunk_idx * chunk_size
                end_idx = start_idx + chunk_size if chunk_idx < num_chunks - 1 else len(samples)
                
                # Get cutoff frequency for this chunk
                avg_cutoff = np.mean(cutoff_hz[start_idx:end_idx])
                
                # Design filter
                nyquist = sample_rate / 2
                normalized_cutoff = avg_cutoff / nyquist
                
                if normalized_cutoff > 0.0 and normalized_cutoff < 1.0:
                    b, a = signal.butter(2, normalized_cutoff, btype='low')
                    
                    # Apply filter to window with padding for smooth transitions
                    pad_size = 200
                    if start_idx >= pad_size and end_idx + pad_size <= len(samples):
                        padded = filtered[start_idx - pad_size:end_idx + pad_size]
                        filtered_padded = signal.filtfilt(b, a, padded)
                        filtered[start_idx:end_idx] = filtered_padded[pad_size:-pad_size]
                    else:
                        filtered[start_idx:end_idx] = signal.filtfilt(b, a, filtered[start_idx:end_idx])
            
            return filtered
        
        except Exception as e:
            logger.debug(f"Filter sweep mono failed: {e}")
            return samples
    
    @staticmethod
    def _add_reverse_effect(
        audio: AudioSegment,
        position_ms: int,
        duration_ms: int = 1000,
    ) -> AudioSegment:
        """
        Add a reverse effect (cymbal swell) at specific position.
        
        Strategy:
        - Reverse a portion of the audio at the transition
        - Creates uplifting "reverse cymbal" sound
        """
        try:
            position_ms = max(0, min(len(audio) - duration_ms, position_ms))
            
            # Get the portion to reverse
            reverse_segment = audio[position_ms:position_ms + duration_ms]
            
            # Reverse it
            reversed_segment = reverse_segment.reverse()
            
            # Add slight volume boost for emphasis
            reversed_segment = reversed_segment.apply_gain(3)  # +3dB
            
            # Add fade in/out for smooth integration
            reversed_segment = reversed_segment.fade_in(100).fade_out(100)
            
            # Replace reverse section
            before = audio[:position_ms]
            after = audio[position_ms + duration_ms:]
            result = before + reversed_segment + after
            
            logger.debug(f"Added reverse effect at {position_ms}ms")
            
            return result
        
        except Exception as e:
            logger.debug(f"Reverse effect failed: {e}, returning original")
            return audio
