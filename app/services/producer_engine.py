"""
Producer Engine: Generates professional song structures and arrangement plans.

This engine synthesizes:
- Song structure (Intro, Verse, Hook, Bridge, Outro)
- Energy curves
- Instrument layers
- Transitions
- Variations
- Render timelines

Output is a ProducerArrangement ready for audio synthesis.
"""

import logging
import random as _random_mod
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Any
from app.services.beat_genome_loader import BeatGenomeLoader
from app.services.producer_models import (
    ProducerArrangement,
    Section,
    SectionType,
    InstrumentType,
    InstrumentLayer,
    EnergyPoint,
    Transition,
    Variation,
    Track,
    TransitionType,
    VariationType,
    StyleProfile,
)

logger = logging.getLogger(__name__)


class ProducerEngine:
    """Generates professional song structures and arrangement plans."""
    
    # Default song structures by template
    STRUCTURE_TEMPLATES = {
        "standard": [
            ("Intro", 8),
            ("Hook", 8),
            ("Verse", 16),
            ("Hook", 8),
            ("Verse", 16),
            ("Bridge", 8),
            ("Hook", 8),
            ("Outro", 4),
        ],
        "progressive": [
            ("Intro", 8),
            ("Verse", 16),
            ("Verse", 16),
            ("Hook", 8),
            ("Bridge", 16),
            ("Hook", 8),
            ("Verse", 8),
            ("Outro", 8),
        ],
        "looped": [
            ("Intro", 8),
            ("Hook", 16),
            ("Hook", 16),
            ("Hook", 16),
            ("Outro", 4),
        ],
        "minimal": [
            ("Intro", 4),
            ("Verse", 8),
            ("Hook", 4),
            ("Verse", 8),
            ("Outro", 4),
        ],
    }
    
    # Instrument layers by section type and genre
    INSTRUMENT_PRESETS = {
        "trap": {
            SectionType.INTRO: [InstrumentType.KICK, InstrumentType.PAD],
            SectionType.VERSE: [InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.HATS, InstrumentType.BASS],
            SectionType.HOOK: [
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.HATS,
                InstrumentType.BASS,
                InstrumentType.LEAD,
                InstrumentType.FX,
            ],
            SectionType.BRIDGE: [InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.PAD],
            SectionType.OUTRO: [InstrumentType.KICK, InstrumentType.PAD],
        },
        "rnb": {
            SectionType.INTRO: [InstrumentType.KICK, InstrumentType.PAD, InstrumentType.STRINGS],
            SectionType.VERSE: [
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.HATS,
                InstrumentType.BASS,
                InstrumentType.PAD,
            ],
            SectionType.HOOK: [
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.HATS,
                InstrumentType.BASS,
                InstrumentType.LEAD,
                InstrumentType.PAD,
                InstrumentType.STRINGS,
            ],
            SectionType.BRIDGE: [InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.PAD],
            SectionType.OUTRO: [InstrumentType.KICK, InstrumentType.PAD],
        },
        "pop": {
            SectionType.INTRO: [InstrumentType.KICK, InstrumentType.PAD],
            SectionType.VERSE: [InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.HATS, InstrumentType.BASS],
            SectionType.HOOK: [
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.HATS,
                InstrumentType.BASS,
                InstrumentType.LEAD,
                InstrumentType.STRINGS,
            ],
            SectionType.BRIDGE: [InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.PAD],
            SectionType.OUTRO: [InstrumentType.KICK, InstrumentType.PAD],
        },
        "cinematic": {
            SectionType.INTRO: [InstrumentType.PAD, InstrumentType.STRINGS],
            SectionType.VERSE: [
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.PAD,
                InstrumentType.STRINGS,
                InstrumentType.HORN,
            ],
            SectionType.HOOK: [
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.HATS,
                InstrumentType.LEAD,
                InstrumentType.PAD,
                InstrumentType.STRINGS,
                InstrumentType.HORN,
            ],
            SectionType.BRIDGE: [InstrumentType.KICK, InstrumentType.PAD, InstrumentType.STRINGS],
            SectionType.OUTRO: [InstrumentType.PAD, InstrumentType.STRINGS],
        },
        "generic": {
            SectionType.INTRO: [InstrumentType.KICK, InstrumentType.PAD],
            SectionType.VERSE: [InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.HATS, InstrumentType.BASS],
            SectionType.HOOK: [
                InstrumentType.KICK,
                InstrumentType.SNARE,
                InstrumentType.HATS,
                InstrumentType.BASS,
                InstrumentType.LEAD,
            ],
            SectionType.BRIDGE: [InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.PAD],
            SectionType.OUTRO: [InstrumentType.KICK, InstrumentType.PAD],
        },
    }

    @staticmethod
    def generate(
        target_seconds: float,
        tempo: float = 120.0,
        genre: str = "generic",
        style_profile: Optional[StyleProfile] = None,
        structure_template: str = "standard",
    ) -> ProducerArrangement:
        """
        Generate a complete ProducerArrangement.

        Args:
            target_seconds: Desired duration
            tempo: BPM (default 120)
            genre: Music genre (trap, rnb, pop, cinematic, generic)
            style_profile: Optional StyleProfile for customization
            structure_template: Template to use (standard, progressive, looped, minimal)

        Returns:
            ProducerArrangement with full structure, energy curve, and instruments
        """
        if tempo <= 0:
            raise ValueError("Tempo must be positive")
        if target_seconds <= 0:
            raise ValueError("target_seconds must be positive")

        # Calculate total bars from target duration
        bar_duration_seconds = (60.0 / tempo) * 4.0
        total_bars = max(8, int(round(target_seconds / bar_duration_seconds)))

        # Initialize arrangement
        arrangement = ProducerArrangement(
            tempo=tempo,
            key="C",  # Default key
            total_bars=total_bars,
            total_seconds=target_seconds,
            genre=genre,
        )

        # Apply style profile if provided
        if style_profile:
            # Handle both old and new StyleProfile formats
            # New format has resolved_params dict instead of drum_style/melody_style/bass_style
            if hasattr(style_profile, 'drum_style'):
                arrangement.drum_style = style_profile.drum_style
                arrangement.melody_style = style_profile.melody_style
                arrangement.bass_style = style_profile.bass_style
            elif hasattr(style_profile, 'resolved_params'):
                # New LLM-based StyleProfile format - map params to arrangement
                params = style_profile.resolved_params or {}
                arrangement.drum_style = f"drum_density_{params.get('drum_density', 0.5)}"
                arrangement.melody_style = f"complexity_{params.get('melody_complexity', 0.5)}"
                arrangement.bass_style = f"presence_{params.get('bass_presence', 0.5)}"

        # Build sections from template
        arrangement.sections = ProducerEngine._build_sections(
            total_bars, structure_template, genre
        )

        # Generate energy curve
        arrangement.energy_curve = ProducerEngine._generate_energy_curve(
            arrangement.sections
        )

        # Assign instruments based on genre and sections
        arrangement = ProducerEngine._assign_instruments(arrangement)

        # Add transitions
        arrangement.transitions = ProducerEngine._generate_transitions(
            arrangement.sections
        )

        # Add variations (every 8 bars minimum)
        arrangement.all_variations = ProducerEngine._generate_variations(
            arrangement.sections
        )

        # Create tracks from instruments
        arrangement.tracks = ProducerEngine._create_tracks(arrangement)

        # Validate
        arrangement = ProducerEngine._validate(arrangement)

        # Apply producer behavior polish (musical realism improvements)
        from app.services.producer_behavior_polish import ProducerBehaviorPolish
        arrangement = ProducerBehaviorPolish.polish(arrangement)

        # Re-create tracks after polish so any instruments added during polishing
        # (e.g. PERCUSSION added to hook sections) are included in the track list.
        arrangement.tracks = ProducerEngine._create_tracks(arrangement)

        # Generate and attach layering plan
        from app.services.arrangement_layering_engine import ArrangementLayeringEngine
        section_names = [s.name.lower() for s in arrangement.sections]
        detected_elements = [i.value for i in arrangement.tracks[0].effects] if arrangement.tracks else None
        if not detected_elements and arrangement.sections:
            detected_elements = [i.value for i in arrangement.sections[0].instruments]
        layering_plan = ArrangementLayeringEngine.generate_layering_plan(
            genre=genre,
            mood="neutral",
            energy_level=1.0,
            arrangement_template=structure_template,
            section_list=section_names,
            detected_elements=detected_elements,
        )
        arrangement.layering_plan = layering_plan
        for idx, section in enumerate(arrangement.sections):
            if idx < len(layering_plan):
                section.layering = layering_plan[idx]

        return arrangement

    @staticmethod
    def _build_sections(
        total_bars: int, template: str, genre: str
    ) -> List[Section]:
        """Build sections from a template structure."""
        if template not in ProducerEngine.STRUCTURE_TEMPLATES:
            template = "standard"

        sections_template = ProducerEngine.STRUCTURE_TEMPLATES[template]
        sections: List[Section] = []
        current_bar = 0

        # Map section names to SectionType
        type_map = {
            "Intro": SectionType.INTRO,
            "Verse": SectionType.VERSE,
            "Hook": SectionType.HOOK,
            "Chorus": SectionType.CHORUS,
            "Bridge": SectionType.BRIDGE,
            "Breakdown": SectionType.BREAKDOWN,
            "Outro": SectionType.OUTRO,
        }

        # Occurrence-aware base energy per section type (0.0–1.0).
        # Index 0 = first occurrence, last value used for all further repeats.
        # Keep in sync with _SECTION_ENERGY_ARC in arrangement_jobs.py.
        energy_arc: dict[SectionType, list[float]] = {
            SectionType.INTRO:     [0.20],
            SectionType.VERSE:     [0.60, 0.80],   # verse 2+ feels bigger
            SectionType.HOOK:      [0.80, 1.00],   # hook 1 builds; hook 2+ at full
            SectionType.CHORUS:    [0.80, 1.00],
            SectionType.BRIDGE:    [0.40],
            SectionType.BREAKDOWN: [0.40],
            SectionType.OUTRO:     [0.25],
        }
        occurrence_counter: dict[SectionType, int] = {}

        for name, bars in sections_template:
            if current_bar >= total_bars:
                break

            # Adjust final section to fit
            if current_bar + bars > total_bars:
                bars = total_bars - current_bar

            if bars <= 0:
                break

            section_type = type_map.get(name, SectionType.VERSE)
            occurrence_counter[section_type] = occurrence_counter.get(section_type, 0) + 1
            occ = occurrence_counter[section_type]
            arc = energy_arc.get(section_type, [0.60])
            energy = arc[min(occ - 1, len(arc) - 1)]
            section = Section(
                name=name,
                section_type=section_type,
                bar_start=current_bar,
                bars=bars,
                energy_level=energy,
            )
            sections.append(section)
            current_bar += bars

        return sections

    @staticmethod
    def _generate_energy_curve(sections: List[Section]) -> List[EnergyPoint]:
        """Generate energy curve across the arrangement."""
        energy_points: List[EnergyPoint] = []

        for section in sections:
            # Base energy by section type
            base_energy = {
                SectionType.INTRO: 0.2,
                SectionType.VERSE: 0.6,
                SectionType.HOOK: 0.9,
                SectionType.CHORUS: 0.95,
                SectionType.BRIDGE: 0.4,
                SectionType.BREAKDOWN: 0.3,
                SectionType.OUTRO: 0.1,
            }.get(section.section_type, 0.5)

            # Add energy points at section start and midpoint
            energy_points.append(
                EnergyPoint(
                    bar=section.bar_start,
                    energy=base_energy,
                    description=f"{section.name} start",
                )
            )

            # Add midpoint for longer sections
            if section.bars >= 8:
                midpoint = section.bar_start + section.bars // 2
                energy_points.append(
                    EnergyPoint(
                        bar=midpoint,
                        energy=min(1.0, base_energy + 0.1),
                        description=f"{section.name} build",
                    )
                )

        # Ensure we have a point at the end
        if energy_points:
            last_bar = energy_points[-1].bar
            if last_bar < max(s.bar_end for s in sections):
                energy_points.append(
                    EnergyPoint(
                        bar=max(s.bar_end for s in sections),
                        energy=0.1,
                        description="final outro",
                    )
                )

        return energy_points

    @staticmethod
    def _assign_instruments(arrangement: ProducerArrangement) -> ProducerArrangement:
        """Assign instruments to each section based on genre and beat genome."""
        genre_key = arrangement.genre.lower()
        
        # Try to load from beat genome first
        try:
            genome = BeatGenomeLoader.load(genre_key)
            instrument_layers = genome.get("instrument_layers", {})
            
            for section in arrangement.sections:
                section_name = section.section_type.value.lower()
                
                # Get instruments for this section from genome
                if section_name in instrument_layers:
                    required = instrument_layers[section_name].get("required", [])
                    optional = instrument_layers[section_name].get("optional", [])
                    
                    # Convert instrument names to InstrumentType enum
                    instruments = []
                    for instr_name in required:
                        try:
                            instruments.append(InstrumentType[instr_name.upper()])
                        except (KeyError, ValueError):
                            logger.warning(f"Unknown instrument type in genome: {instr_name}")
                    
                    section.instruments = instruments
                else:
                    # Fallback to preset if section not in genome
                    logger.debug(f"Section {section_name} not found in genome, using preset")
                    section.instruments = ProducerEngine._get_fallback_instruments(genre_key, section.section_type)
        except FileNotFoundError:
            logger.warning(f"Genome not found for genre '{genre_key}', using hardcoded presets")
            
            # Fallback to hardcoded presets
            if genre_key not in ProducerEngine.INSTRUMENT_PRESETS:
                genre_key = "generic"
            
            presets = ProducerEngine.INSTRUMENT_PRESETS[genre_key]
            for section in arrangement.sections:
                instruments = presets.get(
                    section.section_type,
                    presets.get(SectionType.VERSE, []),
                )
                section.instruments = instruments
        
        return arrangement
    
    @staticmethod
    def _get_fallback_instruments(genre_key: str, section_type: SectionType) -> List[InstrumentType]:
        """Get instruments from hardcoded preset as fallback."""
        if genre_key not in ProducerEngine.INSTRUMENT_PRESETS:
            genre_key = "generic"
        
        presets = ProducerEngine.INSTRUMENT_PRESETS[genre_key]
        return presets.get(
            section_type,
            presets.get(SectionType.VERSE, []),
        )

    @staticmethod
    def _generate_transitions(sections: List[Section]) -> List[Transition]:
        """Generate transitions between consecutive sections."""
        transitions: List[Transition] = []

        for i in range(len(sections) - 1):
            from_section = i
            to_section = i + 1

            # Choose transition type based on section pair
            from_type = sections[from_section].section_type
            to_type = sections[to_section].section_type

            if from_type == SectionType.BRIDGE:
                transition_type = TransitionType.DRUM_FILL
            elif to_type == SectionType.HOOK:
                transition_type = TransitionType.RISER
            else:
                transition_type = TransitionType.CROSSFADE

            transitions.append(
                Transition(
                    from_section=from_section,
                    to_section=to_section,
                    transition_type=transition_type,
                    duration_bars=1,
                    intensity=0.7,
                )
            )

        return transitions

    @staticmethod
    def _generate_variations(sections: List[Section]) -> List[Variation]:
        """Generate variations throughout the arrangement."""
        variations: List[Variation] = []
        variation_types = list(VariationType)
        variation_idx = 0

        for section_idx, section in enumerate(sections):
            # Add variations every 4-8 bars within a section
            for bar_offset in range(8, section.bars, 8):
                actual_bar = section.bar_start + bar_offset

                variation = Variation(
                    bar=actual_bar,
                    section_index=section_idx,
                    variation_type=variation_types[
                        variation_idx % len(variation_types)
                    ],
                    intensity=0.5,
                    description=f"Variation in {section.name}",
                )
                variations.append(variation)
                section.variations.append(variation)
                variation_idx += 1

            # Ensure short sections still get at least one variation cue
            if section.bars >= 4 and not section.variations:
                fallback_bar = section.bar_start + max(1, section.bars - 1)
                fallback_variation = Variation(
                    bar=fallback_bar,
                    section_index=section_idx,
                    variation_type=variation_types[
                        variation_idx % len(variation_types)
                    ],
                    intensity=0.6,
                    description=f"Section-end variation in {section.name}",
                )
                variations.append(fallback_variation)
                section.variations.append(fallback_variation)
                variation_idx += 1

        return variations

    @staticmethod
    def _create_tracks(arrangement: ProducerArrangement) -> List[Track]:
        """Create Track objects from unique instruments across all sections."""
        instruments_used = set()
        for section in arrangement.sections:
            instruments_used.update(section.instruments)

        tracks: List[Track] = []
        track_order = [
            InstrumentType.KICK,
            InstrumentType.SNARE,
            InstrumentType.CLAP,
            InstrumentType.HATS,
            InstrumentType.PERCUSSION,
            InstrumentType.BASS,
            InstrumentType.SYNTH,
            InstrumentType.PAD,
            InstrumentType.MELODY,
            InstrumentType.LEAD,
            InstrumentType.STRINGS,
            InstrumentType.HORN,
            InstrumentType.FX,
            InstrumentType.VOCAL,
        ]

        for instrument in track_order:
            if instrument in instruments_used:
                track = Track(
                    name=f"{instrument.value.capitalize()} Track",
                    instrument=instrument,
                    volume_db=0.0 if instrument == InstrumentType.KICK else -3.0,
                )
                tracks.append(track)

        return tracks

    @staticmethod
    def _validate(arrangement: ProducerArrangement) -> ProducerArrangement:
        """Validate the arrangement and set validation flags."""
        errors: List[str] = []

        # Rule 1: Must have at least 3 sections
        if len(arrangement.sections) < 3:
            errors.append("Arrangement must have at least 3 sections")

        # Rule 2: Hooks must have highest energy
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        other_sections = [
            s for s in arrangement.sections
            if s.section_type not in (SectionType.HOOK, SectionType.CHORUS)
        ]

        if hook_sections and other_sections:
            avg_hook_energy = sum(s.energy_level for s in hook_sections) / len(
                hook_sections
            )
            avg_other_energy = sum(s.energy_level for s in other_sections) / len(
                other_sections
            )
            if avg_hook_energy <= avg_other_energy:
                # Auto-fix: boost hook energy
                for section in hook_sections:
                    section.energy_level = min(1.0, section.energy_level + 0.2)

        # Rule 3: Must have variation
        if not arrangement.all_variations:
            errors.append("Arrangement should include variations")

        # Rule 4: Duration must be >= 30 seconds
        if arrangement.total_seconds < 30:
            errors.append(
                f"Arrangement too short ({arrangement.total_seconds:.1f}s < 30s)"
            )

        # Rule 5: Verses must have fewer instruments than hooks (to leave vocal space)
        verse_sections = [
            s for s in arrangement.sections if s.section_type == SectionType.VERSE
        ]
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]

        if verse_sections and hook_sections:
            avg_verse_count = sum(len(s.instruments) for s in verse_sections) / len(
                verse_sections
            )
            avg_hook_count = sum(len(s.instruments) for s in hook_sections) / len(
                hook_sections
            )
            if avg_verse_count > avg_hook_count:
                errors.append("Verses should have fewer instruments than hooks")

        arrangement.is_valid = len(errors) == 0
        arrangement.validation_errors = errors

        return arrangement


# ---------------------------------------------------------------------------
# Multi-Genre Producer Events System
# ---------------------------------------------------------------------------

# Canonical section labels understood by generate_producer_events.
_SECTION_INTRO = "intro"
_SECTION_VERSE = "verse"
_SECTION_PRE_HOOK = "pre_hook"
_SECTION_HOOK = "hook"
_SECTION_BRIDGE = "bridge"
_SECTION_BREAKDOWN = "breakdown"
_SECTION_OUTRO = "outro"


@dataclass
class ProducerEvent:
    """
    A single producer-level musical event that maps to a real render action.

    Every event MUST affect audio — it is never metadata-only.
    """

    section: str          # Section label (e.g. "verse_1", "hook_2")
    section_type: str     # Canonical section kind (intro, verse, hook …)
    event_type: str       # What kind of musical change this is
    target: str           # Which stem / layer this event targets
    action: str           # The concrete render action to perform
    intensity: float      # 0.0–1.0 strength of the event
    bar_offset: int       # Bar within the section where the event fires (0-indexed)
    parameters: Dict[str, Any] = field(default_factory=dict)
    render_action: str = ""   # Explicit render-pipeline action string

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProducerEventsResult:
    """
    Return value of :func:`generate_producer_events`.

    Contains the full event list plus metadata required by the spec.
    """

    events: List[ProducerEvent] = field(default_factory=list)
    # Required metadata fields
    producer_events_generated: int = 0
    section_variation_score: float = 0.0   # 0.0–1.0
    energy_curve: List[Dict[str, Any]] = field(default_factory=list)
    event_count_per_section: Dict[str, int] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "producer_events_generated": self.producer_events_generated,
            "section_variation_score": self.section_variation_score,
            "energy_curve": self.energy_curve,
            "event_count_per_section": self.event_count_per_section,
            "events": [e.to_dict() for e in self.events],
        }


# ---------------------------------------------------------------------------
# Genre-specific behavior tables
# ---------------------------------------------------------------------------
# Each entry is a mapping:
#   section_type → list of (event_type, target, action_template, intensity_range)
# where action_template is a format string that may reference {intensity}.

_GENRE_BEHAVIOR: Dict[str, Dict[str, List[Tuple[str, str, str, Tuple[float, float]]]]] = {
    "trap": {
        _SECTION_INTRO: [
            ("melody_filter",    "melody",  "lowpass_filter melody cutoff={intensity:.2f}",         (0.3, 0.5)),
            ("fx_atmosphere",    "fx",      "apply_reverb fx depth={intensity:.2f}",                 (0.4, 0.7)),
        ],
        _SECTION_VERSE: [
            ("drum_pattern",     "drums",   "set_drum_pattern basic density={intensity:.2f}",        (0.4, 0.6)),
            ("808_basic",        "808",     "play_808 note=root velocity={intensity:.2f}",            (0.5, 0.7)),
            ("melody_reduce",    "melody",  "duck_melody volume={intensity:.2f}",                     (0.3, 0.5)),
            ("hihat_variation",  "hats",    "hihat_variation period=4 density={intensity:.2f}",       (0.3, 0.5)),
        ],
        _SECTION_PRE_HOOK: [
            ("kick_drop",        "drums",   "drop_kick bar_offset=0",                                 (0.7, 0.9)),
            ("snare_roll",       "drums",   "snare_roll duration=1 density={intensity:.2f}",          (0.6, 0.8)),
            ("riser_fx",         "fx",      "apply_riser fx pitch_end=1.0 intensity={intensity:.2f}", (0.7, 1.0)),
        ],
        _SECTION_HOOK: [
            ("full_melody",      "melody",  "unmute_melody volume=1.0",                               (0.8, 1.0)),
            ("808_active",       "808",     "play_808_pattern pattern=active velocity={intensity:.2f}",(0.7, 1.0)),
            ("hihat_rolls",      "hats",    "hihat_roll count=16 density={intensity:.2f}",             (0.7, 1.0)),
            ("fx_impact",        "fx",      "apply_fx_impact type=impact intensity={intensity:.2f}",   (0.8, 1.0)),
            ("automation_vol",   "master",  "automate_volume ramp=up intensity={intensity:.2f}",       (0.6, 0.9)),
        ],
        _SECTION_BRIDGE: [
            ("melody_chop",      "melody",  "chop_melody rate=1/8 intensity={intensity:.2f}",         (0.5, 0.8)),
            ("counter_melody",   "melody",  "add_counter_melody interval=5th intensity={intensity:.2f}",(0.4, 0.7)),
        ],
        _SECTION_BREAKDOWN: [
            ("drum_strip",       "drums",   "mute_drums layers=snare intensity={intensity:.2f}",       (0.6, 0.9)),
            ("melody_chop",      "melody",  "chop_melody rate=1/4 intensity={intensity:.2f}",          (0.5, 0.8)),
        ],
        _SECTION_OUTRO: [
            ("drum_remove",      "drums",   "fade_out_drums duration=4 intensity={intensity:.2f}",     (0.6, 1.0)),
            ("melody_tail",      "melody",  "keep_melody_tail reverb={intensity:.2f}",                 (0.4, 0.7)),
            ("fx_fade",          "fx",      "fade_out_fx duration=8 intensity={intensity:.2f}",        (0.5, 0.8)),
        ],
    },
    "drill": {
        _SECTION_INTRO: [
            ("melody_filter",    "melody",  "lowpass_filter melody cutoff={intensity:.2f}",         (0.2, 0.4)),
            ("sub_rumble",       "808",     "apply_sub_rumble intensity={intensity:.2f}",             (0.3, 0.6)),
        ],
        _SECTION_VERSE: [
            ("drum_pattern",     "drums",   "set_drum_pattern drill_sliding density={intensity:.2f}", (0.5, 0.7)),
            ("808_slide",        "808",     "play_808_slide note=root slide=1 velocity={intensity:.2f}",(0.6, 0.8)),
            ("hihat_offbeat",    "hats",    "hihat_offbeat spacing=triplet density={intensity:.2f}",   (0.4, 0.6)),
        ],
        _SECTION_PRE_HOOK: [
            ("kick_drop",        "drums",   "drop_kick bar_offset=0",                                  (0.7, 0.9)),
            ("snare_roll",       "drums",   "snare_roll duration=1 density={intensity:.2f}",           (0.6, 0.85)),
            ("dark_riser",       "fx",      "apply_riser fx pitch_end=1.0 dark=1 intensity={intensity:.2f}",(0.7, 1.0)),
        ],
        _SECTION_HOOK: [
            ("full_melody",      "melody",  "unmute_melody volume=1.0",                                (0.8, 1.0)),
            ("808_active",       "808",     "play_808_pattern pattern=slide velocity={intensity:.2f}",  (0.7, 1.0)),
            ("hihat_rolls",      "hats",    "hihat_roll count=32 density={intensity:.2f}",              (0.8, 1.0)),
            ("fx_impact",        "fx",      "apply_fx_impact type=impact intensity={intensity:.2f}",    (0.8, 1.0)),
            ("stab_chop",        "melody",  "chop_melody rate=1/16 stab=1 intensity={intensity:.2f}",  (0.6, 0.9)),
        ],
        _SECTION_BRIDGE: [
            ("melody_chop",      "melody",  "chop_melody rate=1/8 intensity={intensity:.2f}",          (0.5, 0.8)),
            ("counter_melody",   "melody",  "add_counter_melody interval=4th intensity={intensity:.2f}",(0.4, 0.7)),
        ],
        _SECTION_BREAKDOWN: [
            ("drum_strip",       "drums",   "mute_drums layers=snare intensity={intensity:.2f}",        (0.6, 0.9)),
            ("808_sustain",      "808",     "sustain_808 duration=2 intensity={intensity:.2f}",         (0.5, 0.8)),
        ],
        _SECTION_OUTRO: [
            ("drum_remove",      "drums",   "fade_out_drums duration=4 intensity={intensity:.2f}",      (0.6, 1.0)),
            ("melody_tail",      "melody",  "keep_melody_tail reverb={intensity:.2f}",                  (0.4, 0.7)),
        ],
    },
    "rnb": {
        _SECTION_INTRO: [
            ("chord_filter",     "melody",  "lowpass_filter melody cutoff={intensity:.2f}",          (0.3, 0.5)),
            ("pad_swell",        "pad",     "swell_pad volume={intensity:.2f} duration=4",             (0.4, 0.7)),
        ],
        _SECTION_VERSE: [
            ("drum_pattern",     "drums",   "set_drum_pattern rnb_swing density={intensity:.2f}",     (0.3, 0.5)),
            ("bass_groove",      "bass",    "play_bass groove=smooth velocity={intensity:.2f}",        (0.5, 0.7)),
            ("melody_reduce",    "melody",  "duck_melody volume={intensity:.2f}",                      (0.3, 0.5)),
            ("hihat_variation",  "hats",    "hihat_variation period=2 density={intensity:.2f}",        (0.3, 0.5)),
        ],
        _SECTION_PRE_HOOK: [
            ("snare_roll",       "drums",   "snare_roll duration=1 density={intensity:.2f}",           (0.5, 0.7)),
            ("chord_rise",       "melody",  "chord_progression_rise intensity={intensity:.2f}",         (0.6, 0.8)),
        ],
        _SECTION_HOOK: [
            ("full_melody",      "melody",  "unmute_melody volume=1.0",                                (0.8, 1.0)),
            ("bass_active",      "bass",    "play_bass pattern=active velocity={intensity:.2f}",        (0.7, 0.9)),
            ("hihat_rolls",      "hats",    "hihat_roll count=8 density={intensity:.2f}",               (0.6, 0.9)),
            ("fx_impact",        "fx",      "apply_fx_impact type=soft intensity={intensity:.2f}",      (0.7, 0.9)),
            ("counter_melody",   "melody",  "add_counter_melody interval=3rd intensity={intensity:.2f}",(0.5, 0.8)),
            ("automation_vol",   "master",  "automate_volume ramp=smooth intensity={intensity:.2f}",    (0.6, 0.9)),
        ],
        _SECTION_BRIDGE: [
            ("chord_chop",       "melody",  "chop_melody rate=1/4 intensity={intensity:.2f}",           (0.4, 0.7)),
            ("counter_melody",   "melody",  "add_counter_melody interval=6th intensity={intensity:.2f}",(0.4, 0.7)),
        ],
        _SECTION_BREAKDOWN: [
            ("drum_strip",       "drums",   "mute_drums layers=kick intensity={intensity:.2f}",          (0.5, 0.8)),
            ("pad_swell",        "pad",     "swell_pad volume={intensity:.2f} duration=8",               (0.4, 0.7)),
        ],
        _SECTION_OUTRO: [
            ("drum_remove",      "drums",   "fade_out_drums duration=8 intensity={intensity:.2f}",       (0.5, 0.9)),
            ("melody_tail",      "melody",  "keep_melody_tail reverb={intensity:.2f}",                   (0.5, 0.8)),
            ("pad_fade",         "pad",     "fade_out_pad duration=8 intensity={intensity:.2f}",         (0.4, 0.7)),
        ],
    },
    "rage": {
        _SECTION_INTRO: [
            ("distort_intro",    "melody",  "apply_distortion melody intensity={intensity:.2f}",        (0.4, 0.7)),
            ("fx_atmosphere",    "fx",      "apply_distorted_reverb fx depth={intensity:.2f}",           (0.5, 0.8)),
        ],
        _SECTION_VERSE: [
            ("drum_pattern",     "drums",   "set_drum_pattern rage_trap density={intensity:.2f}",       (0.5, 0.7)),
            ("808_distort",      "808",     "play_808_distorted note=root velocity={intensity:.2f}",     (0.6, 0.8)),
            ("hihat_triplet",    "hats",    "hihat_triplet density={intensity:.2f}",                     (0.5, 0.7)),
        ],
        _SECTION_PRE_HOOK: [
            ("kick_drop",        "drums",   "drop_kick bar_offset=0",                                    (0.7, 0.9)),
            ("rage_riser",       "fx",      "apply_riser fx distort=1 intensity={intensity:.2f}",        (0.8, 1.0)),
        ],
        _SECTION_HOOK: [
            ("full_melody",      "melody",  "unmute_melody distort=1 volume=1.0",                        (0.9, 1.0)),
            ("808_heavy",        "808",     "play_808_heavy velocity={intensity:.2f}",                   (0.8, 1.0)),
            ("hihat_rolls",      "hats",    "hihat_roll count=32 triplet=1 density={intensity:.2f}",     (0.8, 1.0)),
            ("fx_impact",        "fx",      "apply_fx_impact type=distorted intensity={intensity:.2f}",  (0.9, 1.0)),
            ("melody_chop",      "melody",  "chop_melody rate=1/16 distort=1 intensity={intensity:.2f}", (0.7, 1.0)),
            ("automation_vol",   "master",  "automate_volume ramp=hard intensity={intensity:.2f}",       (0.7, 1.0)),
        ],
        _SECTION_BRIDGE: [
            ("melody_chop",      "melody",  "chop_melody rate=1/8 distort=1 intensity={intensity:.2f}", (0.6, 0.9)),
            ("counter_melody",   "melody",  "add_counter_melody distort=1 intensity={intensity:.2f}",    (0.5, 0.8)),
        ],
        _SECTION_BREAKDOWN: [
            ("drum_strip",       "drums",   "mute_drums layers=snare intensity={intensity:.2f}",          (0.6, 0.9)),
            ("808_sustain",      "808",     "sustain_808_distort duration=2 intensity={intensity:.2f}",   (0.6, 0.9)),
        ],
        _SECTION_OUTRO: [
            ("drum_remove",      "drums",   "fade_out_drums duration=2 intensity={intensity:.2f}",        (0.6, 1.0)),
            ("melody_tail",      "melody",  "keep_melody_tail distort=0 reverb={intensity:.2f}",          (0.3, 0.6)),
        ],
    },
}

# Section type → base energy (0.0–1.0) used for energy_curve metadata.
_SECTION_BASE_ENERGY: Dict[str, float] = {
    _SECTION_INTRO:     0.20,
    _SECTION_VERSE:     0.60,
    _SECTION_PRE_HOOK:  0.70,
    _SECTION_HOOK:      0.90,
    _SECTION_BRIDGE:    0.40,
    _SECTION_BREAKDOWN: 0.30,
    _SECTION_OUTRO:     0.15,
}

# Per-section-type, additional events for the *second* (and later) occurrence
# to guarantee variation across repeated sections.
_VARIATION_EXTRAS: Dict[str, List[Tuple[str, str, str, Tuple[float, float]]]] = {
    _SECTION_VERSE: [
        ("melody_chop",      "melody", "chop_melody rate=1/8 intensity={intensity:.2f}",     (0.4, 0.7)),
        ("808_variation",    "808",    "808_pitch_variation semitones=2 intensity={intensity:.2f}", (0.4, 0.7)),
    ],
    _SECTION_HOOK: [
        ("extra_fx",         "fx",     "apply_fx_layer type=reverb_tail intensity={intensity:.2f}", (0.6, 1.0)),
        ("808_extra",        "808",    "808_extra_hit velocity={intensity:.2f}",                    (0.7, 1.0)),
        ("hihat_extra",      "hats",   "hihat_roll count=64 density={intensity:.2f}",               (0.8, 1.0)),
    ],
    _SECTION_BRIDGE: [
        ("counter_melody",   "melody", "add_counter_melody interval=7th intensity={intensity:.2f}", (0.4, 0.7)),
    ],
}

# Minimum number of events expected in each section type (for audibility guard).
_MIN_EVENTS: Dict[str, int] = {
    _SECTION_INTRO:     1,
    _SECTION_VERSE:     2,
    _SECTION_PRE_HOOK:  1,
    _SECTION_HOOK:      3,
    _SECTION_BRIDGE:    1,
    _SECTION_BREAKDOWN: 1,
    _SECTION_OUTRO:     1,
}


def _normalise_section_type(raw: str) -> str:
    """
    Convert varied section names (from ProducerArrangementPlanV2 or any plain
    dict/list representation) to the canonical lowercase keys used internally.
    """
    s = raw.lower().strip().replace(" ", "_").replace("-", "_")
    # Handle common aliases
    aliases = {
        "chorus":    _SECTION_HOOK,
        "pre_chorus": _SECTION_PRE_HOOK,
        "prehook":   _SECTION_PRE_HOOK,
    }
    return aliases.get(s, s)


def _resolve_sections(plan: Any) -> List[Dict[str, Any]]:
    """
    Accept a variety of plan representations and return a normalised list of
    section dicts with at least ``section_type`` and ``label`` keys.

    Supported plan types:
    - ``ProducerArrangementPlanV2`` (has ``.sections`` list of ``ProducerSectionPlan``)
    - ``ProducerArrangement`` (has ``.sections`` list of ``Section``)
    - A plain list of dicts
    - A dict with a ``sections`` key
    """
    # Import locally to avoid circular dependencies.
    try:
        from app.services.producer_plan_builder import ProducerArrangementPlanV2
        if isinstance(plan, ProducerArrangementPlanV2):
            return [
                {
                    "section_type": _normalise_section_type(s.section_type.value),
                    "label": s.label,
                    "start_bar": s.start_bar,
                    "length_bars": s.length_bars,
                }
                for s in plan.sections
            ]
    except ImportError:
        pass

    if isinstance(plan, ProducerArrangement):
        return [
            {
                "section_type": _normalise_section_type(s.section_type.value),
                "label": s.name,
                "start_bar": s.bar_start,
                "length_bars": s.bars,
            }
            for s in plan.sections
        ]

    if isinstance(plan, dict) and "sections" in plan:
        raw_sections = plan["sections"]
    elif isinstance(plan, list):
        raw_sections = plan
    else:
        raise TypeError(
            f"generate_producer_events: unsupported plan type {type(plan).__name__}"
        )

    normalised = []
    for sec in raw_sections:
        st = _normalise_section_type(
            sec.get("section_type", sec.get("type", "verse"))
        )
        normalised.append(
            {
                "section_type": st,
                "label": sec.get("label", sec.get("name", st)),
                "start_bar": sec.get("start_bar", sec.get("bar_start", 0)),
                "length_bars": sec.get("length_bars", sec.get("bars", 8)),
            }
        )
    return normalised


def generate_producer_events(
    plan: Any,
    genre: str,
    vibe: str,
    seed: int,
) -> ProducerEventsResult:
    """
    Generate producer-level musical events for a given arrangement plan.

    Each event maps to a real render action and is never metadata-only.
    The same ``seed`` always produces the same output; different seeds produce
    distinct variations.

    Args:
        plan: Arrangement plan — ``ProducerArrangementPlanV2``,
              ``ProducerArrangement``, a list of section dicts, or a dict with
              a ``sections`` key.
        genre: One of ``"trap"``, ``"drill"``, ``"rnb"``, ``"rage"``.
               Unknown genres fall back to ``"trap"``.
        vibe: Free-form vibe string (e.g. ``"dark"``, ``"melodic"``) used to
              modulate intensity.
        seed: Integer seed for deterministic output.

    Returns:
        :class:`ProducerEventsResult` with the full event list and metadata.
    """
    rng = _random_mod.Random(seed)

    genre_key = genre.lower().strip()
    if genre_key not in _GENRE_BEHAVIOR:
        logger.warning(
            "generate_producer_events: unknown genre %r, falling back to 'trap'",
            genre,
        )
        genre_key = "trap"

    # Vibe intensity modifier: "dark", "heavy", "hard" → push toward max.
    vibe_boost = 0.0
    vibe_lower = vibe.lower()
    if any(w in vibe_lower for w in ("dark", "heavy", "hard", "aggressive", "loud")):
        vibe_boost = 0.1
    elif any(w in vibe_lower for w in ("chill", "soft", "smooth", "mellow", "light")):
        vibe_boost = -0.1

    genre_rules = _GENRE_BEHAVIOR[genre_key]
    sections = _resolve_sections(plan)

    # Track how many times each section type has appeared so we can enforce
    # variation for 2nd+ occurrences (verse1 ≠ verse2, hook1 ≠ hook2 …).
    occurrence_counter: Dict[str, int] = {}

    all_events: List[ProducerEvent] = []
    event_count_per_section: Dict[str, int] = {}
    energy_curve: List[Dict[str, Any]] = []

    for sec in sections:
        stype = sec["section_type"]
        label = sec["label"]
        start_bar = sec.get("start_bar", 0)
        length_bars = sec.get("length_bars", 8)

        occurrence_counter[stype] = occurrence_counter.get(stype, 0) + 1
        occurrence = occurrence_counter[stype]

        # Derive a unique section label including its occurrence number.
        sec_label = f"{stype}_{occurrence}"

        # Determine base energy for this section.
        base_energy = _SECTION_BASE_ENERGY.get(stype, 0.5)
        # Hook 2+ is bigger than hook 1.
        if stype == _SECTION_HOOK and occurrence > 1:
            base_energy = min(1.0, base_energy + 0.1)
        # Verse 2+ differs slightly.
        if stype == _SECTION_VERSE and occurrence > 1:
            base_energy = min(1.0, base_energy + 0.1)

        energy_curve.append(
            {
                "section": sec_label,
                "label": label,
                "bar": start_bar,
                "energy": round(base_energy, 3),
            }
        )

        # Gather event templates for this section type.
        templates = list(genre_rules.get(stype, genre_rules.get(_SECTION_VERSE, [])))

        # For 2nd+ occurrences inject variation extras so the section is
        # guaranteed to differ from its first occurrence.
        if occurrence > 1 and stype in _VARIATION_EXTRAS:
            templates = list(templates)  # copy
            templates.extend(_VARIATION_EXTRAS[stype])

        section_events: List[ProducerEvent] = []

        # Generate one event per template, spreading bar offsets across the section.
        step_size = max(1, length_bars // max(1, len(templates)))
        bar_positions = list(range(0, max(1, length_bars), step_size))
        for idx, (etype, target, action_tmpl, (lo, hi)) in enumerate(templates):
            raw_intensity = rng.uniform(lo, hi)
            intensity = max(0.0, min(1.0, raw_intensity + vibe_boost))
            bar_offset = bar_positions[idx] if idx < len(bar_positions) else 0
            render_action = action_tmpl.format(intensity=intensity)
            event = ProducerEvent(
                section=sec_label,
                section_type=stype,
                event_type=etype,
                target=target,
                action=render_action,
                intensity=round(intensity, 4),
                bar_offset=bar_offset,
                parameters={
                    "genre": genre_key,
                    "vibe": vibe,
                    "occurrence": occurrence,
                },
                render_action=render_action,
            )
            section_events.append(event)

        # Enforce minimum events (audibility guard).
        min_required = _MIN_EVENTS.get(stype, 1)
        if len(section_events) < min_required:
            # Generate a fallback generic automation event.
            for _ in range(min_required - len(section_events)):
                intensity = max(0.0, min(1.0, rng.uniform(0.4, 0.7) + vibe_boost))
                render_action = f"automate_volume ramp=neutral intensity={intensity:.2f}"
                section_events.append(
                    ProducerEvent(
                        section=sec_label,
                        section_type=stype,
                        event_type="automation_vol",
                        target="master",
                        action=render_action,
                        intensity=round(intensity, 4),
                        bar_offset=0,
                        parameters={"genre": genre_key, "vibe": vibe, "occurrence": occurrence},
                        render_action=render_action,
                    )
                )

        all_events.extend(section_events)
        event_count_per_section[sec_label] = len(section_events)

    # -----------------------------------------------------------------------
    # Compute section_variation_score
    #
    # Score = fraction of "repeated" section types whose events differ from the
    # first occurrence.  We compare event-type lists only (not intensity values)
    # to keep this deterministic and meaningful.
    # -----------------------------------------------------------------------
    type_event_signatures: Dict[str, List[str]] = {}  # stype → event_types of 1st occurrence
    score_occurrence_counter: Dict[str, int] = {}
    differing = 0
    repeated = 0
    for event in all_events:
        stype = event.section_type
        score_occurrence_counter[stype] = score_occurrence_counter.get(stype, 0) + 1
        occ = score_occurrence_counter[stype]
        sec_label = f"{stype}_{occ}"
        if occ == 1:
            # Record fingerprint of first occurrence (event types in order of first
            # appearance within the section).
            if stype not in type_event_signatures:
                type_event_signatures[stype] = []
            type_event_signatures[stype].append(event.event_type)
        else:
            # Compare against first occurrence fingerprint.
            first_types = set(type_event_signatures.get(stype, []))
            if event.event_type not in first_types:
                differing += 1
            repeated += 1

    variation_score = (differing / repeated) if repeated > 0 else 1.0

    return ProducerEventsResult(
        events=all_events,
        producer_events_generated=len(all_events),
        section_variation_score=round(min(1.0, variation_score), 4),
        energy_curve=energy_curve,
        event_count_per_section=event_count_per_section,
    )
