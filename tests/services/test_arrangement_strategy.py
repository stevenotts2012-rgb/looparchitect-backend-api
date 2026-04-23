"""Tests for StrategySelector / ArrangementStrategy (app/services/arrangement_strategy.py)."""

from __future__ import annotations

import pytest

from app.services.arrangement_strategy import StrategySelector, ArrangementStrategy
from app.services.template_selector import TemplateSelector


def _make_trap_dark_strategy() -> ArrangementStrategy:
    classification = {
        "selected_genre": "trap",
        "selected_vibe": "dark",
        "style_profile": "trap_dark_balanced",
        "genre_confidence": 0.85,
        "vibe_confidence": 0.80,
    }
    sel = TemplateSelector()
    template = sel.select("trap", "dark", 0.6, 0.5, 0.5)
    return StrategySelector().select(
        analysis={"bpm": 140, "energy": 0.6},
        classification=classification,
        template=template,
        variation_seed=0,
    )


def test_trap_dark_strategy_sections():
    """trap+dark strategy sections should include 'hook'."""
    strategy = _make_trap_dark_strategy()
    assert "hook" in strategy.sections


def test_trap_dark_hook_policy_payoff():
    """hook_policy.payoff_level should be 'full' for trap+dark."""
    strategy = _make_trap_dark_strategy()
    assert strategy.hook_policy["payoff_level"] == "full"


def test_trap_dark_outro_policy_strip_808():
    """outro_policy.strip_808 should be True for trap+dark."""
    strategy = _make_trap_dark_strategy()
    assert strategy.outro_policy["strip_808"] is True


def test_trap_dark_energy_curve():
    """hook target energy should be >= 0.9 for trap+dark."""
    strategy = _make_trap_dark_strategy()
    hook_energy = strategy.energy_curve_policy["hook"]["target"]
    assert hook_energy >= 0.9


def test_trap_dark_intro_energy_low():
    """intro energy target should be < 0.3 for trap+dark."""
    strategy = _make_trap_dark_strategy()
    intro_energy = strategy.energy_curve_policy["intro"]["target"]
    assert intro_energy < 0.3


def test_serialization():
    """to_dict() returns a dict with all required keys."""
    strategy = _make_trap_dark_strategy()
    d = strategy.to_dict()
    assert isinstance(d, dict)
    for key in (
        "genre", "vibe", "style_profile", "template_id", "sections",
        "section_length_policy", "energy_curve_policy", "density_policy",
        "hook_policy", "bridge_policy", "outro_policy", "motif_reuse_policy",
        "transition_policy", "variation_seed",
    ):
        assert key in d, f"Missing key: {key}"


def test_strategy_deterministic():
    """Same inputs → same strategy."""
    s1 = _make_trap_dark_strategy()
    s2 = _make_trap_dark_strategy()
    assert s1.to_dict() == s2.to_dict()
