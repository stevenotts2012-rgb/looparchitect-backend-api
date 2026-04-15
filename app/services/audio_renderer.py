"""
Audio Renderer: Converts ProducerArrangement structures into audio.

Uses producer-style logic:
1. Analyze loop to detect components (kick, bass, melody, hats, snare)
2. For each section: apply layer masks, energy modulation, variations, transitions
3. Output: fully arranged audio that's different from input loop

Integrates:
- LayerEngine: Control which instruments are active per section
- EnergyModulationEngine: Translate energy curve to audio effects (volume, EQ, reverb, compression)
- VariationEngine: Add fills, dropouts, chops, filter sweeps
- TransitionEngine: Create risers, impacts, swells between sections
"""

import logging
from typing import Optional
import numpy as np
from pydub import AudioSegment

from app.services.producer_models import ProducerArrangement, Section, SectionType, TransitionType
from app.services.layer_engine import LayerEngine, LoopComponents
from app.services.energy_engine import EnergyModulationEngine
from app.services.variation_engine import VariationEngine
from app.services.transition_engine import TransitionEngine

logger = logging.getLogger(__name__)


class AudioRenderer:
    """Renders audio based on ProducerArrangement structures using producer-style logic."""
    
    def __init__(self, loop_audio: AudioSegment, bpm: float):
        """
        Initialize renderer with loop audio.
        
        Args:
            loop_audio: Base loop AudioSegment to build from
            bpm: Tempo in beats per minute (used for beat/bar calculations)
        """
        self.loop_audio = loop_audio
        self.bpm = bpm
        self.ms_per_beat = (60.0 / bpm) * 1000  # milliseconds per beat
        self.ms_per_bar = self.ms_per_beat * 4  # assume 4/4 time
        
        # Analyze loop to detect components (kick, bass, melody, hats, snare presence)
        self.loop_components = LayerEngine.analyze_loop_components(loop_audio, bpm)
        logger.info(f"Analyzed loop components: {self.loop_components}")
        
    def render_arrangement(self, arrangement: ProducerArrangement) -> AudioSegment:
        """
        Render complete arrangement from ProducerArrangement structure.
        
        Strategy:
        1. For each section: build base loop, apply layer masks, add energy effects
        2. Add variation audio (fills, dropouts) within sections
        3. Add transition audio between sections
        4. Concatenate all sections
        
        Args:
            arrangement: ProducerArrangement with sections, energy curve, transitions
            
        Returns:
            Rendered AudioSegment of full arrangement (unique, producer-style)
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
                f"{section.bars} bars @ energy={section.energy_level:.2f}"
            )
            
            # 1. Render section with layer masks and energy effects
            section_audio = self._render_section(section, arrangement)
            
            # 2. Add variations (fills, dropouts) within section
            section_audio = VariationEngine.add_section_variations(
                section_audio,
                section,
                bpm=self.bpm,
            )
            
            # 3. Add transition before next section (if not last)
            if i < len(arrangement.sections) - 1:
                next_section = arrangement.sections[i + 1]
                transition_audio = TransitionEngine.create_transition(
                    transition_type=TransitionType.RISER,  # Default riser between sections
                    duration_ms=2000,  # 2-second transition
                    intensity=section.energy_level,  # Intensity matches current section energy
                    bpm=self.bpm,
                )
                
                # Mix transition audio at end of section; keep gain neutral to avoid spikes.
                transition_position = len(section_audio) - int(2 * self.ms_per_bar)
                transition_position = max(0, transition_position)
                section_audio = section_audio.overlay(transition_audio, position=transition_position)
                
                logger.debug(f"Added transition from {section.name} to {next_section.name}")
            
            rendered_segments.append(section_audio)
        
        # Concatenate all sections with short crossfades to prevent boundary pops.
        if len(rendered_segments) > 1:
            full_audio = rendered_segments[0]
            for seg in rendered_segments[1:]:
                xfade = min(30, len(full_audio) // 4, len(seg) // 4)
                if xfade > 0:
                    full_audio = full_audio.append(seg, crossfade=xfade)
                else:
                    full_audio = full_audio + seg
        else:
            full_audio = rendered_segments[0]
        
        logger.info(
            f"Render complete: {len(full_audio)}ms ({len(full_audio)/1000:.1f}s) "
            f"(target: {arrangement.total_seconds*1000:.0f}ms)"
        )
        
        return full_audio
    
    def _render_section(
        self,
        section: Section,
        arrangement: ProducerArrangement
    ) -> AudioSegment:
        """
        Render a single section with:
        1. Loop repetition to fill section duration
        2. Layer masking (selective instrument muting based on section.instruments)
        3. Energy modulation (effects applied based on energy level)
        
        Args:
            section: Section to render
            arrangement: Full arrangement for energy curve context
            
        Returns:
            Rendered AudioSegment for this section
        """
        # Calculate section duration in milliseconds
        duration_ms = int(section.bars * self.ms_per_bar)
        
        # Step 1: Build base by repeating loop to fill section duration
        loop_duration_ms = len(self.loop_audio)
        if loop_duration_ms < 100:
            logger.warning(f"Loop too short ({loop_duration_ms}ms), using fallback")
            # Fallback: just repeat once
            base = self.loop_audio
        else:
            num_repeats = max(1, int(duration_ms / loop_duration_ms) + 1)
            base = self.loop_audio
            for _ in range(num_repeats - 1):
                base = base + self.loop_audio
            
            # Trim to exact section length
            base = base[:duration_ms]
        
        # Step 2: Apply layer masks (control which instruments are present)
        # The LayerEngine will mute/attenuate instruments not in section.instruments
        base = LayerEngine.apply_layer_mask(
            base,
            section=section,
            components=self.loop_components,
            energy_level=section.energy_level,
        )
        
        # Step 3: Apply energy-based effect (volume, EQ, reverb, compression)
        # Energy level 0.0 = sparse/quiet, 1.0 = full/loud with effects
        base = EnergyModulationEngine.apply_energy_effects(
            base,
            energy_level=section.energy_level,
            section_type=section.section_type,
        )
        
        logger.debug(
            f"Section {section.name}: {len(base)}ms "
            f"({len(base)/1000:.1f}s, target {duration_ms}ms), "
            f"energy={section.energy_level:.2f}, "
            f"instruments={[i.value for i in section.instruments]}"
        )
        
        return base
    
    def _apply_energy_curve(
        self,
        audio: AudioSegment,
        section: Section,
        arrangement: ProducerArrangement
    ) -> AudioSegment:
        """
        DEPRECATED: Integrated into EnergyModulationEngine.apply_energy_effects()
        
        Kept for compatibility, but actual energy modulation is done in _render_section.
        """
        # This is now done by EnergyModulationEngine
        return audio
    
    def _apply_section_effects(self, audio: AudioSegment, section: Section) -> AudioSegment:
        """
        DEPRECATED: Integrated into EnergyModulationEngine and LayerEngine
        
        Kept for compatibility.
        """
        # Layer-based effects are done by LayerEngine
        # Energy-based effects are done by EnergyModulationEngine
        return audio
    
    def _find_transition(self, arrangement: ProducerArrangement, from_idx: int, to_idx: int):
        """
        DEPRECATED: Transitions now handled directly in render_arrangement()
        
        Kept for compatibility.
        """
        # Transitions are created directly by TransitionEngine in render_arrangement
        return None
    
    def _apply_transition(
        self,
        audio: AudioSegment,
        transition_type: TransitionType,
        intensity: float
    ) -> AudioSegment:
        """
        DEPRECATED: Use TransitionEngine directly
        
        Kept for compatibility.
        """
        # Transitions are created directly by TransitionEngine
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
