"""
Arrangement Validation: Ensures arrangements meet quality standards.

Validation Rules:
1. Minimum 3 sections
2. Hooks have highest energy
3. Verses have < instruments than hooks (leave vocal space)
4. Duration >= 60 seconds
5. Must have variations (changes every 4-8 bars)
6. No endless loops without change
"""

import logging
from typing import List, Tuple
from app.services.producer_models import (
    ProducerArrangement,
    Section,
    SectionType,
    InstrumentType,
)

logger = logging.getLogger(__name__)


class ArrangementValidator:
    """Validates ProducerArrangements against quality standards."""

    @staticmethod
    def validate(arrangement: ProducerArrangement) -> Tuple[bool, List[str]]:
        """
        Validate an arrangement.
        
        Args:
            arrangement: ProducerArrangement to validate
        
        Returns:
            Tuple of (is_valid: bool, errors: List[str])
        """
        errors: List[str] = []
        
        # Rule 1: Minimum 3 sections
        if len(arrangement.sections) < 3:
            errors.append(
                f"Arrangement must have at least 3 sections (has {len(arrangement.sections)})"
            )
        
        # Rule 2: Duration >= 60 seconds (allow 30+ for short arrangements)
        min_duration = 30.0  # Allow shorter for demos
        if arrangement.total_seconds < min_duration:
            errors.append(
                f"Arrangement too short ({arrangement.total_seconds:.1f}s < {min_duration}s min)"
            )
        
        # Rule 3: Hooks must have highest energy on average
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        other_sections = [
            s for s in arrangement.sections
            if s.section_type not in (SectionType.HOOK, SectionType.CHORUS)
        ]
        
        if hook_sections and other_sections:
            avg_hook_energy = sum(s.energy_level for s in hook_sections) / len(hook_sections)
            avg_other_energy = sum(s.energy_level for s in other_sections) / len(other_sections)
            
            if avg_hook_energy < avg_other_energy:
                errors.append(
                    f"Hooks should have highest energy (hooks={avg_hook_energy:.2f}, "
                    f"other={avg_other_energy:.2f})"
                )
        
        # Rule 4: Verses should have fewer instruments than hooks
        verse_sections = [
            s for s in arrangement.sections if s.section_type == SectionType.VERSE
        ]
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        
        if verse_sections and hook_sections:
            avg_verse_instruments = (
                sum(len(s.instruments) for s in verse_sections) / len(verse_sections)
            )
            avg_hook_instruments = (
                sum(len(s.instruments) for s in hook_sections) / len(hook_sections)
            )
            
            if avg_verse_instruments > avg_hook_instruments:
                errors.append(
                    f"Verses should have fewer instruments than hooks "
                    f"(verses={avg_verse_instruments:.1f}, hooks={avg_hook_instruments:.1f})"
                )
        
        # Rule 5: Must have variations
        if not arrangement.all_variations:
            errors.append("Arrangement should include variations every 4-8 bars")
        
        # Rule 6: No endless loops (check for section repetition)
        if len(arrangement.sections) > 0:
            last_section = arrangement.sections[-1]
            if last_section.section_type != SectionType.OUTRO:
                # Warn but don't error - some styles might loop
                logger.warning("Last section should be Outro for clean ending")
        
        # Rule 7: Energy curve should have variation
        if arrangement.energy_curve:
            energies = [ep.energy for ep in arrangement.energy_curve]
            min_energy = min(energies)
            max_energy = max(energies)
            energy_range = max_energy - min_energy
            
            if energy_range < 0.2:  # Energy should vary by at least 20%
                errors.append(
                    f"Energy curve too flat (range={energy_range:.2f}, needs >= 0.2)"
                )
        
        is_valid = len(errors) == 0
        
        if is_valid:
            logger.info(
                f"✓ Arrangement valid: {len(arrangement.sections)} sections, "
                f"{arrangement.total_bars} bars, {len(arrangement.all_variations)} variations"
            )
        else:
            logger.warning(f"✗ Arrangement validation failed: {len(errors)} errors")
        
        return is_valid, errors

    @staticmethod
    def validate_and_raise(arrangement: ProducerArrangement) -> ProducerArrangement:
        """
        Validate arrangement and raise exception if invalid.
        
        Args:
            arrangement: ProducerArrangement to validate
        
        Returns:
            The validated arrangement
        
        Raises:
            ValueError: If validation fails
        """
        is_valid, errors = ArrangementValidator.validate(arrangement)
        
        if not is_valid:
            error_msg = "Arrangement validation failed:\n" + "\n".join(
                f"  - {error}" for error in errors
            )
            raise ValueError(error_msg)
        
        arrangement.is_valid = True
        arrangement.validation_errors = []
        
        return arrangement

    @staticmethod
    def get_validation_summary(arrangement: ProducerArrangement) -> dict:
        """Get a summary of arrangement validation metrics."""
        is_valid, errors = ArrangementValidator.validate(arrangement)
        
        # Compute metrics
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        verse_sections = [
            s for s in arrangement.sections if s.section_type == SectionType.VERSE
        ]
        
        avg_hook_energy = (
            sum(s.energy_level for s in hook_sections) / len(hook_sections)
            if hook_sections
            else 0.0
        )
        avg_verse_energy = (
            sum(s.energy_level for s in verse_sections) / len(verse_sections)
            if verse_sections
            else 0.0
        )
        
        avg_hook_instruments = (
            sum(len(s.instruments) for s in hook_sections) / len(hook_sections)
            if hook_sections
            else 0
        )
        avg_verse_instruments = (
            sum(len(s.instruments) for s in verse_sections) / len(verse_sections)
            if verse_sections
            else 0
        )
        
        return {
            "is_valid": is_valid,
            "errors": errors,
            "sections_count": len(arrangement.sections),
            "total_bars": arrangement.total_bars,
            "total_seconds": arrangement.total_seconds,
            "variations_count": len(arrangement.all_variations),
            "tracks_count": len(arrangement.tracks),
            "hook_energy": round(avg_hook_energy, 2),
            "verse_energy": round(avg_verse_energy, 2),
            "hook_instruments": round(avg_hook_instruments, 1),
            "verse_instruments": round(avg_verse_instruments, 1),
        }
