"""
Strict data models for the AI Producer System.

All models are plain dataclasses — no ORM, no DB migration required.
They are JSON-serialisable via ``dataclasses.asdict``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Primitives
# ---------------------------------------------------------------------------

VALID_TRANSITIONS = {
    "cut",
    "fade_in",
    "fade_out",
    "crossfade",
    "drum_fill",
    "riser",
    "drop",
    "reverse_cymbal",
    "stutter",
    "filter_sweep",
    "none",
}

VAGUE_PHRASES = {
    "make it bigger",
    "add more energy",
    "keep it similar",
    "same but stronger",
    "make it better",
    "add more",
    "keep going",
    "just like before",
    "slightly different",
    "a bit louder",
    "more of the same",
    "similar to previous",
    "generic fill",
}


# ---------------------------------------------------------------------------
# AISectionPlan
# ---------------------------------------------------------------------------

@dataclass
class AISectionPlan:
    """AI-proposed plan for a single arrangement section.

    Fields
    ------
    section_name:
        Canonical name, e.g. ``"verse"``, ``"hook"``, ``"bridge"``.
    occurrence:
        1-indexed occurrence counter for repeated section types.
    bars:
        Length of this section in bars.
    target_energy:
        Desired energy level in ``[0.0, 1.0]``.
    target_density:
        Desired layer density in ``[0.0, 1.0]`` (proportion of available
        roles that should be active).
    active_roles:
        Instrument/stem roles that should be present throughout.
    introduced_elements:
        Roles or sound elements first appearing in this section.
    dropped_elements:
        Roles or sound elements removed from the prior section.
    transition_in:
        How the section arrives (must be one of :data:`VALID_TRANSITIONS`).
    transition_out:
        How the section exits (must be one of :data:`VALID_TRANSITIONS`).
    variation_strategy:
        Concrete description of what makes this occurrence different from the
        previous one (required when ``occurrence > 1``).
    micro_timeline_notes:
        Free-form production notes for internal micro-plan events.
    rationale:
        Why this section was planned this way.
    """

    section_name: str
    occurrence: int
    bars: int
    target_energy: float
    target_density: float
    active_roles: list[str] = field(default_factory=list)
    introduced_elements: list[str] = field(default_factory=list)
    dropped_elements: list[str] = field(default_factory=list)
    transition_in: str = "cut"
    transition_out: str = "cut"
    variation_strategy: str = ""
    micro_timeline_notes: str = ""
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.section_name:
            raise ValueError("section_name must not be empty")
        if self.occurrence < 1:
            raise ValueError(f"occurrence must be >= 1, got {self.occurrence}")
        if self.bars < 1:
            raise ValueError(f"bars must be >= 1, got {self.bars}")
        if not (0.0 <= self.target_energy <= 1.0):
            raise ValueError(
                f"target_energy must be in [0.0, 1.0], got {self.target_energy}"
            )
        if not (0.0 <= self.target_density <= 1.0):
            raise ValueError(
                f"target_density must be in [0.0, 1.0], got {self.target_density}"
            )
        if self.transition_in not in VALID_TRANSITIONS:
            raise ValueError(
                f"transition_in '{self.transition_in}' not in VALID_TRANSITIONS"
            )
        if self.transition_out not in VALID_TRANSITIONS:
            raise ValueError(
                f"transition_out '{self.transition_out}' not in VALID_TRANSITIONS"
            )


# ---------------------------------------------------------------------------
# AIMicroPlanEvent
# ---------------------------------------------------------------------------

@dataclass
class AIMicroPlanEvent:
    """A single micro-level production event within a section.

    Fields
    ------
    bar_start:
        1-indexed bar where the event begins (relative to section start).
    bar_end:
        1-indexed bar where the event ends (inclusive, relative to section start).
    role:
        Target instrument/stem role.
    action:
        Concrete action, e.g. ``"add_layer"``, ``"mute"``, ``"drum_fill"``,
        ``"filter_sweep"``, ``"pitch_bend"``.
    intensity:
        Strength of the action in ``[0.0, 1.0]``.
    notes:
        Brief description of the intended effect.
    """

    bar_start: int
    bar_end: int
    role: str
    action: str
    intensity: float
    notes: str = ""

    def __post_init__(self) -> None:
        if self.bar_start < 1:
            raise ValueError(f"bar_start must be >= 1, got {self.bar_start}")
        if self.bar_end < self.bar_start:
            raise ValueError(
                f"bar_end ({self.bar_end}) must be >= bar_start ({self.bar_start})"
            )
        if not self.role:
            raise ValueError("role must not be empty")
        if not self.action:
            raise ValueError("action must not be empty")
        if not (0.0 <= self.intensity <= 1.0):
            raise ValueError(
                f"intensity must be in [0.0, 1.0], got {self.intensity}"
            )


# ---------------------------------------------------------------------------
# AIProducerPlan
# ---------------------------------------------------------------------------

@dataclass
class AIProducerPlan:
    """The complete AI-proposed producer plan for an arrangement.

    Fields
    ------
    section_plans:
        Ordered list of :class:`AISectionPlan` objects.
    micro_plan_events:
        All micro-level events across all sections.
    global_energy_curve:
        Per-section target energy values (same length as ``section_plans``).
    novelty_targets:
        Mapping of ``"section_name:occurrence"`` → novelty descriptor string.
    risk_flags:
        List of strings describing potential arrangement risks.
    planner_notes:
        Free-form notes from the planner agent for debugging.
    """

    section_plans: list[AISectionPlan] = field(default_factory=list)
    micro_plan_events: list[AIMicroPlanEvent] = field(default_factory=list)
    global_energy_curve: list[float] = field(default_factory=list)
    novelty_targets: dict[str, str] = field(default_factory=dict)
    risk_flags: list[str] = field(default_factory=list)
    planner_notes: str = ""


# ---------------------------------------------------------------------------
# AICriticScore
# ---------------------------------------------------------------------------

@dataclass
class AICriticScore:
    """Scores produced by the Critic Agent.

    All numeric scores are in ``[0.0, 1.0]``.

    Fields
    ------
    repeated_section_contrast_score:
        Repeated sections must differ meaningfully.
    hook_payoff_score:
        Hook must feel like payoff, not just a louder verse.
    timeline_movement_score:
        Changes occur every 4–8 bars when material allows.
    groove_fit_score:
        Section groove logic aligns with energy and section type.
    transition_quality_score:
        Section boundaries are non-generic and non-duplicated.
    novelty_score:
        Later hooks and verses evolve from earlier ones.
    vagueness_score:
        Punishes vague/generic planning language (1.0 = no vagueness).
    overall_score:
        Weighted composite of the above.
    warnings:
        Human-readable warning strings explaining low scores.
    """

    repeated_section_contrast_score: float = 1.0
    hook_payoff_score: float = 1.0
    timeline_movement_score: float = 1.0
    groove_fit_score: float = 1.0
    transition_quality_score: float = 1.0
    novelty_score: float = 1.0
    vagueness_score: float = 1.0
    overall_score: float = 1.0
    warnings: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        for attr in (
            "repeated_section_contrast_score",
            "hook_payoff_score",
            "timeline_movement_score",
            "groove_fit_score",
            "transition_quality_score",
            "novelty_score",
            "vagueness_score",
            "overall_score",
        ):
            v = getattr(self, attr)
            if not (0.0 <= v <= 1.0):
                raise ValueError(f"{attr} must be in [0.0, 1.0], got {v}")


# ---------------------------------------------------------------------------
# AIRepairAction
# ---------------------------------------------------------------------------

@dataclass
class AIRepairAction:
    """A single repair action taken by the Repair Agent.

    Fields
    ------
    section_name:
        Name of the section that was repaired.
    reason:
        Why the repair was needed.
    action_taken:
        Concrete description of what was changed.
    before:
        Snapshot of the relevant plan state before repair.
    after:
        Snapshot of the relevant plan state after repair.
    """

    section_name: str
    reason: str
    action_taken: str
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.section_name:
            raise ValueError("section_name must not be empty")
        if not self.reason:
            raise ValueError("reason must not be empty")
        if not self.action_taken:
            raise ValueError("action_taken must not be empty")


# ---------------------------------------------------------------------------
# AIProducerResult
# ---------------------------------------------------------------------------

@dataclass
class AIProducerResult:
    """Final result returned by the orchestrator.

    Fields
    ------
    planner_output:
        The (possibly repaired) :class:`AIProducerPlan`.
    critic_scores:
        Scores from the final critic pass.
    repair_actions:
        All repair actions taken across all repair passes.
    validator_warnings:
        Warnings emitted by the hard-rule validator.
    accepted:
        ``True`` if the plan passed scoring and validation.
    rejected_reason:
        Human-readable explanation when ``accepted`` is ``False``.
    fallback_used:
        ``True`` if the deterministic fallback plan was substituted.
    """

    planner_output: Optional[AIProducerPlan] = None
    critic_scores: Optional[AICriticScore] = None
    repair_actions: list[AIRepairAction] = field(default_factory=list)
    validator_warnings: list[str] = field(default_factory=list)
    accepted: bool = False
    rejected_reason: str = ""
    fallback_used: bool = False
