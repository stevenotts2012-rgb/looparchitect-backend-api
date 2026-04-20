"""
Planner Agent — builds the initial strict arrangement plan.

Responsibilities:
- Accept available roles, source quality, arrangement template, and optional
  reference profile.
- Produce a deterministic :class:`AIProducerPlan` with section plans and
  micro-plan events.
- Enforce all hard rules without using vague language.

This module does NOT call any AI/LLM service.  Planning is fully deterministic.
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Any, Optional, Sequence

from app.services.ai_producer_system.schemas import (
    AIMicroPlanEvent,
    AIProducerPlan,
    AISectionPlan,
    VALID_TRANSITIONS,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section energy / density lookup tables
# ---------------------------------------------------------------------------

_SECTION_ENERGY: dict[str, float] = {
    "intro": 0.35,
    "verse": 0.55,
    "pre_hook": 0.70,
    "hook": 0.85,
    "chorus": 0.85,
    "post_hook": 0.65,
    "bridge": 0.40,
    "breakdown": 0.30,
    "drop": 0.90,
    "outro": 0.30,
    "build": 0.65,
}

_SECTION_DENSITY: dict[str, float] = {
    "intro": 0.30,
    "verse": 0.50,
    "pre_hook": 0.65,
    "hook": 0.80,
    "chorus": 0.80,
    "post_hook": 0.60,
    "bridge": 0.30,
    "breakdown": 0.25,
    "drop": 0.90,
    "outro": 0.25,
    "build": 0.60,
}

_SECTION_TRANSITION_IN: dict[str, str] = {
    "intro": "fade_in",
    "verse": "cut",
    "pre_hook": "riser",
    "hook": "drop",
    "chorus": "drop",
    "post_hook": "cut",
    "bridge": "filter_sweep",
    "breakdown": "fade_out",
    "drop": "riser",
    "outro": "fade_out",
    "build": "riser",
}

_SECTION_TRANSITION_OUT: dict[str, str] = {
    "intro": "cut",
    "verse": "drum_fill",
    "pre_hook": "cut",
    "hook": "cut",
    "chorus": "cut",
    "post_hook": "cut",
    "bridge": "cut",
    "breakdown": "reverse_cymbal",
    "drop": "cut",
    "outro": "fade_out",
    "build": "cut",
}

# Roles to introduce when a hook occurrence increases
_HOOK_ESCALATION_ROLES: list[list[str]] = [
    [],                          # occurrence 1 — baseline
    ["harmony", "fx"],           # occurrence 2 — add pads / FX
    ["percussion", "vocal"],     # occurrence 3 — add extra percussion + vocal ad-libs
]

# Roles to drop during bridge / breakdown
_BRIDGE_DROP_ROLES = {"bass", "drums", "melody"}
_BREAKDOWN_DROP_ROLES = {"bass", "drums", "melody", "percussion"}


# ---------------------------------------------------------------------------
# Public interface
# ---------------------------------------------------------------------------

class PlannerAgent:
    """Builds strict AI-producer plans from available source material.

    Parameters
    ----------
    available_roles:
        Stem/instrument roles present in the source material.
    source_quality:
        One of ``"true_stems"``, ``"zip_stems"``, ``"ai_separated"``,
        ``"stereo_fallback"``.
    """

    def __init__(
        self,
        available_roles: Optional[Sequence[str]] = None,
        source_quality: str = "stereo_fallback",
    ) -> None:
        self.available_roles: list[str] = list(available_roles or [])
        self.source_quality = source_quality
        self._is_weak = (
            source_quality == "stereo_fallback"
            or len(self.available_roles) < 2
        )

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    def build_plan(
        self,
        section_template: list[dict[str, Any]],
        reference_profile: Optional[dict[str, Any]] = None,
    ) -> AIProducerPlan:
        """Build and return an :class:`AIProducerPlan`.

        Parameters
        ----------
        section_template:
            Ordered list of dicts describing the arrangement structure.
            Each dict must have at minimum ``{"name": str, "bars": int}``.
        reference_profile:
            Optional dict with keys like ``"genre"``, ``"energy"``, and
            ``"hook_escalation"`` from an upstream reference analyser.

        Returns
        -------
        AIProducerPlan
            Fully populated plan.  Never raises.
        """
        logger.info(
            "PLANNER: building plan — %d sections, quality=%s, roles=%s",
            len(section_template),
            self.source_quality,
            self.available_roles,
        )

        ref = reference_profile or {}
        energy_boost = float(ref.get("energy", 0.5)) - 0.5  # delta vs neutral 0.5

        section_plans: list[AISectionPlan] = []
        occurrence_counter: dict[str, int] = {}

        for spec in section_template:
            name = str(spec.get("name", "verse")).strip().lower()
            bars = max(1, int(spec.get("bars", 8)))
            occurrence_counter[name] = occurrence_counter.get(name, 0) + 1
            occurrence = occurrence_counter[name]

            sp = self._build_section_plan(
                name=name,
                bars=bars,
                occurrence=occurrence,
                energy_boost=energy_boost,
            )
            section_plans.append(sp)

        # Enforce hard rules across the full plan
        section_plans = self._enforce_hard_rules(section_plans)

        # Build micro plan events
        micro_events = self._build_micro_events(section_plans)

        # Build global energy curve
        energy_curve = [sp.target_energy for sp in section_plans]

        # Novelty targets
        novelty_targets = self._build_novelty_targets(section_plans)

        # Risk flags
        risk_flags = self._detect_risk_flags(section_plans, energy_curve)

        plan = AIProducerPlan(
            section_plans=section_plans,
            micro_plan_events=micro_events,
            global_energy_curve=energy_curve,
            novelty_targets=novelty_targets,
            risk_flags=risk_flags,
            planner_notes=(
                f"Built from {len(section_plans)} sections "
                f"({self.source_quality} source, "
                f"{len(self.available_roles)} roles available)."
            ),
        )
        logger.info(
            "PLANNER: plan built — %d sections, %d micro events, %d risk flags",
            len(section_plans),
            len(micro_events),
            len(risk_flags),
        )
        return plan

    # ------------------------------------------------------------------
    # Section plan construction
    # ------------------------------------------------------------------

    def _build_section_plan(
        self,
        name: str,
        bars: int,
        occurrence: int,
        energy_boost: float,
    ) -> AISectionPlan:
        base_energy = _SECTION_ENERGY.get(name, 0.55)
        base_density = _SECTION_DENSITY.get(name, 0.50)

        energy = max(0.0, min(1.0, base_energy + energy_boost * 0.3))
        density = base_density

        # Escalate hooks on each occurrence
        if name in ("hook", "chorus"):
            escalation_idx = min(occurrence - 1, len(_HOOK_ESCALATION_ROLES) - 1)
            extra_roles = _HOOK_ESCALATION_ROLES[escalation_idx]
            energy = min(1.0, base_energy + (occurrence - 1) * 0.03 + energy_boost * 0.3)
            density = min(1.0, base_density + (occurrence - 1) * 0.05)
        else:
            extra_roles = []

        # Active roles
        active_roles = self._select_active_roles(name, density)

        # Introduced and dropped elements
        introduced = list(extra_roles) if occurrence > 1 else list(active_roles[:2])
        dropped: list[str] = []

        if name in ("bridge", "breakdown"):
            dropped = [r for r in _BRIDGE_DROP_ROLES if r in active_roles]
            active_roles = [r for r in active_roles if r not in _BRIDGE_DROP_ROLES]
            if name == "breakdown":
                dropped = [r for r in _BREAKDOWN_DROP_ROLES if r in active_roles]
                active_roles = [r for r in active_roles if r not in _BREAKDOWN_DROP_ROLES]

        if name == "outro":
            dropped = active_roles[len(active_roles) // 2:]
            active_roles = active_roles[: len(active_roles) // 2]

        # Transitions
        transition_in = _SECTION_TRANSITION_IN.get(name, "cut")
        transition_out = _SECTION_TRANSITION_OUT.get(name, "cut")

        # Variation strategy (required when occurrence > 1)
        variation_strategy = self._make_variation_strategy(name, occurrence, active_roles, extra_roles)

        # Rationale
        rationale = self._make_rationale(name, occurrence, energy, density)

        return AISectionPlan(
            section_name=name,
            occurrence=occurrence,
            bars=bars,
            target_energy=round(energy, 3),
            target_density=round(density, 3),
            active_roles=list(active_roles),
            introduced_elements=list(introduced),
            dropped_elements=list(dropped),
            transition_in=transition_in,
            transition_out=transition_out,
            variation_strategy=variation_strategy,
            micro_timeline_notes=(
                f"Bars {1}–{bars}: primary motion from {', '.join(active_roles[:2]) or 'all roles'}."
                if active_roles else f"Bars 1–{bars}: minimal texture only."
            ),
            rationale=rationale,
        )

    def _select_active_roles(self, section_name: str, density: float) -> list[str]:
        """Select which available roles should be active for this section."""
        if not self.available_roles:
            return []

        n = max(1, round(len(self.available_roles) * density))
        # Order by priority for the section type
        priority = _role_priority_for_section(section_name)
        sorted_roles = sorted(
            self.available_roles,
            key=lambda r: priority.get(r, 99),
        )
        return sorted_roles[:n]

    def _make_variation_strategy(
        self,
        name: str,
        occurrence: int,
        active_roles: list[str],
        extra_roles: list[str],
    ) -> str:
        if occurrence == 1:
            return ""

        strategies: dict[str, str] = {
            "verse": (
                f"Verse {occurrence}: add filter-swept upper layers on bars 5–8, "
                f"swap kick pattern to off-beat 16th emphasis, "
                f"introduce '{active_roles[0] if active_roles else 'melody'}' counter-motif."
            ),
            "hook": (
                f"Hook {occurrence}: layer {', '.join(extra_roles) if extra_roles else 'additional percussion'} "
                f"from bar 1, push energy to {round(min(1.0, 0.80 + (occurrence - 1) * 0.05), 2)}, "
                f"use stutter on final 2 bars before exit."
            ),
            "chorus": (
                f"Chorus {occurrence}: doubles melody at octave above from bar 3, "
                f"percussion density increases by 20%, "
                f"transition out switches from cut to reverse_cymbal."
            ),
            "pre_hook": (
                f"Pre-hook {occurrence}: strip low end completely on bars 1–2 "
                f"to create tension, re-enter bass on bar 3."
            ),
        }
        generic = (
            f"{name.title()} occurrence {occurrence}: "
            f"re-introduce {', '.join(active_roles[:2]) or 'primary roles'} "
            f"with shifted rhythmic placement (+1 16th offset), "
            f"apply subtle pitch modulation on melodic elements."
        )
        return strategies.get(name, generic)

    def _make_rationale(
        self,
        name: str,
        occurrence: int,
        energy: float,
        density: float,
    ) -> str:
        base_rationales: dict[str, str] = {
            "intro": (
                f"Intro at energy={energy:.2f}: establish tonal centre and groove "
                f"without overwhelming listener. Density {density:.2f} builds anticipation."
            ),
            "verse": (
                f"Verse {occurrence} at energy={energy:.2f}: deliver lyrical/melodic content "
                f"at controlled density {density:.2f}. Must contrast with hook payoff."
            ),
            "pre_hook": (
                f"Pre-hook at energy={energy:.2f}: tension ramp before hook. "
                f"Density {density:.2f} primes listener for drop."
            ),
            "hook": (
                f"Hook {occurrence} at energy={energy:.2f}: primary payoff moment. "
                f"Energy and density ({density:.2f}) must exceed all verses."
            ),
            "chorus": (
                f"Chorus {occurrence} at energy={energy:.2f}: primary payoff moment. "
                f"Full density ({density:.2f}) — all signature elements present."
            ),
            "bridge": (
                f"Bridge at energy={energy:.2f}: contrast section. "
                f"Reduced density {density:.2f} creates ear relief before final hook."
            ),
            "breakdown": (
                f"Breakdown at energy={energy:.2f}: maximum tension through absence. "
                f"Density {density:.2f} — strips to bare texture only."
            ),
            "outro": (
                f"Outro at energy={energy:.2f}: wind-down. "
                f"Density {density:.2f} decreases progressively to create closure."
            ),
            "drop": (
                f"Drop at energy={energy:.2f}: maximum impact. "
                f"All elements re-enter simultaneously at density {density:.2f}."
            ),
        }
        return base_rationales.get(
            name,
            f"{name.title()} occurrence {occurrence}: energy={energy:.2f}, density={density:.2f}.",
        )

    # ------------------------------------------------------------------
    # Hard rule enforcement
    # ------------------------------------------------------------------

    def _enforce_hard_rules(
        self, section_plans: list[AISectionPlan]
    ) -> list[AISectionPlan]:
        """Apply all cross-section hard rules in-place and return the list."""
        self._enforce_repeated_section_contrast(section_plans)
        self._enforce_hook_escalation(section_plans)
        self._enforce_bridge_breakdown_density(section_plans)
        self._enforce_outro_simplification(section_plans)
        return section_plans

    def _enforce_repeated_section_contrast(
        self, section_plans: list[AISectionPlan]
    ) -> None:
        """Ensure repeated sections have concrete differences."""
        seen: dict[str, AISectionPlan] = {}
        for sp in section_plans:
            key = sp.section_name
            if key in seen:
                prior = seen[key]
                # Force energy/density delta
                if abs(sp.target_energy - prior.target_energy) < 0.05:
                    sp.target_energy = min(1.0, prior.target_energy + 0.05)
                if not sp.variation_strategy:
                    sp.variation_strategy = self._make_variation_strategy(
                        sp.section_name, sp.occurrence, sp.active_roles, []
                    )
            seen[key] = sp

    def _enforce_hook_escalation(self, section_plans: list[AISectionPlan]) -> None:
        """Hook 3 must be highest payoff if present."""
        hooks = [sp for sp in section_plans if sp.section_name in ("hook", "chorus")]
        if len(hooks) >= 3:
            max_prior = max(h.target_energy for h in hooks[:2])
            if hooks[2].target_energy <= max_prior:
                hooks[2].target_energy = min(1.0, max_prior + 0.05)
                if not hooks[2].variation_strategy:
                    hooks[2].variation_strategy = (
                        "Hook 3 (final payoff): add full ensemble stack, "
                        "increase percussion density by 30%, "
                        "extend drop outro by 2 bars with reverse-cymbal exit."
                    )

    def _enforce_bridge_breakdown_density(
        self, section_plans: list[AISectionPlan]
    ) -> None:
        """Bridge and breakdown must have below-average density."""
        if not section_plans:
            return
        avg_density = sum(sp.target_density for sp in section_plans) / len(section_plans)
        for sp in section_plans:
            if sp.section_name in ("bridge", "breakdown"):
                if sp.target_density >= avg_density:
                    sp.target_density = max(0.10, avg_density - 0.15)

    def _enforce_outro_simplification(
        self, section_plans: list[AISectionPlan]
    ) -> None:
        """Outro must reduce density and energy below the average."""
        if not section_plans:
            return
        avg_energy = sum(sp.target_energy for sp in section_plans) / len(section_plans)
        avg_density = sum(sp.target_density for sp in section_plans) / len(section_plans)
        for sp in section_plans:
            if sp.section_name == "outro":
                if sp.target_energy >= avg_energy:
                    sp.target_energy = max(0.10, avg_energy - 0.20)
                if sp.target_density >= avg_density:
                    sp.target_density = max(0.10, avg_density - 0.20)

    # ------------------------------------------------------------------
    # Micro-plan event construction
    # ------------------------------------------------------------------

    def _build_micro_events(
        self, section_plans: list[AISectionPlan]
    ) -> list[AIMicroPlanEvent]:
        """Generate concrete micro-level events for each section."""
        events: list[AIMicroPlanEvent] = []
        if self._is_weak:
            return events

        for sp in section_plans:
            events.extend(self._micro_events_for_section(sp))

        return events

    def _micro_events_for_section(
        self, sp: AISectionPlan
    ) -> list[AIMicroPlanEvent]:
        events: list[AIMicroPlanEvent] = []
        if not sp.active_roles or sp.bars < 4:
            return events

        primary_role = sp.active_roles[0]

        # Variation event at section midpoint
        mid = max(1, sp.bars // 2)
        events.append(AIMicroPlanEvent(
            bar_start=mid,
            bar_end=mid,
            role=primary_role,
            action="pattern_change",
            intensity=0.6,
            notes=f"Midpoint pattern change in {sp.section_name} occurrence {sp.occurrence}.",
        ))

        # Periodic drum fill every 8 bars
        bar = 8
        while bar <= sp.bars:
            drum_role = next(
                (r for r in sp.active_roles if "drum" in r or "perc" in r),
                primary_role,
            )
            events.append(AIMicroPlanEvent(
                bar_start=bar,
                bar_end=bar,
                role=drum_role,
                action="drum_fill",
                intensity=0.5,
                notes=f"Periodic fill at bar {bar} of {sp.section_name}.",
            ))
            bar += 8

        # Hook: add layer entry at bar 3
        if sp.section_name in ("hook", "chorus") and sp.bars >= 4:
            if len(sp.active_roles) > 1:
                events.append(AIMicroPlanEvent(
                    bar_start=3,
                    bar_end=3,
                    role=sp.active_roles[1],
                    action="add_layer",
                    intensity=0.8,
                    notes=(
                        f"Hook {sp.occurrence}: layer second element "
                        f"at bar 3 for payoff build."
                    ),
                ))

        # Bridge: filter sweep on bar 1
        if sp.section_name in ("bridge", "breakdown") and sp.active_roles:
            events.append(AIMicroPlanEvent(
                bar_start=1,
                bar_end=2,
                role=sp.active_roles[0],
                action="filter_sweep",
                intensity=0.7,
                notes="Breakdown entry: high-pass filter sweep to strip low end.",
            ))

        return events

    # ------------------------------------------------------------------
    # Novelty targets
    # ------------------------------------------------------------------

    def _build_novelty_targets(
        self, section_plans: list[AISectionPlan]
    ) -> dict[str, str]:
        targets: dict[str, str] = {}
        for sp in section_plans:
            if sp.occurrence > 1:
                key = f"{sp.section_name}:{sp.occurrence}"
                targets[key] = sp.variation_strategy or (
                    f"{sp.section_name} occurrence {sp.occurrence} must differ "
                    f"from occurrence {sp.occurrence - 1} via concrete role/rhythm change."
                )
        return targets

    # ------------------------------------------------------------------
    # Risk flags
    # ------------------------------------------------------------------

    def _detect_risk_flags(
        self,
        section_plans: list[AISectionPlan],
        energy_curve: list[float],
    ) -> list[str]:
        flags: list[str] = []

        if energy_curve:
            span = max(energy_curve) - min(energy_curve)
            if span < 0.10:
                flags.append(
                    f"FLAT_ENERGY_CURVE: span={span:.3f} < 0.10 — "
                    "arrangement lacks dynamic range."
                )

        hooks = [sp for sp in section_plans if sp.section_name in ("hook", "chorus")]
        verses = [sp for sp in section_plans if sp.section_name == "verse"]
        if hooks and verses:
            avg_hook_e = sum(h.target_energy for h in hooks) / len(hooks)
            avg_verse_e = sum(v.target_energy for v in verses) / len(verses)
            if avg_hook_e <= avg_verse_e:
                flags.append(
                    "HOOK_NOT_LOUDER_THAN_VERSE: hook energy must exceed verse energy."
                )

        if self._is_weak:
            flags.append(
                "WEAK_SOURCE: limited stem separation — "
                "arrangement rules applied in degraded mode."
            )

        return flags


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _role_priority_for_section(section_name: str) -> dict[str, int]:
    """Return a priority map for stem roles in a given section type."""
    base = {
        "drums": 1,
        "percussion": 2,
        "bass": 3,
        "melody": 4,
        "vocals": 5,
        "vocal": 5,
        "harmony": 6,
        "pads": 7,
        "fx": 8,
        "accent": 9,
    }
    if section_name in ("bridge", "breakdown", "outro"):
        base.update({"drums": 9, "percussion": 8, "bass": 7, "pads": 1, "harmony": 2, "fx": 3})
    elif section_name == "intro":
        base.update({"pads": 1, "harmony": 2, "melody": 3, "fx": 4, "drums": 5, "bass": 6})
    return base
