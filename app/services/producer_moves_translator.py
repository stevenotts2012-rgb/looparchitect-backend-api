"""Producer Moves Translator.

Translates high-level UI producer move names into structured planning intents
that guide the timeline engine, pattern variation engine, and section planner.

Producer moves are *preference inputs* — they become hints to the deeper
planning system rather than direct, one-to-one arrangement events.

Architecture
------------
``translate_producer_moves(moves)``
    → resolves aliases, detects and resolves conflicts, returns a
      :class:`MoveTranslationResult` containing:

    * ``selected_producer_moves``   – normalised accepted move names
    * ``translated_planning_intents`` – structured intents (one per move)
    * ``timeline_events_from_moves``  – bar-level timeline event hints
    * ``pattern_events_from_moves``   – pattern-level action hints
    * ``conflicting_moves_resolved``  – log of conflicts that were fixed

Usage::

    from app.services.producer_moves_translator import translate_producer_moves

    result = translate_producer_moves(["hook_drop", "bridge_breakdown"])
    # result.translated_planning_intents contains dicts with section_intent,
    # timeline_intent, pattern_intent, transition_intent etc.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core intent data types
# ---------------------------------------------------------------------------


@dataclass
class PlanningIntent:
    """Structured planning intent derived from a single producer move.

    Attributes:
        move_name: Canonical move name (e.g. ``"hook_drop"``).
        section_intent: Human-readable description of the section-level planning
            goal, e.g. ``"pre_hook_tension_plus_controlled_hook_reentry"``.
        timeline_intent: The kind of timeline event this move implies, drawn from
            the set of :class:`~app.services.timeline_engine.types.TimelineEvent`
            action strings (e.g. ``"riser_to_crash"``, ``"drum_fill"``).
        pattern_intent: The pattern-level action this move implies, corresponding
            to :class:`~app.services.pattern_variation_engine.types.PatternAction`
            values (e.g. ``"hat_density_up"``, ``"bass_dropout"``).
        transition_intent: The transition type this move suggests, e.g.
            ``"fx_hit"``, ``"mute_drop"``, ``"crossfade"``, ``"none"``.
        target_sections: Section types this move affects, e.g.
            ``["hook", "pre_hook"]``.
        energy_modifier: Signed fractional energy adjustment for target sections,
            clamped to [−1, +1].  Positive values raise energy; negative reduce it.
        density_modifier: Signed fractional layer-density adjustment, clamped to
            [−1, +1].  Applied as a multiplier against the current layer count.
        parameters: Move-specific key/value pairs for downstream engine use.
    """

    move_name: str
    section_intent: str
    timeline_intent: str
    pattern_intent: str
    transition_intent: str
    target_sections: List[str]
    energy_modifier: float = 0.0
    density_modifier: float = 0.0
    parameters: Dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "move_name": self.move_name,
            "section_intent": self.section_intent,
            "timeline_intent": self.timeline_intent,
            "pattern_intent": self.pattern_intent,
            "transition_intent": self.transition_intent,
            "target_sections": list(self.target_sections),
            "energy_modifier": self.energy_modifier,
            "density_modifier": self.density_modifier,
            "parameters": dict(self.parameters),
        }


@dataclass
class MoveTranslationResult:
    """Result of translating a set of producer moves into planning intents.

    This is the observability-ready output consumed by
    :class:`~app.services.producer_moves_engine.ProducerMovesEngine`.

    Attributes:
        selected_producer_moves: Normalised move names that were accepted.
        translated_planning_intents: One intent dict per accepted move.
        timeline_events_from_moves: Bar-level timeline hint dicts.
        pattern_events_from_moves: Pattern-level hint dicts.
        conflicting_moves_resolved: Human-readable conflict resolution log.
    """

    selected_producer_moves: List[str] = field(default_factory=list)
    translated_planning_intents: List[dict] = field(default_factory=list)
    timeline_events_from_moves: List[dict] = field(default_factory=list)
    pattern_events_from_moves: List[dict] = field(default_factory=list)
    conflicting_moves_resolved: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "selected_producer_moves": list(self.selected_producer_moves),
            "translated_planning_intents": list(self.translated_planning_intents),
            "timeline_events_from_moves": list(self.timeline_events_from_moves),
            "pattern_events_from_moves": list(self.pattern_events_from_moves),
            "conflicting_moves_resolved": list(self.conflicting_moves_resolved),
        }

    # Convenience helpers -------------------------------------------------

    def has_move(self, move_name: str) -> bool:
        return move_name in self.selected_producer_moves

    def intents_for_section(self, section_type: str) -> List[dict]:
        """Return all intents that target *section_type*."""
        return [
            i for i in self.translated_planning_intents
            if section_type in i.get("target_sections", [])
        ]

    def combined_energy_modifier(self, section_type: str) -> float:
        """Return the sum of energy_modifier values for *section_type*."""
        return sum(
            float(i.get("energy_modifier", 0.0))
            for i in self.intents_for_section(section_type)
        )

    def combined_density_modifier(self, section_type: str) -> float:
        """Return the sum of density_modifier values for *section_type*."""
        return sum(
            float(i.get("density_modifier", 0.0))
            for i in self.intents_for_section(section_type)
        )


# ---------------------------------------------------------------------------
# Move alias table  (UI display name → canonical name)
# ---------------------------------------------------------------------------

_MOVE_ALIASES: Dict[str, str] = {
    # Hook Drop
    "hook drop": "hook_drop",
    "hook_drop": "hook_drop",
    "hookdrop": "hook_drop",
    # End-of-Section Fill
    "end-of-section fill": "end_of_section_fill",
    "end_of_section_fill": "end_of_section_fill",
    "end of section fill": "end_of_section_fill",
    "eos fill": "end_of_section_fill",
    # Pre-Hook Mute
    "pre-hook mute": "pre_hook_mute",
    "pre_hook_mute": "pre_hook_mute",
    "prehook mute": "pre_hook_mute",
    "pre hook mute": "pre_hook_mute",
    # Silence Drop
    "silence drop": "silence_drop",
    "silence_drop": "silence_drop",
    # Verse Space
    "verse space": "verse_space",
    "verse_space": "verse_space",
    # 8-Bar Hat Roll
    "8-bar hat roll": "eight_bar_hat_roll",
    "eight_bar_hat_roll": "eight_bar_hat_roll",
    "8_bar_hat_roll": "eight_bar_hat_roll",
    "8bar hat roll": "eight_bar_hat_roll",
    "hat roll": "eight_bar_hat_roll",
    "8 bar hat roll": "eight_bar_hat_roll",
    # Layer Lift
    "layer lift": "layer_lift",
    "layer_lift": "layer_lift",
    # Bridge Breakdown
    "bridge breakdown": "bridge_breakdown",
    "bridge_breakdown": "bridge_breakdown",
    # Final Hook Expansion
    "final hook expansion": "final_hook_expansion",
    "final_hook_expansion": "final_hook_expansion",
    # Call-and-Response
    "call-and-response": "call_and_response",
    "call_and_response": "call_and_response",
    "call and response": "call_and_response",
    "call_response": "call_and_response",
    # Intro Tease
    "intro tease": "intro_tease",
    "intro_tease": "intro_tease",
    # Outro Strip
    "outro strip": "outro_strip",
    "outro_strip": "outro_strip",
}


# ---------------------------------------------------------------------------
# Move registry  (canonical name → PlanningIntent)
# ---------------------------------------------------------------------------

_MOVE_REGISTRY: Dict[str, PlanningIntent] = {
    "hook_drop": PlanningIntent(
        move_name="hook_drop",
        section_intent="pre_hook_tension_plus_controlled_hook_reentry_denser_hook_pattern",
        timeline_intent="riser_to_crash",
        pattern_intent="hat_density_up_reentry_808",
        transition_intent="fx_hit",
        target_sections=["hook", "pre_hook"],
        energy_modifier=0.12,
        density_modifier=0.20,
        parameters={
            "pre_hook_tension": True,
            "hook_reentry": "controlled",
            "pattern": "denser",
        },
    ),
    "end_of_section_fill": PlanningIntent(
        move_name="end_of_section_fill",
        section_intent="section_end_activity",
        timeline_intent="drum_fill",
        pattern_intent="snare_fill",
        transition_intent="drum_fill",
        target_sections=["verse", "hook", "bridge", "intro", "outro", "pre_hook"],
        energy_modifier=0.05,
        density_modifier=0.0,
        parameters={"fill_type": "drum_fill"},
    ),
    "pre_hook_mute": PlanningIntent(
        move_name="pre_hook_mute",
        section_intent="tension_build_before_hook",
        timeline_intent="mute_drop",
        pattern_intent="pre_drop_silence",
        transition_intent="silence_drop",
        target_sections=["pre_hook", "hook"],
        energy_modifier=-0.08,
        density_modifier=-0.25,
        parameters={"mute_target": "drums", "duration_bars": 1},
    ),
    "silence_drop": PlanningIntent(
        move_name="silence_drop",
        section_intent="silence_before_hook_impact",
        timeline_intent="silence_drop",
        pattern_intent="pre_drop_silence",
        transition_intent="silence_drop",
        target_sections=["hook"],
        energy_modifier=-0.12,
        density_modifier=-0.35,
        parameters={"silence_duration_bars": 1, "pre_hook": True},
    ),
    "verse_space": PlanningIntent(
        move_name="verse_space",
        section_intent="melody_reduction_for_vocal_space",
        timeline_intent="pull_back",
        pattern_intent="melody_dropout",
        transition_intent="pull_back",
        target_sections=["verse"],
        energy_modifier=-0.05,
        density_modifier=-0.20,
        parameters={"remove_melody": True, "vocal_space": True},
    ),
    "eight_bar_hat_roll": PlanningIntent(
        move_name="eight_bar_hat_roll",
        section_intent="repeated_high_frequency_rhythmic_variation_plan",
        timeline_intent="hat_density_variation_every_4_bars",
        pattern_intent="hat_density_up",
        transition_intent="none",
        target_sections=["verse", "hook"],
        energy_modifier=0.05,
        density_modifier=0.10,
        parameters={"interval_bars": 4, "repeat": True, "variation": "rhythmic"},
    ),
    "layer_lift": PlanningIntent(
        move_name="layer_lift",
        section_intent="add_instrument_layer",
        timeline_intent="add_layer",
        pattern_intent="counter_melody_add",
        transition_intent="fx_rise",
        target_sections=["verse", "hook", "bridge"],
        energy_modifier=0.10,
        density_modifier=0.15,
        parameters={"add_layer": True},
    ),
    "bridge_breakdown": PlanningIntent(
        move_name="bridge_breakdown",
        section_intent="reduced_groove_density_sparse_texture_delayed_reentry",
        timeline_intent="mute_drop",
        pattern_intent="bass_dropout",
        transition_intent="mute_drop",
        target_sections=["bridge", "breakdown"],
        energy_modifier=-0.20,
        density_modifier=-0.30,
        parameters={
            "sparse": True,
            "remove": ["kick", "bass", "hats"],
            "delayed_reentry": True,
        },
    ),
    "final_hook_expansion": PlanningIntent(
        move_name="final_hook_expansion",
        section_intent="maximum_energy_final_hook_payoff",
        timeline_intent="fx_hit_plus_hat_density",
        pattern_intent="hat_density_up_reentry_808",
        transition_intent="fx_hit",
        target_sections=["hook"],
        energy_modifier=0.20,
        density_modifier=0.30,
        parameters={"final_hook_only": True, "expand_all_layers": True},
    ),
    "call_and_response": PlanningIntent(
        move_name="call_and_response",
        section_intent="alternating_phrase_density_and_melody_entry_behavior",
        timeline_intent="delayed_melody_entry",
        pattern_intent="call_response",
        transition_intent="pull_back",
        target_sections=["verse", "hook"],
        energy_modifier=0.0,
        density_modifier=0.0,
        parameters={"alternating_phrase": True, "melody_delayed": True},
    ),
    "intro_tease": PlanningIntent(
        move_name="intro_tease",
        section_intent="minimal_intro_progressive_layer_add",
        timeline_intent="delayed_entry",
        pattern_intent="delayed_melody_entry",
        transition_intent="none",
        target_sections=["intro"],
        energy_modifier=-0.10,
        density_modifier=-0.20,
        parameters={"minimal_start": True, "progressive_buildup": True},
    ),
    "outro_strip": PlanningIntent(
        move_name="outro_strip",
        section_intent="progressive_removal_timeline",
        timeline_intent="progressive_layer_removal",
        pattern_intent="bass_dropout",
        transition_intent="crossfade",
        target_sections=["outro"],
        energy_modifier=-0.15,
        density_modifier=-0.25,
        parameters={"progressive": True, "strip_order": ["drums", "bass", "melody"]},
    ),
}


# ---------------------------------------------------------------------------
# Conflict groups
# Each entry: (description, set_of_conflicting_moves, move_to_keep)
# ---------------------------------------------------------------------------

_CONFLICT_GROUPS: List[tuple] = [
    # Both silence the pre-hook transition zone — keep the stronger one
    (
        "pre_hook_silence_conflict: pre_hook_mute and silence_drop both target silence before hook; keeping silence_drop (stronger)",
        frozenset({"pre_hook_mute", "silence_drop"}),
        "silence_drop",
    ),
    # Outro strip and layer lift are contradictory in the outro section
    (
        "outro_direction_conflict: outro_strip (progressive removal) and layer_lift are contradictory in outro; keeping outro_strip",
        frozenset({"outro_strip", "layer_lift"}),
        "outro_strip",
    ),
    # Intro tease wants minimal start; layer lift wants to add a layer — conflicting in intro
    (
        "intro_conflict: intro_tease (minimal start) and layer_lift conflict in intro section; keeping intro_tease",
        frozenset({"intro_tease", "layer_lift"}),
        "intro_tease",
    ),
]


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------


def _normalise_move(raw: str) -> Optional[str]:
    """Return the canonical move name for *raw*, or ``None`` if unrecognised."""
    key = str(raw or "").strip().lower()
    return _MOVE_ALIASES.get(key)


def _resolve_conflicts(
    moves: List[str],
) -> tuple[List[str], List[str]]:
    """Apply conflict resolution rules to *moves*.

    Returns a tuple of ``(resolved_moves, conflict_log)``.
    """
    move_set = set(moves)
    conflict_log: List[str] = []

    for description, conflict_set, keep in _CONFLICT_GROUPS:
        if conflict_set.issubset(move_set):
            remove_set = conflict_set - {keep}
            move_set -= remove_set
            conflict_log.append(description)
            logger.debug("Conflict resolved: %s", description)

    # Deduplicate while preserving original order
    seen: set[str] = set()
    resolved: List[str] = []
    for m in moves:
        if m in move_set and m not in seen:
            seen.add(m)
            resolved.append(m)

    return resolved, conflict_log


def _build_timeline_hints(intents: List[PlanningIntent]) -> List[dict]:
    """Derive bar-level timeline hints from *intents*.

    These are planning hints, not rendered events.  The timeline engine
    may use them to shape its event schedule.
    """
    hints: List[dict] = []
    for intent in intents:
        hints.append({
            "source_move": intent.move_name,
            "timeline_intent": intent.timeline_intent,
            "target_sections": list(intent.target_sections),
            "transition_intent": intent.transition_intent,
            "energy_modifier": intent.energy_modifier,
        })
    return hints


def _build_pattern_hints(intents: List[PlanningIntent]) -> List[dict]:
    """Derive pattern-level hints from *intents*.

    These are planning hints that can guide bar-level pattern variation
    decisions inside each section.
    """
    hints: List[dict] = []
    for intent in intents:
        hints.append({
            "source_move": intent.move_name,
            "pattern_intent": intent.pattern_intent,
            "target_sections": list(intent.target_sections),
            "density_modifier": intent.density_modifier,
            "parameters": dict(intent.parameters),
        })
    return hints


def translate_producer_moves(
    moves: Optional[Sequence[str]],
) -> MoveTranslationResult:
    """Translate a list of UI producer move names into structured planning intents.

    Parameters
    ----------
    moves:
        List of move name strings from the frontend (e.g. ``["Hook Drop",
        "Bridge Breakdown"]``).  Unrecognised moves are silently skipped.
        ``None`` or an empty list returns an empty result.

    Returns
    -------
    MoveTranslationResult
        Ready for consumption by :class:`~app.services.producer_moves_engine.ProducerMovesEngine`.
    """
    if not moves:
        return MoveTranslationResult()

    # 1. Normalise aliases
    normalised: List[str] = []
    for raw in moves:
        canonical = _normalise_move(raw)
        if canonical is None:
            logger.debug("Producer move '%s' is unrecognised — skipped.", raw)
            continue
        normalised.append(canonical)

    if not normalised:
        return MoveTranslationResult()

    # 2. Resolve conflicts
    resolved_moves, conflict_log = _resolve_conflicts(normalised)

    # 3. Look up intents
    intents: List[PlanningIntent] = []
    for move in resolved_moves:
        intent = _MOVE_REGISTRY.get(move)
        if intent is not None:
            intents.append(intent)
        else:
            logger.warning("No registry entry for move '%s' — skipped.", move)

    # 4. Build timeline and pattern hints
    timeline_hints = _build_timeline_hints(intents)
    pattern_hints = _build_pattern_hints(intents)

    return MoveTranslationResult(
        selected_producer_moves=list(resolved_moves),
        translated_planning_intents=[i.to_dict() for i in intents],
        timeline_events_from_moves=timeline_hints,
        pattern_events_from_moves=pattern_hints,
        conflicting_moves_resolved=conflict_log,
    )
