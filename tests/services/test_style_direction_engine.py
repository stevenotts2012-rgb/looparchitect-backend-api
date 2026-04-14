"""Unit tests for StyleDirectionEngine."""

from __future__ import annotations

import pytest

from app.services.style_direction_engine import StyleDirectionEngine
from app.services.producer_models import StyleProfile


# ---------------------------------------------------------------------------
# parse()
# ---------------------------------------------------------------------------


class TestStyleDirectionEngineParseBasic:
    def test_returns_style_profile(self):
        profile = StyleDirectionEngine.parse("trap beat")
        assert isinstance(profile, StyleProfile)

    def test_empty_string_returns_default(self):
        profile = StyleDirectionEngine.parse("")
        assert isinstance(profile, StyleProfile)
        assert profile.genre == "generic"

    def test_none_returns_default(self):
        profile = StyleDirectionEngine.parse(None)
        assert isinstance(profile, StyleProfile)
        assert profile.genre == "generic"

    def test_non_string_returns_default(self):
        profile = StyleDirectionEngine.parse(42)
        assert isinstance(profile, StyleProfile)
        assert profile.genre == "generic"

    def test_whitespace_only_returns_default(self):
        profile = StyleDirectionEngine.parse("   ")
        assert isinstance(profile, StyleProfile)

    def test_profile_has_required_fields(self):
        profile = StyleDirectionEngine.parse("dark trap")
        assert profile.genre is not None
        assert isinstance(profile.bpm_range, tuple)
        assert len(profile.bpm_range) == 2
        assert 0.0 <= profile.energy <= 1.0
        assert profile.drum_style is not None
        assert profile.melody_style is not None
        assert profile.bass_style is not None
        assert profile.structure_template is not None


# ---------------------------------------------------------------------------
# Genre detection
# ---------------------------------------------------------------------------


class TestGenreDetection:
    def test_trap_keyword_detected(self):
        profile = StyleDirectionEngine.parse("trap beat")
        assert profile.genre == "trap"

    def test_drill_keyword_detected(self):
        profile = StyleDirectionEngine.parse("drill beat aggressive")
        assert profile.genre == "drill"

    def test_rnb_keyword_detected(self):
        profile = StyleDirectionEngine.parse("r&b smooth")
        assert profile.genre == "rnb"

    def test_afrobeats_keyword_detected(self):
        profile = StyleDirectionEngine.parse("afrobeats vibe")
        assert profile.genre == "afrobeats"

    def test_house_keyword_detected(self):
        profile = StyleDirectionEngine.parse("house music electronic")
        assert profile.genre == "house"

    def test_cinematic_keyword_detected(self):
        profile = StyleDirectionEngine.parse("cinematic film score")
        assert profile.genre == "cinematic"

    def test_jazz_lofi_keyword_detected(self):
        profile = StyleDirectionEngine.parse("lofi chill beats")
        assert profile.genre == "jazz"

    def test_unknown_genre_defaults_to_generic(self):
        profile = StyleDirectionEngine.parse("xyzzy foobar unknown style")
        assert profile.genre == "generic"

    def test_808_maps_to_trap(self):
        profile = StyleDirectionEngine.parse("808 heavy beat")
        assert profile.genre == "trap"

    def test_case_insensitive(self):
        profile_lower = StyleDirectionEngine.parse("trap")
        profile_upper = StyleDirectionEngine.parse("TRAP")
        # Both should be detected (input is lowercased)
        assert profile_lower.genre == "trap"
        assert profile_upper.genre == "trap"


# ---------------------------------------------------------------------------
# BPM range for genre
# ---------------------------------------------------------------------------


class TestBpmRangeForGenre:
    @pytest.mark.parametrize("genre,expected_min,expected_max", [
        ("trap", 85, 115),
        ("rnb", 80, 105),
        ("pop", 95, 130),
        ("cinematic", 60, 100),
        ("afrobeats", 95, 130),
        ("drill", 130, 160),
        ("house", 120, 130),
        ("jazz", 80, 120),
    ])
    def test_bpm_range_for_genre(self, genre, expected_min, expected_max):
        bpm_range = StyleDirectionEngine._bpm_for_genre(genre)
        assert bpm_range == (expected_min, expected_max)

    def test_unknown_genre_fallback_bpm(self):
        bpm_range = StyleDirectionEngine._bpm_for_genre("unknown_genre")
        assert isinstance(bpm_range, tuple)
        assert len(bpm_range) == 2
        assert bpm_range[0] < bpm_range[1]

    def test_trap_bpm_is_reasonable(self):
        profile = StyleDirectionEngine.parse("trap")
        lo, hi = profile.bpm_range
        assert lo < hi
        assert lo >= 60
        assert hi <= 220


# ---------------------------------------------------------------------------
# Mood / energy detection
# ---------------------------------------------------------------------------


class TestMoodAndEnergyDetection:
    def test_aggressive_mood_high_energy(self):
        profile = StyleDirectionEngine.parse("aggressive hard beat")
        assert profile.energy >= 0.8

    def test_chill_mood_lower_energy(self):
        profile = StyleDirectionEngine.parse("chill relaxed vibe")
        assert profile.energy <= 0.5

    def test_energetic_mood(self):
        profile = StyleDirectionEngine.parse("energetic upbeat exciting")
        assert profile.energy >= 0.75

    def test_dark_mood_medium_energy(self):
        profile = StyleDirectionEngine.parse("dark gritty moody")
        assert 0.4 <= profile.energy <= 0.8

    def test_neutral_fallback_energy(self):
        energy = StyleDirectionEngine._energy_for_mood("neutral")
        assert energy == 0.5

    def test_energy_always_in_range(self):
        for text in ["trap", "drill aggressive", "lofi chill", "cinematic dramatic", ""]:
            profile = StyleDirectionEngine.parse(text)
            assert 0.0 <= profile.energy <= 1.0


# ---------------------------------------------------------------------------
# Artist references
# ---------------------------------------------------------------------------


class TestArtistDetection:
    def test_lil_baby_detected(self):
        profile = StyleDirectionEngine.parse("lil baby type beat")
        assert "lil baby" in profile.references

    def test_drake_detected(self):
        profile = StyleDirectionEngine.parse("drake vibe rnb")
        assert "drake" in profile.references

    def test_hans_zimmer_detected(self):
        profile = StyleDirectionEngine.parse("hans zimmer cinematic")
        assert "hans zimmer" in profile.references

    def test_daft_punk_detected(self):
        profile = StyleDirectionEngine.parse("daft punk house electronic")
        assert "daft punk" in profile.references

    def test_no_artist_empty_references(self):
        profile = StyleDirectionEngine.parse("generic beat")
        # References should be an empty list (no known artist)
        assert profile.references == []


# ---------------------------------------------------------------------------
# Drum / melody / bass style
# ---------------------------------------------------------------------------


class TestStyleAttributes:
    def test_trap_drum_style_is_programmed(self):
        profile = StyleDirectionEngine.parse("trap beat")
        assert profile.drum_style == "programmed"

    def test_cinematic_drum_style_is_orchestral(self):
        profile = StyleDirectionEngine.parse("cinematic film epic")
        assert profile.drum_style == "orchestral"

    def test_live_keyword_overrides_drum_style(self):
        profile = StyleDirectionEngine.parse("trap live drums beat")
        assert profile.drum_style == "live"

    def test_acoustic_keyword_overrides_drum_style(self):
        profile = StyleDirectionEngine.parse("acoustic drum beat")
        assert profile.drum_style == "acoustic"

    def test_trap_bass_style_is_sub(self):
        profile = StyleDirectionEngine.parse("trap beat")
        assert profile.bass_style == "sub"

    def test_808_forces_sub_bass(self):
        profile = StyleDirectionEngine.parse("808 slap trap")
        assert profile.bass_style == "sub"

    def test_drill_melody_minimalist(self):
        profile = StyleDirectionEngine.parse("drill beat hard")
        assert profile.melody_style == "minimalist"


# ---------------------------------------------------------------------------
# Structure template
# ---------------------------------------------------------------------------


class TestStructureTemplate:
    def test_trap_uses_standard_template(self):
        profile = StyleDirectionEngine.parse("trap beat")
        assert profile.structure_template == "standard"

    def test_afrobeats_uses_looped_template(self):
        profile = StyleDirectionEngine.parse("afrobeats vibe")
        assert profile.structure_template == "looped"

    def test_cinematic_uses_progressive_template(self):
        profile = StyleDirectionEngine.parse("cinematic dramatic score")
        assert profile.structure_template == "progressive"

    def test_unknown_genre_has_template(self):
        profile = StyleDirectionEngine.parse("unknown xyz")
        assert profile.structure_template is not None


# ---------------------------------------------------------------------------
# Description
# ---------------------------------------------------------------------------


class TestDescription:
    def test_description_is_non_empty_for_known_genre(self):
        profile = StyleDirectionEngine.parse("trap beat aggressive")
        assert len(profile.description) > 0

    def test_description_contains_genre(self):
        profile = StyleDirectionEngine.parse("house electronic beat")
        assert "house" in profile.description.lower()

    def test_description_contains_artist_when_detected(self):
        profile = StyleDirectionEngine.parse("drake vibe")
        assert "drake" in profile.description.lower()


# ---------------------------------------------------------------------------
# _default_profile()
# ---------------------------------------------------------------------------


class TestDefaultProfile:
    def test_default_profile_is_generic(self):
        profile = StyleDirectionEngine._default_profile()
        assert profile.genre == "generic"

    def test_default_profile_valid_bpm(self):
        profile = StyleDirectionEngine._default_profile()
        lo, hi = profile.bpm_range
        assert lo < hi

    def test_default_energy_is_midpoint(self):
        profile = StyleDirectionEngine._default_profile()
        assert profile.energy == 0.5
