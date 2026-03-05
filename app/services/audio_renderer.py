"""
Audio Renderer: Converts ProducerArrangement structures into audio.

Takes a loop audio file and ProducerArrangement metadata, then renders
structured arrangements with sections, energy curves, and transitions.
"""

import logging
from typing import Optional
from pydub import AudioSegment
from app.services.producer_models import ProducerArrangement, Section, TransitionType

logger = logging.getLogger(__name__)


class AudioRenderer:
    """Renders audio based on ProducerArrangement structures."""
    
    def __init__(self, loop_audio: AudioSegment, bpm: float):
        """
        Initialize renderer with loop audio.
        
        Args:
            loop_audio: Base loop AudioSegment to build from
            bpm: Tempo in beats per minute
        """
        self.loop_audio = loop_audio
        self.bpm = bpm
        self.ms_per_beat = (60.0 / bpm) * 1000  # milliseconds per beat
        self.ms_per_bar = self.ms_per_beat * 4  # assume 4/4 time
        
    def render_arrangement(self, arrangement: ProducerArrangement) -> AudioSegment:
        """
        Render complete arrangement from ProducerArrangement structure.
        
        Args:
            arrangement: ProducerArrangement with sections and metadata
            
        Returns:
            Rendered AudioSegment of full arrangement
        """
        logger.info(
            f"Rendering arrangement: {len(arrangement.sections)} sections, "
            f"{arrangement.total_bars} bars, {arrangement.tempo} BPM"
        )
        
        if not arrangement.sections:
            logger.warning("No sections in arrangement, returning loop audio")
            return self.loop_audio
        
        rendered_segments = []
        
        for i, section in enumerate(arrangement.sections):
            logger.info(
                f"Rendering section {i+1}/{len(arrangement.sections)}: "
                f"{section.name} ({section.section_type.value}), "
                f"bars {section.bar_start}-{section.bar_end}"
            )
            
            # Render section audio
            section_audio = self._render_section(section, arrangement)
            
            # Apply transition if not the last section
            if i < len(arrangement.sections) - 1:
                transition = self._find_transition(arrangement, i, i + 1)
                if transition:
                    section_audio = self._apply_transition(
                        section_audio,
                        transition.transition_type,
                        transition.intensity
                    )
            
            rendered_segments.append(section_audio)
        
        # Concatenate all sections
        full_audio = sum(rendered_segments) if len(rendered_segments) > 1 else rendered_segments[0]
        
        logger.info(
            f"Render complete: {len(full_audio)}ms "
            f"(target: {arrangement.total_seconds * 1000}ms)"
        )
        
        return full_audio
    
    def _render_section(
        self,
        section: Section,
        arrangement: ProducerArrangement
    ) -> AudioSegment:
        """
        Render a single section with energy modulation.
        
        Args:
            section: Section to render
            arrangement: Full arrangement for energy curve context
            
        Returns:
            Rendered AudioSegment for this section
        """
        # Calculate section duration in milliseconds
        duration_ms = int(section.bars * self.ms_per_bar)
        
        # Build base by repeating loop
        loop_duration_ms = len(self.loop_audio)
        num_repeats = int(duration_ms / loop_duration_ms) + 1
        
        base = self.loop_audio * num_repeats
        base = base[:duration_ms]  # Trim to exact section length
        
        # Apply energy curve modulation
        base = self._apply_energy_curve(base, section, arrangement)
        
        # Apply section-specific effects based on type
        base = self._apply_section_effects(base, section)
        
        logger.debug(
            f"Section {section.name}: {len(base)}ms "
            f"(target: {duration_ms}ms, bars: {section.bars})"
        )
        
        return base
    
    def _apply_energy_curve(
        self,
        audio: AudioSegment,
        section: Section,
        arrangement: ProducerArrangement
    ) -> AudioSegment:
        """
        Apply energy curve modulation to audio.
        
        Adjusts volume based on energy level and curve points.
        
        Args:
            audio: Input audio
            section: Current section
            arrangement: Full arrangement with energy_curve
            
        Returns:
            Audio with energy modulation applied
        """
        # Use section's energy level as base
        energy_level = section.energy_level
        
        # Check if there are energy curve points for this section
        section_energy_points = [
            ep for ep in arrangement.energy_curve
            if section.bar_start <= ep.bar <= section.bar_end
        ]
        
        if section_energy_points:
            # Use average of energy points in this section
            avg_energy = sum(ep.energy for ep in section_energy_points) / len(section_energy_points)
            energy_level = avg_energy
        
        # Convert energy (0-1) to volume adjustment in dB
        # energy 0.0 = -20dB, energy 0.5 = 0dB, energy 1.0 = +6dB
        if energy_level < 0.5:
            db_adjustment = -20 + (energy_level * 40)  # -20 to 0 dB
        else:
            db_adjustment = (energy_level - 0.5) * 12  # 0 to +6 dB
        
        logger.debug(
            f"Energy modulation for {section.name}: "
            f"level={energy_level:.2f}, db_adjustment={db_adjustment:+.1f}dB"
        )
        
        # Apply volume adjustment
        return audio + db_adjustment
    
    def _apply_section_effects(
        self,
        audio: AudioSegment,
        section: Section
    ) -> AudioSegment:
        """
        Apply section-type specific effects.
        
        Args:
            audio: Input audio
            section: Section metadata
            
        Returns:
            Audio with section effects applied
        """
        from app.services.producer_models import SectionType
        
        # Intro: Fade in
        if section.section_type == SectionType.INTRO:
            fade_duration = min(2000, len(audio) // 2)  # Max 2 seconds
            audio = audio.fade_in(fade_duration)
        
        # Outro: Fade out
        elif section.section_type == SectionType.OUTRO:
            fade_duration = min(3000, len(audio) // 2)  # Max 3 seconds
            audio = audio.fade_out(fade_duration)
        
        # Bridge: Apply subtle filter effect (reduce high end)
        elif section.section_type == SectionType.BRIDGE:
            # Reduce volume slightly for contrast
            audio = audio - 2
        
        return audio
    
    def _find_transition(
        self,
        arrangement: ProducerArrangement,
        from_idx: int,
        to_idx: int
    ) -> Optional[object]:
        """Find transition between two sections."""
        for trans in arrangement.transitions:
            if trans.from_section == from_idx and trans.to_section == to_idx:
                return trans
        return None
    
    def _apply_transition(
        self,
        audio: AudioSegment,
        transition_type: TransitionType,
        intensity: float
    ) -> AudioSegment:
        """
        Apply transition effect to end of audio segment.
        
        Args:
            audio: Input audio
            transition_type: Type of transition effect
            intensity: Effect intensity (0-1)
            
        Returns:
            Audio with transition effect applied
        """
        transition_duration = min(1000, len(audio) // 4)  # Max 1 second
        
        if transition_type == TransitionType.RISER:
            # Fade in volume at end for riser effect
            split_point = len(audio) - transition_duration
            pre_transition = audio[:split_point]
            transition_part = audio[split_point:]
            
            # Apply gain increase
            db_increase = 3 * intensity  # Up to +3dB
            transition_part = transition_part + db_increase
            
            audio = pre_transition + transition_part
        
        elif transition_type == TransitionType.SILENCE_DROP:
            # Add brief silence before next section
            from pydub import AudioSegment as AS
            silence_ms = int(500 * intensity)  # Up to 500ms
            silence = AS.silent(duration=silence_ms)
            audio = audio + silence
        
        elif transition_type == TransitionType.FILTER_SWEEP:
            # Fade out high frequencies at end
            split_point = len(audio) - transition_duration
            pre_transition = audio[:split_point]
            transition_part = audio[split_point:]
            
            # Reduce volume slightly to simulate filter
            db_reduction = -6 * intensity  # Up to -6dB
            transition_part = transition_part + db_reduction
            
            audio = pre_transition + transition_part
        
        logger.debug(
            f"Applied transition: {transition_type.value} "
            f"(intensity={intensity:.2f})"
        )
        
        return audio


def render_arrangement(
    loop_audio: AudioSegment,
    producer_arrangement: ProducerArrangement,
    target_bpm: float
) -> AudioSegment:
    """
    Convenience function to render arrangement.
    
    Args:
        loop_audio: Base loop audio
        producer_arrangement: Arrangement structure
        target_bpm: Tempo in BPM
        
    Returns:
        Rendered audio
    """
    renderer = AudioRenderer(loop_audio, target_bpm)
    return renderer.render_arrangement(producer_arrangement)
