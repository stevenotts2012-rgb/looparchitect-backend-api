"""Arrangement strategy — combines genre, vibe, template, and all musical policies.

The ArrangementStrategy is the high-level musical plan that downstream engines
should follow. It is produced by the StrategySelector from the loop analysis,
genre/vibe classification, and template selection outputs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from app.services.template_selector import TemplateDefinition

logger = logging.getLogger(__name__)


@dataclass
class ArrangementStrategy:
    """Complete musical strategy used by the renderer and downstream engines.

    All policy dicts are keyed by section type (e.g. ``"hook"``, ``"verse"``).
    """

    genre: str
    vibe: str
    style_profile: str
    template_id: str
    sections: list[str]
    section_length_policy: dict[str, dict[str, int]]
    energy_curve_policy: dict[str, dict[str, float]]
    density_policy: dict[str, dict[str, float]]
    hook_policy: dict[str, Any]
    bridge_policy: dict[str, Any]
    outro_policy: dict[str, Any]
    motif_reuse_policy: dict[str, Any]
    transition_policy: dict[str, Any]
    variation_seed: int

    def to_dict(self) -> dict[str, Any]:
        """Serialize the strategy to a plain dict."""
        return {
            "genre": self.genre,
            "vibe": self.vibe,
            "style_profile": self.style_profile,
            "template_id": self.template_id,
            "sections": list(self.sections),
            "section_length_policy": dict(self.section_length_policy),
            "energy_curve_policy": dict(self.energy_curve_policy),
            "density_policy": dict(self.density_policy),
            "hook_policy": dict(self.hook_policy),
            "bridge_policy": dict(self.bridge_policy),
            "outro_policy": dict(self.outro_policy),
            "motif_reuse_policy": dict(self.motif_reuse_policy),
            "transition_policy": dict(self.transition_policy),
            "variation_seed": self.variation_seed,
        }


# ---------------------------------------------------------------------------
# Canonical policy sets
# ---------------------------------------------------------------------------

_TRAP_DARK_SECTION_LENGTH: dict[str, dict[str, int]] = {
    "intro":    {"min_bars": 4, "max_bars": 8,  "default_bars": 4},
    "verse":    {"min_bars": 16, "max_bars": 16, "default_bars": 16},
    "pre_hook": {"min_bars": 4, "max_bars": 8,  "default_bars": 4},
    "hook":     {"min_bars": 8, "max_bars": 16, "default_bars": 16},
    "outro":    {"min_bars": 4, "max_bars": 8,  "default_bars": 4},
}

_TRAP_DARK_ENERGY_CURVE: dict[str, dict[str, float]] = {
    "intro":    {"target": 0.2,  "allowance": 0.1},
    "verse":    {"target": 0.6,  "allowance": 0.15},
    "pre_hook": {"target": 0.75, "allowance": 0.1},
    "hook":     {"target": 1.0,  "allowance": 0.1},
    "outro":    {"target": 0.25, "allowance": 0.1},
}

_TRAP_DARK_DENSITY: dict[str, dict[str, float]] = {
    "intro":    {"target": 0.3,  "cap": 0.4},
    "verse":    {"target": 0.5,  "cap": 0.65},
    "pre_hook": {"target": 0.45, "cap": 0.6},
    "hook":     {"target": 0.85, "cap": 1.0},
    "outro":    {"target": 0.25, "cap": 0.4},
}

_TRAP_DARK_HOOK_POLICY: dict[str, Any] = {
    "payoff_level": "full",
    "reentry_style": "accent",
    "escalation": True,
}

_TRAP_DARK_BRIDGE_POLICY: dict[str, Any] = {
    "reset": True,
    "sparse": True,
}

_TRAP_DARK_OUTRO_POLICY: dict[str, Any] = {
    "resolve": True,
    "strip_808": True,
    "reduce_drums": True,
}

_TRAP_DARK_MOTIF_REUSE: dict[str, Any] = {
    "intensity": "strong_in_hook",
    "transformations": ["inversion", "fragmentation"],
}

_TRAP_DARK_TRANSITION: dict[str, Any] = {
    "aggression": 0.7,
}


def _default_section_length() -> dict[str, dict[str, int]]:
    return {
        "intro":    {"min_bars": 4, "max_bars": 8,  "default_bars": 4},
        "verse":    {"min_bars": 8, "max_bars": 16, "default_bars": 8},
        "pre_hook": {"min_bars": 4, "max_bars": 8,  "default_bars": 4},
        "hook":     {"min_bars": 8, "max_bars": 16, "default_bars": 8},
        "outro":    {"min_bars": 4, "max_bars": 8,  "default_bars": 4},
    }


def _default_energy_curve() -> dict[str, dict[str, float]]:
    return {
        "intro":    {"target": 0.3,  "allowance": 0.15},
        "verse":    {"target": 0.55, "allowance": 0.15},
        "pre_hook": {"target": 0.65, "allowance": 0.1},
        "hook":     {"target": 0.85, "allowance": 0.1},
        "outro":    {"target": 0.3,  "allowance": 0.15},
    }


def _default_density() -> dict[str, dict[str, float]]:
    return {
        "intro":    {"target": 0.3,  "cap": 0.5},
        "verse":    {"target": 0.5,  "cap": 0.7},
        "pre_hook": {"target": 0.5,  "cap": 0.65},
        "hook":     {"target": 0.75, "cap": 0.95},
        "outro":    {"target": 0.3,  "cap": 0.5},
    }


class StrategySelector:
    """Builds an :class:`ArrangementStrategy` from classification + template outputs."""

    def select(
        self,
        analysis: dict[str, Any],
        classification: dict[str, Any],
        template: "TemplateDefinition",
        variation_seed: int = 0,
    ) -> ArrangementStrategy:
        """Build the strategy for the given genre/vibe/template combination.

        Parameters
        ----------
        analysis:       Loop analysis dict (same format as GenreVibeClassifier input).
        classification: Output of GenreVibeClassifier.classify().
        template:       Selected TemplateDefinition.
        variation_seed: Deterministic seed for any seed-dependent policy choices.

        Returns
        -------
        ArrangementStrategy
        """
        genre = str(classification.get("selected_genre") or "generic")
        vibe = str(classification.get("selected_vibe") or "dark")
        style_profile = str(classification.get("style_profile") or f"{genre}_{vibe}_balanced")

        if genre == "trap" and vibe == "dark":
            return ArrangementStrategy(
                genre=genre,
                vibe=vibe,
                style_profile=style_profile,
                template_id=template.template_id,
                sections=list(template.sections),
                section_length_policy=dict(_TRAP_DARK_SECTION_LENGTH),
                energy_curve_policy=dict(_TRAP_DARK_ENERGY_CURVE),
                density_policy=dict(_TRAP_DARK_DENSITY),
                hook_policy=dict(_TRAP_DARK_HOOK_POLICY),
                bridge_policy=dict(_TRAP_DARK_BRIDGE_POLICY),
                outro_policy=dict(_TRAP_DARK_OUTRO_POLICY),
                motif_reuse_policy=dict(_TRAP_DARK_MOTIF_REUSE),
                transition_policy=dict(_TRAP_DARK_TRANSITION),
                variation_seed=variation_seed,
            )

        # Generic/fallback strategy for all other genre+vibe combinations
        return ArrangementStrategy(
            genre=genre,
            vibe=vibe,
            style_profile=style_profile,
            template_id=template.template_id,
            sections=list(template.sections),
            section_length_policy=_default_section_length(),
            energy_curve_policy=_default_energy_curve(),
            density_policy=_default_density(),
            hook_policy={
                "payoff_level": "medium",
                "reentry_style": "smooth",
                "escalation": False,
            },
            bridge_policy={"reset": True, "sparse": False},
            outro_policy={"resolve": True, "strip_808": False, "reduce_drums": True},
            motif_reuse_policy={
                "intensity": "moderate",
                "transformations": ["fragmentation"],
            },
            transition_policy={"aggression": 0.4},
            variation_seed=variation_seed,
        )
