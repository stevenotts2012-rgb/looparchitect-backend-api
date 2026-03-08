"""
Transition Engine: Create audio transitions between sections.

Transition types:
- Riser: Synthesized rising tone (kick pitch bend up)
- Impact: Kick drum or impact sound
- Filter Sweep: Low-pass filter automation
- Silence Drop: Brief quiet moment for tension
- Downlifter: Reverse riser (pitch moving down)
- Swell: Volume envelope swelling at section boundary
"""

import logging
from typing import Optional
import numpy as np
from pydub import AudioSegment
from pydub.generators import Sine

from app.services.producer_models import Transition, TransitionType

logger = logging.getLogger(__name__)


class TransitionEngine:
    """Create seamless transitions between sections."""
    
    @staticmethod
    def create_transition(
        transition_type: TransitionType,
        duration_ms: float = 2000,
        intensity: float = 0.5,
        bpm: float = 120,
    ) -> AudioSegment:
        """
        Synthesize transition audio (riser, impact, sweep, etc).
        
        Args:
            transition_type: Type of transition
            duration_ms: Transition duration in milliseconds
            intensity: 0.0 (subtle) to 1.0 (aggressive)
            bpm: Tempo context
        
        Returns:
            AudioSegment with transition audio
        """
        try:
            if transition_type == TransitionType.RISER:
                return TransitionEngine._create_riser(duration_ms, intensity)
            elif transition_type == TransitionType.IMPACT:
                return TransitionEngine._create_impact(duration_ms, intensity)
            elif transition_type == TransitionType.SILENCE_DROP:
                return TransitionEngine._create_silence_drop(duration_ms)
            elif transition_type == TransitionType.DOWNLIFTER:
                return TransitionEngine._create_downlifter(duration_ms, intensity)
            elif transition_type == TransitionType.SWELL:
                return TransitionEngine._create_swell(duration_ms, intensity)
            else:
                logger.warning(f"Unknown transition type: {transition_type}, returning silence")
                return AudioSegment.silent(duration=int(duration_ms))
        
        except Exception as e:
            logger.warning(f"Transition creation failed: {e}, returning silence")
            return AudioSegment.silent(duration=int(duration_ms))
    
    @staticmethod
    def apply_transition_before_section(
        base_audio: AudioSegment,
        transition: Transition,
        bpm: float = 120,
    ) -> AudioSegment:
        """
        Apply transition audio before a section (mix into last bar of previous section).
        
        Args:
            base_audio: Base section audio
            transition: Transition metadata with type and duration
            bpm: Tempo context
        
        Returns:
            Audio with transition mixed in
        """
        try:
            # Create transition audio
            transition_audio = TransitionEngine.create_transition(
                transition_type=transition.transition_type,
                duration_ms=transition.duration * 1000,  # Assume duration is in seconds
                intensity=transition.intensity,
                bpm=bpm,
            )
            
            # Position transition in last portion of audio
            # Place it in the last 2 bars so it leads into next section
            ms_per_bar = (60000.0 / bpm) * 4
            transition_position = len(base_audio) - int(2 * ms_per_bar)
            transition_position = max(0, transition_position)
            
            # Overlay transition onto base
            # Transition should be louder so it's prominent
            transition_audio_boosted = transition_audio.apply_gain(3)  # +3dB
            
            # Use overlay to mix (base underneath, transition on top)
            result = base_audio.overlay(transition_audio_boosted, position=transition_position)
            
            logger.debug(
                f"Applied {transition.transition_type.value} transition "
                f"at position {transition_position}ms, duration {transition.duration}s"
            )
            
            return result
        
        except Exception as e:
            logger.debug(f"Transition application failed: {e}, returning base")
            return base_audio
    
    @staticmethod
    def _create_riser(
        duration_ms: float = 2000,
        intensity: float = 0.5,
    ) -> AudioSegment:
        """
        Create a riser sound (rising pitch synthesized tone).
        
        Simulates a synthesizer riser that builds tension into next section.
        
        Args:
            duration_ms: Riser duration in milliseconds
            intensity: 0.0 (subtle) to 1.0 (aggressive)
        
        Returns:
            AudioSegment with riser sound
        """
        try:
            # Sample rate
            sample_rate = 44100
            duration_sec = duration_ms / 1000.0
            num_samples = int(sample_rate * duration_sec)
            
            # Create time vector
            t = np.linspace(0, duration_sec, num_samples)
            
            # Frequency ranges for rising effect
            # Start: ~100 Hz
            # End: ~1500 Hz (depends on intensity)
            start_freq = 100.0 + (intensity * 50)   # 100-150 Hz start
            end_freq = 1500.0 + (intensity * 2000)  # 1500-3500 Hz end
            
            # Create frequency trajectory (exponential curve for natural rising feel)
            freqs = start_freq * np.exp(np.log(end_freq / start_freq) * t / duration_sec)
            
            # Generate phase for sinusoid (integrate frequency to get phase)
            phase = 2 * np.pi * np.cumsum(freqs) / sample_rate
            
            # Create sine wave with frequency envelope
            wave = np.sin(phase)
            
            # Add harmonics for richness (at 2x and 3x fundamental)
            wave += 0.5 * np.sin(2 * phase)      # Second harmonic
            wave += 0.3 * np.sin(3 * phase)      # Third harmonic
            
            # Normalize
            wave = wave / np.max(np.abs(wave))
            
            # Apply amplitude envelope (fade in, then sustain, then fade out)
            fade_in_samples = int(0.05 * sample_rate)   # 50ms fade in
            fade_out_samples = int(0.3 * sample_rate)   # 300ms fade out
            
            envelope = np.ones(num_samples)
            envelope[:fade_in_samples] = np.linspace(0, 1, fade_in_samples)
            envelope[-fade_out_samples:] = np.linspace(1, 0, fade_out_samples)
            
            wave = wave * envelope
            
            # Intensity affects volume
            # 0.0: -12dB, 1.0: 0dB
            volume_db = -12.0 + (intensity * 12.0)
            volume_linear = 10 ** (volume_db / 20.0)
            wave = wave * volume_linear
            
            # Convert to 16-bit audio
            wave = np.int16(wave * 32767)
            
            # Create AudioSegment
            audio = AudioSegment(
                wave.tobytes(),
                frame_rate=sample_rate,
                sample_width=2,
                channels=1
            )
            
            logger.debug(f"Created riser: {start_freq:.0f}Hz → {end_freq:.0f}Hz over {duration_ms:.0f}ms")
            
            return audio
        
        except Exception as e:
            logger.debug(f"Riser creation failed: {e}")
            return AudioSegment.silent(duration=int(duration_ms))
    
    @staticmethod
    def _create_impact(
        duration_ms: float = 1000,
        intensity: float = 0.5,
    ) -> AudioSegment:
        """
        Create an impact sound (kick drum like).
        
        Args:
            duration_ms: Total impact duration (usually 0.05-0.2s for impact itself, rest is decay)
            intensity: 0.0 (soft) to 1.0 (hard)
        
        Returns:
            AudioSegment with impact sound
        """
        try:
            # Sample rate
            sample_rate = 44100
            duration_sec = duration_ms / 1000.0
            num_samples = int(sample_rate * duration_sec)
            
            # Create time vector
            t = np.linspace(0, duration_sec, num_samples)
            
            # Kick drum pit at start: ~100Hz tone that immediately decays
            pitch_freq = 100.0 + (intensity * 50)  # 100-150 Hz
            
            # Very fast frequency drop (more intense = faster drop)
            # At t=0: pitch_freq
            # At t=0.1s: drop to 40 Hz
            drop_time = 0.05 + (0.05 * (1 - intensity))  # 0.05-0.1s depending on intensity
            
            # Frequency envelope: steep drop
            freqs = np.where(
                t < drop_time,
                pitch_freq - (pitch_freq - 40) * (t / drop_time),  # Linear drop
                40  # Hold low pitch
            )
            
            # Generate phase
            phase = 2 * np.pi * np.cumsum(freqs) / sample_rate
            
            # Create sine wave
            wave = np.sin(phase)
            
            # Hard amplitude envelope (sharp attack, exponential decay)
            attack_samples = int(0.01 * sample_rate)  # 10ms attack
            attack_envelope = np.linspace(0, 1, attack_samples)
            
            # Exponential decay over rest of duration
            decay_samples = num_samples - attack_samples
            decay_envelope = np.exp(-3.0 * np.arange(decay_samples) / decay_samples)
            
            # Combine envelopes
            envelope = np.concatenate([attack_envelope, decay_envelope])
            
            # Clip to length if needed
            envelope = envelope[:num_samples]
            if len(envelope) < num_samples:
                envelope = np.concatenate([envelope, np.zeros(num_samples - len(envelope))])
            
            # Apply envelope
            wave = wave * envelope
            
            # Intensity affects volume
            volume_db = -6.0 + (intensity * 6.0)  # -6 to 0 dB
            volume_linear = 10 ** (volume_db / 20.0)
            wave = wave * volume_linear
            
            # Convert to 16-bit audio
            wave = np.int16(wave * 32767)
            
            # Create AudioSegment (convert mono to stereo for immersion)
            audio = AudioSegment(
                wave.tobytes(),
                frame_rate=sample_rate,
                sample_width=2,
                channels=1
            )
            
            logger.debug(f"Created impact: {pitch_freq:.0f}Hz kick with intensity {intensity:.2f}")
            
            return audio
        
        except Exception as e:
            logger.debug(f"Impact creation failed: {e}")
            return AudioSegment.silent(duration=int(duration_ms))
    
    @staticmethod
    def _create_silence_drop(
        duration_ms: float = 500,
    ) -> AudioSegment:
        """
        Create silence (used for silence drop / tension moment).
        
        Args:
            duration_ms: Duration of silence
        
        Returns:
            Silent AudioSegment
        """
        return AudioSegment.silent(duration=int(duration_ms))
    
    @staticmethod
    def _create_downlifter(
        duration_ms: float = 2000,
        intensity: float = 0.5,
    ) -> AudioSegment:
        """
        Create a downlifter sound (reverse of riser).
        
        Pitch moves downward, creates contrast to riser.
        
        Args:
            duration_ms: Downlifter duration
            intensity: 0.0 (subtle) to 1.0 (aggressive)
        
        Returns:
            AudioSegment with downlifter sound
        """
        try:
            # Create by reversing a riser
            riser = TransitionEngine._create_riser(duration_ms, intensity)
            
            # Reverse to create downlifter effect
            downlifter = riser.reverse()
            
            logger.debug(f"Created downlifter with intensity {intensity:.2f}")
            
            return downlifter
        
        except Exception as e:
            logger.debug(f"Downlifter creation failed: {e}")
            return AudioSegment.silent(duration=int(duration_ms))
    
    @staticmethod
    def _create_swell(
        duration_ms: float = 2000,
        intensity: float = 0.5,
    ) -> AudioSegment:
        """
        Create a swell effect (volume swelling at section boundary).
        
        Creates effect of music swelling as new section comes in.
        
        Args:
            duration_ms: Duration over which swell occurs
            intensity: 0.0 (subtle) to 1.0 (dramatic)
        
        Returns:
            AudioSegment with swell effect
        """
        try:
            # Create a white noise swell (pads swelling sound)
            sample_rate = 44100
            duration_sec = duration_ms / 1000.0
            num_samples = int(sample_rate * duration_sec)
            
            # Generate white noise
            noise = np.random.normal(0, 0.1, num_samples)
            
            # Apply swell envelope (starts quiet, swells up, then decays)
            # First 30%: fade in from silence
            # Middle 40%: sustain at peak
            # Last 30%: fade out
            
            fade_in_sample_count = int(num_samples * 0.3)
            sustain_sample_count = int(num_samples * 0.4)
            fade_out_sample_count = num_samples - fade_in_sample_count - sustain_sample_count
            
            envelope = np.concatenate([
                np.linspace(0, 1, fade_in_sample_count),           # Fade in
                np.ones(sustain_sample_count),                     # Sustain at 1.0
                np.linspace(1, 0, fade_out_sample_count),          # Fade out
            ])
            
            # Apply high-pass filter to make swell more musical (remove rumble)
            from scipy import signal
            
            # Normalize noise first
            noise = noise / (np.max(np.abs(noise)) + 0.01)
            
            # HPF at 500 Hz
            nyquist = sample_rate / 2
            normalized_cutoff = 500 / nyquist
            b, a = signal.butter(2, normalized_cutoff, btype='high')
            noise_filtered = signal.filtfilt(b, a, noise)
            
            # Now apply envelope
            swell = noise_filtered * envelope
            
            # Apply intensity as volume
            volume_db = -12.0 + (intensity * 12.0)
            volume_linear = 10 ** (volume_db / 20.0)
            swell = swell * volume_linear
            
            # Convert to 16-bit audio
            swell = np.int16(swell * 32767)
            
            # Create AudioSegment
            audio = AudioSegment(
                swell.tobytes(),
                frame_rate=sample_rate,
                sample_width=2,
                channels=1
            )
            
            logger.debug(f"Created swell with intensity {intensity:.2f}")
            
            return audio
        
        except Exception as e:
            logger.debug(f"Swell creation failed: {e}")
            return AudioSegment.silent(duration=int(duration_ms))
