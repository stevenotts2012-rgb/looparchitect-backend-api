"""Tests for style validation service (app/services/style_validation.py)."""

import pytest

from app.services.style_validation import StyleValidationService


@pytest.fixture
def svc():
    return StyleValidationService()


# ---------------------------------------------------------------------------
# Happy-path validation
# ---------------------------------------------------------------------------

def test_valid_minimal_profile(svc):
    profile = {"intent": "dark trap beat", "energy": 0.8, "darkness": 0.9,
                "bounce": 0.5, "warmth": 0.3, "texture": "gritty"}
    normalized, warnings = svc.validate_and_normalize(profile)
    assert normalized["intent"] == "dark trap beat"
    assert normalized["texture"] == "gritty"
    assert warnings == []


def test_valid_profile_with_all_fields(svc):
    profile = {
        "intent": "chill lofi study beat",
        "energy": 0.3,
        "darkness": 0.2,
        "bounce": 0.6,
        "warmth": 0.8,
        "texture": "smooth",
        "references": ["Nujabes", "J Dilla"],
        "avoid": ["harsh clipping"],
        "seed": 7,
        "confidence": 0.95,
    }
    normalized, warnings = svc.validate_and_normalize(profile)
    assert normalized["energy"] == 0.3
    assert normalized["warmth"] == 0.8
    assert normalized["references"] == ["Nujabes", "J Dilla"]
    assert normalized["seed"] == 7
    assert warnings == []


def test_normalization_rounds_float_values(svc):
    profile = {"intent": "test", "energy": 0.123456, "darkness": 0.678901,
                "bounce": 0.5, "warmth": 0.5}
    normalized, _ = svc.validate_and_normalize(profile)
    # Should be rounded to 2 decimal places
    assert normalized["energy"] == round(0.123456, 2)
    assert normalized["darkness"] == round(0.678901, 2)


def test_default_values_are_applied(svc):
    # Minimal profile – missing optional sliders should use defaults
    profile = {"intent": "test beat"}
    normalized, warnings = svc.validate_and_normalize(profile)
    assert normalized["energy"] == 0.5
    assert normalized["darkness"] == 0.5
    assert normalized["bounce"] == 0.5
    assert normalized["warmth"] == 0.5
    assert normalized["texture"] == "balanced"
    assert normalized["seed"] == 42
    assert normalized["confidence"] == 0.8


# ---------------------------------------------------------------------------
# Validation errors (ValueError expected)
# ---------------------------------------------------------------------------

def test_missing_intent_raises(svc):
    with pytest.raises(ValueError, match="intent"):
        svc.validate_and_normalize({})


def test_empty_intent_raises(svc):
    with pytest.raises(ValueError, match="intent"):
        svc.validate_and_normalize({"intent": "   "})


def test_intent_too_long_raises(svc):
    with pytest.raises(ValueError):
        svc.validate_and_normalize({"intent": "x" * 501})


def test_energy_out_of_range_raises(svc):
    with pytest.raises(ValueError, match="energy"):
        svc.validate_and_normalize({"intent": "test", "energy": 1.5})


def test_darkness_out_of_range_raises(svc):
    with pytest.raises(ValueError, match="darkness"):
        svc.validate_and_normalize({"intent": "test", "darkness": -0.1})


def test_bounce_out_of_range_raises(svc):
    with pytest.raises(ValueError, match="bounce"):
        svc.validate_and_normalize({"intent": "test", "bounce": 2.0})


def test_warmth_out_of_range_raises(svc):
    with pytest.raises(ValueError, match="warmth"):
        svc.validate_and_normalize({"intent": "test", "warmth": -1})


def test_invalid_texture_raises(svc):
    with pytest.raises(ValueError, match="texture"):
        svc.validate_and_normalize({"intent": "test", "texture": "rough"})


def test_references_not_list_raises(svc):
    with pytest.raises(ValueError, match="references"):
        svc.validate_and_normalize({"intent": "test", "references": "Nujabes"})


def test_avoid_not_list_raises(svc):
    with pytest.raises(ValueError, match="avoid"):
        svc.validate_and_normalize({"intent": "test", "avoid": "clipping"})


# ---------------------------------------------------------------------------
# Warning cases
# ---------------------------------------------------------------------------

def test_too_many_references_produces_warning_and_truncates(svc):
    refs = [f"artist_{i}" for i in range(12)]
    normalized, warnings = svc.validate_and_normalize({"intent": "test", "references": refs})
    assert len(normalized["references"]) == 10
    assert any("reference" in w.lower() for w in warnings)


def test_too_many_avoid_items_produces_warning_and_truncates(svc):
    avoids = [f"avoid_{i}" for i in range(11)]
    normalized, warnings = svc.validate_and_normalize({"intent": "test", "avoid": avoids})
    assert len(normalized["avoid"]) == 10
    assert any("avoid" in w.lower() for w in warnings)


def test_negative_seed_produces_warning_and_is_made_positive(svc):
    normalized, warnings = svc.validate_and_normalize({"intent": "test", "seed": -5})
    assert normalized["seed"] == 5
    assert any("seed" in w.lower() for w in warnings)


def test_out_of_range_confidence_is_clamped_with_warning(svc):
    normalized, warnings = svc.validate_and_normalize({"intent": "test", "confidence": 1.5})
    assert 0 <= normalized["confidence"] <= 1
    assert any("confidence" in w.lower() for w in warnings)


# ---------------------------------------------------------------------------
# Texture case normalization
# ---------------------------------------------------------------------------

def test_texture_is_lowercased(svc):
    normalized, _ = svc.validate_and_normalize({"intent": "test", "texture": "SMOOTH"})
    assert normalized["texture"] == "smooth"
