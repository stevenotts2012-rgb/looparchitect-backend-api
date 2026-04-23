"""
Instrument Activation Rules Engine.

Loads the centralized JSON ruleset that controls which instruments play,
how dense they are, and how musical behavior evolves per section.

The ruleset is the authoritative "musical brain" of LoopArchitect:
- Templates define structure
- Rules define behavior (this module)
- Strategy defines intent
- Resolved Plan defines execution
- Renderer produces sound

Usage::

    engine = InstrumentActivationRules()
    rules = engine.get_rules_for_section("hook")
    modified = engine.apply_genre_vibe_modifiers(rules, genre="trap", vibe="hype")
    modified = engine.apply_variation_seed(modified, seed=42)

``get_rules_for_section`` returns a dict with per-role rules::

    {
      "roles": {
        "drums":      {"active": True, "density": 1.0, "complexity": 0.85, ...},
        "bass":       {"active": True, "density": 0.9, ...},
        "melody":     {"active": True, "density": 0.85, ...},
        ...
      },
      "section_type": "hook",
    }

Section name normalisation:
    PRE_CHORUS  → PRE_HOOK
    CHORUS      → HOOK
    BUILDUP     → PRE_HOOK
    BREAKDOWN   → BRIDGE
"""

from __future__ import annotations

import copy
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

RULE_SET_VERSION = "1.0.0"

# Required section types that must be present in the ruleset.
_REQUIRED_SECTIONS: frozenset[str] = frozenset({
    "INTRO", "VERSE", "PRE_HOOK", "HOOK", "BRIDGE", "OUTRO",
})

# Required per-role fields.
_REQUIRED_ROLE_FIELDS: frozenset[str] = frozenset({"active"})

# Roles that carry density/complexity and therefore must be validated.
_DENSITY_ROLES: frozenset[str] = frozenset({
    "melody", "arp", "chords", "bass", "drums", "percussion", "fx",
})

# Canonical section name normalisation map.
_SECTION_NORMALISE: Dict[str, str] = {
    # Input variant → canonical JSON key (upper-case, underscore)
    "pre_chorus":  "PRE_HOOK",
    "prechorus":   "PRE_HOOK",
    "pre-chorus":  "PRE_HOOK",
    "pre_hook":    "PRE_HOOK",
    "chorus":      "HOOK",
    "drop":        "HOOK",
    "hook":        "HOOK",
    "buildup":     "PRE_HOOK",
    "build_up":    "PRE_HOOK",
    "build":       "PRE_HOOK",
    "intro":       "INTRO",
    "verse":       "VERSE",
    "bridge":      "BRIDGE",
    "breakdown":   "BRIDGE",
    "outro":       "OUTRO",
}

# Path to the bundled JSON ruleset.
_RULES_JSON_PATH: Path = Path(__file__).parent / "data" / "instrument_activation_rules.json"

# Density variation range applied by variation_seed (safe ±0.1).
_VARIATION_DENSITY_DELTA: float = 0.1


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


class InstrumentActivationRules:
    """Centralized Instrument Activation Rules engine.

    Loads and validates the JSON ruleset on first construction.  All public
    methods return *copies* of the internal rule data — callers may mutate
    the returned dicts freely.

    The engine is designed to be instantiated once and reused across requests.
    """

    def __init__(self, rules_path: Optional[Path] = None) -> None:
        self._path = rules_path or _RULES_JSON_PATH
        self._raw: Dict[str, Any] = {}
        self._sections: Dict[str, Dict] = {}
        self._genre_modifiers: Dict[str, Dict] = {}
        self._vibe_modifiers: Dict[str, Dict] = {}
        self._load_failure: Optional[str] = None
        self._load()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        """True when the ruleset loaded and validated without error."""
        return self._load_failure is None

    @property
    def version(self) -> str:
        return str(self._raw.get("version") or RULE_SET_VERSION)

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def get_rules_for_section(self, section_type: str) -> Dict[str, Any]:
        """Return a deep copy of the base rules for *section_type*.

        Parameters
        ----------
        section_type:
            Any section type string — normalised to the canonical JSON key
            internally (e.g. ``"pre_chorus"`` → ``"PRE_HOOK"``).

        Returns
        -------
        dict
            ``{"section_type": str, "roles": {role: {rule fields}}}``.
            Returns an empty ``roles`` dict when the section is unknown and
            the engine is operating in fallback mode.

        Raises
        ------
        KeyError
            When the ruleset is loaded but does not contain *section_type*.
        """
        canonical = _normalise_section(section_type)
        if canonical not in self._sections:
            if not self.is_loaded:
                logger.warning(
                    "instrument_activation_rules: ruleset not loaded "
                    "(reason: %s) — returning empty rules for %r",
                    self._load_failure,
                    section_type,
                )
                return {"section_type": section_type, "roles": {}}
            raise KeyError(
                f"instrument_activation_rules: unknown section type {section_type!r} "
                f"(normalised: {canonical!r}). "
                f"Valid sections: {sorted(self._sections)}"
            )
        return {
            "section_type": canonical,
            "roles": copy.deepcopy(self._sections[canonical]),
        }

    def apply_genre_vibe_modifiers(
        self,
        rules: Dict[str, Any],
        *,
        genre: str = "generic",
        vibe: str = "",
    ) -> Dict[str, Any]:
        """Apply genre and vibe modifier deltas to *rules* (in-place copy).

        Parameters
        ----------
        rules:
            Dict returned by :meth:`get_rules_for_section`.
        genre:
            Genre string (e.g. ``"trap"``, ``"rnb"``, ``"pop"``).
        vibe:
            Vibe/mood string (e.g. ``"dark"``, ``"hype"``, ``"emotional"``).

        Returns
        -------
        dict
            A new modified copy of *rules*.  The original is never mutated.
        """
        result = copy.deepcopy(rules)
        roles = result.get("roles") or {}

        genre_lower = str(genre or "").lower().strip()
        vibe_lower = str(vibe or "").lower().strip()

        modifiers_applied: List[str] = []

        for source_key, modifier_map in (
            (genre_lower, self._genre_modifiers),
            (vibe_lower, self._vibe_modifiers),
        ):
            if not source_key:
                continue
            mod = modifier_map.get(source_key)
            if not mod:
                continue
            for role, deltas in mod.items():
                if role not in roles:
                    continue
                role_rule = roles[role]
                for field_name, value in deltas.items():
                    if field_name.endswith("_delta"):
                        base_field = field_name[: -len("_delta")]
                        current = float(role_rule.get(base_field) or 0.0)
                        role_rule[base_field] = _clamp(current + float(value))
                    else:
                        # Boolean or direct override (e.g. slides=true)
                        role_rule[field_name] = value
                modifiers_applied.append(f"{source_key}:{role}")

        if modifiers_applied:
            result["_modifiers_applied"] = modifiers_applied
            logger.debug(
                "instrument_activation_rules: applied modifiers for genre=%r vibe=%r: %s",
                genre,
                vibe,
                modifiers_applied,
            )

        return result

    def apply_variation_seed(
        self,
        rules: Dict[str, Any],
        seed: int,
    ) -> Dict[str, Any]:
        """Apply deterministic variation based on *seed* to *rules*.

        Variations applied (all deterministic for the same seed):
        - Slightly vary density ± :data:`_VARIATION_DENSITY_DELTA` (max).
        - Toggle optional roles (arp, percussion) on/off.
        - Vary hat roll probability.
        - Vary FX intensity.

        Returns
        -------
        dict
            A new modified copy of *rules*.
        """
        result = copy.deepcopy(rules)
        roles = result.get("roles") or {}
        rng = random.Random(int(seed))

        for role, rule in roles.items():
            if not isinstance(rule, dict):
                continue
            density_current = float(rule.get("density") or 0.0)
            if density_current > 0.0:
                delta = rng.uniform(-_VARIATION_DENSITY_DELTA, _VARIATION_DENSITY_DELTA)
                rule["density"] = _clamp(density_current + delta)

            # Toggle optional roles (arp, percussion, fx) with 30% probability.
            if role in {"arp", "percussion"} and rule.get("active") is False:
                if rng.random() < 0.30:
                    rule["active"] = True
                    rule["_variation_toggled"] = True

            # Vary hat/percussion roll probability.
            if role == "percussion" and rule.get("active"):
                if rng.random() < 0.40:
                    rule["rolls"] = True

            # Vary FX intensity.
            if role == "fx":
                intensity = float(rule.get("intensity") or 0.5)
                rule["intensity"] = _clamp(intensity + rng.uniform(-0.1, 0.1))

        result["_variation_seed"] = seed
        return result

    def get_rule_set_metadata(self) -> Dict[str, Any]:
        """Return metadata about the loaded ruleset."""
        return {
            "version": self.version,
            "is_loaded": self.is_loaded,
            "load_failure": self._load_failure,
            "sections_available": sorted(self._sections),
            "path": str(self._path),
        }

    # ------------------------------------------------------------------
    # Internal: load + validate
    # ------------------------------------------------------------------

    def _load(self) -> None:
        """Load and validate the JSON ruleset from disk."""
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._validate(raw)
            self._raw = raw
            self._sections = {
                k: v for k, v in raw.get("sections", {}).items()
            }
            self._genre_modifiers = dict(raw.get("genre_modifiers") or {})
            self._vibe_modifiers = dict(raw.get("vibe_modifiers") or {})
            logger.info(
                "instrument_activation_rules: loaded v%s from %s "
                "(%d sections, %d genre mods, %d vibe mods)",
                raw.get("version"),
                self._path,
                len(self._sections),
                len(self._genre_modifiers),
                len(self._vibe_modifiers),
            )
        except Exception as exc:
            self._load_failure = str(exc)
            logger.error(
                "instrument_activation_rules: failed to load ruleset from %s: %s",
                self._path,
                exc,
            )

    def _validate(self, raw: Dict[str, Any]) -> None:
        """Validate the ruleset structure, raising ValueError on failure."""
        sections = raw.get("sections")
        if not isinstance(sections, dict):
            raise ValueError("ruleset 'sections' must be a dict")

        missing = _REQUIRED_SECTIONS - set(sections)
        if missing:
            raise ValueError(
                f"ruleset missing required section types: {sorted(missing)}"
            )

        for section_name, roles in sections.items():
            if not isinstance(roles, dict):
                raise ValueError(
                    f"section {section_name!r}: roles must be a dict, got {type(roles)}"
                )
            for role_name, rule in roles.items():
                if not isinstance(rule, dict):
                    raise ValueError(
                        f"section {section_name!r} role {role_name!r}: "
                        f"rule must be a dict, got {type(rule)}"
                    )
                # Required field check.
                for req in _REQUIRED_ROLE_FIELDS:
                    if req not in rule:
                        raise ValueError(
                            f"section {section_name!r} role {role_name!r}: "
                            f"missing required field {req!r}"
                        )
                # Validate density / complexity range.
                for field in ("density", "complexity"):
                    val = rule.get(field)
                    if val is not None:
                        try:
                            fval = float(val)
                        except (TypeError, ValueError) as exc:
                            raise ValueError(
                                f"section {section_name!r} role {role_name!r}: "
                                f"{field} must be numeric, got {val!r}"
                            ) from exc
                        if not (0.0 <= fval <= 1.0):
                            raise ValueError(
                                f"section {section_name!r} role {role_name!r}: "
                                f"{field}={fval} is outside valid range 0.0–1.0"
                            )

        # Cross-section density warnings (non-fatal).
        hook_roles = sections.get("HOOK") or {}
        verse_roles = sections.get("VERSE") or {}
        for role in ("drums", "bass", "melody"):
            hook_density = float((hook_roles.get(role) or {}).get("density") or 0.0)
            verse_density = float((verse_roles.get(role) or {}).get("density") or 0.0)
            if hook_density < verse_density:
                logger.warning(
                    "instrument_activation_rules: HOOK %s density (%.2f) < "
                    "VERSE density (%.2f) — check ruleset",
                    role,
                    hook_density,
                    verse_density,
                )

        intro_roles = sections.get("INTRO") or {}
        for forbidden_role in ("bass", "drums"):
            intro_rule = intro_roles.get(forbidden_role) or {}
            if intro_rule.get("active"):
                logger.warning(
                    "instrument_activation_rules: INTRO has %s active=True — "
                    "INTRO must not allow bass or drums",
                    forbidden_role,
                )

        outro_roles = sections.get("OUTRO") or {}
        outro_bass = (outro_roles.get("bass") or {}).get("active")
        if outro_bass:
            logger.warning(
                "instrument_activation_rules: OUTRO has bass active=True — "
                "OUTRO must remove bass"
            )


# ---------------------------------------------------------------------------
# Module-level singleton (lazy)
# ---------------------------------------------------------------------------

_ENGINE: Optional[InstrumentActivationRules] = None


def get_engine() -> InstrumentActivationRules:
    """Return the module-level singleton :class:`InstrumentActivationRules`.

    The engine is constructed on first call and cached for subsequent calls.
    """
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = InstrumentActivationRules()
    return _ENGINE


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def get_rules_for_section(section_type: str) -> Dict[str, Any]:
    """Module-level shortcut for :meth:`InstrumentActivationRules.get_rules_for_section`.

    Returns an empty ``{"section_type": ..., "roles": {}}`` dict when the
    engine failed to load, so callers never need to handle exceptions.
    """
    engine = get_engine()
    if not engine.is_loaded:
        return {"section_type": section_type, "roles": {}}
    try:
        return engine.get_rules_for_section(section_type)
    except KeyError:
        logger.warning(
            "instrument_activation_rules: no rules for section %r — returning empty",
            section_type,
        )
        return {"section_type": section_type, "roles": {}}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------


def _normalise_section(section_type: str) -> str:
    """Normalise a section type string to the canonical JSON key.

    Examples
    --------
    >>> _normalise_section("pre_chorus")
    'PRE_HOOK'
    >>> _normalise_section("HOOK")
    'HOOK'
    >>> _normalise_section("chorus")
    'HOOK'
    """
    lower = str(section_type or "").lower().strip().replace("-", "_")
    canonical = _SECTION_NORMALISE.get(lower)
    if canonical:
        return canonical
    # If not found, try upper-casing (the JSON keys are already upper-case)
    upper = lower.upper()
    if upper in _REQUIRED_SECTIONS:
        return upper
    return lower.upper()


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp *value* to [lo, hi] and round to 4 decimal places."""
    return round(max(lo, min(hi, float(value))), 4)
