"""Comprehensive tests for app/services/stem_loader.py.

Covers: load_stems_from_metadata, validate_stem_sync, normalize_stem_durations,
and additional map_instruments_to_stems scenarios.
"""

from __future__ import annotations

import io
from unittest.mock import MagicMock, patch

import pytest
from pydub import AudioSegment


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _silent(duration_ms: int = 500, sample_rate: int = 44100) -> AudioSegment:
    """Create a silent AudioSegment for test use."""
    seg = AudioSegment.silent(duration=duration_ms)
    seg = seg.set_frame_rate(sample_rate)
    return seg


# ===========================================================================
# validate_stem_sync
# ===========================================================================


class TestValidateStemSync:
    def test_returns_true_when_all_same_length(self):
        from app.services.stem_loader import validate_stem_sync

        stems = {
            "drums": _silent(1000),
            "bass": _silent(1000),
            "melody": _silent(1000),
        }
        assert validate_stem_sync(stems, tolerance_ms=100) is True

    def test_returns_false_when_empty(self):
        from app.services.stem_loader import validate_stem_sync

        assert validate_stem_sync({}) is False

    def test_returns_false_when_difference_exceeds_tolerance(self):
        from app.services.stem_loader import validate_stem_sync

        stems = {
            "drums": _silent(1000),
            "bass": _silent(500),  # 500ms difference → exceeds 100ms tolerance
        }
        assert validate_stem_sync(stems, tolerance_ms=100) is False

    def test_returns_true_when_difference_within_tolerance(self):
        from app.services.stem_loader import validate_stem_sync

        stems = {
            "drums": _silent(1000),
            "bass": _silent(1050),  # only 50ms apart
        }
        assert validate_stem_sync(stems, tolerance_ms=100) is True

    def test_returns_true_for_single_stem(self):
        from app.services.stem_loader import validate_stem_sync

        stems = {"drums": _silent(500)}
        assert validate_stem_sync(stems) is True

    def test_exact_boundary_tolerance(self):
        from app.services.stem_loader import validate_stem_sync

        stems = {
            "drums": _silent(1000),
            "bass": _silent(1100),  # 100ms difference = tolerance
        }
        # 100ms diff is NOT > 100ms, so should return True
        assert validate_stem_sync(stems, tolerance_ms=100) is True

    def test_just_over_boundary(self):
        from app.services.stem_loader import validate_stem_sync

        stems = {
            "drums": _silent(1000),
            "bass": _silent(1101),  # 101ms diff > 100ms tolerance
        }
        assert validate_stem_sync(stems, tolerance_ms=100) is False


# ===========================================================================
# normalize_stem_durations
# ===========================================================================


class TestNormalizeStemDurations:
    def test_returns_empty_dict_unchanged(self):
        from app.services.stem_loader import normalize_stem_durations

        result = normalize_stem_durations({})
        assert result == {}

    def test_trims_longer_stems_to_shortest(self):
        from app.services.stem_loader import normalize_stem_durations

        stems = {
            "drums": _silent(1000),
            "bass": _silent(800),  # shortest
            "melody": _silent(1200),
        }
        result = normalize_stem_durations(stems)
        assert len(result["drums"]) == 800
        assert len(result["bass"]) == 800
        assert len(result["melody"]) == 800

    def test_leaves_same_length_stems_unchanged(self):
        from app.services.stem_loader import normalize_stem_durations

        stems = {
            "drums": _silent(500),
            "bass": _silent(500),
        }
        result = normalize_stem_durations(stems)
        assert len(result["drums"]) == 500
        assert len(result["bass"]) == 500

    def test_single_stem_unchanged(self):
        from app.services.stem_loader import normalize_stem_durations

        stems = {"drums": _silent(750)}
        result = normalize_stem_durations(stems)
        assert len(result["drums"]) == 750

    def test_returns_all_keys(self):
        from app.services.stem_loader import normalize_stem_durations

        stems = {
            "drums": _silent(300),
            "bass": _silent(600),
            "melody": _silent(900),
        }
        result = normalize_stem_durations(stems)
        assert set(result.keys()) == {"drums", "bass", "melody"}


# ===========================================================================
# load_stems_from_metadata
# ===========================================================================


class TestLoadStemsFromMetadata:
    def test_raises_when_metadata_none(self):
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        with pytest.raises(StemLoadError, match="None or empty"):
            load_stems_from_metadata(None)

    def test_raises_when_metadata_empty(self):
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        with pytest.raises(StemLoadError, match="None or empty"):
            load_stems_from_metadata({})

    def test_raises_when_not_enabled(self):
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        with pytest.raises(StemLoadError, match="not enabled"):
            load_stems_from_metadata({"enabled": False, "succeeded": True, "stems": {}})

    def test_raises_when_not_succeeded(self):
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        with pytest.raises(StemLoadError, match="did not succeed"):
            load_stems_from_metadata({"enabled": True, "succeeded": False, "stems": {}})

    def test_raises_when_no_stems_dict(self):
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        with pytest.raises(StemLoadError, match="No stems dict"):
            load_stems_from_metadata({"enabled": True, "succeeded": True, "stems": None})

    def test_raises_when_stems_not_dict(self):
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        with pytest.raises(StemLoadError, match="No stems dict"):
            load_stems_from_metadata({"enabled": True, "succeeded": True, "stems": "not_a_dict"})

    def test_uses_stem_s3_keys_if_present(self):
        """stem_s3_keys takes precedence over stems."""
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        # Both keys present; stem_s3_keys should win; but no actual file → error
        meta = {
            "enabled": True,
            "succeeded": True,
            "stem_s3_keys": {"drums": None},
            "stems": {},
        }
        # stems dict is picked via "stem_s3_keys" key (or "stems" if not present)
        # with a None value, the stem gets skipped; then no stems → raises
        with pytest.raises(StemLoadError):
            load_stems_from_metadata(meta)

    def test_skips_stem_with_no_key(self):
        """A stem entry with a None/falsy value is skipped and logged."""
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        meta = {
            "enabled": True,
            "succeeded": True,
            "stems": {"drums": None, "bass": ""},
        }
        # Both stems have falsy keys → skipped → no stems → StemLoadError
        with pytest.raises(StemLoadError):
            load_stems_from_metadata(meta)

    def test_raises_when_all_stems_fail_to_load(self):
        """All stems error out → StemLoadError."""
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        meta = {
            "enabled": True,
            "succeeded": True,
            "stems": {"drums": "nonexistent_key"},
        }
        # _load_stem_audio_from_storage will fail → StemLoadError
        with pytest.raises(StemLoadError, match="No stems could be loaded"):
            load_stems_from_metadata(meta)

    def test_loads_stems_from_local_storage(self, tmp_path, monkeypatch):
        """Successfully loads a stem from local storage."""
        from app.services import stem_loader
        from app.services.stem_loader import load_stems_from_metadata

        # Create a real WAV file in tmp_path
        seg = _silent(500, sample_rate=44100)
        wav_path = tmp_path / "drums.wav"
        seg.export(str(wav_path), format="wav")

        # Patch storage to be in local mode pointing to tmp_path
        mock_storage = MagicMock()
        mock_storage.use_s3 = False
        mock_storage.upload_dir = tmp_path

        with patch.object(stem_loader, "storage", mock_storage):
            meta = {
                "enabled": True,
                "succeeded": True,
                "stems": {"drums": "subdir/drums.wav"},
            }
            result = load_stems_from_metadata(meta)

        assert "drums" in result
        assert isinstance(result["drums"], AudioSegment)

    def test_raises_stem_load_error_when_local_file_missing(self, tmp_path, monkeypatch):
        """Raises StemLoadError when local stem file does not exist."""
        from app.services import stem_loader
        from app.services.stem_loader import StemLoadError, load_stems_from_metadata

        mock_storage = MagicMock()
        mock_storage.use_s3 = False
        mock_storage.upload_dir = tmp_path

        with patch.object(stem_loader, "storage", mock_storage):
            meta = {
                "enabled": True,
                "succeeded": True,
                "stems": {"drums": "missing_file.wav"},
            }
            with pytest.raises(StemLoadError):
                load_stems_from_metadata(meta)


# ===========================================================================
# map_instruments_to_stems – additional edge-case scenarios
# ===========================================================================


class TestMapInstrumentsToStems:
    def test_empty_instruments_returns_all_stems(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {
            "drums": _silent(500),
            "bass": _silent(500),
        }
        result = map_instruments_to_stems([], available)
        assert set(result.keys()) == {"drums", "bass"}

    def test_exact_match_by_stem_name(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"drums": _silent(500), "bass": _silent(500)}
        result = map_instruments_to_stems(["drums"], available)
        assert "drums" in result

    def test_instrument_alias_resolved(self):
        from app.services.stem_loader import map_instruments_to_stems

        # "kick" should map to "drums" if drums is available
        available = {"drums": _silent(500)}
        result = map_instruments_to_stems(["kick"], available)
        assert "drums" in result

    def test_snare_maps_to_drums(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"drums": _silent(500)}
        result = map_instruments_to_stems(["snare"], available)
        assert "drums" in result

    def test_hats_maps_to_drums(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"drums": _silent(500)}
        result = map_instruments_to_stems(["hats"], available)
        assert "drums" in result

    def test_sub_maps_to_bass(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"bass": _silent(500)}
        result = map_instruments_to_stems(["sub"], available)
        assert "bass" in result

    def test_unavailable_instrument_omitted(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"drums": _silent(500)}
        result = map_instruments_to_stems(["vocals"], available)
        assert result == {}

    def test_full_mix_excluded_when_isolated_stems_present(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {
            "full_mix": _silent(500),
            "drums": _silent(500),
            "bass": _silent(500),
        }
        result = map_instruments_to_stems(["full_mix", "drums", "bass"], available)
        assert "full_mix" not in result
        assert "drums" in result or "bass" in result

    def test_full_mix_used_when_only_stem(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"full_mix": _silent(500)}
        result = map_instruments_to_stems(["full_mix"], available)
        assert "full_mix" in result

    def test_fallback_to_full_mix_when_no_match(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"full_mix": _silent(500)}
        result = map_instruments_to_stems(["totally_unknown_instrument"], available)
        assert "full_mix" in result

    def test_case_insensitive_instrument_matching(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"bass": _silent(500)}
        result = map_instruments_to_stems(["Bass"], available)
        assert "bass" in result

    def test_deduplication_of_same_family_roles(self):
        """drums and percussion are same family; only one should appear."""
        from app.services.stem_loader import map_instruments_to_stems

        available = {
            "drums": _silent(500),
            "percussion": _silent(500),
        }
        result = map_instruments_to_stems(["kick", "snare", "percussion"], available)
        # Should have at most one of drums/percussion (same rhythm family)
        assert len([k for k in result.keys() if k in ("drums", "percussion")]) == 1

    def test_lead_maps_to_melody(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"melody": _silent(500)}
        result = map_instruments_to_stems(["lead"], available)
        assert "melody" in result

    def test_pad_maps_to_pads_or_harmony(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"pads": _silent(500)}
        result = map_instruments_to_stems(["pad"], available)
        assert "pads" in result

    def test_fx_instrument_maps_to_fx_stem(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"fx": _silent(500)}
        result = map_instruments_to_stems(["fx"], available)
        assert "fx" in result

    def test_sfx_maps_to_fx(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"fx": _silent(500)}
        result = map_instruments_to_stems(["sfx"], available)
        assert "fx" in result

    def test_returns_audio_segment_values(self):
        from app.services.stem_loader import map_instruments_to_stems

        available = {"bass": _silent(500)}
        result = map_instruments_to_stems(["bass"], available)
        assert isinstance(result["bass"], AudioSegment)
