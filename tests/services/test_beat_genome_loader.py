"""Unit tests for BeatGenomeLoader."""

from __future__ import annotations

import json
import pytest
from pathlib import Path

from app.services.beat_genome_loader import BeatGenomeLoader, load_beat_genome


# ---------------------------------------------------------------------------
# list_available()
# ---------------------------------------------------------------------------


class TestBeatGenomeLoaderListAvailable:
    def test_returns_list(self):
        genomes = BeatGenomeLoader.list_available()
        assert isinstance(genomes, list)

    def test_list_is_sorted(self):
        genomes = BeatGenomeLoader.list_available()
        assert genomes == sorted(genomes)

    def test_known_genomes_present(self):
        genomes = BeatGenomeLoader.list_available()
        # At least one genome should exist in the repo
        assert len(genomes) > 0

    def test_no_json_extension_in_names(self):
        genomes = BeatGenomeLoader.list_available()
        for genome in genomes:
            assert not genome.endswith(".json"), f"Expected stem, got: {genome}"


# ---------------------------------------------------------------------------
# load()
# ---------------------------------------------------------------------------


class TestBeatGenomeLoaderLoad:
    def setup_method(self):
        """Clear cache before each test so we get clean state."""
        BeatGenomeLoader.reload_cache()

    def test_load_known_genome(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available in config/genomes/")
        name = available[0]
        # Split into genre (and optional mood)
        parts = name.split("_", 1)
        genre = parts[0]
        mood = parts[1] if len(parts) == 2 else None
        genome = BeatGenomeLoader.load(genre, mood)
        assert isinstance(genome, dict)

    def test_load_returns_dict_with_data(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available")
        name = available[0]
        parts = name.split("_", 1)
        genome = BeatGenomeLoader.load(parts[0], parts[1] if len(parts) == 2 else None)
        assert len(genome) > 0

    def test_load_unknown_genre_raises_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            BeatGenomeLoader.load("xyzzy_unknown_genre_that_wont_exist_ever")

    def test_load_caches_result(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available")
        name = available[0]
        parts = name.split("_", 1)
        genre = parts[0]
        mood = parts[1] if len(parts) == 2 else None

        genome1 = BeatGenomeLoader.load(genre, mood)
        genome2 = BeatGenomeLoader.load(genre, mood)
        assert genome1 is genome2  # Same object from cache

    def test_load_error_message_lists_available(self):
        with pytest.raises(FileNotFoundError) as exc_info:
            BeatGenomeLoader.load("zzz_nonexistent")
        # Error message should mention available genomes
        assert "available" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# get_genre_default()
# ---------------------------------------------------------------------------


class TestBeatGenomeLoaderGetGenreDefault:
    def setup_method(self):
        BeatGenomeLoader.reload_cache()

    def test_get_default_for_existing_genre(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available")
        # Use the genre part of the first available genome
        genre = available[0].split("_")[0]
        genome = BeatGenomeLoader.get_genre_default(genre)
        assert isinstance(genome, dict)

    def test_get_default_for_nonexistent_genre_raises(self):
        with pytest.raises(FileNotFoundError):
            BeatGenomeLoader.get_genre_default("zzz_genre_that_cannot_exist")


# ---------------------------------------------------------------------------
# validate()
# ---------------------------------------------------------------------------


class TestBeatGenomeLoaderValidate:
    def test_valid_genome_passes(self):
        genome = {
            "name": "Test Trap Dark",
            "genre": "trap",
            "section_lengths": {"intro": 8, "verse": 16, "hook": 8},
            "energy_curve": [
                {"section": "intro", "energy": 0.3},
                {"section": "verse", "energy": 0.6},
                {"section": "hook", "energy": 0.9},
            ],
            "instrument_layers": {
                "intro": ["kick", "hats"],
                "verse": ["kick", "snare", "bass"],
            },
        }
        is_valid, errors = BeatGenomeLoader.validate(genome)
        assert is_valid is True
        assert errors == []

    def test_missing_required_field_fails(self):
        genome = {
            # Missing "name", "section_lengths", "energy_curve", "instrument_layers"
            "genre": "trap",
        }
        is_valid, errors = BeatGenomeLoader.validate(genome)
        assert is_valid is False
        assert any("missing required field" in e.lower() for e in errors)

    def test_invalid_section_length_fails(self):
        genome = {
            "name": "Bad Genome",
            "genre": "trap",
            "section_lengths": {"intro": -1},  # negative bars
            "energy_curve": [{"section": "intro", "energy": 0.5}],
            "instrument_layers": {},
        }
        is_valid, errors = BeatGenomeLoader.validate(genome)
        assert is_valid is False

    def test_energy_value_out_of_range_fails(self):
        genome = {
            "name": "Bad Energy",
            "genre": "trap",
            "section_lengths": {"intro": 8},
            "energy_curve": [{"section": "intro", "energy": 1.5}],  # > 1.0
            "instrument_layers": {},
        }
        is_valid, errors = BeatGenomeLoader.validate(genome)
        assert is_valid is False
        assert any("energy" in e.lower() for e in errors)

    def test_negative_energy_fails(self):
        genome = {
            "name": "Negative Energy",
            "genre": "trap",
            "section_lengths": {"intro": 8},
            "energy_curve": [{"section": "intro", "energy": -0.1}],
            "instrument_layers": {},
        }
        is_valid, errors = BeatGenomeLoader.validate(genome)
        assert is_valid is False

    def test_energy_curve_missing_keys_fails(self):
        genome = {
            "name": "Missing Keys",
            "genre": "trap",
            "section_lengths": {"intro": 8},
            "energy_curve": [{"section": "intro"}],  # missing "energy"
            "instrument_layers": {},
        }
        is_valid, errors = BeatGenomeLoader.validate(genome)
        assert is_valid is False

    def test_instrument_layers_not_dict_fails(self):
        genome = {
            "name": "Wrong Layers",
            "genre": "trap",
            "section_lengths": {"intro": 8},
            "energy_curve": [{"section": "intro", "energy": 0.5}],
            "instrument_layers": ["kick", "snare"],  # should be a dict
        }
        is_valid, errors = BeatGenomeLoader.validate(genome)
        assert is_valid is False

    def test_returns_tuple_of_bool_and_list(self):
        result = BeatGenomeLoader.validate({})
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], bool)
        assert isinstance(result[1], list)


# ---------------------------------------------------------------------------
# reload_cache() and get_cache_stats()
# ---------------------------------------------------------------------------


class TestBeatGenomeLoaderCache:
    def test_reload_cache_clears(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available")
        name = available[0]
        parts = name.split("_", 1)
        genre = parts[0]
        mood = parts[1] if len(parts) == 2 else None

        BeatGenomeLoader.load(genre, mood)
        assert BeatGenomeLoader.get_cache_stats()["cached_genomes"] > 0

        BeatGenomeLoader.reload_cache()
        assert BeatGenomeLoader.get_cache_stats()["cached_genomes"] == 0

    def test_get_cache_stats_structure(self):
        BeatGenomeLoader.reload_cache()
        stats = BeatGenomeLoader.get_cache_stats()
        assert "cached_genomes" in stats
        assert "cache_keys" in stats
        assert isinstance(stats["cached_genomes"], int)
        assert isinstance(stats["cache_keys"], list)

    def test_cache_grows_after_load(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available")

        BeatGenomeLoader.reload_cache()
        initial = BeatGenomeLoader.get_cache_stats()["cached_genomes"]

        name = available[0]
        parts = name.split("_", 1)
        BeatGenomeLoader.load(parts[0], parts[1] if len(parts) == 2 else None)

        assert BeatGenomeLoader.get_cache_stats()["cached_genomes"] == initial + 1


# ---------------------------------------------------------------------------
# load_beat_genome() convenience function
# ---------------------------------------------------------------------------


class TestLoadBeatGenomeConvenienceWrapper:
    def setup_method(self):
        BeatGenomeLoader.reload_cache()

    def test_wrapper_delegates_to_loader(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available")
        name = available[0]
        parts = name.split("_", 1)
        genre = parts[0]
        mood = parts[1] if len(parts) == 2 else None

        genome_via_class = BeatGenomeLoader.load(genre, mood)
        BeatGenomeLoader.reload_cache()
        genome_via_fn = load_beat_genome(genre, mood)

        assert genome_via_class == genome_via_fn


# ---------------------------------------------------------------------------
# Validate all real genome files
# ---------------------------------------------------------------------------


class TestRealGenomesValidate:
    """Validate that every genome file in config/genomes/ passes schema validation."""

    def test_all_genomes_are_valid(self):
        available = BeatGenomeLoader.list_available()
        if not available:
            pytest.skip("No genomes available")

        BeatGenomeLoader.reload_cache()
        for name in available:
            parts = name.split("_", 1)
            genre = parts[0]
            mood = parts[1] if len(parts) == 2 else None
            genome = BeatGenomeLoader.load(genre, mood)
            is_valid, errors = BeatGenomeLoader.validate(genome)
            assert is_valid, f"Genome '{name}' failed validation: {errors}"
