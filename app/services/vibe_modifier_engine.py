"""
Vibe Modifier Engine.

Applies vibe-based transformations to Instrument Activation Rules
*before* the Variation Engine and resolution steps.

Integration point::

    rules = instrument_activation_rules.get_rules_for_section(section_type)
    rules = vibe_modifier_engine.apply_vibe(
        section_type=section_type,
        instrument_rules=rules,
        selected_vibe=selected_vibe,
        variation_seed=variation_seed,
    )
    # → then pass to Variation Engine → FinalPlanResolver

Supported vibes: dark, emotional, hype, pain, rage, ambient, cinematic

Rule file: config/vibe_modifier_rules.json

Safety guarantee
----------------
If the config is missing or a vibe is not found, the engine falls back to
the original ``instrument_rules`` unchanged and logs a warning.  It never
raises exceptions.
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

_CONFIG_PATH: Path = (
    Path(__file__).parent.parent.parent / "config" / "vibe_modifier_rules.json"
)

_SUPPORTED_VIBES: frozenset[str] = frozenset(
    {"dark", "emotional", "hype", "pain", "rage", "ambient", "cinematic"}
)

# Role mapping for multiplier targets
_MELODY_ROLE = "melody"
_CHORD_ROLE = "chords"
_BASS_ROLE = "bass"      # 808 in trap/hip-hop context
_FX_ROLE = "fx"
_ARP_ROLE = "arp"        # counter-melody voice
_PERCUSSION_ROLE = "percussion"  # hihat / percussion

# Clamp helpers
_LO: float = 0.0
_HI: float = 1.0


# ---------------------------------------------------------------------------
# Internal: config loader (module-level singleton)
# ---------------------------------------------------------------------------

_RULES: Optional[Dict[str, Any]] = None
_LOAD_FAILURE: Optional[str] = None


def _load_rules(path: Path = _CONFIG_PATH) -> Dict[str, Any]:
    """Load vibe modifier rules JSON, caching on first call."""
    global _RULES, _LOAD_FAILURE
    if _RULES is not None:
        return _RULES
    try:
        _RULES = json.loads(path.read_text(encoding="utf-8"))
        logger.info(
            "vibe_modifier_engine: loaded rules v%s from %s (%d vibes)",
            _RULES.get("version"),
            path,
            len(_RULES.get("vibes") or {}),
        )
    except Exception as exc:
        _LOAD_FAILURE = str(exc)
        logger.error("vibe_modifier_engine: failed to load %s: %s", path, exc)
        _RULES = {}
    return _RULES


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def apply_vibe(
    *,
    section_type: str,
    instrument_rules: Dict[str, Any],
    selected_vibe: str,
    variation_seed: int,
    rules_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Apply vibe-based transformations to *instrument_rules*.

    Parameters
    ----------
    section_type:
        Section name (e.g. ``"HOOK"``, ``"VERSE"``).  Normalised to upper-case
        for energy-shift lookup.
    instrument_rules:
        Dict returned by
        :func:`~app.services.instrument_activation_rules.get_rules_for_section`.
        The original is never mutated.
    selected_vibe:
        One of ``dark``, ``emotional``, ``hype``, ``pain``, ``rage``,
        ``ambient``, ``cinematic``.
    variation_seed:
        Integer seed used for all probabilistic decisions, guaranteeing
        deterministic output for the same inputs.
    rules_path:
        Optional override path to ``vibe_modifier_rules.json`` (useful in
        tests).

    Returns
    -------
    dict
        A deep copy of *instrument_rules* with vibe transformations applied
        and metadata fields added (``vibe_applied``, ``vibe_name``,
        ``vibe_modifiers_applied``, ``density_before_vs_after``).
        Returns the original (deep-copied) rules on any failure.
    """
    result = copy.deepcopy(instrument_rules)

    vibe_key = str(selected_vibe or "").lower().strip()
    if not vibe_key:
        return result

    try:
        config = _load_rules(rules_path or _CONFIG_PATH)
        vibes = (config or {}).get("vibes") or {}

        vibe_cfg = vibes.get(vibe_key)
        if not vibe_cfg:
            logger.warning(
                "vibe_modifier_engine: unknown vibe %r — returning original rules",
                selected_vibe,
            )
            return result

        roles_before = _snapshot_densities(result.get("roles") or {})

        _apply_multipliers(result, vibe_cfg)
        _apply_probabilistic_features(result, vibe_cfg, variation_seed)
        _apply_section_energy_shift(result, section_type, vibe_cfg)
        filters_applied = _apply_filters(result, vibe_cfg, variation_seed)

        roles_after = _snapshot_densities(result.get("roles") or {})

        # Attach metadata
        result["vibe_applied"] = True
        result["vibe_name"] = vibe_key
        result["vibe_modifiers_applied"] = _collect_modifiers_applied(
            vibe_cfg, filters_applied
        )
        result["density_before_vs_after"] = {
            role: {"before": roles_before.get(role), "after": roles_after.get(role)}
            for role in set(roles_before) | set(roles_after)
        }

        logger.debug(
            "vibe_modifier_engine: applied vibe=%r to section=%r (seed=%d)",
            vibe_key,
            section_type,
            variation_seed,
        )

    except Exception as exc:  # noqa: BLE001 — safety net; never crash
        logger.error(
            "vibe_modifier_engine: unexpected error for vibe=%r section=%r: %s — "
            "returning original rules",
            selected_vibe,
            section_type,
            exc,
        )
        return copy.deepcopy(instrument_rules)

    return result


# ---------------------------------------------------------------------------
# Step 1 — Apply multipliers
# ---------------------------------------------------------------------------


def _apply_multipliers(rules: Dict[str, Any], vibe_cfg: Dict[str, Any]) -> None:
    """Multiply density / intensity fields and clamp to [0, 1] in-place."""
    mults = vibe_cfg.get("multipliers") or {}
    roles = rules.get("roles") or {}

    _multiply_role_field(
        roles, _MELODY_ROLE, "density",
        float(mults.get("melody_density_multiplier") or 1.0),
    )
    _multiply_role_field(
        roles, _CHORD_ROLE, "density",
        float(mults.get("chord_density_multiplier") or 1.0),
    )
    _multiply_role_field(
        roles, _BASS_ROLE, "complexity",
        float(mults.get("808_complexity_multiplier") or 1.0),
    )
    _multiply_role_field(
        roles, _FX_ROLE, "intensity",
        float(mults.get("fx_intensity_multiplier") or 1.0),
    )


def _multiply_role_field(
    roles: Dict[str, Any],
    role: str,
    field: str,
    multiplier: float,
) -> None:
    rule = roles.get(role)
    if not isinstance(rule, dict):
        return
    current = rule.get(field)
    if current is None:
        return
    rule[field] = _clamp(float(current) * multiplier)


# ---------------------------------------------------------------------------
# Step 2 — Apply probabilistic features
# ---------------------------------------------------------------------------


def _apply_probabilistic_features(
    rules: Dict[str, Any],
    vibe_cfg: Dict[str, Any],
    seed: int,
) -> None:
    """Apply probabilistic instrument feature toggles deterministically."""
    prob = vibe_cfg.get("probabilistic_features") or {}
    roles = rules.get("roles") or {}
    rng = random.Random(int(seed) ^ 0xDEAD_BEEF)  # dedicated sub-seed

    # Counter melody (arp role)
    if rng.random() < float(prob.get("counter_melody_activation") or 0.0):
        arp = roles.get(_ARP_ROLE)
        if isinstance(arp, dict):
            arp["active"] = True
            arp["_vibe_counter_melody"] = True

    # 808 slides (bass role)
    if rng.random() < float(prob.get("808_slide_chance") or 0.0):
        bass = roles.get(_BASS_ROLE)
        if isinstance(bass, dict):
            bass["slides"] = True
            bass["_vibe_slides"] = True

    # Hihat rolls (percussion role)
    if rng.random() < float(prob.get("hihat_roll_chance") or 0.0):
        perc = roles.get(_PERCUSSION_ROLE)
        if isinstance(perc, dict):
            perc["rolls"] = True
            perc["_vibe_rolls"] = True


# ---------------------------------------------------------------------------
# Step 3 — Apply section energy shift
# ---------------------------------------------------------------------------


def _apply_section_energy_shift(
    rules: Dict[str, Any],
    section_type: str,
    vibe_cfg: Dict[str, Any],
) -> None:
    """Add the vibe's section-specific energy shift to ``target_energy``."""
    shifts = vibe_cfg.get("section_energy_shift") or {}
    canonical = str(section_type or "").upper().strip()
    shift = float(shifts.get(canonical) or 0.0)
    if shift == 0.0:
        return

    current_energy = float(rules.get("target_energy") or rules.get("energy") or 0.5)
    rules["target_energy"] = _clamp(current_energy + shift)


# ---------------------------------------------------------------------------
# Step 4 — Apply filters
# ---------------------------------------------------------------------------

_FILTER_KEYS: List[str] = [
    "lowpass_chance",
    "highpass_chance",
    "distortion_chance",
    "bitcrush_chance",
    "reverb_chance",
    "delay_chance",
    "stereo_widening_chance",
]


def _apply_filters(
    rules: Dict[str, Any],
    vibe_cfg: Dict[str, Any],
    seed: int,
) -> List[str]:
    """Apply probabilistic DSP filter flags; returns list of activated filters."""
    filters_cfg = vibe_cfg.get("filters") or {}
    rng = random.Random(int(seed) ^ 0xCAFE_BABE)  # dedicated sub-seed

    activated: List[str] = []
    applied_filters: Dict[str, bool] = {}

    for key in _FILTER_KEYS:
        prob = float(filters_cfg.get(key) or 0.0)
        if rng.random() < prob:
            filter_name = key.replace("_chance", "")
            applied_filters[filter_name] = True
            activated.append(filter_name)

    if applied_filters:
        rules["vibe_filters"] = applied_filters

    return activated


# ---------------------------------------------------------------------------
# Step 5+ — Metadata helpers
# ---------------------------------------------------------------------------


def _snapshot_densities(roles: Dict[str, Any]) -> Dict[str, Optional[float]]:
    """Return a mapping of role → current density (or None if absent)."""
    out: Dict[str, Optional[float]] = {}
    for role, rule in roles.items():
        if isinstance(rule, dict):
            val = rule.get("density")
            out[role] = float(val) if val is not None else None
    return out


def _collect_modifiers_applied(
    vibe_cfg: Dict[str, Any],
    filters_applied: List[str],
) -> List[str]:
    """Summarise which modifier categories were present."""
    applied: List[str] = []
    if vibe_cfg.get("multipliers"):
        applied.append("multipliers")
    if vibe_cfg.get("probabilistic_features"):
        applied.append("probabilistic_features")
    if vibe_cfg.get("section_energy_shift"):
        applied.append("section_energy_shift")
    for f in filters_applied:
        applied.append(f"filter:{f}")
    return applied


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def _clamp(value: float, lo: float = _LO, hi: float = _HI) -> float:
    """Clamp *value* to [lo, hi] and round to 4 decimal places."""
    return round(max(lo, min(hi, float(value))), 4)


# ---------------------------------------------------------------------------
# Module-level reset helper (for testing)
# ---------------------------------------------------------------------------


def _reset_cache() -> None:
    """Reset the cached rules (used in tests that override rules_path)."""
    global _RULES, _LOAD_FAILURE
    _RULES = None
    _LOAD_FAILURE = None
