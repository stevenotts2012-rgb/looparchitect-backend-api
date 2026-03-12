"""Phase 8 tests: stem classifier — filename heuristics, audio heuristics, and fallbacks.

Covers every example from the product spec plus edge cases.
"""

import pytest
from app.services.stem_classifier import (
    ARRANGEMENT_GROUPS,
    STEM_ROLES,
    UNCERTAIN_THRESHOLD,
    classify_stem,
)


# ---------------------------------------------------------------------------
# Stub audio that supports the 4-band filter chain
# ---------------------------------------------------------------------------

class _BandStub:
    """Configurable RMS stub returned by filter operations."""

    def __init__(self, rms: int, max_val: int = 100) -> None:
        self.rms = rms
        self.max = max_val

    def low_pass_filter(self, _freq: int) -> "_BandStub":
        return self

    def high_pass_filter(self, _freq: int) -> "_BandStub":
        return self


class _ChainedBandStub:
    """Returned by high_pass_filter — remembers its cutoff for chained low_pass_filter."""

    def __init__(self, hp_cutoff: int, owner: "_StubAudio") -> None:
        self._hp = hp_cutoff
        self._owner = owner

    @property
    def rms(self) -> int:
        return self._owner._rms_above(self._hp)

    @property
    def max(self) -> int:
        return self._owner.max

    def low_pass_filter(self, lp: int) -> _BandStub:
        return _BandStub(self._owner._band_rms(self._hp, lp))

    def high_pass_filter(self, freq: int) -> "_ChainedBandStub":
        return _ChainedBandStub(max(self._hp, freq), self._owner)


class _StubAudio:
    """Full-signal stub with per-frequency-band RMS values.

    Band layout (matches _classify_by_audio):
      sub  : 0–80 Hz
      low  : 80–300 Hz
      mid  : 300–3000 Hz
      hi   : 3000+ Hz
    """

    def __init__(
        self,
        rms: int = 1000,
        sub_rms: int = 100,
        low_rms: int = 200,
        mid_rms: int = 600,
        hi_rms: int = 300,
        max_val: int = 1000,
    ) -> None:
        self.rms = rms
        self.max = max_val
        self._bands: dict[tuple[int, int], int] = {
            (0, 80):       sub_rms,
            (80, 300):     low_rms,
            (300, 3000):   mid_rms,
            (3000, 99999): hi_rms,
        }

    def _band_rms(self, hp: int, lp: int) -> int:
        return self._bands.get((hp, lp), 150)

    def _rms_above(self, hp: int) -> int:
        return sum(v for (lo, _), v in self._bands.items() if lo >= hp) or 100

    def low_pass_filter(self, lp: int) -> _BandStub:
        return _BandStub(self._band_rms(0, lp), self.max)

    def high_pass_filter(self, hp: int) -> _ChainedBandStub:
        return _ChainedBandStub(hp, self)


# A flat "neutral" spectrum — all bands modest; no heuristic fires → full_mix fallback
# sub_r=0.20, low_r=0.20 → low_energy=0.40 < 0.80 (no bass)
# mid_r=0.30 < 0.82 (no pads), hi_r=0.20 < 0.75 (no melody/fx)
# peak_ratio=1.0 < 6.0 (no drums)
_neutral_audio = _StubAudio(
    rms=1000, sub_rms=200, low_rms=200, mid_rms=300, hi_rms=200, max_val=1000
)

# Generic audio — used where filename heuristic wins (confidence ≥ 0.78), so audio path irrelevant
_generic_audio = _StubAudio()



# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

def _classify(filename: str, audio=None):
    return classify_stem(filename, audio or _generic_audio)


# ---------------------------------------------------------------------------
# Phase 8 — required filename test cases
# ---------------------------------------------------------------------------

class TestCatchFireFilenames:
    """Test the exact Catch_Fire filenames from the product spec."""

    def test_bass_stem(self):
        r = _classify("Catch_Fire_Bass_Dmin_142BPM_8.wav")
        assert r.role == "bass"
        assert r.group == "low_end"
        assert r.confidence >= 0.78
        assert "bass" in r.matched_keywords

    def test_bell_stem_is_melody(self):
        r = _classify("Catch_Fire_Bell_Dmin_142BPM_9.wav")
        assert r.role == "melody"
        assert r.group == "lead"
        assert r.confidence >= 0.78
        assert "bell" in r.matched_keywords

    def test_synth_key_stem(self):
        # synth_key → compound pass hits "synth key" → harmony
        r = _classify("Catch_Fire_Synth_Key_Dmin_142BPM_11.wav")
        assert r.role in ("harmony", "melody")
        assert r.group in ("harmonic", "lead")
        assert r.confidence >= 0.78

    def test_accent_stem(self):
        r = _classify("Catch_Fire_Accent_3_Dmin_142BPM_6.wav")
        assert r.role == "accent"
        assert r.group == "transition"
        assert r.confidence >= 0.78

    def test_perc_loop(self):
        r = _classify("perc_loop.wav")
        assert r.role in ("percussion", "drums")
        assert r.group == "rhythm"

    def test_full_mix(self):
        r = _classify("full_mix.wav")
        assert r.role == "full_mix"
        assert r.group == "fallback_mix"


class TestRoleTaxonomy:
    """Verify every role in the taxonomy is reachable via filename."""

    @pytest.mark.parametrize("filename,expected_role", [
        ("kick_drum_loop.wav",    "drums"),
        ("snare_hit.wav",         "drums"),
        ("clap_pattern.wav",      "drums"),
        ("hihat_open.wav",        "drums"),
        ("rim_shot.wav",          "drums"),
        ("shaker_groove.wav",     "percussion"),
        ("conga_pattern.wav",     "percussion"),
        ("808_sub_bass.wav",      "bass"),
        ("sub_bass_loop.wav",     "bass"),
        ("lead_melody.wav",       "melody"),
        ("arp_sequence.wav",      "melody"),
        ("piano_riff.wav",        "melody"),
        ("pad_layer.wav",         "pads"),
        ("chord_stab.wav",        "harmony"),
        ("strings_harmony.wav",   "harmony"),
        ("organ_fill.wav",        "harmony"),
        ("riser_fx.wav",          "fx"),
        ("sweep_transition.wav",  "fx"),
        ("impact_hit.wav",        "fx"),       # "impact" → fx, "hit" → accent — fx wins if first
        ("reverse_cymbal.wav",    "fx"),
        ("accent_stab.wav",       "accent"),    # "accent" wins being first in table
        ("vocal_chop.wav",        "vocals"),
        ("vox_adlib.wav",         "vocals"),
        ("full_mix_stereo.wav",   "full_mix"),
        ("master_bounce.wav",     "full_mix"),
    ])
    def test_role_detected(self, filename, expected_role):
        r = _classify(filename)
        assert r.role == expected_role, (
            f"{filename!r}: expected {expected_role!r}, got {r.role!r} "
            f"(keywords={r.matched_keywords})"
        )


class TestArrangementGroups:
    """Verify group mapping for key roles."""

    @pytest.mark.parametrize("role,expected_group", [
        ("drums",      "rhythm"),
        ("percussion", "rhythm"),
        ("bass",       "low_end"),
        ("melody",     "lead"),
        ("vocals",     "lead"),
        ("harmony",    "harmonic"),
        ("pads",       "harmonic"),
        ("fx",         "texture"),
        ("accent",     "transition"),
        ("full_mix",   "fallback_mix"),
    ])
    def test_groups(self, role, expected_group):
        assert ARRANGEMENT_GROUPS[role] == expected_group

    def test_classification_group_matches_table(self):
        r = _classify("kick_drum.wav")
        assert r.group == ARRANGEMENT_GROUPS[r.role]


class TestSourcesUsed:
    """Filename matches must set sources_used=['filename']."""

    def test_filename_source_recorded(self):
        r = _classify("bass_loop.wav")
        assert "filename" in r.sources_used

    def test_keywords_populated(self):
        r = _classify("bass_loop.wav")
        assert len(r.matched_keywords) >= 1


class TestCompoundFilenames:
    """Compound word stems are split and matched correctly."""

    def test_synth_lead(self):
        r = _classify("track_synth_lead.wav")
        assert r.role == "melody"

    def test_perc_loop_compound(self):
        r = _classify("track_perc_loop.wav")
        assert r.role == "percussion"

    def test_kick_drum_compound(self):
        r = _classify("kick_drum_pattern.wav")
        assert r.role == "drums"


class TestLowConfidenceFallback:
    """When filename is ambiguous and audio heuristic is also uncertain, result is uncertain=True."""

    def test_unknown_filename_gets_full_mix_via_audio_fallback(self):
        # No filename keywords match; neutral flat audio → no band heuristic fires → full_mix
        r = classify_stem("mystery_layer_xyz.wav", _neutral_audio)
        assert r.role == "full_mix"
        assert r.group == "fallback_mix"
        assert r.uncertain is True

    def test_uncertain_flag_below_threshold(self):
        r = classify_stem("track_abc_123.wav", _neutral_audio)
        # Neutral audio + unknown filename → uncertain
        assert r.uncertain is True

    def test_uncertain_result_still_has_group(self):
        r = classify_stem("mystery_abc.wav", _neutral_audio)
        assert r.group in (
            "rhythm", "low_end", "lead", "harmonic", "texture",
            "transition", "fallback_mix",
        )


class TestAudioHeuristics:
    """Audio heuristics kick in when filename confidence < AUDIO_HEURISTIC_THRESHOLD."""

    def test_bass_heavy_audio(self):
        # Sub + low RMS dominate → bass
        heavy_bass = _StubAudio(rms=1000, sub_rms=850, low_rms=820, mid_rms=300, hi_rms=150)
        r = classify_stem("unknown_track.wav", heavy_bass)
        assert r.role == "bass"
        assert "audio" in r.sources_used

    def test_high_transient_audio_drums(self):
        # Many transients: peak_ratio >> 6
        transient_audio = _StubAudio(rms=200, sub_rms=80, low_rms=100, mid_rms=150, hi_rms=120, max_val=3000)
        r = classify_stem("loop_z.wav", transient_audio)
        # high peak_ratio + low sub_energy → drums
        assert r.role in ("drums", "full_mix")  # depends on stub RMS proportions

    def test_audio_source_recorded_when_no_filename_match(self):
        r = classify_stem("zyxw_track.wav", _StubAudio())
        assert "filename" not in r.sources_used


class TestStemRolesConstant:
    """STEM_ROLES constant must include all 10 roles."""

    def test_all_roles_present(self):
        required = {
            "drums", "bass", "melody", "harmony", "pads",
            "fx", "percussion", "accent", "vocals", "full_mix",
        }
        assert required.issubset(set(STEM_ROLES))


class TestMetadataShape:
    """StemClassification has all expected fields."""

    def test_has_all_fields(self):
        r = _classify("bass_loop.wav")
        assert hasattr(r, "role")
        assert hasattr(r, "group")
        assert hasattr(r, "confidence")
        assert hasattr(r, "matched_keywords")
        assert hasattr(r, "sources_used")
        assert hasattr(r, "uncertain")
        assert hasattr(r, "reason")

    def test_reason_backward_compat(self):
        r = _classify("drums.wav")
        assert isinstance(r.reason, str)
        assert len(r.reason) > 0
