"""
Groove Engine — main orchestrator.

Transforms section contexts into :class:`GroovePlan` objects by:

1. Selecting the most appropriate :class:`GrooveProfile` for the section.
2. Building microtiming groove events using :mod:`microtiming`.
3. Building accent events using :mod:`accent_engine`.
4. Scoring the resulting plan with :func:`score_bounce`.
5. Tracking state via :class:`GrooveState` for deterministic escalation.

Usage::

    from app.services.groove_engine import GrooveEngine, GrooveContext

    engine = GrooveEngine()
    ctx = GrooveContext(
        section_name="Hook 2",
        section_index=6,
        section_occurrence_index=1,
        total_occurrences=3,
        bars=16,
        energy=0.9,
        density=0.8,
        active_roles=["drums", "bass", "melody"],
        source_quality="true_stems",
    )
    plan = engine.build_groove_plan(ctx)

The engine is stateful — instantiate once and call :meth:`build_groove_plan`
once per section **in arrangement order** so state escalation is correct.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.services.groove_engine.accent_engine import build_accent_events
from app.services.groove_engine.groove_profiles import get_profile_for_section
from app.services.groove_engine.groove_state import GrooveState
from app.services.groove_engine.microtiming import safe_offset
from app.services.groove_engine.types import GrooveContext, GrooveEvent, GroovePlan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Groove intensity targets per section type
# ---------------------------------------------------------------------------

_BASE_GROOVE_INTENSITY: dict = {
    "intro": 0.20,
    "verse": 0.50,
    "pre_hook": 0.45,
    "hook": 0.80,
    "bridge": 0.30,
    "breakdown": 0.25,
    "outro": 0.18,
}

_DEFAULT_GROOVE_INTENSITY: float = 0.50

# Minimum intensity increment per hook occurrence (ensures escalation)
_HOOK_ESCALATION_STEP: float = 0.06

# Minimum intensity increment per verse occurrence
_VERSE_ESCALATION_STEP: float = 0.04


class GrooveEngine:
    """Builds :class:`GroovePlan` objects for each section in arrangement order.

    The engine is stateful: call :meth:`build_groove_plan` once per section
    in arrangement order.

    Parameters
    ----------
    default_source_quality:
        Source quality mode used when the context does not supply one.
    """

    def __init__(self, default_source_quality: str = "true_stems") -> None:
        self.default_source_quality = default_source_quality
        self._state = GrooveState()

    def build_groove_plan(self, ctx: GrooveContext) -> GroovePlan:
        """Build and return a :class:`GroovePlan` for *ctx*.

        Parameters
        ----------
        ctx:
            Section context produced from Timeline + Pattern Variation plans.

        Returns
        -------
        GroovePlan
            Fully populated plan.  Stereo-fallback sources return a
            minimal plan with conservative profile selection only.
        """
        source_quality = ctx.source_quality or self.default_source_quality
        section_type = ctx.section_type
        occurrence = self._state.next_occurrence(section_type)

        # --- 1. Select groove profile ---
        profile = get_profile_for_section(
            section_type=section_type,
            occurrence=occurrence,
            energy=ctx.energy,
            source_quality=source_quality,
        )

        # --- 2. Determine groove intensity ---
        groove_intensity = self._compute_groove_intensity(
            section_type=section_type,
            occurrence=occurrence,
            energy=ctx.energy,
            source_quality=source_quality,
        )

        # --- 3. Build groove events ---
        groove_events: List[GrooveEvent] = []
        heuristics: List[str] = []

        if source_quality != "stereo_fallback":
            # Microtiming events
            mt_events, mt_heuristics = self._build_microtiming_events(
                ctx=ctx,
                profile=profile,
                occurrence=occurrence,
                source_quality=source_quality,
            )
            groove_events.extend(mt_events)
            heuristics.extend(mt_heuristics)

            # Accent events
            accent_events = build_accent_events(
                profile=profile,
                bars=ctx.bars,
                energy=ctx.energy,
                section_type=section_type,
                occurrence=occurrence,
                source_quality=source_quality,
                active_roles=ctx.active_roles,
            )
            groove_events.extend(accent_events)
            if accent_events:
                heuristics.append("accent_events")

        # Section-type specific heuristics
        heuristics.extend(self._section_heuristics(section_type, occurrence, ctx.energy))

        # --- 4. Score bounce ---
        plan = GroovePlan(
            section_name=ctx.section_name,
            groove_profile_name=profile.name,
            groove_events=groove_events,
            groove_intensity=groove_intensity,
            bounce_score=0.0,
            applied_heuristics=heuristics,
        )
        plan.bounce_score = score_bounce(plan, ctx, self._state)

        # --- 5. Update state ---
        self._state.record_section(
            section_name=ctx.section_name,
            section_type=section_type,
            profile_name=profile.name,
            groove_intensity=groove_intensity,
        )

        logger.info(
            "GROOVE_ENGINE section=%r profile=%r intensity=%.2f bounce=%.2f "
            "events=%d heuristics=%s source_quality=%s",
            ctx.section_name,
            profile.name,
            groove_intensity,
            plan.bounce_score,
            len(groove_events),
            heuristics,
            source_quality,
        )

        return plan

    # ------------------------------------------------------------------ #
    # Groove intensity                                                     #
    # ------------------------------------------------------------------ #

    def _compute_groove_intensity(
        self,
        section_type: str,
        occurrence: int,
        energy: float,
        source_quality: str,
    ) -> float:
        """Return deterministic groove intensity for this section."""
        base = _BASE_GROOVE_INTENSITY.get(section_type, _DEFAULT_GROOVE_INTENSITY)

        # Scale by energy
        energy_boost = (energy - 0.5) * 0.3
        intensity = base + energy_boost

        # Escalation for hooks and verses
        if section_type == "hook":
            last = self._state.last_hook_intensity()
            min_intensity = last + _HOOK_ESCALATION_STEP if last > 0 else intensity
            intensity = max(intensity, min_intensity)

        elif section_type == "verse":
            last = self._state.last_verse_intensity()
            if last > 0 and occurrence > 1:
                intensity = max(intensity, last + _VERSE_ESCALATION_STEP)

        # Weak sources: cap at more conservative maximum
        if source_quality == "stereo_fallback":
            intensity = min(intensity, 0.35)
        elif source_quality == "ai_separated":
            intensity = min(intensity, 0.65)

        return round(max(0.0, min(1.0, intensity)), 4)

    # ------------------------------------------------------------------ #
    # Microtiming events                                                   #
    # ------------------------------------------------------------------ #

    def _build_microtiming_events(
        self,
        ctx: GrooveContext,
        profile,
        occurrence: int,
        source_quality: str,
    ) -> tuple:
        """Build microtiming GrooveEvents and return (events, heuristics)."""
        events: List[GrooveEvent] = []
        heuristics: List[str] = []

        # Roles that receive microtiming events
        timing_roles = _timing_roles_from_context(ctx)

        for role in timing_roles:
            offset = safe_offset(
                role=role,
                profile=profile,
                energy=ctx.energy,
                occurrence=occurrence,
                source_quality=source_quality,
            )
            if offset is None:
                continue

            groove_type = _groove_type_for_role(role, offset)

            events.append(GrooveEvent(
                bar_start=1,
                bar_end=ctx.bars,
                role=role,
                groove_type=groove_type,
                intensity=round(min(1.0, profile.accent_density + 0.3), 3),
                timing_offset_ms=offset,
                parameters={"profile": profile.name},
            ))

            heuristic = _heuristic_for_role(role, offset)
            if heuristic and heuristic not in heuristics:
                heuristics.append(heuristic)

        return events, heuristics

    # ------------------------------------------------------------------ #
    # Section heuristics                                                   #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _section_heuristics(
        section_type: str,
        occurrence: int,
        energy: float,
    ) -> List[str]:
        """Return named heuristics describing decisions made for this section."""
        heuristics: List[str] = []

        if section_type == "hook":
            if occurrence > 1:
                heuristics.append("hook_escalation")
            else:
                heuristics.append("hook_confident_pocket")

        elif section_type == "verse":
            if occurrence == 1:
                heuristics.append("verse_stable_groove")
            else:
                heuristics.append("verse_more_alive")

        elif section_type == "pre_hook":
            heuristics.append("pre_hook_tension")

        elif section_type in ("bridge", "breakdown"):
            heuristics.append("bridge_reset")

        elif section_type == "outro":
            heuristics.append("outro_relax")

        elif section_type == "intro":
            heuristics.append("intro_atmosphere")

        if energy > 0.8:
            heuristics.append("high_energy_lift")

        return heuristics


# ---------------------------------------------------------------------------
# Bounce scoring
# ---------------------------------------------------------------------------

def score_bounce(
    plan: GroovePlan,
    ctx: GrooveContext,
    state: Optional[GrooveState] = None,
) -> float:
    """Score the groove plan for musical bounce quality.

    Heuristics
    ----------
    * Repeated sections that differ slightly → positive.
    * Hook groove stronger than verse → positive.
    * Too-static accents → penalty.
    * Over-busy groove in low-energy sections → penalty.
    * Bridge too active → penalty.

    Returns
    -------
    float
        Score in [0.0, 1.0].  Plans scoring < 0.3 should be warned about.
    """
    score = 0.5  # baseline

    section_type = ctx.section_type

    # Reward: events present means groove is active
    event_count = len(plan.groove_events)
    if event_count > 0:
        score += min(0.15, event_count * 0.02)

    # Reward: hook groove stronger than verse
    if state and section_type == "hook":
        max_verse = state.max_verse_intensity()
        if max_verse > 0 and plan.groove_intensity > max_verse + 0.05:
            score += 0.12

    # Reward: hook escalation (each hook more intense than last)
    if state and section_type == "hook" and len(state.hook_intensities) > 0:
        if plan.groove_intensity > state.last_hook_intensity():
            score += 0.08

    # Reward: verse differentiation (verse 2 more alive than verse 1)
    if state and section_type == "verse" and ctx.occurrence > 1:
        if plan.groove_intensity > state.last_verse_intensity() + 0.02:
            score += 0.07

    # Penalty: over-busy groove in low-energy sections
    if ctx.energy < 0.4 and event_count > 6:
        score -= 0.12

    # Penalty: bridge / breakdown too active
    if section_type in ("bridge", "breakdown") and plan.groove_intensity > 0.55:
        score -= 0.15

    # Penalty: outro too active
    if section_type == "outro" and plan.groove_intensity > 0.45:
        score -= 0.12

    # Penalty: intro over-animated
    if section_type == "intro" and event_count > 4:
        score -= 0.08

    # Penalty: too-static (no events at all in a high-energy section)
    if ctx.energy > 0.6 and event_count == 0:
        score -= 0.15

    # Reward: presence of heuristics (indicates active decisions)
    score += min(0.08, len(plan.applied_heuristics) * 0.015)

    return round(max(0.0, min(1.0, score)), 4)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _timing_roles_from_context(ctx: GrooveContext) -> List[str]:
    """Return the subset of active roles that should receive microtiming events."""
    timing_roles_priority = ["drums", "bass", "percussion"]
    return [role for role in timing_roles_priority if role in ctx.active_roles]


def _groove_type_for_role(role: str, offset: float) -> str:
    """Return a named groove type string based on role and offset direction."""
    role_lower = role.lower()
    if role_lower == "drums":
        return "hat_push" if offset < 0 else "hat_lag"
    if role_lower == "bass":
        return "bass_lag"
    if role_lower == "percussion":
        return "perc_push" if offset < 0 else "perc_lag"
    return "timing_nudge"


def _heuristic_for_role(role: str, offset: float) -> Optional[str]:
    """Return a heuristic name for a microtiming decision."""
    role_lower = role.lower()
    if role_lower == "drums":
        return "hat_push" if offset < 0 else "hat_lag"
    if role_lower == "bass":
        return "bass_lag"
    if role_lower == "percussion":
        return "perc_push"
    return None
