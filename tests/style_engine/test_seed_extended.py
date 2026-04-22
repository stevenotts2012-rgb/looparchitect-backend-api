"""Extended tests for app/style_engine/seed.py — covering uncovered branches."""

import pytest

from app.style_engine.seed import choice_weighted, create_rng, normalize_seed


# ===========================================================================
# normalize_seed — uncovered branches
# ===========================================================================


class TestNormalizeSeedExtended:
    def test_none_seed_returns_non_negative_int(self):
        """normalize_seed(None) must return a non-negative integer."""
        result = normalize_seed(None)
        assert isinstance(result, int)
        assert 0 <= result <= 2**31 - 1

    def test_none_seed_is_non_deterministic(self):
        """Two calls with None should typically return different values (randomised)."""
        results = {normalize_seed(None) for _ in range(20)}
        # Very unlikely all 20 random seeds are identical
        assert len(results) > 1

    def test_string_seed_returns_int(self):
        result = normalize_seed("hello-world")
        assert isinstance(result, int)

    def test_string_seed_is_deterministic(self):
        assert normalize_seed("same-string") == normalize_seed("same-string")

    def test_different_strings_give_different_seeds(self):
        assert normalize_seed("alpha") != normalize_seed("beta")

    def test_int_seed_masks_to_31_bits(self):
        big = 2**32 - 1  # 0xFFFFFFFF
        result = normalize_seed(big)
        assert result == big & 0x7FFFFFFF

    def test_negative_int_masked(self):
        """Negative integers are bit-masked; result must be non-negative."""
        result = normalize_seed(-1)
        assert result >= 0

    def test_zero_int_seed(self):
        assert normalize_seed(0) == 0


# ===========================================================================
# create_rng — extended
# ===========================================================================


class TestCreateRngExtended:
    def test_returns_tuple_of_int_and_random(self):
        import random
        seed_val, rng = create_rng(99)
        assert isinstance(seed_val, int)
        assert isinstance(rng, random.Random)

    def test_none_seed_creates_valid_rng(self):
        seed_val, rng = create_rng(None)
        assert isinstance(seed_val, int)
        # Should be able to generate numbers without error
        assert isinstance(rng.randint(0, 100), int)

    def test_string_seed_creates_valid_rng(self):
        seed_val, rng = create_rng("deterministic")
        assert isinstance(seed_val, int)
        num = rng.random()
        assert 0.0 <= num < 1.0

    def test_rng_sequence_matches_seed(self):
        """The RNG sequence from create_rng must match manual Random(seed)."""
        import random
        seed_val, rng = create_rng(12345)
        ref = random.Random(seed_val)
        for _ in range(10):
            assert rng.random() == ref.random()


# ===========================================================================
# choice_weighted
# ===========================================================================


class TestChoiceWeighted:
    def _rng(self, seed: int = 0) -> object:
        import random
        return random.Random(seed)

    def test_returns_item_from_options(self):
        options = ["a", "b", "c"]
        weights = [1.0, 1.0, 1.0]
        result = choice_weighted(self._rng(), options, weights)
        assert result in options

    def test_empty_options_raises_value_error(self):
        with pytest.raises(ValueError):
            choice_weighted(self._rng(), [], [])

    def test_mismatched_lengths_raises_value_error(self):
        with pytest.raises(ValueError):
            choice_weighted(self._rng(), ["a", "b"], [1.0])

    def test_zero_total_weight_raises_value_error(self):
        with pytest.raises(ValueError):
            choice_weighted(self._rng(), ["a", "b"], [0.0, 0.0])

    def test_negative_total_weight_raises_value_error(self):
        with pytest.raises(ValueError):
            choice_weighted(self._rng(), ["a"], [-1.0])

    def test_single_option_always_returned(self):
        import random
        for seed in range(10):
            result = choice_weighted(random.Random(seed), ["only"], [1.0])
            assert result == "only"

    def test_biased_weights_favour_heavy_option(self):
        """With heavily biased weights, the heavier option should dominate."""
        import random
        options = ["rare", "common"]
        weights = [0.01, 99.99]
        counts = {"rare": 0, "common": 0}
        for i in range(200):
            chosen = choice_weighted(random.Random(i), options, weights)
            counts[chosen] += 1
        assert counts["common"] > counts["rare"] * 5

    def test_deterministic_with_same_seed(self):
        import random
        options = ["x", "y", "z"]
        weights = [1.0, 2.0, 3.0]
        result_a = choice_weighted(random.Random(7), options, weights)
        result_b = choice_weighted(random.Random(7), options, weights)
        assert result_a == result_b

    def test_works_with_non_float_weights(self):
        """Integer weights should also be accepted (summed as numeric)."""
        import random
        result = choice_weighted(random.Random(0), [1, 2, 3], [1, 2, 3])
        assert result in [1, 2, 3]
