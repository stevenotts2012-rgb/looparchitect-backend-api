"""Unit tests for stem_role_mapper (filename → canonical role mapping)."""

from __future__ import annotations

import pytest

from app.services.stem_role_mapper import (
    RoleMapResult,
    map_ai_stem_to_role,
    map_filename_to_role,
)
from app.services.canonical_stem_manifest import (
    SOURCE_AI_SEPARATED,
    SOURCE_UPLOADED_STEM,
    SOURCE_ZIP_STEM,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_result(
    result: RoleMapResult,
    expected_role: str,
    min_confidence: float = 0.5,
    fallback: bool = False,
) -> None:
    assert result.canonical_role == expected_role, (
        f"Expected '{expected_role}' but got '{result.canonical_role}' "
        f"(confidence={result.confidence})"
    )
    assert result.confidence >= min_confidence
    assert result.fallback is fallback


# ---------------------------------------------------------------------------
# map_filename_to_role – clear matches
# ---------------------------------------------------------------------------


class TestMapFilenameToRoleClearMatches:
    @pytest.mark.parametrize("filename,expected_role", [
        ("kick.wav",            "kick"),
        ("kik.wav",             "kick"),
        ("bd.wav",              "kick"),
        ("bassdrum.wav",        "kick"),
        ("snare.wav",           "snare"),
        ("snr.wav",             "snare"),
        ("clap.wav",            "clap"),
        ("hihat.wav",           "hi_hat"),
        ("hi-hat.wav",          "hi_hat"),
        ("hh.wav",              "hi_hat"),
        ("hat.wav",             "hi_hat"),
        ("cymbal.wav",          "cymbals"),
        ("crash.wav",           "cymbals"),
        ("bass.wav",            "bass"),
        ("sub bass.wav",        "bass"),
        ("808.wav",             "808"),
        ("piano.wav",           "piano"),
        ("epiano.wav",          "piano"),
        ("guitar.wav",          "guitar"),
        ("pad.wav",             "pads"),
        ("pads.wav",            "pads"),
        ("strings.wav",         "strings"),
        ("synth.wav",           "synth"),
        ("arp.wav",             "arp"),
        ("melody.wav",          "melody"),
        ("lead.wav",            "melody"),
        ("fx.wav",              "fx"),
        ("sfx.wav",             "fx"),
        ("riser.wav",           "fx"),
        ("vocal.wav",           "vocal"),
        ("vocals.wav",          "vocal"),
        ("vox.wav",             "vocal"),
        ("harmony.wav",         "harmony"),
        ("chords.wav",          "harmony"),
        ("full mix.wav",        "full_mix"),
        ("mixdown.wav",         "full_mix"),
    ])
    def test_clear_filename_mapping(self, filename, expected_role):
        result = map_filename_to_role(filename)
        assert result.canonical_role == expected_role
        assert result.confidence >= 0.5

    def test_result_type(self):
        result = map_filename_to_role("kick.wav")
        assert isinstance(result, RoleMapResult)

    def test_confidence_is_float(self):
        result = map_filename_to_role("snare.wav")
        assert isinstance(result.confidence, float)

    def test_matched_keywords_populated(self):
        result = map_filename_to_role("kick.wav")
        assert len(result.matched_keywords) > 0

    def test_source_type_default(self):
        result = map_filename_to_role("kick.wav")
        assert result.source_type == SOURCE_UPLOADED_STEM

    def test_source_type_zip(self):
        result = map_filename_to_role("kick.wav", source_type=SOURCE_ZIP_STEM)
        assert result.source_type == SOURCE_ZIP_STEM


# ---------------------------------------------------------------------------
# map_filename_to_role – fallback for unknown filenames
# ---------------------------------------------------------------------------


class TestMapFilenameToRoleFallback:
    def test_unknown_filename_returns_full_mix_fallback(self):
        result = map_filename_to_role("zzz_completely_unknown_stem_xyzzy.wav")
        assert result.canonical_role == "full_mix"
        assert result.fallback is True

    def test_fallback_confidence_is_low(self):
        result = map_filename_to_role("zzz_completely_unknown_stem_xyzzy.wav")
        assert result.confidence < 0.6

    def test_path_stem_extracted_from_full_path(self):
        result = map_filename_to_role("/some/path/to/kick_drum.wav")
        assert result.canonical_role == "kick"

    def test_case_insensitive_matching(self):
        result_lower = map_filename_to_role("KICK.WAV")
        assert result_lower.canonical_role == "kick"

    def test_broad_role_populated(self):
        result = map_filename_to_role("kick.wav")
        assert result.broad_role is not None
        assert isinstance(result.broad_role, str)


# ---------------------------------------------------------------------------
# map_filename_to_role – compound alias matching
# ---------------------------------------------------------------------------


class TestCompoundAliasMatching:
    def test_sub_bass_maps_to_bass(self):
        result = map_filename_to_role("sub_bass.wav")
        assert result.canonical_role == "bass"

    def test_bass_line_maps_to_bass(self):
        result = map_filename_to_role("bass_line.wav")
        assert result.canonical_role == "bass"

    def test_open_hat_maps_to_hi_hat(self):
        result = map_filename_to_role("open_hat.wav")
        assert result.canonical_role == "hi_hat"

    def test_bell_melody_maps_to_melody(self):
        result = map_filename_to_role("bell_melody.wav")
        assert result.canonical_role == "melody"

    def test_riser_fx_maps_to_fx(self):
        result = map_filename_to_role("riser_fx.wav")
        assert result.canonical_role == "fx"


# ---------------------------------------------------------------------------
# map_filename_to_role – multi-hit bonus
# ---------------------------------------------------------------------------


class TestMultiHitBonus:
    def test_multiple_matching_keywords_boost_confidence(self):
        """A filename containing multiple kick aliases should be high confidence."""
        result_single = map_filename_to_role("kick.wav")
        result_multi = map_filename_to_role("kick_kik_bd.wav")
        # Multi-hit bonus applies; confidence should be >= single
        assert result_multi.confidence >= result_single.confidence


# ---------------------------------------------------------------------------
# map_ai_stem_to_role
# ---------------------------------------------------------------------------


class TestMapAiStemToRole:
    @pytest.mark.parametrize("stem_name,expected_role", [
        ("drums",  "drums"),
        ("bass",   "bass"),
        ("vocals", "vocal"),
        ("vocal",  "vocal"),
        ("other",  "melody"),
        ("melody", "melody"),
        ("piano",  "piano"),
        ("guitar", "guitar"),
    ])
    def test_ai_stem_mapping(self, stem_name, expected_role):
        result = map_ai_stem_to_role(stem_name)
        assert result.canonical_role == expected_role

    def test_default_confidence(self):
        result = map_ai_stem_to_role("drums")
        assert result.confidence == 0.72

    def test_custom_confidence(self):
        result = map_ai_stem_to_role("bass", confidence=0.9)
        assert result.confidence == 0.9

    def test_source_type_is_ai_separated(self):
        result = map_ai_stem_to_role("drums")
        assert result.source_type == SOURCE_AI_SEPARATED

    def test_fallback_false_for_known_stems(self):
        result = map_ai_stem_to_role("drums")
        assert result.fallback is False

    def test_unknown_ai_stem_defaults_to_melody(self):
        result = map_ai_stem_to_role("zzz_unknown_stem")
        assert result.canonical_role == "melody"

    def test_broad_role_populated(self):
        result = map_ai_stem_to_role("bass")
        assert result.broad_role is not None

    def test_result_type(self):
        result = map_ai_stem_to_role("drums")
        assert isinstance(result, RoleMapResult)

    def test_case_normalized(self):
        result_lower = map_ai_stem_to_role("drums")
        result_upper = map_ai_stem_to_role("DRUMS")
        assert result_lower.canonical_role == result_upper.canonical_role
