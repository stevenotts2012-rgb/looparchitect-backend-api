"""
Core data types for the Decision Engine.

The Decision Engine operates ABOVE the Timeline Engine, Pattern Variation Engine,
Groove Engine, Drop Engine, and Motif System.  It is the "producer brain" that
decides what roles to hold back, remove, reintroduce, and when to create contrast
so the arrangement stops sounding like layered repetition.

All types are pure Python dataclasses with no audio or I/O dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


# ---------------------------------------------------------------------------
# Supported action types
# ---------------------------------------------------------------------------

SUPPORTED_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "hold_back_role",
        "remove_role",
        "delay_entry",
        "reintroduce_role",
        "strip_to_core",
        "reduce_density",
        "force_payoff",
        "suppress_full_stack",
        "pre_hook_subtraction",
        "bridge_reset",
        "outro_resolution",
    }
)

# Action types that reduce density / remove material.
SUBTRACTIVE_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "hold_back_role",
        "remove_role",
        "strip_to_core",
        "reduce_density",
        "suppress_full_stack",
        "pre_hook_subtraction",
        "bridge_reset",
        "outro_resolution",
    }
)

# Action types that add or restore material.
ADDITIVE_ACTION_TYPES: frozenset[str] = frozenset(
    {
        "reintroduce_role",
        "force_payoff",
    }
)

# Valid target-fullness labels.
VALID_FULLNESS_LABELS: frozenset[str] = frozenset({"sparse", "medium", "full"})


# ---------------------------------------------------------------------------
# DecisionAction
# ---------------------------------------------------------------------------


@dataclass
class DecisionAction:
    """A single producer decision applied to a section.

    Attributes:
        section_name: Raw section name (e.g. ``"verse_1"``).
        occurrence_index: 0-based index of how many times this section type
            has been processed before.
        action_type: Named action.  Must be in :data:`SUPPORTED_ACTION_TYPES`.
        target_role: Instrument role this action targets, or ``None`` for
            actions that do not target a specific role.
        bar_start: Bar number (1-indexed) where the action begins, or ``None``
            when the action applies to the full section.
        bar_end: Bar number (1-indexed, inclusive) where the action ends, or
            ``None`` when the action applies to the full section.
        intensity: Strength of the action in [0.0, 1.0].
        reason: Short human-readable explanation of why this action was chosen.
        notes: Optional longer annotation for debugging.
    """

    section_name: str
    occurrence_index: int
    action_type: str
    target_role: Optional[str]
    bar_start: Optional[int]
    bar_end: Optional[int]
    intensity: float
    reason: str
    notes: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.section_name:
            raise ValueError("section_name must be a non-empty string")
        if self.occurrence_index < 0:
            raise ValueError(
                f"occurrence_index must be >= 0, got {self.occurrence_index}"
            )
        if self.action_type not in SUPPORTED_ACTION_TYPES:
            raise ValueError(
                f"action_type must be one of {sorted(SUPPORTED_ACTION_TYPES)}, "
                f"got {self.action_type!r}"
            )
        self.intensity = max(0.0, min(1.0, float(self.intensity)))
        if self.bar_start is not None and self.bar_start < 1:
            raise ValueError(f"bar_start must be >= 1, got {self.bar_start}")
        if (
            self.bar_start is not None
            and self.bar_end is not None
            and self.bar_end < self.bar_start
        ):
            raise ValueError(
                f"bar_end ({self.bar_end}) must be >= bar_start ({self.bar_start})"
            )
        if not self.reason:
            raise ValueError("reason must be a non-empty string")

    @property
    def is_subtractive(self) -> bool:
        """Return True when this action removes or withholds material."""
        return self.action_type in SUBTRACTIVE_ACTION_TYPES

    @property
    def is_additive(self) -> bool:
        """Return True when this action restores or adds material."""
        return self.action_type in ADDITIVE_ACTION_TYPES

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        d: dict = {
            "section_name": self.section_name,
            "occurrence_index": self.occurrence_index,
            "action_type": self.action_type,
            "target_role": self.target_role,
            "bar_start": self.bar_start,
            "bar_end": self.bar_end,
            "intensity": round(self.intensity, 4),
            "reason": self.reason,
        }
        if self.notes is not None:
            d["notes"] = self.notes
        return d


# ---------------------------------------------------------------------------
# SectionDecision
# ---------------------------------------------------------------------------


@dataclass
class SectionDecision:
    """The complete producer decision for a single section.

    Attributes:
        section_name: Raw section name (e.g. ``"verse_1"``).
        occurrence_index: 0-based occurrence index for this section type.
        target_fullness: One of ``"sparse"``, ``"medium"``, or ``"full"``.
        allow_full_stack: Whether the full role stack may play simultaneously.
        required_subtractions: Ordered list of subtractive :class:`DecisionAction`
            objects the section must honour.
        required_reentries: Ordered list of additive :class:`DecisionAction`
            objects the section must honour.
        protected_roles: Roles that must NOT be removed in this section.
        blocked_roles: Roles that must NOT be present in this section.
        decision_score: Overall quality of this section's decision in [0.0, 1.0].
        rationale: Human-readable list of reasoning notes.
    """

    section_name: str
    occurrence_index: int
    target_fullness: str
    allow_full_stack: bool
    required_subtractions: List[DecisionAction] = field(default_factory=list)
    required_reentries: List[DecisionAction] = field(default_factory=list)
    protected_roles: List[str] = field(default_factory=list)
    blocked_roles: List[str] = field(default_factory=list)
    decision_score: float = 0.5
    rationale: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.section_name:
            raise ValueError("section_name must be a non-empty string")
        if self.occurrence_index < 0:
            raise ValueError(
                f"occurrence_index must be >= 0, got {self.occurrence_index}"
            )
        if self.target_fullness not in VALID_FULLNESS_LABELS:
            raise ValueError(
                f"target_fullness must be one of {sorted(VALID_FULLNESS_LABELS)}, "
                f"got {self.target_fullness!r}"
            )
        self.decision_score = max(0.0, min(1.0, float(self.decision_score)))

    @property
    def subtraction_count(self) -> int:
        """Return the number of required subtractions."""
        return len(self.required_subtractions)

    @property
    def reentry_count(self) -> int:
        """Return the number of required re-entries."""
        return len(self.required_reentries)

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "section_name": self.section_name,
            "occurrence_index": self.occurrence_index,
            "target_fullness": self.target_fullness,
            "allow_full_stack": self.allow_full_stack,
            "required_subtractions": [a.to_dict() for a in self.required_subtractions],
            "required_reentries": [a.to_dict() for a in self.required_reentries],
            "protected_roles": list(self.protected_roles),
            "blocked_roles": list(self.blocked_roles),
            "decision_score": round(self.decision_score, 4),
            "rationale": list(self.rationale),
        }


# ---------------------------------------------------------------------------
# DecisionPlan
# ---------------------------------------------------------------------------


@dataclass
class DecisionPlan:
    """Full decision plan for a complete arrangement.

    Attributes:
        section_decisions: Ordered list of :class:`SectionDecision` objects,
            one per section in the arrangement.
        global_contrast_score: Aggregate contrast quality across the arrangement
            [0.0, 1.0].  Higher means stronger verse-to-hook contrast, better
            bridge resets, cleaner outros.
        payoff_readiness_score: How well the arrangement has built up before
            each hook [0.0, 1.0].  Higher means pre-hook subtractions properly
            preceded hook payoffs.
        fallback_used: True when the engine fell back to conservative defaults
            due to limited source material.
        warnings: List of human-readable warnings from the planner.
    """

    section_decisions: List[SectionDecision] = field(default_factory=list)
    global_contrast_score: float = 0.0
    payoff_readiness_score: float = 0.0
    fallback_used: bool = False
    warnings: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.global_contrast_score = max(
            0.0, min(1.0, float(self.global_contrast_score))
        )
        self.payoff_readiness_score = max(
            0.0, min(1.0, float(self.payoff_readiness_score))
        )

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "section_decisions": [d.to_dict() for d in self.section_decisions],
            "global_contrast_score": round(self.global_contrast_score, 4),
            "payoff_readiness_score": round(self.payoff_readiness_score, 4),
            "fallback_used": self.fallback_used,
            "warnings": list(self.warnings),
        }


# ---------------------------------------------------------------------------
# DecisionValidationIssue
# ---------------------------------------------------------------------------


@dataclass
class DecisionValidationIssue:
    """A single validation finding from the :class:`DecisionValidator`.

    Attributes:
        severity: Either ``"warning"`` or ``"critical"``.
        rule: Short identifier for the rule that fired (e.g.
            ``"verse_1_full_stack"``).
        section_name: The section name the issue relates to, or ``None``
            for global issues.
        message: Human-readable description of the problem.
    """

    severity: str
    rule: str
    section_name: Optional[str]
    message: str

    def __post_init__(self) -> None:
        if self.severity not in ("warning", "critical"):
            raise ValueError(
                f"severity must be 'warning' or 'critical', got {self.severity!r}"
            )
        if not self.rule:
            raise ValueError("rule must be a non-empty string")
        if not self.message:
            raise ValueError("message must be a non-empty string")

    @property
    def is_critical(self) -> bool:
        """Return True when this is a critical issue."""
        return self.severity == "critical"

    def to_dict(self) -> dict:
        """Return a JSON-serialisable representation."""
        return {
            "severity": self.severity,
            "rule": self.rule,
            "section_name": self.section_name,
            "message": self.message,
        }
