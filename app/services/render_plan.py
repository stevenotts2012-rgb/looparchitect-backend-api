"""
Render Plan Generation: Creates detailed event-based render instructions.

The render plan is the source-of-truth document that tells the worker:
- How many bars to render
- Which instruments enter at which bars
- Which sections appear when
- What tempo and key to use

Format: JSON artifact stored with the arrangement
"""

import logging
from typing import List, Dict
from app.services.producer_models import (
    ProducerArrangement,
    RenderPlan,
    RenderEvent,
    Section,
    InstrumentType,
)

logger = logging.getLogger(__name__)


class RenderPlanGenerator:
    """Generates render plans from ProducerArrangement structures."""

    @staticmethod
    def generate(arrangement: ProducerArrangement) -> RenderPlan:
        """
        Generate a RenderPlan from a ProducerArrangement.
        
        Args:
            arrangement: The producer arrangement
        
        Returns:
            RenderPlan with events and track data
        """
        # Build events: track entries/exits at section boundaries
        events = RenderPlanGenerator._generate_events(arrangement)
        
        # Section metadata for render
        sections = RenderPlanGenerator._section_metadata(arrangement)
        
        # Track metadata
        tracks = RenderPlanGenerator._track_metadata(arrangement)
        
        plan = RenderPlan(
            bpm=arrangement.tempo,
            key=arrangement.key,
            total_bars=arrangement.total_bars,
            sections=sections,
            events=events,
            tracks=tracks,
        )
        
        logger.info(
            f"Generated render plan: {arrangement.total_bars} bars, "
            f"{len(events)} events, {len(tracks)} tracks"
        )
        
        return plan

    @staticmethod
    def _generate_events(arrangement: ProducerArrangement) -> List[RenderEvent]:
        """Generate instrument entry/exit events."""
        events: List[RenderEvent] = []
        previous_instruments = set()
        
        for section_idx, section in enumerate(arrangement.sections):
            current_instruments = set(section.instruments)
            
            # Entering instruments (new ones in this section)
            for instrument in current_instruments - previous_instruments:
                track_name = RenderPlanGenerator._get_track_name(instrument)
                events.append(
                    RenderEvent(
                        bar=section.bar_start,
                        track_name=track_name,
                        event_type="enter",
                        description=f"{track_name} enters in {section.name}",
                    )
                )
            
            # Exiting instruments (ones that were in previous section but not here)
            for instrument in previous_instruments - current_instruments:
                track_name = RenderPlanGenerator._get_track_name(instrument)
                events.append(
                    RenderEvent(
                        bar=section.bar_start,
                        track_name=track_name,
                        event_type="exit",
                        description=f"{track_name} exits before {section.name}",
                    )
                )
            
            # Variations within section
            for variation in section.variations:
                events.append(
                    RenderEvent(
                        bar=variation.bar,
                        track_name=f"{section.name} variation",
                        event_type="variation",
                        description=f"{variation.variation_type.value} at bar {variation.bar}",
                    )
                )
            
            previous_instruments = current_instruments
        
        # Sort by bar
        events.sort(key=lambda e: e.bar)
        
        return events

    @staticmethod
    def _section_metadata(arrangement: ProducerArrangement) -> List[Dict]:
        """Extract section metadata for render plan."""
        sections = []
        
        for section in arrangement.sections:
            sections.append({
                "name": section.name,
                "type": section.section_type.value,
                "bar_start": section.bar_start,
                "bars": section.bars,
                "energy": section.energy_level,
                "instruments": [i.value for i in section.instruments],
            })
        
        return sections

    @staticmethod
    def _track_metadata(arrangement: ProducerArrangement) -> List[Dict]:
        """Extract track metadata for render plan."""
        tracks = []
        
        for track in arrangement.tracks:
            tracks.append({
                "name": track.name,
                "instrument": track.instrument.value,
                "volume_db": track.volume_db,
                "pan": track.pan_left_right,
                "enabled": track.enabled,
            })
        
        return tracks

    @staticmethod
    def _get_track_name(instrument: InstrumentType) -> str:
        """Get friendly track name from instrument type."""
        name_map = {
            InstrumentType.KICK: "Kick",
            InstrumentType.SNARE: "Snare",
            InstrumentType.HATS: "Hi-Hats",
            InstrumentType.CLAP: "Clap",
            InstrumentType.PERCUSSION: "Percussion",
            InstrumentType.BASS: "Bass",
            InstrumentType.PAD: "Pad",
            InstrumentType.LEAD: "Lead",
            InstrumentType.MELODY: "Melody",
            InstrumentType.SYNTH: "Synth",
            InstrumentType.FX: "Effects",
            InstrumentType.VOCAL: "Vocal",
            InstrumentType.STRINGS: "Strings",
            InstrumentType.HORN: "Horn",
        }
        return name_map.get(instrument, instrument.value.capitalize())
