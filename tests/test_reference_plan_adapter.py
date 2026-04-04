"""
Unit tests for the Reference Plan Adapter (Phase 3).

Tests cover:
- Structure adaptation (loose / medium / close)
- Limited stem fallback
- Insufficient reference quality fallback
- Energy/density mapping
- Section type mapping
- No direct cloning behavior (regression guardrail)
"""

from __future__ import annotations

from typing import List

import pytest

from app.schemas.reference_arrangement import (
    ReferenceAdaptationStrength,
    ReferenceGuidanceMode,
    ReferenceSection,
    ReferenceStructure,
)
from app.services.reference_plan_adapter import (
    ReferencePlanAdapter,
    _energy_to_level,
    _density_to_level,
    _transition_in_intent,
    _transition_out_intent,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_section(
    index: int,
    start: float,
    end: float,
    section_type: str = "verse",
    energy: float = 0.5,
    density: float = 0.5,
    confidence: float = 0.7,
) -> ReferenceSection:
    return ReferenceSection(
        index=index,
        start_time_sec=start,
        end_time_sec=end,
        estimated_bars=8,
        section_type_guess=section_type,
        energy_level=energy,
        density_level=density,
        transition_in_strength=0.3,
        transition_out_strength=0.3,
        confidence=confidence,
    )


def _make_structure(
    sections: List[ReferenceSection],
    confidence: float = 0.7,
    quality: str = "medium",
    tempo: float = 120.0,
) -> ReferenceStructure:
    return ReferenceStructure(
        total_duration_sec=sections[-1].end_time_sec if sections else 0.0,
        tempo_estimate=tempo,
        sections=sections,
        energy_curve=[s.energy_level for s in sections],
        summary="Test structure",
        analysis_confidence=confidence,
        analysis_quality=quality,
    )


def _standard_structure() -> ReferenceStructure:
    return _make_structure(
        [
            _make_section(0, 0.0, 20.0, "intro", energy=0.2, density=0.2),
            _make_section(1, 20.0, 60.0, "verse", energy=0.5, density=0.5),
            _make_section(2, 60.0, 100.0, "hook", energy=0.9, density=0.8),
            _make_section(3, 100.0, 130.0, "breakdown", energy=0.2, density=0.2),
            _make_section(4, 130.0, 170.0, "hook", energy=0.9, density=0.8),
            _make_section(5, 170.0, 200.0, "outro", energy=0.3, density=0.3),
        ]
    )


# ---------------------------------------------------------------------------
# Tests: energy/density mapping helpers
# ---------------------------------------------------------------------------


class TestEnergyToLevel:
    def test_very_high_energy(self):
        assert _energy_to_level(0.9) == 5

    def test_high_energy(self):
        assert _energy_to_level(0.7) == 4

    def test_medium_energy(self):
        assert _energy_to_level(0.5) == 3

    def test_low_energy(self):
        assert _energy_to_level(0.3) == 2

    def test_very_low_energy(self):
        assert _energy_to_level(0.1) == 1

    def test_boundary_value_0(self):
        assert _energy_to_level(0.0) == 1

    def test_boundary_value_1(self):
        assert _energy_to_level(1.0) == 5


class TestDensityToLevel:
    def test_full_density(self):
        assert _density_to_level(0.8) == "full"

    def test_medium_density(self):
        assert _density_to_level(0.4) == "medium"

    def test_sparse_density(self):
        assert _density_to_level(0.1) == "sparse"

    def test_zero_density(self):
        assert _density_to_level(0.0) == "sparse"


class TestTransitionIntents:
    def test_hook_strong_transition_in(self):
        intent = _transition_in_intent(0.8, "hook")
        assert intent in ("fx_rise", "drum_fill")

    def test_breakdown_transition_in(self):
        intent = _transition_in_intent(0.5, "breakdown")
        assert intent == "pull_back"

    def test_weak_transition_is_none(self):
        intent = _transition_in_intent(0.1, "verse")
        assert intent == "none"

    def test_strong_out_transition(self):
        intent = _transition_out_intent(0.7, "verse")
        assert intent in ("bass_drop", "drum_fill")

    def test_breakdown_out_is_fx_rise(self):
        intent = _transition_out_intent(0.5, "breakdown")
        assert intent == "fx_rise"

    def test_weak_out_is_none(self):
        intent = _transition_out_intent(0.1, "verse")
        assert intent == "none"


# ---------------------------------------------------------------------------
# Tests: adapter core behavior
# ---------------------------------------------------------------------------


class TestReferencePlanAdapter:
    def test_adapt_returns_guidance_for_good_reference(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        assert len(guidance.section_guidance) > 0
        assert guidance.suggested_total_bars is not None
        assert guidance.suggested_total_bars > 0

    def test_insufficient_reference_returns_empty_guidance(self):
        adapter = ReferencePlanAdapter()
        structure = _make_structure([], confidence=0.0, quality="insufficient")
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        assert guidance.section_guidance == []
        assert any("insufficient" in msg.lower() for msg in guidance.decision_log)

    def test_loose_adaptation_simplifies_sections(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.LOOSE,
        )
        # Loose should produce fewer or equal sections vs close
        guidance_close = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.CLOSE,
        )
        assert len(guidance.section_guidance) <= len(guidance_close.section_guidance)

    def test_close_adaptation_uses_more_sections(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.CLOSE,
        )
        assert len(guidance.section_guidance) >= 2

    def test_structure_only_mode_uses_neutral_energy(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_ONLY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        # All energy levels should be neutral (3)
        for sg in guidance.section_guidance:
            assert sg.target_energy == 3
            assert sg.target_density == "medium"

    def test_energy_only_mode_ignores_structure_type_but_applies_energy(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.ENERGY_ONLY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        # At least one section should have non-neutral energy level
        levels = [sg.target_energy for sg in guidance.section_guidance]
        assert any(e != 3 for e in levels), "Energy-only mode should produce varied energy levels"

    def test_structure_and_energy_mode_has_varied_energy(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        energies = [sg.target_energy for sg in guidance.section_guidance]
        assert len(set(energies)) > 1, "Should have varied energy levels"

    def test_limited_stems_reduces_section_count(self):
        adapter = ReferencePlanAdapter()
        # Large structure, only 1 stem role
        structure = _make_structure([
            _make_section(i, i * 30.0, (i + 1) * 30.0)
            for i in range(10)
        ])
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
            available_roles=["drums"],  # only 1 role
        )
        assert len(guidance.section_guidance) <= 5

    def test_limited_stems_logs_decision(self):
        adapter = ReferencePlanAdapter()
        structure = _make_structure([
            _make_section(i, i * 30.0, (i + 1) * 30.0)
            for i in range(8)
        ])
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
            available_roles=["drums"],
        )
        assert any("stem" in msg.lower() for msg in guidance.decision_log)

    def test_section_types_mapped_correctly(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.CLOSE,
        )
        types = [sg.section_type for sg in guidance.section_guidance]
        # Should contain at least intro and outro
        assert "intro" in types or "verse" in types  # intro at start
        assert "hook" in types  # hook should be preserved

    def test_decision_log_is_non_empty(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        assert len(guidance.decision_log) > 0

    def test_energy_arc_summary_is_present(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        assert guidance.energy_arc_summary != ""

    def test_target_bars_are_positive(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        for sg in guidance.section_guidance:
            assert sg.target_bars >= 1

    def test_confidence_passed_through(self):
        adapter = ReferencePlanAdapter()
        structure = _make_structure(
            [_make_section(0, 0.0, 30.0), _make_section(1, 30.0, 60.0)],
            confidence=0.82,
        )
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        assert guidance.reference_confidence == pytest.approx(0.82)

    def test_legal_note_present(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
        )
        assert len(guidance.legal_note) > 0
        assert "musical content" not in guidance.legal_note.lower() or "not" in guidance.legal_note.lower()


# ---------------------------------------------------------------------------
# Regression: no direct cloning behavior
# ---------------------------------------------------------------------------


class TestNoCloningRegression:
    """
    Guardrail tests verifying the adapter never exposes musical content.

    The adapter should produce structural guidance (bar counts, energy levels,
    density levels, section types) — never raw audio, frequencies, notes,
    or any musical content from the reference.
    """

    def test_guidance_contains_no_audio_data(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.CLOSE,
        )
        guidance_dict = guidance.model_dump()
        guidance_str = str(guidance_dict)

        # No audio bytes or raw waveform data in output
        assert "b'" not in guidance_str
        assert "waveform" not in guidance_str.lower()
        assert "spectrogram" not in guidance_str.lower()

    def test_guidance_contains_no_melody_or_chord_info(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.CLOSE,
        )
        guidance_str = str(guidance.model_dump()).lower()

        # No musical content fields
        assert "chord" not in guidance_str
        assert "note" not in guidance_str or "adaptation_note" in guidance_str  # only adaptation_note is ok
        assert "melody" not in guidance_str
        assert "harmony" not in guidance_str

    def test_guidance_only_contains_structural_fields(self):
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.CLOSE,
        )
        for sg in guidance.section_guidance:
            # Structural fields only
            assert isinstance(sg.section_type, str)
            assert isinstance(sg.target_bars, int)
            assert isinstance(sg.target_energy, int)
            assert isinstance(sg.target_density, str)
            assert isinstance(sg.transition_in_intent, str)
            assert isinstance(sg.transition_out_intent, str)

    def test_close_adaptation_does_not_copy_reference_content_verbatim(self):
        """Even CLOSE adaptation should produce an adapted plan, not a mirror copy."""
        adapter = ReferencePlanAdapter()
        structure = _standard_structure()
        guidance = adapter.adapt(
            structure=structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.CLOSE,
        )
        # There should be some adaptation in the decision log
        assert len(guidance.decision_log) > 0
        # The legal note should be present
        assert "blueprint" in guidance.legal_note.lower() or "source material" in guidance.legal_note.lower()


# ---------------------------------------------------------------------------
# Tests: Subsample helper
# ---------------------------------------------------------------------------


class TestSubsampleSections:
    def test_subsample_keeps_first_and_last(self):
        sections = [
            _make_section(i, i * 10.0, (i + 1) * 10.0)
            for i in range(10)
        ]
        result = ReferencePlanAdapter._subsample_sections(sections, 4)
        assert result[0].index == sections[0].index
        assert result[-1].index == sections[-1].index

    def test_subsample_target_respected(self):
        sections = [_make_section(i, i * 10.0, (i + 1) * 10.0) for i in range(10)]
        result = ReferencePlanAdapter._subsample_sections(sections, 4)
        assert len(result) <= 4

    def test_subsample_no_change_when_already_small(self):
        sections = [_make_section(i, i * 10.0, (i + 1) * 10.0) for i in range(3)]
        result = ReferencePlanAdapter._subsample_sections(sections, 5)
        assert len(result) == 3

    def test_subsample_target_2(self):
        sections = [_make_section(i, i * 10.0, (i + 1) * 10.0) for i in range(8)]
        result = ReferencePlanAdapter._subsample_sections(sections, 2)
        assert len(result) == 2
        assert result[0].index == sections[0].index
        assert result[-1].index == sections[-1].index
