"""
Acceptance Tests for Producer-Style Arrangement System

Verifies:
1. Producer engine generates valid arrangements
2. Style direction engine parses user input correctly
3. Render plan generation works
4. Validation rules are enforced
5. DAW export metadata is correct
"""

import pytest
import json
from app.services.producer_engine import ProducerEngine
from app.services.style_direction_engine import StyleDirectionEngine
from app.services.render_plan import RenderPlanGenerator
from app.services.arrangement_validator import ArrangementValidator
from app.services.daw_export import DAWExporter
from app.services.producer_models import (
    ProducerArrangement,
    StyleProfile,
    SectionType,
    InstrumentType,
)


class TestProducerEngine:
    """Tests for ProducerEngine arrangement generation."""

    def test_generate_basic_arrangement(self):
        """Test basic arrangement generation."""
        arrangement = ProducerEngine.generate(
            target_seconds=60.0,
            tempo=120.0,
            genre="trap",
        )
        
        assert isinstance(arrangement, ProducerArrangement)
        assert arrangement.tempo == 120.0
        assert arrangement.total_seconds == 60.0
        assert arrangement.genre == "trap"
        assert len(arrangement.sections) >= 3

    def test_generate_with_style_profile(self):
        """Test arrangement generation with style profile."""
        style = StyleProfile(
            genre="rnb",
            bpm_range=(80, 105),
            energy=0.6,
            drum_style="programmed",
            melody_style="melodic",
            bass_style="synth",
        )
        
        arrangement = ProducerEngine.generate(
            target_seconds=90.0,
            tempo=95.0,
            genre="rnb",
            style_profile=style,
        )
        
        assert arrangement.genre == "rnb"
        assert arrangement.drum_style == "programmed"
        assert arrangement.melody_style == "melodic"

    def test_arrangement_has_valid_sections(self):
        """Test that arrangement has properly structured sections."""
        arrangement = ProducerEngine.generate(target_seconds=60.0)
        
        # Check sections
        assert len(arrangement.sections) >= 3
        
        # Check bar continuity
        current_bar = 0
        for section in arrangement.sections:
            assert section.bar_start == current_bar
            assert section.bars > 0
            current_bar += section.bars
        
        # Check total bars
        assert current_bar == arrangement.total_bars

    def test_arrangement_has_energy_curve(self):
        """Test that arrangement includes energy curve."""
        arrangement = ProducerEngine.generate(target_seconds=60.0)
        
        assert len(arrangement.energy_curve) > 0
        
        for point in arrangement.energy_curve:
            assert 0.0 <= point.energy <= 1.0
            assert point.bar >= 0

    def test_hook_energy_highest(self):
        """Test that hooks have highest average energy."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        hook_sections = [
            s for s in arrangement.sections
            if s.section_type in (SectionType.HOOK, SectionType.CHORUS)
        ]
        verse_sections = [
            s for s in arrangement.sections
            if s.section_type == SectionType.VERSE
        ]
        
        if hook_sections and verse_sections:
            avg_hook = sum(s.energy_level for s in hook_sections) / len(hook_sections)
            avg_verse = sum(s.energy_level for s in verse_sections) / len(verse_sections)
            
            assert avg_hook >= avg_verse

    def test_verses_fewer_instruments_than_hooks(self):
        """Test that verses have fewer instruments than hooks."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        verse_sections = [
            s for s in arrangement.sections
            if s.section_type == SectionType.VERSE
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
            
            assert avg_verse_instruments <= avg_hook_instruments

    def test_has_variations(self):
        """Test that arrangement includes variations."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        assert len(arrangement.all_variations) > 0
        
        # Variations every 4-8 bars minimum
        for variation in arrangement.all_variations:
            assert variation.bar > 0
            assert 0.0 <= variation.intensity <= 1.0

    def test_tracks_created_from_instruments(self):
        """Test that tracks are created from unique instruments."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        assert len(arrangement.tracks) > 0
        
        # All section instruments should be in tracks
        all_instruments = set()
        for section in arrangement.sections:
            all_instruments.update(section.instruments)
        
        track_instruments = {t.instrument for t in arrangement.tracks}
        
        assert all_instruments == track_instruments


class TestStyleDirectionEngine:
    """Tests for StyleDirectionEngine style parsing."""

    def test_parse_trap_style(self):
        """Test parsing trap style input."""
        profile = StyleDirectionEngine.parse("Southside type aggressive trap")
        
        assert profile.genre == "trap"
        assert profile.drum_style == "programmed"
        assert profile.energy >= 0.7

    def test_parse_rnb_style(self):
        """Test parsing R&B style input."""
        profile = StyleDirectionEngine.parse("Drake R&B smooth melodic vibe")
        
        assert profile.genre == "rnb"
        assert profile.melody_style == "melodic"

    def test_parse_cinematic_style(self):
        """Test parsing cinematic style input."""
        profile = StyleDirectionEngine.parse("Hans Zimmer cinematic dark epic")
        
        assert profile.genre == "cinematic"
        assert profile.energy == 0.6  # dark mood

    def test_parse_afrobeats_style(self):
        """Test parsing Afrobeats style input."""
        profile = StyleDirectionEngine.parse("Wizkid Afrobeats percussive")
        
        assert profile.genre == "afrobeats"

    def test_empty_input_returns_default(self):
        """Test that empty input returns default profile."""
        profile = StyleDirectionEngine.parse("")
        
        assert profile.genre == "generic"
        assert profile.energy == 0.5

    def test_artist_detection(self):
        """Test artist reference detection."""
        profile = StyleDirectionEngine.parse("Like Lil Baby")
        
        assert "lil baby" in profile.references or profile.genre == "trap"

    def test_mood_detection(self):
        """Test mood keyword detection."""
        profile_aggressive = StyleDirectionEngine.parse("aggressive dark hard")
        profile_chill = StyleDirectionEngine.parse("chill relaxed smooth")
        
        assert profile_aggressive.energy > profile_chill.energy


class TestRenderPlan:
    """Tests for RenderPlanGenerator."""

    def test_generate_render_plan(self):
        """Test render plan generation."""
        arrangement = ProducerEngine.generate(target_seconds=60.0)
        render_plan = RenderPlanGenerator.generate(arrangement)
        
        assert render_plan.bpm == arrangement.tempo
        assert render_plan.key == arrangement.key
        assert render_plan.total_bars == arrangement.total_bars
        assert len(render_plan.sections) > 0
        assert len(render_plan.tracks) > 0

    def test_render_plan_has_events(self):
        """Test that render plan includes instrument events."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        render_plan = RenderPlanGenerator.generate(arrangement)
        
        # Should have enter events at section boundaries
        enter_events = [e for e in render_plan.events if e.event_type == "enter"]
        assert len(enter_events) > 0

    def test_render_plan_json_serializable(self):
        """Test that render plan can be serialized to JSON."""
        arrangement = ProducerEngine.generate(target_seconds=60.0)
        render_plan = RenderPlanGenerator.generate(arrangement)
        
        json_str = render_plan.to_json()
        assert isinstance(json_str, str)
        
        # Should parse back
        data = json.loads(json_str)
        assert data["bpm"] == arrangement.tempo
        assert data["total_bars"] == arrangement.total_bars


class TestArrangementValidator:
    """Tests for arrangement validation."""

    def test_valid_arrangement_passes(self):
        """Test that valid arrangement passes validation."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        is_valid, errors = ArrangementValidator.validate(arrangement)
        
        assert is_valid
        assert len(errors) == 0

    def test_too_short_arrangement_fails(self):
        """Test that too-short arrangement fails validation."""
        arrangement = ProducerEngine.generate(target_seconds=10.0)
        
        is_valid, errors = ArrangementValidator.validate(arrangement)
        
        # Should fail - too short
        assert not is_valid or "too short" in str(errors).lower()

    def test_validation_summary_generated(self):
        """Test that validation summary is generated."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        summary = ArrangementValidator.get_validation_summary(arrangement)
        
        assert "is_valid" in summary
        assert "sections_count" in summary
        assert "total_bars" in summary
        assert "variations_count" in summary
        assert summary["sections_count"] >= 3

    def test_minimum_three_sections(self):
        """Test that validation requires minimum 3 sections."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        # should have at least 3 sections
        assert len(arrangement.sections) >= 3
        
        is_valid, errors = ArrangementValidator.validate(arrangement)
        assert is_valid


class TestDAWExport:
    """Tests for DAW export functionality."""

    def test_export_metadata_generated(self):
        """Test that export metadata is generated."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        metadata = DAWExporter.generate_export_metadata(arrangement, arrangement_id=1)
        
        assert metadata["arrangement_id"] == 1
        assert "sections" in metadata
        assert "stem_names" in metadata
        assert "midi_files" in metadata

    def test_markers_csv_generated(self):
        """Test that markers CSV is generated."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        csv_data = DAWExporter.generate_markers_csv(arrangement)
        
        assert isinstance(csv_data, str)
        assert "Name,Start" in csv_data
        
        # Should have at least one section
        lines = csv_data.strip().split("\n")
        assert len(lines) >= 2  # header + at least 1 section

    def test_tempo_map_generated(self):
        """Test that tempo map is generated."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        tempo_map_json = DAWExporter.generate_tempo_map_json(arrangement)
        
        assert isinstance(tempo_map_json, str)
        tempo_map = json.loads(tempo_map_json)
        
        assert tempo_map["bpm"] == arrangement.tempo
        assert tempo_map["total_bars"] == arrangement.total_bars
        assert tempo_map["time_signature"] == "4/4"

    def test_readme_generated(self):
        """Test that README content is generated."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        readme = DAWExporter.generate_readme(arrangement, arrangement_id=1)
        
        assert isinstance(readme, str)
        assert "Arrangement ID: 1" in readme
        assert "LoopArchitect" in readme
        assert str(arrangement.tempo) in readme

    def test_supported_daws_defined(self):
        """Test that supported DAWs are defined."""
        daws = DAWExporter.SUPPORTED_DAWS
        
        expected_daws = ["FL Studio", "Ableton Live", "Logic Pro", "Studio One", "Pro Tools", "Reaper"]
        assert daws == expected_daws

    def test_export_package_info(self):
        """Test that export package info is complete."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        package_info = DAWExporter.get_export_package_info(arrangement)
        
        assert package_info["type"] == "LoopArchitect DAW Export"
        assert "contents" in package_info
        assert "stems" in package_info["contents"]
        assert "midi" in package_info["contents"]
        assert "metadata" in package_info["contents"]
        assert len(package_info["supported_daws"]) == 6


class TestIntegration:
    """Integration tests for complete producer workflow."""

    def test_complete_workflow(self):
        """Test complete producer workflow: style → arrangement → render plan → export."""
        # User input
        style_input = "Trap music like Lil Baby aggressive"
        target_seconds = 90.0
        
        # Step 1: Parse style
        style_profile = StyleDirectionEngine.parse(style_input)
        assert style_profile.genre == "trap"
        
        # Step 2: Generate arrangement
        arrangement = ProducerEngine.generate(
            target_seconds=target_seconds,
            tempo=100.0,  # Common trap tempo
            genre=style_profile.genre,
            style_profile=style_profile,
        )
        assert arrangement.genre == "trap"
        assert len(arrangement.sections) >= 3
        
        # Step 3: Validate
        is_valid, errors = ArrangementValidator.validate(arrangement)
        assert is_valid
        
        # Step 4: Generate render plan
        render_plan = RenderPlanGenerator.generate(arrangement)
        assert render_plan.bpm == arrangement.tempo
        assert len(render_plan.events) > 0
        
        # Step 5: Generate export metadata
        export_info = DAWExporter.generate_export_metadata(arrangement, 1)
        assert export_info["arrangement_id"] == 1
        assert len(export_info["stem_names"]) > 0
        
        # All steps successful
        assert True

    def test_arrangement_serialization(self):
        """Test that arrangements can be serialized to JSON and back."""
        arrangement = ProducerEngine.generate(target_seconds=120.0)
        
        # Serialize
        json_str = arrangement.to_json()
        assert isinstance(json_str, str)
        
        # Parse back
        data = json.loads(json_str)
        assert data["tempo"] == arrangement.tempo
        assert data["total_bars"] == arrangement.total_bars
        assert len(data["sections"]) == len(arrangement.sections)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
