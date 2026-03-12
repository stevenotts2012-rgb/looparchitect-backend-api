"""
STEM-DRIVEN ARRANGEMENT ENGINE

Generates full instrumental arrangements by orchestrating stems across sections.
Unlike the loop-variation engine which applies DSP to a single loop,
this engine activates/deactivates stems per section to create real musical progression.

Core concept:
- Each section defines which stems are active
- Stems are mixed together during render
- Each hook increases intensity by adding stems
- Producer moves create musical events at boundaries
"""

import json
import logging
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Set
from enum import Enum

logger = logging.getLogger(__name__)


class StemRole(str, Enum):
    """Supported stem roles in arrangement."""
    DRUMS = "drums"
    BASS = "bass"
    MELODY = "melody"
    HARMONY = "harmony"
    FX = "fx"
    FULL_MIX = "full_mix"


class ProducerMove(str, Enum):
    """Producer-style events applied at section boundaries."""
    DRUM_FILL = "drum_fill"
    SNARE_ROLL = "snare_roll"
    PRE_HOOK_SILENCE = "pre_hook_silence"
    RISER_FX = "riser_fx"
    CRASH_HIT = "crash_hit"
    REVERSE_CYMBAL = "reverse_cymbal"
    DROP_KICK = "drop_kick"
    BASS_PAUSE = "bass_pause"
    HAT_DENSITY_ROLL = "hat_density_roll"
    PRE_DROP_BUILDOUT = "pre_drop_buildout"


@dataclass
class StemState:
    """State of a single stem in a section."""
    role: StemRole
    active: bool
    gain_db: float = 0.0  # Relative gain adjustment
    pan: float = 0.0  # -1.0 (left) to 1.0 (right), 0.0 = center
    filter_cutoff: Optional[float] = None  # Hz, None = no filter


@dataclass
class SectionConfig:
    """Configuration for a section in the arrangement."""
    name: str
    section_type: str  # "intro", "verse", "hook", "bridge", "outro", etc.
    bar_start: int
    bars: int
    active_stems: Set[StemRole]
    energy_level: float  # 0.0 to 1.0, used for hook evolution
    producer_moves: List[ProducerMove]
    stem_states: Dict[StemRole, StemState]  # Detailed stem configs
    bpm: int
    
    def to_dict(self) -> dict:
        """Convert to JSON-serializable dict."""
        return {
            "name": self.name,
            "section_type": self.section_type,
            "bar_start": self.bar_start,
            "bars": self.bars,
            "active_stems": [s.value for s in self.active_stems],
            "energy_level": self.energy_level,
            "producer_moves": [m.value for m in self.producer_moves],
            "stem_states": {
                role.value: {
                    "active": state.active,
                    "gain_db": state.gain_db,
                    "pan": state.pan,
                    "filter_cutoff": state.filter_cutoff,
                }
                for role, state in self.stem_states.items()
            },
            "bpm": self.bpm,
        }


class StemArrangementEngine:
    """Generates stem-based arrangements from audio stems."""
    
    def __init__(self, available_stems: Dict[StemRole, str], tempo: int, key: str):
        """
        Initialize engine with available stems.
        
        Args:
            available_stems: Dict mapping StemRole to audio file path
            tempo: BPM
            key: Musical key (e.g., "C major")
        """
        self.available_stems = available_stems
        self.tempo = tempo
        self.key = key
        # Derive available roles from provided stems
        self.available_roles: Set[StemRole] = set(available_stems.keys())
    
    def generate_arrangement(
        self,
        target_bars: int,
        genre: Optional[str] = None,
        intensity: Optional[str] = None,
    ) -> List[SectionConfig]:
        """
        Generate a complete stem-based arrangement.
        
        Args:
            target_bars: Total arrangement length in bars
            genre: Music genre hint (e.g., "trap", "rnb")
            intensity: "low", "medium", "high"
        
        Returns:
            List of SectionConfig objects defining the arrangement
        """
        if not self.available_stems:
            raise ValueError("No stems available for arrangement")
        
        # Determine section count and types based on target duration
        section_plan = self._plan_sections(target_bars, genre or "generic")
        
        # Generate sections with increasing intensity
        sections: List[SectionConfig] = []
        bar_counter = 0
        hook_count = 0
        
        for section_plan_item in section_plan:
            section_type = section_plan_item["type"]
            bars = section_plan_item["bars"]
            
            if section_type == "hook":
                hook_count += 1
            
            # Calculate energy level - hooks should be highest
            energy_level = self._calculate_energy_level(
                section_type=section_type,
                hook_number=hook_count if section_type == "hook" else None,
                total_hooks=section_plan.count({"type": "hook"}),
            )
            
            # Determine active stems for this section
            active_stems = self._determine_active_stems(
                section_type=section_type,
                energy_level=energy_level,
                available_roles=self.available_roles,
            )
            
            # Generate producer moves for section boundary
            producer_moves = self._generate_producer_moves(
                section_type=section_type,
                hook_number=hook_count if section_type == "hook" else None,
            )
            
            # Create stem states (detailed stem configuration)
            stem_states = self._create_stem_states(active_stems)
            
            section = SectionConfig(
                name=f"{section_type.capitalize()} {sections.__len__() + 1}",
                section_type=section_type,
                bar_start=bar_counter,
                bars=bars,
                active_stems=active_stems,
                energy_level=energy_level,
                producer_moves=producer_moves,
                stem_states=stem_states,
                bpm=self.tempo,
            )
            
            sections.append(section)
            bar_counter += bars
        
        logger.info(
            f"Generated stem arrangement: {len(sections)} sections, "
            f"{bar_counter} bars, roles={[r.value for r in self.available_roles]}"
        )
        
        return sections
    
    def _plan_sections(self, target_bars: int, genre: str) -> List[Dict]:
        """Plan section structure based on target duration and genre."""
        # Standard song structure: intro (4) + verse (8) + hook (8) + verse (8) + hook (8) + bridge (8) + hook (8) + outro (4) = 56 bars
        # For shorter lengths, condense; for longer, extend
        
        if target_bars <= 16:
            return [
                {"type": "intro", "bars": 4},
                {"type": "verse", "bars": 8},
                {"type": "hook", "bars": 4},
            ]
        elif target_bars <= 32:
            return [
                {"type": "intro", "bars": 4},
                {"type": "verse", "bars": 8},
                {"type": "hook", "bars": 8},
                {"type": "outro", "bars": 4},
            ]
        else:
            # Full structure, extended
            intro_bars = 4
            verse_bars = 8
            hook_bars = 8
            bridge_bars = 8
            outro_bars = 4
            
            # Calculate how many full iterations we can fit
            full_cycle = intro_bars + (verse_bars * 2) + (hook_bars * 2) + bridge_bars + outro_bars  # 48 bars
            
            sections = [{"type": "intro", "bars": intro_bars}]
            
            remaining = target_bars - intro_bars - outro_bars
            cycle_count = remaining // (verse_bars * 2 + hook_bars * 2 + bridge_bars)
            
            for _ in range(max(1, cycle_count)):
                sections.extend([
                    {"type": "verse", "bars": verse_bars},
                    {"type": "hook", "bars": hook_bars},
                    {"type": "verse", "bars": verse_bars},
                    {"type": "hook", "bars": hook_bars},
                ])
            
            # Add bridge
            remaining_bars = target_bars - sum(s["bars"] for s in sections) - outro_bars
            if remaining_bars >= bridge_bars:
                sections.append({"type": "bridge", "bars": bridge_bars})
            
            # Add final hook if space
            remaining_bars = target_bars - sum(s["bars"] for s in sections) - outro_bars
            if remaining_bars >= hook_bars:
                sections.append({"type": "hook", "bars": hook_bars})
            
            sections.append({"type": "outro", "bars": outro_bars})
            
            return sections
    
    def _calculate_energy_level(
        self,
        section_type: str,
        hook_number: Optional[int] = None,
        total_hooks: int = 1,
    ) -> float:
        """Calculate energy level for a section (0.0 to 1.0)."""
        base_energy = {
            "intro": 0.3,
            "verse": 0.5,
            "hook": 0.8,
            "bridge": 0.6,
            "outro": 0.2,
        }.get(section_type, 0.5)
        
        # Progressive hook evolution: each hook is higher energy
        if section_type == "hook" and hook_number is not None:
            progression = min(1.0, 0.7 + (0.1 * hook_number))
            return progression
        
        return base_energy
    
    def _determine_active_stems(
        self,
        section_type: str,
        energy_level: float,
        available_roles: Set[StemRole],
    ) -> Set[StemRole]:
        """Determine which stems should be active in this section."""
        active = set()
        
        # Base selection by section type
        if section_type == "intro":
            # Intro: typically pad/harmony + maybe melody
            if StemRole.HARMONY in available_roles:
                active.add(StemRole.HARMONY)
            if StemRole.MELODY in available_roles and StemRole.HARMONY in available_roles:
                active.add(StemRole.MELODY)
        
        elif section_type == "verse":
            # Verse: drums + bass, maybe melody
            if StemRole.DRUMS in available_roles:
                active.add(StemRole.DRUMS)
            if StemRole.BASS in available_roles:
                active.add(StemRole.BASS)
            if StemRole.MELODY in available_roles and energy_level > 0.5:
                active.add(StemRole.MELODY)
        
        elif section_type == "hook":
            # Hook: Full energy - drums, bass, melody, harmony
            if StemRole.DRUMS in available_roles:
                active.add(StemRole.DRUMS)
            if StemRole.BASS in available_roles:
                active.add(StemRole.BASS)
            if StemRole.MELODY in available_roles:
                active.add(StemRole.MELODY)
            if StemRole.HARMONY in available_roles and energy_level > 0.75:
                active.add(StemRole.HARMONY)
            if StemRole.FX in available_roles and energy_level > 0.85:
                active.add(StemRole.FX)
        
        elif section_type == "bridge":
            # Bridge: Often stripped down or different texture
            if StemRole.HARMONY in available_roles:
                active.add(StemRole.HARMONY)
            if StemRole.FX in available_roles:
                active.add(StemRole.FX)
            # May or may not have drums/bass depending on style
            if energy_level > 0.65:
                if StemRole.DRUMS in available_roles:
                    active.add(StemRole.DRUMS)
        
        elif section_type == "outro":
            # Outro: Wind down, typically just melody + harmony
            if StemRole.MELODY in available_roles:
                active.add(StemRole.MELODY)
            if StemRole.HARMONY in available_roles:
                active.add(StemRole.HARMONY)
        
        # Fallback: if nothing selected, use available stems
        if not active:
            active = available_roles.copy()
        
        return active
    
    def _generate_producer_moves(
        self,
        section_type: str,
        hook_number: Optional[int] = None,
    ) -> List[ProducerMove]:
        """Generate producer moves for section transitions."""
        moves: List[ProducerMove] = []
        
        if section_type == "intro":
            pass  # Intros are clean
        
        elif section_type == "verse":
            if hook_number is None:  # Only add for verses before hooks, not after
                pass
        
        elif section_type == "hook":
            # Pre-hook: add tension
            if hook_number == 1:
                moves.append(ProducerMove.DRUM_FILL)
                moves.append(ProducerMove.PRE_HOOK_SILENCE)
            elif hook_number == 2:
                moves.append(ProducerMove.SNARE_ROLL)
                moves.append(ProducerMove.RISER_FX)
            elif hook_number and hook_number >= 3:
                moves.append(ProducerMove.CRASH_HIT)
                moves.append(ProducerMove.PRE_DROP_BUILDOUT)
        
        elif section_type == "bridge":
            # Bridge often strips things down
            moves.append(ProducerMove.BASS_PAUSE)
        
        elif section_type == "outro":
            pass  # Outros fade naturally
        
        return moves
    
    def _create_stem_states(self, active_stems: Set[StemRole]) -> Dict[StemRole, StemState]:
        """Create detailed stem state configuration for active stems."""
        states: Dict[StemRole, StemState] = {}
        
        for role in self.available_roles:
            is_active = role in active_stems
            
            # Default configuration
            gain_db = 0.0
            pan = 0.0
            filter_cutoff = None
            
            # Fine-tuning per role
            if role == StemRole.DRUMS:
                pan = 0.0  # Center
            elif role == StemRole.BASS:
                pan = 0.0  # Center
            elif role == StemRole.MELODY:
                pan = 0.1  # Slightly right
            elif role == StemRole.HARMONY:
                pan = -0.1  # Slightly left
            elif role == StemRole.FX:
                pan = 0.0  # Can be anywhere
            
            states[role] = StemState(
                role=role,
                active=is_active,
                gain_db=gain_db,
                pan=pan,
                filter_cutoff=filter_cutoff,
            )
        
        return states
