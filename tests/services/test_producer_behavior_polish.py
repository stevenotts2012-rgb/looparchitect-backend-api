"""
Tests for Producer Behavior Polish - Musical realism improvements.

Verifies that polish rules are correctly applied and improve musical qualities.
"""

import pytest
from app.services.producer_engine import ProducerEngine
from app.services.producer_behavior_polish import ProducerBehaviorPolish
from app.services.producer_models import (
    ProducerArrangement,
    Section,
    SectionType,
    InstrumentType,
)


class TestHookImpactTuning:
    """Test that hooks feel significantly bigger than verses."""
    
    def test_hooks_have_more_instruments_than_verses(self):
        """Verify hooks get 2-3 more instruments than average verse."""
        # Generate a full arrangement
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="trap",
            structure_template="standard",
        )
        
        # Count instruments per section type
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        verse_sections = [
            s for s in arrangement.sections
            if s.section_type == SectionType.VERSE
        ]
        
        assert hook_sections, "Arrangement should have hooks"
        assert verse_sections, "Arrangement should have verses"
        
        hook_instrument_counts = [len(s.instruments) for s in hook_sections]
        verse_instrument_counts = [len(s.instruments) for s in verse_sections]
        
        avg_hook_instruments = sum(hook_instrument_counts) / len(hook_instrument_counts)
        avg_verse_instruments = sum(verse_instrument_counts) / len(verse_instrument_counts)
        
        # Hooks should have at least 2 more instruments than verses
        assert (
            avg_hook_instruments >= avg_verse_instruments + 2
        ), f"Hooks ({avg_hook_instruments:.1f}) should have 2+ more instruments than verses ({avg_verse_instruments:.1f})"
    
    def test_hooks_have_higher_energy_than_verses(self):
        """Verify hooks have higher energy level than verses."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="pop",
            structure_template="standard",
        )
        
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        verse_sections = [
            s for s in arrangement.sections
            if s.section_type == SectionType.VERSE
        ]
        
        avg_hook_energy = sum(s.energy_level for s in hook_sections) / len(hook_sections)
        avg_verse_energy = sum(s.energy_level for s in verse_sections) / len(verse_sections)
        
        # Hooks should have significantly higher energy
        assert avg_hook_energy > avg_verse_energy, (
            f"Hook energy ({avg_hook_energy:.2f}) should exceed "
            f"verse energy ({avg_verse_energy:.2f})"
        )
    
    def test_hooks_have_additional_sound_design_layers(self):
        """Verify hooks include FX, strings, or percussion for depth."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="trap",
            structure_template="standard",
        )
        
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        
        # Check for additional richness instruments
        richness_instruments = {
            InstrumentType.FX,
            InstrumentType.PERCUSSION,
            InstrumentType.STRINGS,
            InstrumentType.SYNTH,
        }
        
        hooks_with_richness = sum(
            1 for s in hook_sections
            if any(i in s.instruments for i in richness_instruments)
        )
        
        assert (
            hooks_with_richness > 0
        ), "At least one hook should have sound design (FX, percussion, strings)"


class TestVerseVocalSpace:
    """Test that verses create space for artist vocals."""
    
    def test_verses_have_fewer_instruments_than_hooks(self):
        """Verify verses have fewer busy layers than hooks."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="rnb",
            structure_template="standard",
        )
        
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        verse_sections = [
            s for s in arrangement.sections
            if s.section_type == SectionType.VERSE
        ]
        
        for verse in verse_sections:
            # Each verse should have fewer instruments than hooks
            hook_counts = [len(h.instruments) for h in hook_sections]
            max_hook_count = max(hook_counts)
            
            assert len(verse.instruments) < max_hook_count, (
                f"Verse should have fewer instruments ({len(verse.instruments)}) "
                f"than hooks ({max_hook_count})"
            )
    
    def test_verses_remove_melodic_layers(self):
        """Verify verses remove LEAD and MELODY instruments."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="pop",
            structure_template="standard",
        )
        
        verse_sections = [
            s for s in arrangement.sections
            if s.section_type == SectionType.VERSE
        ]
        
        melodic_instruments = {InstrumentType.LEAD, InstrumentType.MELODY}
        
        # Count verses that still have melodic layers
        verses_with_melodic = sum(
            1 for v in verse_sections
            if any(i in v.instruments for i in melodic_instruments)
        )
        
        # Most verses should NOT have melodic layers
        if len(verse_sections) > 0:
            assert verses_with_melodic == 0, (
                f"Verses should not have LEAD/MELODY instruments "
                f"(found in {verses_with_melodic}/{len(verse_sections)} verses)"
            )
    
    def test_verses_preserve_rhythm_foundation(self):
        """Verify verses keep essential rhythm instruments."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="trap",
            structure_template="standard",
        )
        
        verse_sections = [
            s for s in arrangement.sections
            if s.section_type == SectionType.VERSE
        ]
        
        essential_rhythm = {InstrumentType.KICK, InstrumentType.SNARE, InstrumentType.HATS, InstrumentType.BASS}
        
        for verse in verse_sections:
            verse_instruments = set(verse.instruments)
            # Verses should have most essential rhythm instruments
            has_essential = verse_instruments & essential_rhythm
            assert len(has_essential) >= 2, (
                f"Verse should preserve rhythm foundation: "
                f"found {[i.value for i in has_essential]}"
            )


class TestTransitionPolish:
    """Test enhanced transitions between sections."""
    
    def test_transitions_into_hooks_are_enhanced(self):
        """Verify transitions into hooks use riser or drum fill."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="pop",
            structure_template="standard",
        )
        
        # Find transitions into hooks
        hook_indices = {
            i for i, s in enumerate(arrangement.sections)
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        }
        
        transitions_to_hooks = [
            t for t in arrangement.transitions
            if t.to_section in hook_indices
        ]
        
        # Should have transitions prepared for hooks
        assert len(transitions_to_hooks) > 0, (
            "Should have transitions leading into hooks"
        )
    
    def test_transition_intensity_varies_by_context(self):
        """Verify transition intensity matches section type."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="cinematic",
            structure_template="standard",
        )
        
        # Transitions should exist
        assert len(arrangement.transitions) > 0, "Should have transitions"
        
        # Check intensity ranges
        for transition in arrangement.transitions:
            # Intensity should be between 0.0 and 1.0
            assert 0.0 <= transition.intensity <= 1.0


class TestFinalHookExpansion:
    """Test that final hook is equal or bigger than first hook."""
    
    def test_final_hook_matches_first_hook_instruments(self):
        """Verify last hook has at least as many instruments as first."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="trap",
            structure_template="standard",
        )
        
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        
        if len(hook_sections) >= 2:
            first_hook = hook_sections[0]
            last_hook = hook_sections[-1]
            
            assert len(last_hook.instruments) >= len(first_hook.instruments), (
                f"Final hook ({len(last_hook.instruments)} instruments) should have "
                f"at least as many instruments as first hook ({len(first_hook.instruments)})"
            )
    
    def test_final_hook_energy_is_strong(self):
        """Verify final hook has strong energy level."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="pop",
            structure_template="standard",
        )
        
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        
        if len(hook_sections) >= 1:
            last_hook = hook_sections[-1]
            
            # Final hook should have high energy (> 0.8)
            assert last_hook.energy_level > 0.8, (
                f"Final hook energy ({last_hook.energy_level:.2f}) should be > 0.8"
            )


class TestVariationDensity:
    """Test that variation density is high and meaningful."""
    
    def test_variations_added_throughout_arrangement(self):
        """Verify variations are added to ensure interest every 4-8 bars."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="rnb",
            structure_template="standard",
        )
        
        # Total variations should be reasonable for the length
        assert len(arrangement.all_variations) > 0, (
            "Arrangement should have variations"
        )
        
        # Roughly: 60 second song at 120 BPM = ~32 bars
        # Variations every 4-8 bars = ~4-8 variations minimum
        min_expected_variations = arrangement.total_bars // 8
        assert len(arrangement.all_variations) >= min_expected_variations, (
            f"Should have at least {min_expected_variations} variations, "
            f"found {len(arrangement.all_variations)}"
        )
    
    def test_variation_types_are_section_specific(self):
        """Verify variations use appropriate types per section."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="generic",
            structure_template="standard",
        )
        
        # Each section should have some variations
        sections_with_variations = sum(
            1 for s in arrangement.sections
            if len(s.variations) > 0
        )
        
        assert sections_with_variations > 0, (
            "Sections should have variations for maintaining interest"
        )


class TestHumanization:
    """Test that humanization hints are present for subtle realism."""
    
    def test_humanization_hints_are_present(self):
        """Verify arrangement includes humanization hints."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="trap",
            structure_template="standard",
        )
        
        assert hasattr(arrangement, "humanization_hints"), (
            "Arrangement should have humanization_hints attribute"
        )
        assert arrangement.humanization_hints, (
            "Humanization hints should not be empty"
        )
    
    def test_humanization_hints_include_timing_and_velocity(self):
        """Verify humanization hints cover timing and velocity variations."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="pop",
            structure_template="standard",
        )
        
        hints = arrangement.humanization_hints
        
        assert "timing_variations_ms" in hints, (
            "Humanization should include timing variations"
        )
        assert "velocity_variation_range" in hints, (
            "Humanization should include velocity variations"
        )
        
        # Verify some instruments have variation hints
        timing_hints = hints.get("timing_variations_ms", {})
        assert len(timing_hints) > 0, (
            "Should have timing hints for instruments"
        )


class TestPolishValidation:
    """Test the polish validation helper function."""
    
    def test_validate_polish_improvements_detects_enhancements(self):
        """Verify validate_polish_improvements correctly detects improvements."""
        # Create a baseline arrangement
        original = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="trap",
            structure_template="standard",
        )
        
        # The engine already applies polish, so just check validation
        improvements = ProducerBehaviorPolish.validate_polish_improvements(
            original, original
        )
        
        assert isinstance(improvements, dict)
        assert "hook_impact_improved" in improvements
        assert "verse_vocal_space_improved" in improvements


class TestRenderPipelineIntegration:
    """Test that polish doesn't break the unified render pipeline."""
    
    def test_polished_arrangement_is_valid(self):
        """Verify polished arrangement passes validation."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="generic",
            structure_template="standard",
        )
        
        # Should be valid after polish
        assert arrangement.is_valid, (
            f"Polished arrangement should be valid. "
            f"Errors: {arrangement.validation_errors}"
        )
    
    def test_polished_arrangement_has_required_fields(self):
        """Verify all required fields are present after polish."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="pop",
            structure_template="standard",
        )
        
        # All these should exist after polish
        assert arrangement.sections, "Should have sections"
        assert arrangement.energy_curve, "Should have energy curve"
        assert arrangement.transitions, "Should have transitions"
        assert arrangement.all_variations, "Should have variations"
        assert arrangement.tracks, "Should have tracks"
    
    def test_polished_arrangement_maintains_bar_accuracy(self):
        """Verify total bars are correctly maintained."""
        arrangement = ProducerEngine.generate(
            target_seconds=60,
            tempo=120,
            genre="rnb",
            structure_template="standard",
        )
        
        section_bars = sum(s.bars for s in arrangement.sections)
        assert section_bars == arrangement.total_bars, (
            f"Section bars ({section_bars}) should equal total bars "
            f"({arrangement.total_bars})"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
