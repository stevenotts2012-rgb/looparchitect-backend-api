"""Tests for GenreVibeClassifier (app/services/genre_vibe_classifier.py)."""

from __future__ import annotations

import pytest

from app.services.genre_vibe_classifier import GenreVibeClassifier


@pytest.fixture
def clf():
    return GenreVibeClassifier()


def test_trap_classification_from_bpm(clf):
    """BPM 140 + '808' tag → genre=trap."""
    result = clf.classify({"bpm": 140, "instrument_tags": ["808", "hi-hat"]})
    assert result["selected_genre"] == "trap"


def test_drill_classification_from_tags(clf):
    """BPM 140 + 'drill' tag → genre=drill."""
    result = clf.classify({"bpm": 140, "instrument_tags": ["drill", "slide"]})
    assert result["selected_genre"] == "drill"


def test_dark_vibe_from_energy(clf):
    """energy=0.3 → vibe=dark."""
    result = clf.classify({"energy": 0.3, "bpm": 140, "instrument_tags": ["808"]})
    assert result["selected_vibe"] == "dark"


def test_hype_vibe_from_energy(clf):
    """energy=0.9 → vibe=hype."""
    result = clf.classify({"bpm": 140, "energy": 0.9, "instrument_tags": ["808"]})
    assert result["selected_vibe"] == "hype"


def test_genre_hint_override(clf):
    """genre_hint='rnb' → genre=rnb, confidence=0.9."""
    result = clf.classify({"bpm": 140, "genre_hint": "rnb", "instrument_tags": ["808"]})
    assert result["selected_genre"] == "rnb"
    assert result["genre_confidence"] == 0.9


def test_style_profile_format(clf):
    """style_profile should be '{genre}_{vibe}_...'."""
    result = clf.classify({"bpm": 140, "instrument_tags": ["808"], "energy": 0.4})
    profile = result["style_profile"]
    parts = profile.split("_")
    assert len(parts) >= 3
    assert parts[0] == result["selected_genre"]
    assert parts[1] == result["selected_vibe"]


def test_confidence_capped(clf):
    """Confidence values must never exceed 0.95."""
    result = clf.classify({
        "bpm": 140,
        "instrument_tags": ["808"],
        "inferred_genre_probs": {"trap": 1.0},
        "inferred_vibe_probs": {"dark": 1.0},
    })
    assert result["genre_confidence"] <= 0.95
    assert result["vibe_confidence"] <= 0.95


def test_default_genre_fallback(clf):
    """Empty analysis → genre=trap (default)."""
    result = clf.classify({})
    assert result["selected_genre"] == "trap"


def test_emotional_vibe_from_tags(clf):
    """instrument_tags=['piano', 'sad'] → vibe=emotional."""
    result = clf.classify({
        "bpm": 140,
        "instrument_tags": ["piano", "sad"],
        "energy": 0.6,
        "loop_density": 0.5,
    })
    assert result["selected_vibe"] == "emotional"


def test_ambient_vibe_from_density(clf):
    """loop_density=0.2 → vibe=ambient (when energy is not low enough for dark)."""
    result = clf.classify({
        "bpm": 140,
        "instrument_tags": ["808"],
        "energy": 0.6,
        "loop_density": 0.2,
    })
    assert result["selected_vibe"] == "ambient"
