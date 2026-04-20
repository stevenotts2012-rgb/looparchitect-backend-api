"""
Tests for ReferenceProfile schema and build_reference_profile() — Phase 5.

Covers:
- Profile fields computed correctly from ReferenceStructure
- hook_density computed from hook sections
- transition_frequency based on boundary strengths
- breakdown_depth from lowest breakdown/bridge energy
- outro_behavior descriptions
- energy_contour shapes
- Empty structure returns valid profile
"""

from __future__ import annotations

import pytest

from app.schemas.reference_arrangement import (
    ReferenceSection,
    ReferenceStructure,
    ReferenceProfile,
)
from app.services.reference_analyzer import build_reference_profile


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
    trans_in: float = 0.2,
    trans_out: float = 0.2,
) -> ReferenceSection:
    bpm = 120.0
    duration = end - start
    bars = max(1, int(round((duration / 60.0) * bpm / 4.0)))
    return ReferenceSection(
        index=index,
        start_time_sec=start,
        end_time_sec=end,
        estimated_bars=bars,
        section_type_guess=section_type,
        energy_level=energy,
        density_level=density,
        transition_in_strength=trans_in,
        transition_out_strength=trans_out,
        confidence=0.7,
    )


def _make_structure(sections: list[ReferenceSection], confidence: float = 0.7) -> ReferenceStructure:
    total = sections[-1].end_time_sec if sections else 0.0
    return ReferenceStructure(
        total_duration_sec=total,
        tempo_estimate=120.0,
        sections=sections,
        energy_curve=[s.energy_level for s in sections],
        summary="Test",
        analysis_confidence=confidence,
        analysis_quality="medium",
    )


# ---------------------------------------------------------------------------
# Basic field extraction
# ---------------------------------------------------------------------------


class TestReferenceProfileFields:
    def test_section_order_extracted(self):
        sections = [
            _make_section(0, 0, 20, "intro"),
            _make_section(1, 20, 50, "verse"),
            _make_section(2, 50, 80, "hook"),
            _make_section(3, 80, 100, "outro"),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.section_order == ["intro", "verse", "hook", "outro"]

    def test_section_lengths_match_count(self):
        sections = [
            _make_section(0, 0, 20, "intro"),
            _make_section(1, 20, 50, "verse"),
            _make_section(2, 50, 80, "hook"),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert len(profile.section_lengths) == 3
        assert all(l >= 1 for l in profile.section_lengths)

    def test_tempo_bpm_passed_through(self):
        sections = [_make_section(0, 0, 30, "verse")]
        structure = _make_structure(sections)
        profile = build_reference_profile(structure)
        assert profile.tempo_bpm == pytest.approx(120.0)

    def test_total_duration_matches(self):
        sections = [_make_section(0, 0, 60, "verse")]
        structure = _make_structure(sections)
        profile = build_reference_profile(structure)
        assert profile.total_duration_sec == pytest.approx(60.0)

    def test_analysis_confidence_passed_through(self):
        sections = [_make_section(0, 0, 30, "verse")]
        profile = build_reference_profile(_make_structure(sections, confidence=0.85))
        assert profile.analysis_confidence == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Hook density
# ---------------------------------------------------------------------------


class TestHookDensity:
    def test_hook_density_computed(self):
        sections = [
            _make_section(0, 0, 20, "verse", density=0.3),
            _make_section(1, 20, 50, "hook", density=0.8),
            _make_section(2, 50, 80, "hook", density=0.6),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.hook_density == pytest.approx(0.7, abs=0.01)

    def test_no_hooks_returns_none(self):
        sections = [
            _make_section(0, 0, 30, "verse"),
            _make_section(1, 30, 60, "verse"),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.hook_density is None


# ---------------------------------------------------------------------------
# Transition frequency
# ---------------------------------------------------------------------------


class TestTransitionFrequency:
    def test_all_weak_transitions_zero_frequency(self):
        sections = [
            _make_section(0, 0, 20, "verse", trans_in=0.1, trans_out=0.1),
            _make_section(1, 20, 40, "hook", trans_in=0.1, trans_out=0.1),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.transition_frequency == 0.0

    def test_all_strong_transitions_full_frequency(self):
        sections = [
            _make_section(0, 0, 20, "verse", trans_in=0.9, trans_out=0.9),
            _make_section(1, 20, 40, "hook", trans_in=0.9, trans_out=0.9),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.transition_frequency == pytest.approx(1.0)

    def test_partial_strong_transitions(self):
        sections = [
            _make_section(0, 0, 20, "verse", trans_in=0.1, trans_out=0.1),
            _make_section(1, 20, 40, "hook", trans_in=0.9, trans_out=0.9),  # strong
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert 0.0 < profile.transition_frequency <= 1.0


# ---------------------------------------------------------------------------
# Breakdown depth
# ---------------------------------------------------------------------------


class TestBreakdownDepth:
    def test_breakdown_depth_computed(self):
        sections = [
            _make_section(0, 0, 20, "verse", energy=0.7),
            _make_section(1, 20, 40, "breakdown", energy=0.1),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.breakdown_depth == pytest.approx(0.1, abs=0.01)

    def test_bridge_counts_as_contrast(self):
        sections = [
            _make_section(0, 0, 20, "hook", energy=0.9),
            _make_section(1, 20, 40, "bridge", energy=0.2),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.breakdown_depth is not None

    def test_no_breakdown_or_bridge_is_none(self):
        sections = [
            _make_section(0, 0, 20, "verse"),
            _make_section(1, 20, 40, "hook"),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.breakdown_depth is None


# ---------------------------------------------------------------------------
# Outro behavior
# ---------------------------------------------------------------------------


class TestOutroBehavior:
    def test_fades_to_silence_for_very_low_energy(self):
        sections = [
            _make_section(0, 0, 30, "verse", energy=0.7),
            _make_section(1, 30, 60, "outro", energy=0.1),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.outro_behavior == "fades_to_silence"

    def test_fades_out_for_low_energy(self):
        sections = [
            _make_section(0, 0, 30, "verse", energy=0.7),
            _make_section(1, 30, 60, "outro", energy=0.3),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.outro_behavior == "fades_out"

    def test_no_outro_empty_string(self):
        sections = [_make_section(0, 0, 30, "verse")]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.outro_behavior == ""


# ---------------------------------------------------------------------------
# Energy contour
# ---------------------------------------------------------------------------


class TestEnergyContour:
    def test_flat_energy_is_flat(self):
        sections = [_make_section(i, i * 10, (i + 1) * 10, "verse", energy=0.5) for i in range(4)]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.energy_contour == "flat"

    def test_builds_to_peak(self):
        sections = [
            _make_section(0, 0, 20, "intro", energy=0.1),
            _make_section(1, 20, 40, "verse", energy=0.3),
            _make_section(2, 40, 60, "hook", energy=0.9),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.energy_contour == "builds_to_peak"

    def test_falls_off(self):
        sections = [
            _make_section(0, 0, 20, "hook", energy=0.9),
            _make_section(1, 20, 40, "verse", energy=0.5),
            _make_section(2, 40, 60, "outro", energy=0.2),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.energy_contour == "falls_off"

    def test_peaks_in_middle(self):
        # With 5 sections, peak at index 2 is clearly in the middle (n//3=1, 2*n//3=3)
        sections = [
            _make_section(0, 0, 20, "intro", energy=0.2),
            _make_section(1, 20, 40, "verse", energy=0.5),
            _make_section(2, 40, 60, "hook", energy=0.9),
            _make_section(3, 60, 80, "verse", energy=0.5),
            _make_section(4, 80, 100, "outro", energy=0.2),
        ]
        profile = build_reference_profile(_make_structure(sections))
        assert profile.energy_contour == "peaks_in_middle"


# ---------------------------------------------------------------------------
# Empty structure
# ---------------------------------------------------------------------------


class TestEmptyStructure:
    def test_empty_structure_returns_valid_profile(self):
        structure = ReferenceStructure(
            total_duration_sec=0.0,
            sections=[],
            energy_curve=[],
            summary="",
            analysis_confidence=0.0,
            analysis_quality="insufficient",
        )
        profile = build_reference_profile(structure)
        assert isinstance(profile, ReferenceProfile)
        assert profile.section_order == []
        assert profile.section_lengths == []
        assert profile.hook_density is None
        assert profile.transition_frequency == 0.0
        assert profile.breakdown_depth is None
        assert profile.energy_contour == "flat"

    def test_profile_model_is_pydantic(self):
        structure = ReferenceStructure(
            total_duration_sec=0.0,
            sections=[],
            energy_curve=[],
            summary="",
            analysis_confidence=0.0,
            analysis_quality="insufficient",
        )
        profile = build_reference_profile(structure)
        d = profile.model_dump()
        assert "section_order" in d
        assert "hook_density" in d
        assert "transition_frequency" in d
        assert "energy_contour" in d
