"""
Energy Modulation Engine: Translate energy curve (0.0-1.0) to audio effects.

Maps energy levels to:
- Volume (dB adjustment)
- Reverb depth (wet/dry mix)
- Compression (ratio and threshold)
- EQ (presence boost)
- Distortion (subtle at max energy)
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
import numpy as np
from pydub import AudioSegment
from pydub.effects import normalize

from app.services.producer_models import Section, SectionType

logger = logging.getLogger(__name__)


@dataclass
class EffectParameters:
    """Audio effect parameters derived from energy level."""
    volume_db: float          # -12 to 0 dB
    reverb_wet: float         # 0.0 to 0.8 (dry to wet)
    reverb_room_size: float   # 0.2 to 0.8
    reverb_decay: float       # 0.8 to 0.3 (seconds)
    compression_ratio: float  # 1.0 (off) to 4.0 (tight)
    compression_threshold: float  # -20 to -5 dB
    eq_presence_db: float     # -3 to 6 dB (boost at ~3kHz)
    distortion_drive: float   # 0.0 to 0.2 (subtle)


class EnergyModulationEngine:
    """Convert energy curve (0.0-1.0) to audio effects."""
    
    @staticmethod
    def get_effect_parameters(energy_level: float) -> EffectParameters:
        """
        Convert 0-1 energy to audio effect parameters.
        
        Energy mapping:
        - 0.0 (Minimal): Sparse, reverb-heavy, compressed
        - 0.3 (Low): Light drums, some body, moderate reverb
        - 0.5 (Medium): Full drums/bass, balanced effects
        - 0.7 (High): All instruments, presence peak, tight compression
        - 1.0 (Maximum): All loud, minimal reverb, aggressive compression
        
        Args:
            energy_level: 0.0 to 1.0 scale
        
        Returns:
            EffectParameters with all settings
        """
        # Clamp to valid range
        energy = max(0.0, min(1.0, energy_level))
        
        # Volume: lower energy = quieter, higher = louder
        # Range: -12dB at 0.0 to 0dB at 1.0
        volume_db = -12.0 + (energy * 12.0)
        
        # Reverb: inverse relationship (low energy = more reverb)
        # At low energy: wet=0.7 (lots of reverb)
        # At high energy: wet=0.1 (dry)
        reverb_wet = 0.7 - (energy * 0.6)  # 0.7 down to 0.1
        reverb_room_size = 0.6 + (energy * 0.2)  # 0.6 to 0.8
        reverb_decay = 1.2 - (energy * 0.9)  # 1.2s down to 0.3s
        
        # Compression: higher energy = more compression (tighter)
        # At low energy: ratio=1.0 (no compression)
        # At high energy: ratio=4.0 (tight)
        compression_ratio = 1.0 + (energy * 3.0)  # 1.0 to 4.0
        compression_threshold = -20.0 + (energy * 15.0)  # -20dB to -5dB
        
        # EQ Presence: boost high mids at higher energy for "punch"
        # At low energy: -2dB (duller)
        # At high energy: +6dB (bright/aggressive)
        eq_presence_db = -2.0 + (energy * 8.0)  # -2 to +6 dB
        
        # Distortion: only at high energy, very subtle
        # At energy < 0.8: no distortion
        # At energy 0.8-1.0: soft distortion
        if energy < 0.8:
            distortion_drive = 0.0
        else:
            # Ramp from 0 to 0.2 between 0.8 and 1.0
            distortion_drive = (energy - 0.8) * 1.0  # 0 to 0.2
        
        return EffectParameters(
            volume_db=volume_db,
            reverb_wet=reverb_wet,
            reverb_room_size=reverb_room_size,
            reverb_decay=reverb_decay,
            compression_ratio=compression_ratio,
            compression_threshold=compression_threshold,
            eq_presence_db=eq_presence_db,
            distortion_drive=distortion_drive,
        )
    
    @staticmethod
    def apply_energy_effects(
        audio: AudioSegment,
        energy_level: float,
        section_type: Optional[SectionType] = None,
    ) -> AudioSegment:
        """
        Apply EQ, reverb, compression, distortion based on energy level.
        
        Args:
            audio: Input AudioSegment
            energy_level: 0.0 to 1.0
            section_type: Optional section type for context (e.g., HOOK = more aggressive)
        
        Returns:
            Audio with effects applied
        """
        try:
            # Get effect parameters for this energy level
            params = EnergyModulationEngine.get_effect_parameters(energy_level)
            
            # Adjust for section type (hooks get more energy, verses less)
            if section_type == SectionType.HOOK:
                params.volume_db += 2.0  # Hooks are 2dB louder
                params.eq_presence_db += 2.0  # More presence in hooks
            elif section_type == SectionType.VERSE:
                params.volume_db -= 1.0  # Verses slightly quieter (vocal space)
                params.reverb_wet += 0.1  # More reverb in verses
            elif section_type == SectionType.BRIDGE:
                params.reverb_wet += 0.15  # Bridge is spacier
                params.reverb_decay *= 1.5  # Longer reverb in bridge
            
            result = audio
            
            # 1. Apply compression (tighten dynamic range at higher energy)
            if params.compression_ratio > 1.1:
                result = EnergyModulationEngine._apply_compression(
                    result,
                    ratio=params.compression_ratio,
                    threshold_db=params.compression_threshold,
                    attack_ms=5,
                    release_ms=50,
                )
            
            # 2. Apply EQ (presence peak at 3kHz)
            result = EnergyModulationEngine._apply_presence_eq(
                result,
                boost_db=params.eq_presence_db,
                center_hz=3000,
            )
            
            # 3. Apply volume scaling
            result = result.apply_gain(params.volume_db)
            
            # 4. Add reverb effect (simplified simulation)
            if params.reverb_wet > 0.05:
                result = EnergyModulationEngine._add_reverb_effect(
                    result,
                    wet=params.reverb_wet,
                    decay_seconds=params.reverb_decay,
                )
            
            # 5. Apply subtle distortion at max energy
            if params.distortion_drive > 0.01:
                result = EnergyModulationEngine._apply_soft_distortion(
                    result,
                    drive=params.distortion_drive,
                )
            
            logger.debug(
                f"Applied energy effects @ {energy_level:.2f}: "
                f"vol={params.volume_db:.1f}dB, "
                f"reverb={params.reverb_wet:.2f}, "
                f"comp_ratio={params.compression_ratio:.1f}, "
                f"presence={params.eq_presence_db:.1f}dB"
            )
            
            return result
        
        except Exception as e:
            logger.warning(f"Energy effect application failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _apply_compression(
        audio: AudioSegment,
        ratio: float = 2.0,
        threshold_db: float = -20,
        attack_ms: float = 5,
        release_ms: float = 100,
    ) -> AudioSegment:
        """
        Apply dynamic range compression.
        
        Ratio > 1.0 means output is quieter than input above threshold.
        E.g., ratio=4.0 means 4dB input above threshold = 1dB output above threshold.
        """
        try:
            # Get audio samples
            samples = np.array(audio.get_array_of_samples())
            
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                for ch in range(2):
                    samples[:, ch] = EnergyModulationEngine._compress_mono(
                        samples[:, ch],
                        ratio=ratio,
                        threshold_db=threshold_db,
                        attack_ms=attack_ms,
                        release_ms=release_ms,
                        sample_rate=audio.frame_rate,
                    )
            else:
                samples = EnergyModulationEngine._compress_mono(
                    samples,
                    ratio=ratio,
                    threshold_db=threshold_db,
                    attack_ms=attack_ms,
                    release_ms=release_ms,
                    sample_rate=audio.frame_rate,
                )
            
            # Clip and convert back
            samples = np.int16(np.clip(samples, -32768, 32767))
            
            return AudioSegment(
                samples.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
        
        except Exception as e:
            logger.debug(f"Compression failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _compress_mono(
        samples: np.ndarray,
        ratio: float,
        threshold_db: float,
        attack_ms: float,
        release_ms: float,
        sample_rate: float,
    ) -> np.ndarray:
        """Apply compression to mono samples."""
        try:
            # Normalize samples to [-1, 1]
            samples = samples.astype(np.float32) / 32768.0
            
            # Convert threshold from dB to linear
            threshold_linear = 10 ** (threshold_db / 20.0)
            
            # Calculate envelope (input level per sample)
            envelope = np.abs(samples)
            
            # Apply attack/release smoothing
            attack_samples = int(attack_ms * sample_rate / 1000)
            release_samples = int(release_ms * sample_rate / 1000)
            
            # Simple exponential moving average for envelope smoothing
            smoothed_env = np.copy(envelope)
            for i in range(1, len(smoothed_env)):
                if envelope[i] > smoothed_env[i - 1]:
                    # Attack phase
                    alpha = 1.0 / max(1, attack_samples)
                else:
                    # Release phase
                    alpha = 1.0 / max(1, release_samples)
                smoothed_env[i] = alpha * envelope[i] + (1 - alpha) * smoothed_env[i - 1]
            
            # Calculate gain reduction
            gain_reduction = np.ones_like(smoothed_env)
            above_threshold = smoothed_env > threshold_linear
            
            if np.any(above_threshold):
                # For samples above threshold: apply ratio
                # gain_reduction = (input_level / threshold) ^ (1/ratio - 1) / (input_level / threshold)
                # Simplified: gain_reduction = threshold / (threshold + ratio * (input - threshold))
                excess = smoothed_env[above_threshold] - threshold_linear
                gain_reduction[above_threshold] = threshold_linear / (smoothed_env[above_threshold] + (ratio - 1) * excess)
            
            # Apply gain reduction
            compressed = samples * gain_reduction
            
            return compressed * 32768.0
        
        except Exception as e:
            logger.debug(f"Mono compression failed: {e}")
            return samples * 32768.0
    
    @staticmethod
    def _apply_presence_eq(
        audio: AudioSegment,
        boost_db: float = 3.0,
        center_hz: float = 3000,
        q: float = 2.0,
    ) -> AudioSegment:
        """
        Apply peaking EQ to boost presence around center frequency.
        
        Gives audio more "punch" and "brightness" at higher energy levels.
        """
        try:
            from scipy import signal
            
            # Get samples
            samples = np.array(audio.get_array_of_samples())
            
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                l_filtered = EnergyModulationEngine._presence_eq_mono(
                    samples[:, 0],
                    boost_db=boost_db,
                    center_hz=center_hz,
                    q=q,
                    sample_rate=audio.frame_rate,
                )
                r_filtered = EnergyModulationEngine._presence_eq_mono(
                    samples[:, 1],
                    boost_db=boost_db,
                    center_hz=center_hz,
                    q=q,
                    sample_rate=audio.frame_rate,
                )
                filtered = np.column_stack((l_filtered, r_filtered)).flatten()
            else:
                filtered = EnergyModulationEngine._presence_eq_mono(
                    samples,
                    boost_db=boost_db,
                    center_hz=center_hz,
                    q=q,
                    sample_rate=audio.frame_rate,
                )
            
            # Clip and convert back
            filtered = np.int16(np.clip(filtered, -32768, 32767))
            
            return AudioSegment(
                filtered.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
        
        except Exception as e:
            logger.debug(f"Presence EQ failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _presence_eq_mono(
        samples: np.ndarray,
        boost_db: float,
        center_hz: float,
        q: float,
        sample_rate: float,
    ) -> np.ndarray:
        """Apply presence peaking EQ to mono samples."""
        try:
            from scipy import signal
            
            # Design peaking EQ filter
            nyquist = sample_rate / 2
            normalized_center = center_hz / nyquist
            
            if normalized_center <= 0.0 or normalized_center >= 1.0:
                return samples * 32768.0  # Can't design filter
            
            # Convert boost in dB to linear gain
            A = 10 ** (boost_db / 40.0)
            w0 = 2 * np.pi * normalized_center
            alpha = np.sin(w0) / (2 * q)
            
            # Peaking filter coefficients (second-order IIR)
            b = [1 + alpha * A, -2 * np.cos(w0), 1 - alpha * A]
            a = [1 + alpha / A, -2 * np.cos(w0), 1 - alpha / A]
            
            b = np.array(b) / a[0]
            a = np.array(a) / a[0]
            
            # Apply filter forward-backward
            samples_norm = samples.astype(np.float32) / 32768.0
            filtered = signal.filtfilt(b, a, samples_norm)
            
            return filtered * 32768.0
        
        except Exception as e:
            logger.debug(f"Presence EQ mono failed: {e}")
            return samples * 32768.0
    
    @staticmethod
    def _add_reverb_effect(
        audio: AudioSegment,
        wet: float = 0.3,
        decay_seconds: float = 1.0,
    ) -> AudioSegment:
        """
        Add simple reverb effect using multiple delayed copies (room simulation).
        
        Creates a spacious sound by mixing in delayed versions of the audio.
        This is a simplified version - real reverb would use convolution.
        """
        try:
            if wet <= 0.01:
                return audio
            
            sample_rate = audio.frame_rate
            
            # Create reverb using multiple delays
            # Room reflections at different times create spatial effect
            reflections = [
                (0.024, 0.5),   # 24ms delay, 0.5 amplitude
                (0.032, 0.4),   # 32ms delay, 0.4 amplitude
                (0.064, 0.3),   # 64ms delay, 0.3 amplitude
                (0.128, 0.15),  # 128ms delay, 0.15 amplitude
                (0.256, 0.08),  # 256ms delay, 0.08 amplitude
            ]
            
            # Limit reflections by decay time
            max_delay = decay_seconds
            reflections = [(delay, amp) for delay, amp in reflections if delay < max_delay]
            
            # Start with dry signal
            dry = audio
            wet_audio = AudioSegment.silent(duration=0)  # Start with silence
            
            # Add each reflection
            for delay_seconds, amplitude in reflections:
                delay_ms = int(delay_seconds * 1000)
                
                # Create silence at start, then audio copy
                silence = AudioSegment.silent(duration=delay_ms)
                delayed = silence + (audio * amplitude)  # Scale reflection amplitude
                
                # Truncate to match original length
                if len(delayed) > len(audio):
                    delayed = delayed[:len(audio)]
                elif len(delayed) < len(audio):
                    delayed = delayed + AudioSegment.silent(duration=len(audio) - len(delayed))
                
                # Accumulate
                wet_audio = wet_audio + delayed
            
            # Mix dry and wet
            # wet_audio is sum of multiple copies, normalize by number of reflections
            wet_audio = wet_audio * (wet / len(reflections))
            dry_mix = dry * (1.0 - wet)
            
            result = dry_mix.overlay(wet_audio)
            
            return result
        
        except Exception as e:
            logger.debug(f"Reverb effect failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _apply_soft_distortion(
        audio: AudioSegment,
        drive: float = 0.1,
    ) -> AudioSegment:
        """
        Apply subtle soft clipping distortion for aggressive energy levels.
        
        Only used at very high energy (near 1.0) and kept subtle (drive < 0.2).
        """
        try:
            if drive <= 0.01:
                return audio
            
            samples = np.array(audio.get_array_of_samples())
            samples = samples.astype(np.float32) / 32768.0
            
            # Soft clipping using tanh (smoother than hard clipping)
            # tanh naturally rounds off peaks
            clipped = np.tanh(samples * (1.0 + drive * 10.0)) / np.tanh(1.0 + drive * 10.0)
            
            # Clip to valid range
            clipped = np.int16(np.clip(clipped * 32768.0, -32768, 32767))
            
            return AudioSegment(
                clipped.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
        
        except Exception as e:
            logger.debug(f"Distortion failed: {e}, returning original")
            return audio
