"""Tests for TemplateSelector (app/services/template_selector.py)."""

from __future__ import annotations

import pytest

from app.services.template_selector import TemplateSelector


@pytest.fixture
def sel():
    return TemplateSelector()


def test_trap_default_template(sel):
    """trap + moderate energy/richness/density → trap_A."""
    tmpl = sel.select("trap", "dark", 0.5, 0.5, 0.5)
    assert tmpl.template_id == "trap_A"


def test_trap_melodic_richness_prefers_trap_C(sel):
    """melodic_richness=0.8 → trap_C."""
    tmpl = sel.select("trap", "dark", 0.5, 0.8, 0.5)
    assert tmpl.template_id == "trap_C"


def test_trap_high_energy_prefers_trap_B(sel):
    """energy=0.8, richness<0.6 → trap_B."""
    tmpl = sel.select("trap", "dark", 0.8, 0.3, 0.5)
    assert tmpl.template_id == "trap_B"


def test_trap_low_density_prefers_trap_D(sel):
    """loop_density=0.2 → trap_D."""
    tmpl = sel.select("trap", "dark", 0.5, 0.5, 0.2)
    assert tmpl.template_id == "trap_D"


def test_user_override_trap_C(sel):
    """user_override='trap_C' → template_id=trap_C regardless of other params."""
    tmpl = sel.select("trap", "dark", 0.1, 0.1, 0.1, user_override="trap_C")
    assert tmpl.template_id == "trap_C"


def test_unknown_override_falls_back(sel):
    """user_override='nonexistent_template' → normal trap selection (fallback invoked)."""
    tmpl_no_override = sel.select("trap", "dark", 0.5, 0.5, 0.5)
    tmpl_bad_override = sel.select("trap", "dark", 0.5, 0.5, 0.5, user_override="nonexistent_template")
    # Both should produce the same result — the bad override is ignored and normal selection runs
    assert tmpl_bad_override.template_id == tmpl_no_override.template_id
    # Result must still be a valid trap template
    assert tmpl_bad_override.template_id in {"trap_A", "trap_B", "trap_C", "trap_D"}


def test_all_templates_returns_list(sel):
    """all_templates() returns a non-empty list of TemplateDefinitions."""
    templates = sel.all_templates()
    assert isinstance(templates, list)
    assert len(templates) > 0
    ids = [t.template_id for t in templates]
    assert "trap_A" in ids
    assert "trap_C" in ids


def test_deterministic_seed(sel):
    """Same inputs + same seed → same template."""
    t1 = sel.select("trap", "dark", 0.8, 0.8, 0.5, variation_seed=42)
    t2 = sel.select("trap", "dark", 0.8, 0.8, 0.5, variation_seed=42)
    assert t1.template_id == t2.template_id


def test_different_seed_may_differ(sel):
    """With multiple candidates, different seeds produce different templates."""
    # melodic_richness > 0.6 → trap_C, loop_density < 0.35 → trap_D: two candidates
    # seed 0 → candidates[0 % 2] = trap_C, seed 1 → candidates[1 % 2] = trap_D
    t0 = sel.select("trap", "dark", 0.5, 0.8, 0.2, variation_seed=0)
    t1 = sel.select("trap", "dark", 0.5, 0.8, 0.2, variation_seed=1)
    # With two candidates, seeds 0 and 1 must produce different results
    assert t0.template_id != t1.template_id


def test_drill_gets_valid_template(sel):
    """drill genre → returns a valid template."""
    tmpl = sel.select("drill", "dark", 0.6, 0.5, 0.5)
    assert tmpl.genre == "drill"
    assert len(tmpl.sections) > 0
