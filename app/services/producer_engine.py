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
from typing import List, Dict, Optional, Tuple
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
        _energy_arc: dict[SectionType, list[float]] = {
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
            arc = _energy_arc.get(section_type, [0.60])
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
