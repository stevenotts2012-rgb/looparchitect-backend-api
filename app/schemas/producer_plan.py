"""
Producer Plan Schemas — Phase 5.

Defines the two-layer AI plan output and observability envelope:

1. ``AIMicroBarRange`` / ``AIMicroSectionPlan`` / ``AIMicroPlan``
   Bar-range micro-plan that lives inside each section plan.

2. ``AICriticScores``
   Structured critic scoring object produced by the AI critic pass.

3. ``ProducerObservability``
   Full observability envelope exposing reference_profile, ai_section_plan,
   ai_micro_plan, ai_rejected_reason, critic_scores,
   ai_plan_vs_actual_match, and repeated_section_deltas.

Design contracts:
- Micro-plan entries must carry concrete bar-range deltas, not vague labels.
- Critic scores are 0.0–1.0 floats with an overall pass/fail flag.
- All observability fields are optional so callers can populate them
  incrementally as the pipeline executes.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Micro-plan types
# ---------------------------------------------------------------------------


class AIMicroBarRange(BaseModel):
    """A concrete producer action applied to a specific bar range within a section.

    All delta fields must be explicit (bar numbers, role names, behavior strings).
    Vague descriptions are rejected during validation.

    Examples of valid concrete deltas
    ----------------------------------
    - role_add=["hat"], bar_start=5, bar_end=8
    - role_remove=["kick"], bar_start=8, bar_end=8
    - melody_behavior="delayed_entry bar 3"
    - fill_at=7
    - drop_at=8, reentry_at=9
    """

    # Bar range within the parent section (1-based, inclusive)
    bar_start: int = Field(..., ge=1, description="First bar of this delta (1-based within section)")
    bar_end: int = Field(..., ge=1, description="Last bar of this delta (1-based within section)")

    # Role additions and removals in this bar range
    role_add: List[str] = Field(
        default_factory=list, description="Roles added at bar_start"
    )
    role_remove: List[str] = Field(
        default_factory=list, description="Roles removed at bar_start"
    )

    # Per-instrument behavior strings — must be specific (e.g. "open_hat_16th")
    kick_behavior: str = Field(default="", description="Kick drum behavior for this range")
    hat_behavior: str = Field(default="", description="Hi-hat behavior for this range")
    bass_behavior: str = Field(default="", description="Bass behavior for this range")
    melody_behavior: str = Field(default="", description="Melody behavior for this range")

    # Timeline events
    fill_at: Optional[int] = Field(
        default=None, description="Bar number (within section) where a fill occurs"
    )
    drop_at: Optional[int] = Field(
        default=None, description="Bar number where a drop/mute occurs"
    )
    reentry_at: Optional[int] = Field(
        default=None, description="Bar number where elements re-enter after a drop"
    )
    delayed_entry_bars: int = Field(
        default=0,
        ge=0,
        description="Number of bars to delay the entry of role_add elements",
    )

    # Reason / audit
    reason: str = Field(
        default="",
        description="Why this delta was applied (producer rationale)",
    )


class AIMicroSectionPlan(BaseModel):
    """Micro-plan for a single section: list of concrete bar-range deltas."""

    section_index: int = Field(..., description="Index of the parent section plan")
    section_label: str = Field(default="", description="Human-readable section label")
    section_type: str = Field(default="", description="Section type (verse, hook, ...)")
    total_bars: int = Field(..., ge=1, description="Total bars in this section")

    # Ordered list of bar-range deltas inside this section
    bar_ranges: List[AIMicroBarRange] = Field(
        default_factory=list,
        description="Concrete bar-range deltas, ordered by bar_start",
    )


class AIMicroPlan(BaseModel):
    """Complete micro-plan: one AIMicroSectionPlan per section in the arrangement."""

    sections: List[AIMicroSectionPlan] = Field(default_factory=list)
    generated_by: str = Field(
        default="deterministic",
        description="'deterministic' | 'ai' — which path generated this micro plan",
    )
    total_deltas: int = Field(default=0, description="Total number of AIMicroBarRange entries")
    validation_errors: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Critic scores
# ---------------------------------------------------------------------------


class AICriticScores(BaseModel):
    """Structured scores from the AI critic pass (all 0.0–1.0).

    A score < 0.5 on any dimension indicates a planning weakness that may
    trigger automatic repair or deterministic fallback.
    """

    # How well repeated sections of the same type contrast with each other
    repeated_section_contrast: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Mean contrast across repeated same-type sections (0=identical, 1=fully different)",
    )

    # Whether the hook sections deliver a clear energy/density payoff
    hook_payoff: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Hook energy advantage score (0=hook not elevated, 1=strong payoff)",
    )

    # Whether energy moves (rises and falls) across the timeline
    timeline_movement: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Fraction of section transitions that show meaningful energy change",
    )

    # Tension/release ratio: presence of pre-hook tension + hook release pattern
    tension_release: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Quality of tension (pre-hook reduces density) followed by release (hook expands)",
    )

    # Overall plan novelty (summary from energy variance + repeated contrast + hook novelty)
    novelty_score: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="Combined novelty/contrast score for the full plan",
    )

    # Fraction of sections where the AI plan matches the actual rendered output
    plan_vs_actual_match: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of sections where plan section_type matches actual rendered section",
    )

    # Overall pass/fail (True when all scores >= threshold)
    passed: bool = Field(default=False, description="True when plan meets all critic thresholds")

    # Human-readable summary of failures
    failure_reasons: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Full observability envelope
# ---------------------------------------------------------------------------


class ProducerObservability(BaseModel):
    """Full planning-layer observability envelope.

    Exposes every intermediate output from the AI planning pipeline so that
    callers (API routes, tests, dashboards) can inspect the full decision chain.
    """

    # Reference profile (from reference_analyzer.build_reference_profile)
    reference_profile: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Structured profile derived from the reference track analysis",
    )

    # Section plan (serialised ProducerArrangementPlanV2.sections)
    ai_section_plan: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="Section-level plan produced by the AI / plan builder",
    )

    # Micro plan
    ai_micro_plan: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Bar-range micro-plan produced by AIMicroPlanner",
    )

    # Why the AI plan was rejected (empty string = not rejected)
    ai_rejected_reason: str = Field(
        default="",
        description="Reason the AI section plan was rejected (empty = accepted)",
    )

    # Critic scores
    critic_scores: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Scores from the AICriticPass",
    )

    # Plan-vs-actual match fraction
    ai_plan_vs_actual_match: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="Fraction of sections where the AI plan matched the rendered output",
    )

    # Delta log for repeated sections
    repeated_section_deltas: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Role/energy diffs between consecutive occurrences of same-type sections",
    )

    # Rules engine violations log
    rules_violations: List[Dict[str, Any]] = Field(
        default_factory=list,
        description="Violations reported by ProducerRulesEngine",
    )

    # Whether deterministic fallback was used
    fallback_used: bool = Field(
        default=False,
        description="True when the deterministic fallback replaced the AI plan",
    )
