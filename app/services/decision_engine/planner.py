"""
Decision Planner — builds a :class:`~app.services.decision_engine.types.DecisionPlan`
across all arrangement sections.

The planner:
1. Iterates through sections in order.
2. Applies producer rules via :mod:`~app.services.decision_engine.rules` to
   determine hold-backs, removals, re-entries, and fullness.
3. Tracks state via :class:`~app.services.decision_engine.state.DecisionEngineState`
   to prevent repeated identical decisions and ensure correct escalation.
4. Computes ``global_contrast_score`` and ``payoff_readiness_score``.

The planner is deterministic — no uncontrolled randomness.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

from app.services.decision_engine.rules import (
    LIMITED_SOURCE_QUALITIES,
    MIN_ROLES_FOR_SUBTRACTION,
    choose_roles_to_hold_back,
    choose_roles_to_remove_for_tension,
    choose_roles_to_reintroduce,
    compute_target_fullness,
    section_can_allow_full_stack,
    should_force_bridge_reset,
    should_force_outro_resolution,
)
from app.services.decision_engine.state import DecisionEngineState
from app.services.decision_engine.types import (
    DecisionAction,
    DecisionPlan,
    SectionDecision,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Section-type derivation
# ---------------------------------------------------------------------------

_KNOWN_SECTION_TYPES: frozenset[str] = frozenset(
    {
        "intro",
        "verse",
        "pre_hook",
        "hook",
        "bridge",
        "breakdown",
        "outro",
    }
)


def _derive_section_type(name: str) -> str:
    """Derive a canonical section type from a raw section name string."""
    n = name.lower().strip()
    for token in ("pre_hook", "pre-hook", "prehook", "buildup", "build"):
        if token in n:
            return "pre_hook"
    for token in ("hook", "chorus", "drop"):
        if token in n:
            return "hook"
    for token in ("verse",):
        if token in n:
            return "verse"
    for token in ("bridge",):
        if token in n:
            return "bridge"
    for token in ("breakdown", "break"):
        if token in n:
            return "breakdown"
    for token in ("intro",):
        if token in n:
            return "intro"
    for token in ("outro",):
        if token in n:
            return "outro"
    return "verse"


# ---------------------------------------------------------------------------
# Action factory helpers
# ---------------------------------------------------------------------------


def _hold_back_action(
    section_name: str,
    occurrence_index: int,
    role: str,
    intensity: float = 0.8,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="hold_back_role",
        target_role=role,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason=f"Hold back {role!r} to preserve room for later growth",
    )


def _remove_for_tension_action(
    section_name: str,
    occurrence_index: int,
    role: str,
    intensity: float = 0.9,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="pre_hook_subtraction",
        target_role=role,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason=f"Remove {role!r} to create tension before hook re-entry",
    )


def _reintroduce_action(
    section_name: str,
    occurrence_index: int,
    role: str,
    intensity: float = 0.9,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="reintroduce_role",
        target_role=role,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason=f"Reintroduce {role!r} for payoff impact",
    )


def _bridge_reset_action(
    section_name: str,
    occurrence_index: int,
    intensity: float = 0.85,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="bridge_reset",
        target_role=None,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason="Force bridge density reset — must be meaningfully less full than hook",
    )


def _outro_resolution_action(
    section_name: str,
    occurrence_index: int,
    intensity: float = 0.7,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="outro_resolution",
        target_role=None,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason="Progressive outro resolution — remove weight toward end",
    )


def _suppress_full_stack_action(
    section_name: str,
    occurrence_index: int,
    intensity: float = 0.75,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="suppress_full_stack",
        target_role=None,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason="Suppress full stack — section must not peak too early",
    )


def _strip_to_core_action(
    section_name: str,
    occurrence_index: int,
    intensity: float = 0.8,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="strip_to_core",
        target_role=None,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason="Strip to core — limited source material, keep only essentials",
    )


def _force_payoff_action(
    section_name: str,
    occurrence_index: int,
    intensity: float = 0.95,
) -> DecisionAction:
    return DecisionAction(
        section_name=section_name,
        occurrence_index=occurrence_index,
        action_type="force_payoff",
        target_role=None,
        bar_start=None,
        bar_end=None,
        intensity=intensity,
        reason="Force payoff — hook must feel earned relative to verse restraint",
    )


# ---------------------------------------------------------------------------
# Scoring helpers
# ---------------------------------------------------------------------------


def _compute_global_contrast_score(decisions: List[SectionDecision]) -> float:
    """Compute global contrast score from 0.0 to 1.0.

    Heuristics:
    - Strong contrast between verse and hook (verse sparse/medium, hook full) = bonus
    - Pre-hook subtraction before hook = bonus
    - Bridge is sparse while hooks are full = bonus
    - Outro is sparse = small bonus
    - Full stack in intro or verse 1 = penalty
    - Bridge is full = large penalty
    """
    if not decisions:
        return 0.0

    score = 0.5  # base

    section_map: Dict[str, List[SectionDecision]] = {}
    for d in decisions:
        stype = _derive_section_type(d.section_name)
        section_map.setdefault(stype, []).append(d)

    hook_decisions = section_map.get("hook", [])
    verse_decisions = section_map.get("verse", [])
    pre_hook_decisions = section_map.get("pre_hook", [])
    bridge_decisions = section_map.get("bridge", [])
    outro_decisions = section_map.get("outro", [])
    breakdown_decisions = section_map.get("breakdown", [])
    intro_decisions = section_map.get("intro", [])

    # Bonus: verse is sparse/medium AND hook is full.
    if verse_decisions and hook_decisions:
        verse_not_full = all(d.target_fullness != "full" for d in verse_decisions)
        hook_full = any(d.target_fullness == "full" for d in hook_decisions)
        if verse_not_full and hook_full:
            score += 0.20

    # Bonus: verse 1 is specifically sparse.
    if verse_decisions and verse_decisions[0].target_fullness == "sparse":
        score += 0.05

    # Bonus: pre-hook has subtractions before hook.
    if pre_hook_decisions and hook_decisions:
        pre_hook_has_subtraction = any(
            d.subtraction_count > 0 for d in pre_hook_decisions
        )
        if pre_hook_has_subtraction:
            score += 0.10

    # Bonus: bridge is sparse.
    all_bridge = bridge_decisions + breakdown_decisions
    if all_bridge:
        bridge_sparse = all(d.target_fullness == "sparse" for d in all_bridge)
        if bridge_sparse and hook_decisions:
            score += 0.10
        # Penalty: bridge is full.
        if any(d.target_fullness == "full" for d in all_bridge):
            score -= 0.25

    # Bonus: outro is sparse.
    if outro_decisions and all(d.target_fullness == "sparse" for d in outro_decisions):
        score += 0.05

    # Penalty: full stack in intro.
    if intro_decisions and any(d.allow_full_stack for d in intro_decisions):
        score -= 0.15

    # Penalty: full stack in verse 1.
    if verse_decisions and verse_decisions[0].allow_full_stack:
        score -= 0.20

    # Bonus: hooks escalate (each hook has >= 1 reentry).
    if len(hook_decisions) >= 2:
        hooks_with_reentry = sum(1 for d in hook_decisions if d.reentry_count > 0)
        if hooks_with_reentry >= 1:
            score += 0.05

    return round(max(0.0, min(1.0, score)), 4)


def _compute_payoff_readiness_score(decisions: List[SectionDecision]) -> float:
    """Compute payoff readiness score from 0.0 to 1.0.

    Measures how well the arrangement has built up before each hook:
    - pre-hook subtraction immediately before hook = strong bonus
    - hook has reentries (held-back material released) = bonus
    - hooks get progressively bigger = bonus
    """
    if not decisions:
        return 0.0

    score = 0.3  # base

    # Walk through the decision sequence and look for pre-hook → hook pairs.
    prev_was_pre_hook = False
    prev_pre_hook_had_subtraction = False
    hook_count = 0
    hook_with_reentry_count = 0

    for d in decisions:
        stype = _derive_section_type(d.section_name)

        if stype == "pre_hook":
            prev_was_pre_hook = True
            prev_pre_hook_had_subtraction = d.subtraction_count > 0
        elif stype == "hook":
            hook_count += 1
            # Bonus: preceded by a pre-hook with subtraction.
            if prev_was_pre_hook and prev_pre_hook_had_subtraction:
                score += 0.20
            # Bonus: hook releases held-back material.
            if d.reentry_count > 0:
                score += 0.10
                hook_with_reentry_count += 1
            prev_was_pre_hook = False
            prev_pre_hook_had_subtraction = False
        else:
            prev_was_pre_hook = False
            prev_pre_hook_had_subtraction = False

    # Cap contribution from multiple hooks so score stays ≤ 1.0.
    return round(max(0.0, min(1.0, score)), 4)


def _build_decision_fingerprint(
    subtractions: List[DecisionAction],
    reentries: List[DecisionAction],
    fullness: str,
) -> FrozenSet[Tuple[str, Optional[str]]]:
    """Build a hashable fingerprint for a section decision."""
    items: List[Tuple[str, Optional[str]]] = []
    items.append(("fullness", fullness))
    for a in subtractions:
        items.append((a.action_type, a.target_role))
    for a in reentries:
        items.append((a.action_type, a.target_role))
    return frozenset(items)


def _compute_section_decision_score(
    section_type: str,
    occurrence_index: int,
    target_fullness: str,
    allow_full_stack: bool,
    subtractions: List[DecisionAction],
    reentries: List[DecisionAction],
    state: DecisionEngineState,
) -> float:
    """Compute a per-section decision quality score [0.0, 1.0]."""
    score = 0.5

    # Hooks should be full and have reentries.
    if section_type == "hook":
        if target_fullness == "full":
            score += 0.15
        if reentries:
            score += 0.15
        if not reentries and state.has_held_back_roles():
            score -= 0.10  # Held-back material existed but wasn't released.

    # Verse 1 should not be full.
    if section_type == "verse" and occurrence_index == 0:
        if target_fullness in ("sparse", "medium"):
            score += 0.10
        if allow_full_stack:
            score -= 0.30

    # Pre-hook should subtract.
    if section_type == "pre_hook":
        if subtractions:
            score += 0.20
        else:
            score -= 0.10

    # Bridge should be sparse.
    if section_type in ("bridge", "breakdown"):
        if target_fullness == "sparse":
            score += 0.15
        elif target_fullness == "full":
            score -= 0.25

    # Outro should be sparse.
    if section_type == "outro":
        if target_fullness == "sparse":
            score += 0.10

    # Repeated sections should differ.
    if occurrence_index > 0 and state.section_fingerprints_are_identical(section_type):
        score -= 0.15

    return round(max(0.0, min(1.0, score)), 4)


# ---------------------------------------------------------------------------
# DecisionPlanner
# ---------------------------------------------------------------------------


class DecisionPlanner:
    """Build a :class:`~app.services.decision_engine.types.DecisionPlan` from
    an arrangement's section sequence.

    Parameters
    ----------
    source_quality:
        Source quality mode string (e.g. ``"true_stems"``, ``"stereo_fallback"``).
    available_roles:
        Instrument roles present in the source material.
    context:
        Optional dict with additional context (e.g. summaries from upstream
        engines).  Keys recognised:

        * ``section_energies``    – dict mapping section name → energy [0,1]
        * ``active_roles``        – list of roles currently active (overrides
                                     ``available_roles`` per section if provided)
        * ``pattern_variation_summary`` – opaque summary from Pattern Variation Engine
        * ``groove_summary``      – opaque summary from Groove Engine
        * ``drop_summary``        – opaque summary from Drop Engine
        * ``motif_summary``       – opaque summary from Motif Engine

    Usage::

        planner = DecisionPlanner(
            source_quality="true_stems",
            available_roles=["kick", "bass", "chords", "melody", "pad"],
        )
        plan = planner.build(sections=[...])
    """

    def __init__(
        self,
        source_quality: str = "stereo_fallback",
        available_roles: Optional[List[str]] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.source_quality = source_quality
        self.available_roles: List[str] = list(available_roles or [])
        self.context: Dict[str, Any] = context or {}

    def build(
        self,
        sections: List[Dict[str, Any]],
    ) -> DecisionPlan:
        """Build a :class:`DecisionPlan` from an arrangement section sequence.

        Parameters
        ----------
        sections:
            Ordered list of section dicts.  Each dict must contain at least a
            ``type`` or ``name`` key identifying the section type.

        Returns
        -------
        DecisionPlan
            The complete producer decision plan.
        """
        if not sections:
            return DecisionPlan(
                section_decisions=[],
                global_contrast_score=0.0,
                payoff_readiness_score=0.0,
                fallback_used=True,
                warnings=["No sections provided — returning empty plan"],
            )

        is_limited = self.source_quality in LIMITED_SOURCE_QUALITIES
        fallback_used = is_limited or len(self.available_roles) < MIN_ROLES_FOR_SUBTRACTION

        state = DecisionEngineState()
        decisions: List[SectionDecision] = []
        warnings: List[str] = []

        for section in sections:
            raw_name = str(section.get("type") or section.get("name") or "verse")
            section_type = _derive_section_type(raw_name)
            occurrence_index = state.get_occurrence_index(section_type)

            # Build this section's decision.
            decision = self._build_section_decision(
                section_name=raw_name,
                section_type=section_type,
                occurrence_index=occurrence_index,
                state=state,
                fallback_used=fallback_used,
                warnings=warnings,
            )
            decisions.append(decision)

            # Update state from this decision.
            fingerprint = _build_decision_fingerprint(
                subtractions=decision.required_subtractions,
                reentries=decision.required_reentries,
                fullness=decision.target_fullness,
            )
            state.record_section(
                section_name=raw_name,
                section_type=section_type,
                fullness=decision.target_fullness,
                action_fingerprint=fingerprint,
                allow_full_stack=decision.allow_full_stack,
            )

            # Update held-back tracking based on decision actions.
            for action in decision.required_subtractions:
                if action.target_role and action.action_type in (
                    "hold_back_role",
                    "pre_hook_subtraction",
                    "remove_role",
                ):
                    state.hold_back_role(action.target_role)

            for action in decision.required_reentries:
                if action.target_role and action.action_type == "reintroduce_role":
                    state.reintroduce_role(action.target_role)

        # Compute global scores.
        contrast = _compute_global_contrast_score(decisions)
        payoff = _compute_payoff_readiness_score(decisions)

        logger.debug(
            "DecisionPlanner: built plan — sections=%d contrast=%.3f payoff=%.3f "
            "fallback=%s warnings=%d",
            len(decisions),
            contrast,
            payoff,
            fallback_used,
            len(warnings),
        )

        return DecisionPlan(
            section_decisions=decisions,
            global_contrast_score=contrast,
            payoff_readiness_score=payoff,
            fallback_used=fallback_used,
            warnings=warnings,
        )

    def _build_section_decision(
        self,
        section_name: str,
        section_type: str,
        occurrence_index: int,
        state: DecisionEngineState,
        fallback_used: bool,
        warnings: List[str],
    ) -> SectionDecision:
        """Build the decision for a single section."""
        subtractions: List[DecisionAction] = []
        reentries: List[DecisionAction] = []
        rationale: List[str] = []

        currently_held_back = list(state.held_back_roles)

        # --- Determine allow_full_stack ---
        allow_full = section_can_allow_full_stack(
            section_type=section_type,
            source_quality=self.source_quality,
            available_roles=self.available_roles,
            occurrence_index=occurrence_index,
            prior_hook_fullness=state.last_hook_fullness(),
        )

        # --- Determine target fullness ---
        target_fullness = compute_target_fullness(
            section_type=section_type,
            source_quality=self.source_quality,
            available_roles=self.available_roles,
            occurrence_index=occurrence_index,
            held_back_count=len(currently_held_back),
        )

        # --- Section-type-specific rules ---

        if section_type == "intro":
            self._apply_intro_rules(
                section_name, occurrence_index, state, subtractions, rationale, warnings
            )

        elif section_type == "verse":
            self._apply_verse_rules(
                section_name, occurrence_index, state, subtractions, reentries,
                rationale, warnings
            )

        elif section_type == "pre_hook":
            self._apply_pre_hook_rules(
                section_name, occurrence_index, state, subtractions, rationale, warnings
            )

        elif section_type == "hook":
            self._apply_hook_rules(
                section_name, occurrence_index, state, subtractions, reentries,
                rationale, warnings
            )

        elif section_type in ("bridge", "breakdown"):
            self._apply_bridge_rules(
                section_name, occurrence_index, state, subtractions, rationale, warnings
            )

        elif section_type == "outro":
            self._apply_outro_rules(
                section_name, occurrence_index, state, subtractions, rationale, warnings
            )

        # --- Force outro resolution if needed ---
        if section_type == "outro" and should_force_outro_resolution(
            section_type, target_fullness, self.source_quality
        ):
            if not any(a.action_type == "outro_resolution" for a in subtractions):
                subtractions.append(
                    _outro_resolution_action(section_name, occurrence_index)
                )
                rationale.append("Forced outro resolution — outro must not end full")

        # --- Force bridge reset if needed ---
        if section_type in ("bridge", "breakdown") and should_force_bridge_reset(
            section_type,
            state.last_hook_fullness(),
            self.source_quality,
            self.available_roles,
        ):
            if not any(a.action_type == "bridge_reset" for a in subtractions):
                subtractions.append(
                    _bridge_reset_action(section_name, occurrence_index)
                )
                rationale.append("Forced bridge reset — must be less full than hook")

        # --- Suppress full stack if allow_full is False and no suppression yet ---
        if not allow_full and section_type not in ("hook",):
            if not any(a.action_type == "suppress_full_stack" for a in subtractions):
                subtractions.append(
                    _suppress_full_stack_action(section_name, occurrence_index)
                )
                rationale.append(
                    f"Suppress full stack — {section_type} must not peak too early"
                )

        # --- Warn if repeated section has identical decision pattern ---
        if occurrence_index > 0 and self.available_roles:
            fp = _build_decision_fingerprint(subtractions, reentries, target_fullness)
            existing = state.section_decision_fingerprints.get(section_type, [])
            if existing and all(e == fp for e in existing):
                warnings.append(
                    f"Section '{section_name}' (type={section_type}, "
                    f"occurrence={occurrence_index}) has identical decision pattern "
                    f"to previous occurrence(s)"
                )

        # Determine protected roles (core roles not being subtracted).
        protected = [
            r for r in self.available_roles
            if r in {"kick", "bass", "drums", "melody", "lead"}
            and r not in [a.target_role for a in subtractions if a.target_role]
        ]

        # Blocked roles = currently held back + roles we just added.
        blocked: List[str] = []
        for action in subtractions:
            if action.target_role and action.action_type in (
                "hold_back_role",
                "remove_role",
            ):
                blocked.append(action.target_role)

        score = _compute_section_decision_score(
            section_type=section_type,
            occurrence_index=occurrence_index,
            target_fullness=target_fullness,
            allow_full_stack=allow_full,
            subtractions=subtractions,
            reentries=reentries,
            state=state,
        )

        return SectionDecision(
            section_name=section_name,
            occurrence_index=occurrence_index,
            target_fullness=target_fullness,
            allow_full_stack=allow_full,
            required_subtractions=subtractions,
            required_reentries=reentries,
            protected_roles=protected,
            blocked_roles=blocked,
            decision_score=score,
            rationale=rationale,
        )

    # -------------------------------------------------------------------------
    # Per-section-type rule application
    # -------------------------------------------------------------------------

    def _apply_intro_rules(
        self,
        section_name: str,
        occurrence_index: int,
        state: DecisionEngineState,
        subtractions: List[DecisionAction],
        rationale: List[str],
        warnings: List[str],
    ) -> None:
        """Intro: hold back most non-core layers; tease identity."""
        rationale.append("Intro: tease identity — do not reveal full arrangement")

        if len(self.available_roles) < MIN_ROLES_FOR_SUBTRACTION:
            rationale.append("Limited roles — applying minimal restraint only")
            return

        roles_to_hold = choose_roles_to_hold_back(
            available_roles=self.available_roles,
            source_quality=self.source_quality,
            section_type="intro",
            occurrence_index=occurrence_index,
            already_held_back=list(state.held_back_roles),
        )
        for role in roles_to_hold:
            subtractions.append(
                _hold_back_action(section_name, occurrence_index, role, intensity=0.85)
            )
            rationale.append(f"Hold back {role!r} in intro")

    def _apply_verse_rules(
        self,
        section_name: str,
        occurrence_index: int,
        state: DecisionEngineState,
        subtractions: List[DecisionAction],
        reentries: List[DecisionAction],
        rationale: List[str],
        warnings: List[str],
    ) -> None:
        """Verse rules: no full stack in Verse 1; Verse 2 may evolve."""
        if occurrence_index == 0:
            rationale.append("Verse 1: must not be full — preserve room for growth")
            roles_to_hold = choose_roles_to_hold_back(
                available_roles=self.available_roles,
                source_quality=self.source_quality,
                section_type="verse",
                occurrence_index=0,
                already_held_back=list(state.held_back_roles),
            )
            for role in roles_to_hold:
                subtractions.append(
                    _hold_back_action(section_name, occurrence_index, role, intensity=0.8)
                )
                rationale.append(f"Suppress {role!r} in Verse 1")

        else:
            rationale.append(
                "Verse 2+: must differ from Verse 1 — allow strategic reintroduction"
            )
            # Allow one strategic reintroduction.
            roles_to_reintroduce = choose_roles_to_reintroduce(
                held_back_roles=sorted(state.held_back_roles),
                section_type="verse",
                source_quality=self.source_quality,
                occurrence_index=occurrence_index,
            )
            for role in roles_to_reintroduce:
                reentries.append(
                    _reintroduce_action(section_name, occurrence_index, role, intensity=0.6)
                )
                rationale.append(f"Strategic reintroduction of {role!r} in Verse 2+")

            # Still hold back something to maintain restraint vs. hook.
            still_available = [
                r for r in self.available_roles if r not in state.reintroduced_roles
            ]
            extra_holds = choose_roles_to_hold_back(
                available_roles=still_available,
                source_quality=self.source_quality,
                section_type="verse",
                occurrence_index=occurrence_index,
                already_held_back=list(state.held_back_roles),
            )
            for role in extra_holds:
                subtractions.append(
                    _hold_back_action(section_name, occurrence_index, role, intensity=0.7)
                )
                rationale.append(f"Hold back {role!r} in Verse 2+ to maintain hook headroom")

    def _apply_pre_hook_rules(
        self,
        section_name: str,
        occurrence_index: int,
        state: DecisionEngineState,
        subtractions: List[DecisionAction],
        rationale: List[str],
        warnings: List[str],
    ) -> None:
        """Pre-hook: create tension through subtraction."""
        rationale.append("Pre-hook: create tension — subtract before hook re-entry")
        roles_to_remove = choose_roles_to_remove_for_tension(
            available_roles=self.available_roles,
            source_quality=self.source_quality,
            currently_held_back=list(state.held_back_roles),
        )
        if roles_to_remove:
            for role in roles_to_remove:
                subtractions.append(
                    _remove_for_tension_action(section_name, occurrence_index, role)
                )
                rationale.append(f"Remove {role!r} for pre-hook tension")
        else:
            rationale.append(
                "No suitable tension-removal candidate — applying density suppression"
            )

    def _apply_hook_rules(
        self,
        section_name: str,
        occurrence_index: int,
        state: DecisionEngineState,
        subtractions: List[DecisionAction],
        reentries: List[DecisionAction],
        rationale: List[str],
        warnings: List[str],
    ) -> None:
        """Hook rules: reintroduce held-back material; force payoff."""
        held = sorted(state.held_back_roles)
        roles_to_reintroduce = choose_roles_to_reintroduce(
            held_back_roles=held,
            section_type="hook",
            source_quality=self.source_quality,
            occurrence_index=occurrence_index,
        )
        if roles_to_reintroduce:
            for role in roles_to_reintroduce:
                reentries.append(
                    _reintroduce_action(section_name, occurrence_index, role)
                )
                rationale.append(f"Reintroduce {role!r} for hook payoff")
            reentries.append(_force_payoff_action(section_name, occurrence_index))
            rationale.append("Force hook payoff")
        else:
            if occurrence_index == 0:
                rationale.append(
                    "Hook 1: no held-back material to reintroduce — payoff limited"
                )
                warnings.append(
                    f"Hook '{section_name}': no held-back material available for "
                    "reintroduction; payoff may feel weak"
                )
            else:
                # Subsequent hooks with nothing held back — still force payoff.
                reentries.append(_force_payoff_action(section_name, occurrence_index))
                rationale.append("Hook payoff — escalate energy even without held-back material")

        if occurrence_index >= 1:
            rationale.append(
                f"Hook {occurrence_index + 1}: must feel bigger or more confident "
                "than previous hook"
            )

    def _apply_bridge_rules(
        self,
        section_name: str,
        occurrence_index: int,
        state: DecisionEngineState,
        subtractions: List[DecisionAction],
        rationale: List[str],
        warnings: List[str],
    ) -> None:
        """Bridge/Breakdown: must reset energy and density."""
        rationale.append("Bridge/Breakdown: reset energy — must be less full than hook")
        roles_to_hold = choose_roles_to_hold_back(
            available_roles=self.available_roles,
            source_quality=self.source_quality,
            section_type="bridge",
            occurrence_index=occurrence_index,
            already_held_back=list(state.held_back_roles),
        )
        for role in roles_to_hold:
            subtractions.append(
                _hold_back_action(section_name, occurrence_index, role, intensity=0.9)
            )
            rationale.append(f"Strip {role!r} for bridge reset")

    def _apply_outro_rules(
        self,
        section_name: str,
        occurrence_index: int,
        state: DecisionEngineState,
        subtractions: List[DecisionAction],
        rationale: List[str],
        warnings: List[str],
    ) -> None:
        """Outro: resolve progressively; remove weight."""
        rationale.append("Outro: resolve — remove weight progressively")
        # Always emit an explicit outro_resolution action as the producer signal.
        subtractions.append(_outro_resolution_action(section_name, occurrence_index))
        rationale.append("Outro resolution action — remove weight toward end")
        # Hold back anything remaining.
        roles_to_hold = choose_roles_to_hold_back(
            available_roles=self.available_roles,
            source_quality=self.source_quality,
            section_type="outro",
            occurrence_index=occurrence_index,
            already_held_back=list(state.held_back_roles),
        )
        for role in roles_to_hold:
            subtractions.append(
                _hold_back_action(section_name, occurrence_index, role, intensity=0.75)
            )
            rationale.append(f"Remove {role!r} for outro resolution")
