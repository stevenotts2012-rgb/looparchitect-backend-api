"""
Resolved Render Plan — canonical structure consumed by the renderer.

The :class:`ResolvedRenderPlan` is the single source-of-truth produced by
:class:`~app.services.final_plan_resolver.FinalPlanResolver` after merging all
engine outputs (Timeline, Pattern Variation, Groove, Decision, Drop, Motif).

The renderer must consume this structure rather than the raw per-engine
annotations stored in ``render_plan["sections"]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# ResolvedBoundaryEvent
# ---------------------------------------------------------------------------


@dataclass
class ResolvedBoundaryEvent:
    """A single deduplicated boundary/transition event for one section edge.

    Attributes:
        event_type:  Canonical event type string (e.g. ``"drum_fill"``).
        source_engine: Engine that contributed this event (e.g. ``"drop"``).
        placement: ``"pre_boundary"``, ``"boundary"``, or ``"post_boundary"``.
        intensity: Event strength [0.0, 1.0].
        bar:  Absolute bar number where the event is placed.
        params: Arbitrary key/value pairs for downstream DSP.
    """

    event_type: str
    source_engine: str
    placement: str
    intensity: float
    bar: int
    params: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "event_type": self.event_type,
            "source_engine": self.source_engine,
            "placement": self.placement,
            "intensity": round(self.intensity, 4),
            "bar": self.bar,
            "params": dict(self.params),
        }


# ---------------------------------------------------------------------------
# ResolvedSection
# ---------------------------------------------------------------------------


@dataclass
class ResolvedSection:
    """Final resolved state of a single section ready for rendering.

    This captures *what the renderer will actually do* — not what was planned
    by any individual engine.

    Attributes:
        section_name:          Human-readable section label (e.g. ``"Hook 1"``).
        section_type:          Canonical section type (e.g. ``"hook"``).
        bar_start:             Absolute bar number where this section begins.
        bars:                  Total bars in this section.
        energy:                Final energy level [0.0, 1.0].
        final_active_roles:    Roles that *will* be rendered (after all subtractions).
        final_blocked_roles:   Roles that were blocked (Decision Engine or exclusion).
        final_reentries:       Roles reintroduced mid-section by Decision Engine.
        final_boundary_events: Deduplicated ordered list of boundary events.
        final_pattern_events:  Pattern Variation events applied in this section.
        final_groove_events:   Groove Engine events applied in this section.
        final_motif_treatment: Motif Engine treatment dict, or ``None``.
        timeline_events:       Timeline Engine events applied in this section.
        loop_variant:          Loop variant key used for this section (if any).
        phrase_plan:           Phrase-level variation plan dict (if any).
        hook_evolution:        Hook evolution stage (if any).
        variations:            Non-boundary variation instructions (gain, filter…).
    """

    section_name: str
    section_type: str
    bar_start: int
    bars: int
    energy: float
    final_active_roles: List[str]
    final_blocked_roles: List[str] = field(default_factory=list)
    final_reentries: List[str] = field(default_factory=list)
    final_boundary_events: List[ResolvedBoundaryEvent] = field(default_factory=list)
    final_pattern_events: List[dict] = field(default_factory=list)
    final_groove_events: List[dict] = field(default_factory=list)
    final_motif_treatment: Optional[dict] = None
    timeline_events: List[dict] = field(default_factory=list)
    loop_variant: Optional[str] = None
    phrase_plan: Optional[dict] = None
    hook_evolution: Optional[str] = None
    variations: List[dict] = field(default_factory=list)
    # Instrument Activation Rules metadata (populated by FinalPlanResolver when rules are applied).
    rule_snapshot: Optional[Dict[str, Any]] = None
    target_fullness: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "section_name": self.section_name,
            "section_type": self.section_type,
            "bar_start": self.bar_start,
            "bars": self.bars,
            "energy": round(self.energy, 4),
            "final_active_roles": list(self.final_active_roles),
            "final_blocked_roles": list(self.final_blocked_roles),
            "final_reentries": list(self.final_reentries),
            "final_boundary_events": [e.to_dict() for e in self.final_boundary_events],
            "final_pattern_events": list(self.final_pattern_events),
            "final_groove_events": list(self.final_groove_events),
            "final_motif_treatment": self.final_motif_treatment,
            "timeline_events": list(self.timeline_events),
            "loop_variant": self.loop_variant,
            "phrase_plan": self.phrase_plan,
            "hook_evolution": self.hook_evolution,
            "variations": list(self.variations),
            "rule_snapshot": self.rule_snapshot,
            "target_fullness": self.target_fullness,
            "active_roles_count": len(self.final_active_roles),
            "blocked_roles_count": len(self.final_blocked_roles),
        }


# ---------------------------------------------------------------------------
# ResolvedRenderPlan
# ---------------------------------------------------------------------------


@dataclass
class ResolvedRenderPlan:
    """The single canonical render instruction set consumed by the renderer.

    Produced by :class:`~app.services.final_plan_resolver.FinalPlanResolver`
    after merging all engine outputs.  The renderer must consume this rather
    than the scattered per-engine annotations in the raw render plan.

    Attributes:
        resolved_sections: Ordered list of :class:`ResolvedSection` objects.
        bpm:               Tempo in beats-per-minute.
        key:               Musical key string (e.g. ``"C major"``).
        total_bars:        Sum of bar counts across all sections.
        source_quality:    Source quality mode (``"true_stems"``, etc.).
        available_roles:   All roles available in source material.
        genre:             Genre hint for mastering.
        render_profile:    Raw render-profile dict (passed through).
        resolver_version:  Monotonically incrementing resolver version number.
        noop_annotations:  Engine metadata that did not affect final audio.
    """

    resolved_sections: List[ResolvedSection]
    bpm: float
    key: str
    total_bars: int
    source_quality: str
    available_roles: List[str]
    genre: str = "generic"
    render_profile: Dict[str, Any] = field(default_factory=dict)
    resolver_version: int = 1
    noop_annotations: List[dict] = field(default_factory=list)
    # Instrument Activation Rules observability.
    rules_applied: bool = False
    rule_set_version: Optional[str] = None
    rule_modifiers: Dict[str, Any] = field(default_factory=dict)
    # Generative Producer Primary observability.
    generative_producer_primary_used: bool = False
    generative_producer_primary_fallback_used: bool = False
    generative_producer_primary_fallback_reason: str = ""
    generative_producer_events_applied: int = 0
    generative_producer_events_skipped: int = 0

    # ---------------------------------------------------------------------------
    # Convenience properties
    # ---------------------------------------------------------------------------

    @property
    def section_count(self) -> int:
        return len(self.resolved_sections)

    @property
    def final_section_role_map(self) -> Dict[str, List[str]]:
        """Map from section_name to final_active_roles for the whole arrangement."""
        return {
            sec.section_name: list(sec.final_active_roles)
            for sec in self.resolved_sections
        }

    @property
    def all_boundary_event_types(self) -> List[str]:
        """Flat list of all boundary event types across all sections (in order)."""
        types: List[str] = []
        for sec in self.resolved_sections:
            for evt in sec.final_boundary_events:
                types.append(evt.event_type)
        return types

    # ---------------------------------------------------------------------------
    # Serialisation
    # ---------------------------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "resolver_version": self.resolver_version,
            "bpm": self.bpm,
            "key": self.key,
            "total_bars": self.total_bars,
            "source_quality": self.source_quality,
            "available_roles": list(self.available_roles),
            "genre": self.genre,
            "render_profile": dict(self.render_profile),
            "section_count": self.section_count,
            "resolved_sections": [s.to_dict() for s in self.resolved_sections],
            "final_section_role_map": self.final_section_role_map,
            "noop_annotations": list(self.noop_annotations),
            "rules_applied": self.rules_applied,
            "rule_set_version": self.rule_set_version,
            "rule_modifiers": dict(self.rule_modifiers),
            "generative_producer_primary_used": self.generative_producer_primary_used,
            "generative_producer_primary_fallback_used": self.generative_producer_primary_fallback_used,
            "generative_producer_primary_fallback_reason": self.generative_producer_primary_fallback_reason,
            "generative_producer_events_applied": self.generative_producer_events_applied,
            "generative_producer_events_skipped": self.generative_producer_events_skipped,
        }
