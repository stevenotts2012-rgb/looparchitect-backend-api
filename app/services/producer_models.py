"""
Producer-style arrangement data models using Python dataclasses.

These models represent the song structure, energy curves, instrument layers,
and transitions that guide audio generation and render planning.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional
from enum import Enum
import json


class SectionType(str, Enum):
    """Musical section types in a track."""
    INTRO = "Intro"
    VERSE = "Verse"
    HOOK = "Hook"
    CHORUS = "Chorus"
    BRIDGE = "Bridge"
    BREAKDOWN = "Breakdown"
    OUTRO = "Outro"
    TRANSITION = "Transition"


class InstrumentType(str, Enum):
    """Instrument categories."""
    KICK = "kick"
    SNARE = "snare"
    HATS = "hats"
    CLAP = "clap"
    PERCUSSION = "percussion"
    BASS = "bass"
    PAD = "pad"
    LEAD = "lead"
    MELODY = "melody"
    SYNTH = "synth"
    FX = "fx"
    VOCAL = "vocal"
    STRINGS = "strings"
    HORN = "horn"


class TransitionType(str, Enum):
    """Transition effect types between sections."""
    DRUM_FILL = "drum_fill"
    RISER = "riser"
    REVERSE_CYMBAL = "reverse_cymbal"
    IMPACT = "impact"
    SILENCE_DROP = "silence_drop"
    CROSSFADE = "crossfade"
    FILTER_SWEEP = "filter_sweep"


class VariationType(str, Enum):
    """Variation techniques to add throughout a section."""
    HIHAT_ROLL = "hihat_roll"
    DRUM_FILL = "drum_fill"
    VELOCITY_CHANGE = "velocity_change"
    INSTRUMENT_DROPOUT = "instrument_dropout"
    MELODY_SWAP = "melody_swap"
    BASS_VARIATION = "bass_variation"
    AUTOMATION = "automation"


@dataclass
class Track:
    """Represents a single instrument track in the arrangement."""
    name: str
    instrument: InstrumentType
    volume_db: float = 0.0
    pan_left_right: float = 0.0  # -1.0 (left) to 1.0 (right)
    effects: List[str] = field(default_factory=list)
    enabled: bool = True


@dataclass
class InstrumentLayer:
    """Instruments that should be active in a section."""
    section_type: SectionType
    instruments: List[InstrumentType]
    description: str = ""
    
    def has_instrument(self, instrument: InstrumentType) -> bool:
        """Check if this layer includes an instrument."""
        return instrument in self.instruments


@dataclass
class EnergyPoint:
    """Single point in an energy curve (bar index -> energy level)."""
    bar: int
    energy: float  # 0.0 to 1.0
    description: str = ""


@dataclass
class Transition:
    """Transition between two sections."""
    from_section: int  # Section index
    to_section: int
    transition_type: TransitionType
    duration_bars: int = 1
    intensity: float = 0.7  # 0.0 to 1.0


@dataclass
class Variation:
    """Variation applied at a specific bar in a section."""
    bar: int
    section_index: int
    variation_type: VariationType
    intensity: float = 0.5  # 0.0 to 1.0
    description: str = ""


@dataclass
class Section:
    """Musical section (Intro, Verse, Hook, etc.)."""
    name: str = ""
    section_type: SectionType = SectionType.VERSE
    bar_start: int = 0
    bars: int = 8
    energy_level: float = 0.5  # 0.0 to 1.0
    instruments: List[InstrumentType] = field(default_factory=list)
    variations: List[Variation] = field(default_factory=list)
    # Optional layering info
    layering: Optional['SectionLayering'] = None
    
    @property
    def bar_end(self) -> int:
        """Inclusive end bar."""
        return self.bar_start + self.bars - 1


@dataclass
class SectionLayering:
    """Layering intelligence output for a section."""
    section_name: str
    active_elements: List[str]
    muted_elements: List[str]
    introduced_elements: List[str]
    removed_elements: List[str]
    transition_in: Optional[str]
    transition_out: Optional[str]
    variation_strategy: Optional[str]
    energy_level: Optional[float]



@dataclass
class ProducerArrangement:
    """Complete producer-style song arrangement structure."""
    
    # Metadata
    tempo: float = 120.0  # BPM
    key: str = "C"  # Musical key (C, D, E, F, G, A, B, etc.)
    total_bars: int = 96
    total_seconds: float = 48.0  # Computed: (60 / tempo) * 4 * total_bars
    
    # Song structure
    sections: List[Section] = field(default_factory=list)
    # Optional layering plan for all sections
    layering_plan: Optional[List[SectionLayering]] = None
    
    # Energy envelope
    energy_curve: List[EnergyPoint] = field(default_factory=list)
    
    # Instrument tracks
    tracks: List[Track] = field(default_factory=list)
    
    # Transitions between sections
    transitions: List[Transition] = field(default_factory=list)
    
    # All variations across the arrangement
    all_variations: List[Variation] = field(default_factory=list)
    
    # Style metadata (from StyleProfile)
    genre: str = "generic"
    drum_style: str = "acoustic"
    melody_style: str = "melodic"
    bass_style: str = "synth"
    
    # Validation flags
    is_valid: bool = True
    validation_errors: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "tempo": self.tempo,
            "key": self.key,
            "total_bars": self.total_bars,
            "total_seconds": self.total_seconds,
            "sections": [
                {
                    "name": s.name,
                    "type": s.section_type.value,
                    "bar_start": s.bar_start,
                    "bars": s.bars,
                    "energy": s.energy_level,
                    "instruments": [i.value for i in s.instruments],
                    "variations": len(s.variations),
                    "layering": s.layering.__dict__ if s.layering else None,
                }
                for s in self.sections
            ],
            "layering_plan": [l.__dict__ for l in self.layering_plan] if self.layering_plan else None,
            "energy_curve": [
                {"bar": ep.bar, "energy": ep.energy}
                for ep in self.energy_curve
            ],
            "tracks": [
                {
                    "name": t.name,
                    "instrument": t.instrument.value,
                    "volume_db": t.volume_db,
                    "enabled": t.enabled,
                }
                for t in self.tracks
            ],
            "genre": self.genre,
            "drum_style": self.drum_style,
            "melody_style": self.melody_style,
            "bass_style": self.bass_style,
            "is_valid": self.is_valid,
            "validation_errors": self.validation_errors,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class StyleProfile:
    """Style direction profile derived from user input or preset."""
    
    genre: str = "generic"
    bpm_range: tuple = (90, 140)  # (min, max)
    energy: float = 0.5  # 0.0 to 1.0
    drum_style: str = "acoustic"  # acoustic, electronic, live, programmed, etc.
    melody_style: str = "melodic"  # melodic, rhythmic, minimalist, orchestral, etc.
    bass_style: str = "synth"  # synth, acoustic, electric, sub, etc.
    structure_template: str = "standard"  # standard, progressive, looped, etc.
    
    # Additional metadata
    description: str = ""
    references: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)


@dataclass
class RenderEvent:
    """Event marking when an instrument enters or changes in the arrangement."""
    bar: int
    track_name: str
    event_type: str  # "enter", "exit", "variation", "fill"
    description: str = ""


@dataclass
class RenderPlan:
    """Detailed render plan that the worker uses to generate audio."""
    
    bpm: float
    key: str
    total_bars: int
    sections: List[Dict]  # Section metadata
    events: List[RenderEvent] = field(default_factory=list)
    tracks: List[Dict] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "bpm": self.bpm,
            "key": self.key,
            "total_bars": self.total_bars,
            "sections": self.sections,
            "events": [
                {
                    "bar": e.bar,
                    "track": e.track_name,
                    "type": e.event_type,
                    "description": e.description,
                }
                for e in self.events
            ],
            "tracks": self.tracks,
        }
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
