"""Resolved Arrangement Plan — genre-aware canonical plan consumed by the renderer.

The ResolvedArrangementPlan is the single source of truth produced by the
GenreAwarePlanResolver after:
  1. Genre/vibe classification
  2. Template selection
  3. Arrangement strategy construction
  4. Engine output merging and conflict resolution

This extends the existing ResolvedRenderPlan with genre/vibe/style context.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ResolvedArrangementSection:
    """Genre-aware resolved state of a single section ready for rendering.

    Extends the concept of :class:`~app.services.resolved_render_plan.ResolvedSection`
    with genre/vibe/style context and richer policy annotations.

    Attributes:
        section_name:            Human-readable section label (e.g. ``"Hook 1"``).
        section_type:            Canonical section type (e.g. ``"hook"``).
        occurrence_index:        Zero-based index for repeated section types.
        start_bar:               Absolute bar where the section begins.
        length_bars:             Total bars in this section.
        target_energy:           Energy target from the arrangement strategy.
        target_fullness:         Fullness target from the Decision Engine.
        final_active_roles:      Roles that will be rendered.
        final_blocked_roles:     Roles blocked by Decision Engine or exclusion.
        final_reentry_roles:     Roles reintroduced mid-section.
        final_pattern_events:    Pattern Variation events applied.
        final_groove_events:     Groove Engine events applied.
        final_boundary_events:   Deduplicated boundary/transition events.
        final_motif_treatment:   Motif Engine treatment dict, or ``None``.
        final_transition_profile: Transition style label (e.g. ``"aggressive"``).
        final_hook_payoff_level: Hook payoff label (e.g. ``"full"``).
        final_notes:             Freeform resolver notes for observability.
    """

    section_name: str
    section_type: str
    occurrence_index: int
    start_bar: int
    length_bars: int
    target_energy: float
    target_fullness: float
    final_active_roles: list[str]
    final_blocked_roles: list[str] = field(default_factory=list)
    final_reentry_roles: list[str] = field(default_factory=list)
    final_pattern_events: list[dict] = field(default_factory=list)
    final_groove_events: list[dict] = field(default_factory=list)
    final_boundary_events: list[dict] = field(default_factory=list)
    final_motif_treatment: dict | None = None
    final_transition_profile: str = "standard"
    final_hook_payoff_level: str = "medium"
    final_notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {
            "section_name": self.section_name,
            "section_type": self.section_type,
            "occurrence_index": self.occurrence_index,
            "start_bar": self.start_bar,
            "length_bars": self.length_bars,
            "target_energy": round(self.target_energy, 4),
            "target_fullness": round(self.target_fullness, 4),
            "final_active_roles": list(self.final_active_roles),
            "final_blocked_roles": list(self.final_blocked_roles),
            "final_reentry_roles": list(self.final_reentry_roles),
            "final_pattern_events": list(self.final_pattern_events),
            "final_groove_events": list(self.final_groove_events),
            "final_boundary_events": list(self.final_boundary_events),
            "final_motif_treatment": self.final_motif_treatment,
            "final_transition_profile": self.final_transition_profile,
            "final_hook_payoff_level": self.final_hook_payoff_level,
            "final_notes": list(self.final_notes),
        }


@dataclass
class ResolvedArrangementPlan:
    """The single canonical genre-aware instruction set consumed by the renderer.

    Produced by :class:`~app.services.plan_resolver.GenreAwarePlanResolver`.

    Attributes:
        loop_id:                    Source loop identifier (if available).
        selected_genre:             Classified genre (e.g. ``"trap"``).
        selected_vibe:              Classified vibe (e.g. ``"dark"``).
        style_profile:              Combined style label (e.g. ``"trap_dark_sparse"``).
        template_id:                Selected template (e.g. ``"trap_C"``).
        variation_seed:             Seed used for deterministic selection.
        sections:                   Ordered resolved sections.
        global_scores:              Aggregate quality scores.
        warnings:                   Resolver warnings for observability.
        fallback_used:              True when the resolver fell back to a minimal plan.
        arrangement_strategy_summary: Summary of the ArrangementStrategy applied.
        resolver_conflicts:         Conflicts detected and resolved.
        resolver_skipped_actions:   Engine actions that were skipped with reasons.
    """

    loop_id: int | None
    selected_genre: str
    selected_vibe: str
    style_profile: str
    template_id: str
    variation_seed: int
    sections: list[ResolvedArrangementSection]
    global_scores: dict[str, float] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    fallback_used: bool = False
    arrangement_strategy_summary: dict[str, Any] = field(default_factory=dict)
    resolver_conflicts: list[dict] = field(default_factory=list)
    resolver_skipped_actions: list[dict] = field(default_factory=list)

    @property
    def section_count(self) -> int:
        """Number of resolved sections."""
        return len(self.sections)

    def to_dict(self) -> dict[str, Any]:
        """Serialize the plan to a plain dict."""
        return {
            "loop_id": self.loop_id,
            "selected_genre": self.selected_genre,
            "selected_vibe": self.selected_vibe,
            "style_profile": self.style_profile,
            "template_id": self.template_id,
            "variation_seed": self.variation_seed,
            "section_count": self.section_count,
            "sections": [s.to_dict() for s in self.sections],
            "global_scores": dict(self.global_scores),
            "warnings": list(self.warnings),
            "fallback_used": self.fallback_used,
            "arrangement_strategy_summary": dict(self.arrangement_strategy_summary),
            "resolver_conflicts": list(self.resolver_conflicts),
            "resolver_skipped_actions": list(self.resolver_skipped_actions),
        }
