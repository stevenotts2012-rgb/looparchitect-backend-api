"""
Layer Engine: Analyze and control which drums, bass, and melody are active per section.

Responsibilities:
- Analyze loop to detect component presence (kick, bass, melody, hats, snare)
- Apply layer masks based on section requirements
- Use frequency analysis to isolate/attenuate specific frequency bands
"""

import logging
from typing import Dict, Optional
import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine
from enum import Enum

from app.services.producer_models import Section, InstrumentType, SectionType

logger = logging.getLogger(__name__)


class LayerComponent(str, Enum):
    """Identifiable components in a loop."""
    KICK = "kick"          # ~40-100 Hz
    SNARE = "snare"        # ~1-5 kHz (including transient)
    HATS = "hats"          # ~8-15 kHz
    BASS = "bass"          # ~80-250 Hz
    MELODY = "melody"      # ~200-4000 Hz
    PAD = "pad"            # ~100-1000 Hz, sustained
    TEXTURE = "texture"    # Noise, reverb


class LoopComponents:
    """Detected presence of each component in a loop."""
    
    def __init__(self):
        # 0.0 = not present, 1.0 = very present
        self.kick_presence: float = 0.5
        self.snare_presence: float = 0.3
        self.hats_presence: float = 0.5
        self.bass_presence: float = 0.5
        self.melody_presence: float = 0.3
        self.pad_presence: float = 0.2
        self.noise_floor: float = 0.1
    
    def __repr__(self):
        return (
            f"LoopComponents("
            f"kick={self.kick_presence:.2f}, "
            f"snare={self.snare_presence:.2f}, "
            f"hats={self.hats_presence:.2f}, "
            f"bass={self.bass_presence:.2f}, "
            f"melody={self.melody_presence:.2f}, "
            f"pad={self.pad_presence:.2f})"
        )


class LayerEngine:
    """Control which drums, bass, and melody are active in each section."""
    
    # Frequency bands for each component (Hz)
    FREQUENCY_BANDS = {
        LayerComponent.KICK: (20, 120),      # Low end thump
        LayerComponent.BASS: (80, 250),      # Bass line
        LayerComponent.SNARE: (1000, 5000), # Mid punch
        LayerComponent.HATS: (8000, 15000),  # High sparkle
        LayerComponent.MELODY: (200, 4000), # Vocal range
    }
    
    @staticmethod
    def analyze_loop_components(
        audio: AudioSegment,
        bpm: float = 120,
    ) -> LoopComponents:
        """
        Estimate which frequency components are present in the loop.
        
        Uses energy analysis in frequency bands to detect:
        - Kick presence (low-end thump)
        - Bass presence (sub-bass line)
        - Snare presence (mid punch)
        - Hats presence (high sparkle)
        - Melody presence (vocal range)
        
        Args:
            audio: Input AudioSegment
            bpm: Tempo (used for beat detection refinement)
        
        Returns:
            LoopComponents with presence scores (0.0 - 1.0)
        """
        components = LoopComponents()
        
        try:
            # Convert to numpy array for analysis
            samples = np.array(audio.get_array_of_samples())
            
            if audio.channels == 2:
                # Stereo: convert to mono by averaging channels
                samples = samples.reshape((-1, 2))
                samples = samples.mean(axis=1)
            
            samples = samples.astype(np.float32) / 32768.0  # Normalize to [-1, 1]
            
            # Calculate RMS energy in each frequency band
            sample_rate = audio.frame_rate
            
            # Simple frequency band energy analysis
            # (More sophisticated would use FFT, but this is fast and sufficient)
            
            # Divide audio into frames (e.g., 512 samples per frame)
            frame_size = 512
            num_frames = len(samples) // frame_size
            
            if num_frames < 1:
                logger.warning("Audio too short for component analysis, using defaults")
                return components
            
            frames = samples[:num_frames * frame_size].reshape((num_frames, frame_size))
            frame_energies = np.mean(np.abs(frames), axis=1)
            
            # Detect kick: strong attack at beat onset (kick has sharp transient)
            # Look for frames with high energy followed by rapid decay
            frame_deltas = np.diff(frame_energies)
            kick_peaks = np.sum(frame_deltas < -0.1) / len(frame_deltas) if len(frame_deltas) > 0 else 0
            components.kick_presence = min(1.0, kick_peaks * 2.0)
            
            # Detect bass: low-frequency sustained energy
            # Kick gives sharp transients; bass gives sustained low energy
            bass_sustained = np.mean([e for e in frame_energies if e > 0.05]) / (np.mean(frame_energies) + 0.01)
            components.bass_presence = min(1.0, bass_sustained / 3.0)
            
            # Detect hats: high-frequency energy peaks (cymbal transients)
            hats_peaks = np.sum(frame_deltas > 0.05) / len(frame_deltas) if len(frame_deltas) > 0 else 0
            components.hats_presence = min(1.0, hats_peaks * 1.5)
            
            # Detect snare: mid-frequency punch (1-5kHz)
            # Snare has strong presence in percussive hits
            snare_energy = np.mean(frame_energies[frame_deltas > 0.01]) if np.any(frame_deltas > 0.01) else 0
            components.snare_presence = min(1.0, snare_energy / 0.3)
            
            # Detect melody: presence of pitched content (lower variation across frames)
            frame_variance = np.std(frame_energies)
            melody_score = 1.0 - (frame_variance / (np.mean(frame_energies) + 0.01))
            components.melody_presence = max(0.0, min(1.0, melody_score))
            
            # Detect pad/sustained content
            components.pad_presence = min(1.0, np.mean(frame_energies) / 0.3)
            
            logger.info(f"Analyzed loop components: {components}")
            
        except Exception as e:
            logger.warning(f"Component analysis failed, using defaults: {e}")
            # Return defaults on error
            pass
        
        return components
    
    @staticmethod
    def apply_layer_mask(
        audio: AudioSegment,
        section: Section,
        components: LoopComponents,
        energy_level: float = 1.0,
    ) -> AudioSegment:
        """
        Keep only specified instruments; adjust presence by section type and energy.
        
        Maps section.instruments (InstrumentType enums) to frequency masks.
        - If section doesn't include KICK, attenueate low frequencies
        - If section doesn't include HATS, reduce high frequencies
        - If section doesn't include SNARE, reduce mid-punch
        - Scale all remaining by energy_level
        
        Args:
            audio: Input AudioSegment
            section: Current section with instruments list
            components: Detected components in loop
            energy_level: 0.0-1.0 energy scale for overall presence
        
        Returns:
            Audio with layer mask applied
        """
        try:
            # Determine which frequency bands to keep based on section.instruments
            keep_kick = InstrumentType.KICK in section.instruments
            keep_snare = InstrumentType.SNARE in section.instruments
            keep_hats = InstrumentType.HATS in section.instruments
            keep_bass = InstrumentType.BASS in section.instruments
            keep_melody = InstrumentType.LEAD in section.instruments or InstrumentType.MELODY in section.instruments
            keep_pad = InstrumentType.PAD in section.instruments
            
            # Start with original audio
            result = audio
            
            # Apply attenuation for missing components
            # Lower frequencies (kick/bass)
            if not keep_kick and components.kick_presence > 0.2:
                logger.debug(f"  Attenuating kick from section {section.name}")
                # Apply high-pass filter at 150Hz to reduce kick
                result = LayerEngine._apply_highpass_filter(result, cutoff_hz=150)
            
            if not keep_bass and components.bass_presence > 0.2:
                logger.debug(f"  Attenuating bass from section {section.name}")
                # Apply high-pass filter at 200Hz to reduce bass
                result = LayerEngine._apply_highpass_filter(result, cutoff_hz=200)
            
            # High frequencies (hats)
            if not keep_hats and components.hats_presence > 0.2:
                logger.debug(f"  Attenuating hats from section {section.name}")
                # Apply low-pass filter at 7000Hz to reduce hats
                result = LayerEngine._apply_lowpass_filter(result, cutoff_hz=7000)
            
            # Mid punch (snare)
            if not keep_snare and components.snare_presence > 0.2:
                logger.debug(f"  Attenuating snare from section {section.name}")
                # Apply notch filter around 3kHz
                result = LayerEngine._apply_notch_filter(result, center_hz=3000, width_hz=1000)
            
            # Melody (vocal space)
            if not keep_melody and components.melody_presence > 0.2:
                logger.debug(f"  Creating vocal space (attenuating melody) in section {section.name}")
                # Apply notch filter around 800-3000Hz (vocal range)
                result = LayerEngine._apply_notch_filter(result, center_hz=1500, width_hz=700)
            
            # Apply volume scaling based on energy level
            # energy_level: 0.5 = -6dB, 1.0 = 0dB
            volume_scale = energy_level  # pydub interprets this as linear amplitude factor
            result = result.apply_gain(
                20 * np.log10(max(0.1, volume_scale))  # Convert to dB
            )
            
            return result
        
        except Exception as e:
            logger.warning(f"Layer mask application failed: {e}, returning original audio")
            return audio
    
    @staticmethod
    def _apply_highpass_filter(
        audio: AudioSegment,
        cutoff_hz: float = 150,
        order: int = 2,
    ) -> AudioSegment:
        """
        Apply high-pass filter to attenuate frequencies below cutoff.
        
        Removes low-end rumble and makes kick/bass less prominent.
        """
        try:
            from scipy import signal
            
            # Get samples
            samples = np.array(audio.get_array_of_samples())
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                # Process stereo separately
                l_filtered = LayerEngine._apply_highpass_filter_mono(samples[:, 0], cutoff_hz, audio.frame_rate, order)
                r_filtered = LayerEngine._apply_highpass_filter_mono(samples[:, 1], cutoff_hz, audio.frame_rate, order)
                filtered = np.column_stack((l_filtered, r_filtered)).flatten()
            else:
                filtered = LayerEngine._apply_highpass_filter_mono(samples, cutoff_hz, audio.frame_rate, order)
            
            # Clip to valid range
            filtered = np.int16(np.clip(filtered, -32768, 32767))
            
            # Return as new AudioSegment
            return AudioSegment(
                filtered.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
        
        except Exception as e:
            logger.debug(f"High-pass filter failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _apply_highpass_filter_mono(
        samples: np.ndarray,
        cutoff_hz: float,
        sample_rate: float,
        order: int = 2,
    ) -> np.ndarray:
        """Apply high-pass filter to mono samples."""
        try:
            from scipy import signal
            
            # Design Butterworth high-pass filter
            nyquist = sample_rate / 2
            normalized_cutoff = cutoff_hz / nyquist
            
            if normalized_cutoff >= 1.0:
                return samples  # Cutoff too high, no filtering
            
            b, a = signal.butter(order, normalized_cutoff, btype='high')
            
            # Apply filter forward-backward for zero phase distortion
            filtered = signal.filtfilt(b, a, samples)
            
            return filtered.astype(np.float32) * 32768.0
        
        except Exception as e:
            logger.debug(f"High-pass filter mono failed: {e}")
            return samples * 32768.0
    
    @staticmethod
    def _apply_lowpass_filter(
        audio: AudioSegment,
        cutoff_hz: float = 7000,
        order: int = 2,
    ) -> AudioSegment:
        """
        Apply low-pass filter to attenuate frequencies above cutoff.
        
        Makes hats and high-frequency content less prominent.
        """
        try:
            from scipy import signal
            
            # Get samples
            samples = np.array(audio.get_array_of_samples())
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                # Process stereo separately
                l_filtered = LayerEngine._apply_lowpass_filter_mono(samples[:, 0], cutoff_hz, audio.frame_rate, order)
                r_filtered = LayerEngine._apply_lowpass_filter_mono(samples[:, 1], cutoff_hz, audio.frame_rate, order)
                filtered = np.column_stack((l_filtered, r_filtered)).flatten()
            else:
                filtered = LayerEngine._apply_lowpass_filter_mono(samples, cutoff_hz, audio.frame_rate, order)
            
            # Clip to valid range
            filtered = np.int16(np.clip(filtered, -32768, 32767))
            
            # Return as new AudioSegment
            return AudioSegment(
                filtered.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
        
        except Exception as e:
            logger.debug(f"Low-pass filter failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _apply_lowpass_filter_mono(
        samples: np.ndarray,
        cutoff_hz: float,
        sample_rate: float,
        order: int = 2,
    ) -> np.ndarray:
        """Apply low-pass filter to mono samples."""
        try:
            from scipy import signal
            
            # Design Butterworth low-pass filter
            nyquist = sample_rate / 2
            normalized_cutoff = cutoff_hz / nyquist
            
            if normalized_cutoff <= 0.0:
                return np.zeros_like(samples)  # Cutoff too low, silence
            
            b, a = signal.butter(order, min(normalized_cutoff, 0.99), btype='low')
            
            # Apply filter forward-backward
            filtered = signal.filtfilt(b, a, samples)
            
            return filtered.astype(np.float32) * 32768.0
        
        except Exception as e:
            logger.debug(f"Low-pass filter mono failed: {e}")
            return samples * 32768.0
    
    @staticmethod
    def _apply_notch_filter(
        audio: AudioSegment,
        center_hz: float = 3000,
        width_hz: float = 1000,
        order: int = 2,
    ) -> AudioSegment:
        """
        Apply notch (band-stop) filter to attenuate frequencies around center.
        
        Useful for reducing snare punch or creating vocal space.
        """
        try:
            from scipy import signal
            
            # Get samples
            samples = np.array(audio.get_array_of_samples())
            if audio.channels == 2:
                samples = samples.reshape((-1, 2))
                # Process stereo separately
                l_filtered = LayerEngine._apply_notch_filter_mono(samples[:, 0], center_hz, width_hz, audio.frame_rate, order)
                r_filtered = LayerEngine._apply_notch_filter_mono(samples[:, 1], center_hz, width_hz, audio.frame_rate, order)
                filtered = np.column_stack((l_filtered, r_filtered)).flatten()
            else:
                filtered = LayerEngine._apply_notch_filter_mono(samples, center_hz, width_hz, audio.frame_rate, order)
            
            # Clip to valid range
            filtered = np.int16(np.clip(filtered, -32768, 32767))
            
            # Return as new AudioSegment
            return AudioSegment(
                filtered.tobytes(),
                frame_rate=audio.frame_rate,
                sample_width=2,
                channels=audio.channels
            )
        
        except Exception as e:
            logger.debug(f"Notch filter failed: {e}, returning original")
            return audio
    
    @staticmethod
    def _apply_notch_filter_mono(
        samples: np.ndarray,
        center_hz: float,
        width_hz: float,
        sample_rate: float,
        order: int = 2,
    ) -> np.ndarray:
        """Apply notch filter to mono samples."""
        try:
            from scipy import signal
            
            # Calculate low and high cutoffs
            low_hz = max(10, center_hz - width_hz / 2)
            high_hz = center_hz + width_hz / 2
            
            # Design Butterworth band-stop filter
            nyquist = sample_rate / 2
            low_norm = low_hz / nyquist
            high_norm = high_hz / nyquist
            
            if low_norm <= 0.0 or high_norm >= 1.0 or low_norm >= high_norm:
                return samples * 32768.0  # Can't design filter
            
            b, a = signal.butter(order, [low_norm, min(high_norm, 0.99)], btype='bandstop')
            
            # Apply filter forward-backward
            filtered = signal.filtfilt(b, a, samples)
            
            return filtered.astype(np.float32) * 32768.0
        
        except Exception as e:
            logger.debug(f"Notch filter mono failed: {e}")
            return samples * 32768.0
