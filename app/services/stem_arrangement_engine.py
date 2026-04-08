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
from typing import TYPE_CHECKING, List, Dict, Optional, Set
from enum import Enum

if TYPE_CHECKING:
    from app.services.canonical_stem_manifest import CanonicalStemManifest

logger = logging.getLogger(__name__)


class StemRole(str, Enum):
    """Supported stem roles in arrangement (expanded taxonomy)."""
    DRUMS      = "drums"
    BASS       = "bass"
    MELODY     = "melody"
    HARMONY    = "harmony"
    PADS       = "pads"
    FX         = "fx"
    PERCUSSION = "percussion"
    ACCENT     = "accent"
    VOCALS     = "vocals"
    FULL_MIX   = "full_mix"


# Arrangement group → set of roles that belong to it
STEM_GROUPS: dict[str, frozenset["StemRole"]] = {
    "rhythm":       frozenset({StemRole.DRUMS, StemRole.PERCUSSION}),
    "low_end":      frozenset({StemRole.BASS}),
    "lead":         frozenset({StemRole.MELODY, StemRole.VOCALS}),
    "harmonic":     frozenset({StemRole.HARMONY, StemRole.PADS}),
    "texture":      frozenset({StemRole.FX}),
    "transition":   frozenset({StemRole.ACCENT}),
    "fallback_mix": frozenset({StemRole.FULL_MIX}),
}


def _roles_in_group(group: str, available: "set[StemRole]") -> "set[StemRole]":
    """Return available roles that belong to *group*."""
    return available & STEM_GROUPS.get(group, frozenset())


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
        """Determine which stems should be active using arrangement groups.

        Group semantics
        ---------------
        rhythm      : drums, percussion
        low_end     : bass
        lead        : melody, vocals
        harmonic    : harmony, pads
        texture     : fx
        transition  : accent
        fallback_mix: full_mix
        """
        active: Set[StemRole] = set()

        def add_group(group: str) -> None:
            active.update(_roles_in_group(group, available_roles))

        if section_type == "intro":
            # INTRO: lead + harmonic + texture — no rhythm or low_end
            add_group("lead")
            add_group("harmonic")
            add_group("texture")

        elif section_type == "verse":
            # VERSE: rhythm + low_end + reduced lead
            add_group("rhythm")
            add_group("low_end")
            if energy_level >= 0.5:
                add_group("lead")

        elif section_type == "hook":
            # HOOK: all main groups; accent/fx at higher energy
            add_group("rhythm")
            add_group("low_end")
            add_group("lead")
            if energy_level > 0.70:
                add_group("harmonic")
            if energy_level > 0.85:
                add_group("texture")
            if energy_level > 0.90:
                add_group("transition")

        elif section_type == "bridge":
            # BRIDGE: harmonic + texture; rhythm reduced; no low_end
            add_group("harmonic")
            add_group("texture")
            if energy_level > 0.60:
                add_group("rhythm")

        elif section_type == "outro":
            # OUTRO: harmonic + lead fade; rhythm stripped
            add_group("lead")
            add_group("harmonic")

        # full_mix stems: always include as fallback if no other stems active
        if not active:
            add_group("fallback_mix")

        # Last resort — if still nothing, activate everything available
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

        # Panning and gain defaults per role (musical convention)
        _role_defaults: Dict[StemRole, tuple[float, float]] = {
            StemRole.DRUMS:       (0.0,   0.0),
            StemRole.PERCUSSION:  (0.1,   0.0),
            StemRole.BASS:        (0.0,   0.0),
            StemRole.MELODY:      (0.12,  0.0),
            StemRole.VOCALS:      (0.0,   0.0),
            StemRole.HARMONY:     (-0.12, 0.0),
            StemRole.PADS:        (-0.08, -1.5),  # slightly quieter
            StemRole.FX:          (0.0,   0.0),
            StemRole.ACCENT:      (0.0,   0.0),
            StemRole.FULL_MIX:    (0.0,   0.0),
        }

        for role in self.available_roles:
            pan, gain_db = _role_defaults.get(role, (0.0, 0.0))
            states[role] = StemState(
                role=role,
                active=role in active_stems,
                gain_db=gain_db,
                pan=pan,
                filter_cutoff=None,
            )

        return states


# ---------------------------------------------------------------------------
# Canonical role → StemRole bridge (Phase 6)
# ---------------------------------------------------------------------------

# Mapping from canonical sub-roles to their parent StemRole enum value.
# Sub-roles that don't directly map to a StemRole are folded into their
# nearest broad equivalent so the existing arrangement logic continues to work.
_CANONICAL_TO_STEM_ROLE: dict[str, StemRole] = {
    # Drums sub-roles → DRUMS
    "kick":       StemRole.DRUMS,
    "snare":      StemRole.DRUMS,
    "clap":       StemRole.DRUMS,
    "hi_hat":     StemRole.DRUMS,
    "cymbals":    StemRole.DRUMS,
    # Percussion keeps its own role
    "percussion": StemRole.PERCUSSION,
    # Drums broad
    "drums":      StemRole.DRUMS,
    # Low-end
    "bass":       StemRole.BASS,
    "808":        StemRole.BASS,
    # Melodic sub-roles → MELODY or HARMONY
    "piano":      StemRole.MELODY,
    "guitar":     StemRole.MELODY,
    "synth":      StemRole.MELODY,
    "arp":        StemRole.MELODY,
    "melody":     StemRole.MELODY,
    "keys":       StemRole.HARMONY,
    "strings":    StemRole.HARMONY,
    "harmony":    StemRole.HARMONY,
    # Pads
    "pads":       StemRole.PADS,
    # FX
    "fx":         StemRole.FX,
    # Vocals
    "vocal":      StemRole.VOCALS,
    "vocals":     StemRole.VOCALS,
    # Accent
    "accent":     StemRole.ACCENT,
    # Full mix
    "full_mix":   StemRole.FULL_MIX,
}


def stem_role_from_canonical(canonical_role: str) -> StemRole:
    """Resolve a canonical role string to the StemRole enum used by the arrangement engine.

    Falls back to StemRole.FULL_MIX for unknown roles so the engine never errors.
    """
    return _CANONICAL_TO_STEM_ROLE.get(canonical_role.lower(), StemRole.FULL_MIX)


def build_engine_from_manifest(
    manifest: "CanonicalStemManifest",  # type: ignore[name-defined]
    tempo: int,
    key: str,
) -> "StemArrangementEngine":
    """Build a StemArrangementEngine from a CanonicalStemManifest.

    When detailed sub-roles are available (kick, snare, etc.) they are folded
    into their parent StemRole so the existing arrangement logic works correctly.
    When multiple sub-roles map to the same StemRole, the highest-confidence
    entry's file key is used.

    Parameters
    ----------
    manifest:
        A CanonicalStemManifest produced by any of the three ingestion modes.
    tempo:
        Song BPM.
    key:
        Musical key (e.g. "C minor").
    """
    available_stems: dict[StemRole, str] = {}

    # Group entries by their mapped StemRole and pick the best file_key
    for entry in manifest.stems:
        role_enum = stem_role_from_canonical(entry.role)
        # Prefer the highest-confidence entry per StemRole
        if role_enum not in available_stems:
            available_stems[role_enum] = entry.file_key
        # (first-encountered wins; entries are in insertion order from ingestion)

    return StemArrangementEngine(
        available_stems=available_stems,
        tempo=tempo,
        key=key,
    )

