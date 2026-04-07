"""
Section Identity Engine — Phase 2–7 of the real-arrangement initiative.

Root causes fixed here:
1. section_type role selection was occurrence-blind — verse 2 == verse 1.
2. No forbidden-role enforcement (intro had drums, bridge had full groove).
3. Repeated sections got identical role sets with no evolution strategy.
4. Transitions existed as string labels only; no material handoff logic.
5. No inspectable quality metrics — couldn't detect "fake arrangement" output.

This module provides:
- SECTION_PROFILES: per-section identity rules (priorities, forbidden, density, contrast).
- select_roles_for_section(): deterministic, occurrence-aware role selector.
- compute_arrangement_quality(): inspectable quality metrics for QA/logging.
- get_transition_events(): deterministic transition event generator per section boundary.
- SECTION_IDENTITY_ENGINE_VERSION: version string for rollout traceability.

Integration points:
- arrangement_planner.py  → _roles_for_section()
- arrangement_jobs.py     → _apply_stem_primary_section_states()
- Both gated by PRODUCER_SECTION_IDENTITY_V2 feature flag.

Design principles:
- Fully deterministic for the same inputs (no random, no LLM).
- Inspectable — every decision logged to ArrangementQualityMetrics.
- Backward-compatible — all public APIs accept the same types as callers use today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

SECTION_IDENTITY_ENGINE_VERSION = "1.0"

# ---------------------------------------------------------------------------
# Per-section identity profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SectionProfile:
    """Immutable behavior profile for one section type."""

    # Roles ordered from most-preferred to least-preferred for this section.
    role_priorities: tuple[str, ...]

    # Roles that must NEVER be active in this section.
    # E.g. intro must not have drums; bridge must not have drums/bass.
    forbidden_roles: frozenset[str]

    # (min, max) active roles for this section.  Enforced after forbidden filtering.
    density_min: int
    density_max: int

    # Minimum Jaccard-distance to adjacent section of a DIFFERENT type.
    # 0.0 = no constraint; 0.5 = must share ≤50% of roles.
    contrast_vs_adjacent: float

    # How many extra roles to add per additional occurrence (0 = no escalation).
    escalation_per_repeat: int

    # Whether repeated occurrences should subtract roles to create tension.
    subtract_on_repeat: bool

    # Default transition INTO this section type.
    default_transition_in: str

    # Default transition OUT of this section type.
    default_transition_out: str


# All section profiles — the canonical musical identity rules.
SECTION_PROFILES: dict[str, SectionProfile] = {
    "intro": SectionProfile(
        role_priorities=("pads", "fx", "melody", "arp", "vocal", "synth"),
        forbidden_roles=frozenset({"drums", "bass", "percussion"}),
        density_min=1,
        density_max=2,
        contrast_vs_adjacent=0.50,   # intro must differ substantially from verse
        escalation_per_repeat=0,
        subtract_on_repeat=False,
        default_transition_in="none",
        default_transition_out="drum_fill",
    ),
    "verse": SectionProfile(
        role_priorities=("drums", "bass", "melody", "vocal", "synth", "percussion", "arp", "pads"),
        forbidden_roles=frozenset(),
        density_min=2,
        density_max=3,
        contrast_vs_adjacent=0.30,
        escalation_per_repeat=1,     # verse 2 adds one role vs verse 1
        subtract_on_repeat=False,
        default_transition_in="drum_fill",
        default_transition_out="lift",
    ),
    "pre_hook": SectionProfile(
        role_priorities=("bass", "arp", "fx", "percussion", "melody", "vocal", "synth"),
        forbidden_roles=frozenset({"pads"}),  # pads soften; pre-hook needs edge
        density_min=2,
        density_max=3,
        contrast_vs_adjacent=0.30,
        escalation_per_repeat=0,
        subtract_on_repeat=True,     # pre-hook 2: drop drums for "felt-absence" tension
        default_transition_in="fx_rise",
        default_transition_out="pull_back",
    ),
    "hook": SectionProfile(
        role_priorities=("drums", "bass", "melody", "synth", "vocal", "percussion", "arp", "pads", "fx"),
        forbidden_roles=frozenset(),
        density_min=3,
        density_max=5,
        contrast_vs_adjacent=0.40,   # hook must differ from verse by >= 40%
        escalation_per_repeat=1,     # each hook occurrence adds one role
        subtract_on_repeat=False,
        default_transition_in="fx_hit",
        default_transition_out="none",
    ),
    "bridge": SectionProfile(
        role_priorities=("pads", "fx", "melody", "vocal", "arp", "synth"),
        forbidden_roles=frozenset({"drums", "bass", "percussion"}),
        density_min=1,
        density_max=2,
        contrast_vs_adjacent=0.50,
        escalation_per_repeat=0,
        subtract_on_repeat=False,
        default_transition_in="mute_drop",
        default_transition_out="riser",
    ),
    "breakdown": SectionProfile(
        role_priorities=("pads", "fx", "vocal", "arp", "melody", "synth"),
        forbidden_roles=frozenset({"drums", "bass", "percussion"}),
        density_min=1,
        density_max=2,
        contrast_vs_adjacent=0.50,
        escalation_per_repeat=0,
        subtract_on_repeat=False,
        default_transition_in="silence_drop",
        default_transition_out="riser",
    ),
    "outro": SectionProfile(
        role_priorities=("pads", "fx", "melody", "arp", "vocal"),
        forbidden_roles=frozenset({"drums", "bass", "percussion"}),
        density_min=1,
        density_max=2,
        contrast_vs_adjacent=0.40,
        escalation_per_repeat=0,
        subtract_on_repeat=False,
        default_transition_in="crossfade",
        default_transition_out="none",
    ),
}

# Fallback profile used when section type is unrecognised.
_FALLBACK_PROFILE = SectionProfile(
    role_priorities=("drums", "bass", "melody", "pads", "fx", "synth", "arp", "vocal"),
    forbidden_roles=frozenset(),
    density_min=2,
    density_max=3,
    contrast_vs_adjacent=0.25,
    escalation_per_repeat=0,
    subtract_on_repeat=False,
    default_transition_in="none",
    default_transition_out="none",
)


def _profile(section_type: str) -> SectionProfile:
    return SECTION_PROFILES.get(str(section_type).strip().lower(), _FALLBACK_PROFILE)


# ---------------------------------------------------------------------------
# Role selection — the core deterministic algorithm
# ---------------------------------------------------------------------------


def select_roles_for_section(
    section_type: str,
    available_roles: list[str],
    occurrence: int = 1,
    prev_same_type_roles: Optional[list[str]] = None,
    next_section_type: Optional[str] = None,
    prev_adjacent_roles: Optional[list[str]] = None,
) -> list[str]:
    """Return the active role list for one section occurrence.

    Parameters
    ----------
    section_type:
        Canonical section type string (intro / verse / pre_hook / hook /
        bridge / breakdown / outro).
    available_roles:
        All roles that exist in the source (drums, bass, melody, …).
    occurrence:
        How many times this section type has already appeared (1 = first).
    prev_same_type_roles:
        Active roles from the previous occurrence of the SAME section type.
        Used for evolution (verse 1 → verse 2).
    next_section_type:
        The section type that follows this one.  Used to ensure contrast.
    prev_adjacent_roles:
        Active roles from the immediately preceding section (different type).
        Used to enforce contrast_vs_adjacent.

    Returns
    -------
    list[str]
        Ordered list of active roles (subset of available_roles).
    """
    if not available_roles:
        return []

    profile = _profile(section_type)
    available_set = set(available_roles)

    # 1. Filter out forbidden roles.
    permitted = [r for r in available_roles if r not in profile.forbidden_roles]

    # 2. Order by the profile's role preference.
    preferred_order = [r for r in profile.role_priorities if r in set(permitted)]
    # Append any permitted roles not in the preference list (preserves all available roles).
    for r in permitted:
        if r not in set(preferred_order):
            preferred_order.append(r)

    if not preferred_order:
        # Every available role is forbidden — pick the 1 least-harmful
        return [available_roles[0]] if available_roles else []

    # 3. Determine target count.
    target_count = _target_density(
        profile=profile,
        occurrence=occurrence,
        total_permitted=len(preferred_order),
    )

    # 4. Derive base candidate list (first target_count from ordered preferences).
    candidates = preferred_order[:target_count]

    # 5. Apply occurrence evolution.
    candidates = _apply_evolution(
        profile=profile,
        occurrence=occurrence,
        candidates=candidates,
        preferred_order=preferred_order,
        prev_same_type_roles=prev_same_type_roles or [],
    )

    # 6. Enforce contrast vs. immediately preceding section.
    if prev_adjacent_roles:
        candidates = _enforce_adjacent_contrast(
            profile=profile,
            candidates=candidates,
            preferred_order=preferred_order,
            prev_adjacent_roles=prev_adjacent_roles,
            available_roles=available_roles,
        )

    # 7. Prefer avoiding full_mix when 2+ isolated roles exist.
    non_full = [r for r in candidates if r != "full_mix"]
    if len(non_full) >= 2:
        candidates = non_full

    # 8. Clamp to density bounds.
    candidates = candidates[: profile.density_max]
    if len(candidates) < profile.density_min and preferred_order:
        extra = [r for r in preferred_order if r not in set(candidates)]
        candidates.extend(extra[: profile.density_min - len(candidates)])

    # 9. Final guard: ensure all selected roles are actually available.
    candidates = [r for r in candidates if r in available_set]

    return candidates if candidates else (preferred_order[:1] if preferred_order else [])


def _target_density(
    profile: SectionProfile,
    occurrence: int,
    total_permitted: int,
) -> int:
    """Calculate target number of roles based on profile and occurrence."""
    base = profile.density_min
    if profile.escalation_per_repeat > 0 and occurrence > 1:
        escalation = min(
            profile.density_max - profile.density_min,
            (occurrence - 1) * profile.escalation_per_repeat,
        )
        base = profile.density_min + escalation
    # Never exceed profile max or available permitted roles.
    return max(profile.density_min, min(profile.density_max, base, total_permitted))


def _apply_evolution(
    profile: SectionProfile,
    occurrence: int,
    candidates: list[str],
    preferred_order: list[str],
    prev_same_type_roles: list[str],
) -> list[str]:
    """Mutate candidate list to enforce repeated-section evolution."""
    if occurrence <= 1 or not prev_same_type_roles:
        return candidates

    prev_set = set(prev_same_type_roles)
    current_set = set(candidates)

    # If the candidate set is identical to the previous, force a change.
    if current_set == prev_set:
        # Try to add a new role not in prev.
        extras = [r for r in preferred_order if r not in prev_set and r not in current_set]
        if extras and len(candidates) < profile.density_max:
            candidates = list(candidates) + [extras[0]]
        elif extras and candidates:
            # Swap out the least preferred role for a new one.
            candidates = [c for c in candidates if c != candidates[-1]] + [extras[0]]

    # For sections with subtract_on_repeat: drop the first rhythmic role on repeat 2+.
    # This creates tension-through-absence (e.g. pre_hook 2 loses drums).
    if profile.subtract_on_repeat and occurrence >= 2:
        rhythmic_roles = ("drums", "percussion")
        for r in rhythmic_roles:
            if r in set(candidates) and len(candidates) > profile.density_min:
                candidates = [c for c in candidates if c != r]
                break

    return candidates


def _enforce_adjacent_contrast(
    profile: SectionProfile,
    candidates: list[str],
    preferred_order: list[str],
    prev_adjacent_roles: list[str],
    available_roles: list[str],
) -> list[str]:
    """Ensure candidates are sufficiently different from the previous section."""
    threshold = profile.contrast_vs_adjacent
    if threshold <= 0.0:
        return candidates

    current_diff = _jaccard_distance(candidates, prev_adjacent_roles)
    if current_diff >= threshold:
        return candidates  # Already distinct enough.

    prev_set = set(prev_adjacent_roles)

    # Try swapping in roles not in prev_set.
    attempt = list(candidates)
    for role in preferred_order:
        if role in prev_set or role in set(attempt):
            continue
        # Replace the most-overlapping role in attempt.
        overlapping = [r for r in attempt if r in prev_set]
        if overlapping:
            attempt = [r for r in attempt if r != overlapping[-1]]
            attempt.append(role)
        elif len(attempt) < profile.density_max:
            attempt.append(role)

        if _jaccard_distance(attempt, prev_adjacent_roles) >= threshold:
            return attempt

    # Last resort: strip roles shared with prev until contrast threshold met.
    stripped = [r for r in attempt if r not in prev_set]
    if stripped:
        return stripped[: max(profile.density_min, 1)]

    return candidates


# ---------------------------------------------------------------------------
# Transition event generation
# ---------------------------------------------------------------------------


@dataclass
class TransitionEvent:
    """A single deterministic transition event at a section boundary."""

    bar: int                    # Global bar where the event occurs.
    event_type: str             # Matches _RENDER_MOVE_EVENT_TYPES in arrangement_jobs.
    placement: str              # "end_of_section" | "start_of_section"
    intensity: float            # 0.0–1.0
    params: dict = field(default_factory=dict)
    description: str = ""


def get_transition_events(
    prev_section_type: str,
    next_section_type: str,
    prev_end_bar: int,
    next_start_bar: int,
    occurrence_of_next: int = 1,
) -> list[TransitionEvent]:
    """Return deterministic transition events for the boundary between two sections.

    Parameters
    ----------
    prev_section_type, next_section_type:
        Section type strings for the outgoing and incoming sections.
    prev_end_bar:
        Last bar of the outgoing section (inclusive).
    next_start_bar:
        First bar of the incoming section.
    occurrence_of_next:
        How many times the incoming section type has appeared (1 = first).

    Returns
    -------
    list[TransitionEvent]
        Empty if no transition is warranted; otherwise 1–3 events.
    """
    events: list[TransitionEvent] = []
    prev = str(prev_section_type).strip().lower()
    nxt = str(next_section_type).strip().lower()

    # Hook entry is the highest-priority transition.
    if nxt in {"hook", "drop", "chorus"}:
        # Silence drop before hook.
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="silence_drop_before_hook",
            placement="end_of_section",
            intensity=0.85,
            description="Brief silence before hook entry for impact",
        ))
        # Crash hit at hook downbeat.
        events.append(TransitionEvent(
            bar=next_start_bar,
            event_type="crash_hit",
            placement="start_of_section",
            intensity=0.90,
            description="Hook entry crash",
        ))
        # Extra final-hook expansion for repeated hooks.
        if occurrence_of_next >= 3:
            events.append(TransitionEvent(
                bar=next_start_bar,
                event_type="final_hook_expansion",
                placement="start_of_section",
                intensity=0.95,
                params={"hook_occurrence": occurrence_of_next},
                description="Final hook expansion for maximum payoff",
            ))
        return events

    # Pre-hook creates tension before the hook.
    if nxt == "pre_hook":
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="snare_pickup",
            placement="end_of_section",
            intensity=0.80,
            description="Snare pickup leading into pre-hook",
        ))
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="riser_fx",
            placement="end_of_section",
            intensity=0.75,
            description="FX riser into pre-hook",
        ))
        return events

    # Bridge/breakdown entry: strong mute drop.
    if nxt in {"bridge", "breakdown"}:
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="pre_hook_silence_drop",
            placement="end_of_section",
            intensity=0.88,
            description="Subtraction drop before bridge/breakdown",
        ))
        return events

    # Section-end drum fills for verse → anything or hook → verse.
    if prev in {"verse", "hook"} and nxt not in {"outro", "breakdown", "bridge"}:
        events.append(TransitionEvent(
            bar=max(0, prev_end_bar),
            event_type="drum_fill",
            placement="end_of_section",
            intensity=0.70,
            description=f"Drum fill exiting {prev}",
        ))

    return events


# ---------------------------------------------------------------------------
# Quality metrics
# ---------------------------------------------------------------------------


@dataclass
class ArrangementQualityMetrics:
    """Inspectable quality scores for a completed arrangement plan.

    All scores are in [0.0, 1.0].  Higher is better.
    """

    section_contrast_score: float = 0.0
    """Average Jaccard distance between adjacent sections of different types."""

    repetition_variation_score: float = 0.0
    """Average role-set change across repeated sections (0 = all identical)."""

    transition_impact_score: float = 0.0
    """Fraction of boundaries that have at least one material transition event."""

    role_choreography_score: float = 0.0
    """Fraction of sections where the lead role differs from the prior section."""

    payoff_strength_score: float = 0.0
    """Ratio of hook density to verse density (capped at 1.0)."""

    warnings: list[str] = field(default_factory=list)
    """Human-readable QA warnings (non-fatal)."""


@dataclass
class _SectionSnapshot:
    """Minimal section descriptor for metric computation."""

    section_type: str
    active_roles: list[str]
    occurrence: int


def compute_arrangement_quality(
    sections: list[dict],
) -> ArrangementQualityMetrics:
    """Compute inspectable quality metrics from a list of rendered section dicts.

    Each dict must have at minimum:
        - ``type`` or ``section_type`` (str)
        - ``instruments`` or ``active_stem_roles`` or ``active_roles`` (list[str])

    Parameters
    ----------
    sections:
        List of section dicts as produced by the render pipeline.

    Returns
    -------
    ArrangementQualityMetrics
        Fully populated metrics object with warnings list.
    """
    metrics = ArrangementQualityMetrics()
    if not sections:
        metrics.warnings.append("No sections to evaluate")
        return metrics

    snaps: list[_SectionSnapshot] = []
    occurrence_counter: dict[str, int] = {}
    for s in sections:
        stype = str(s.get("type") or s.get("section_type") or "verse").strip().lower()
        roles = list(
            s.get("instruments") or s.get("active_stem_roles") or s.get("active_roles") or []
        )
        occurrence_counter[stype] = occurrence_counter.get(stype, 0) + 1
        snaps.append(_SectionSnapshot(stype, roles, occurrence_counter[stype]))

    # ---- section_contrast_score ----
    contrast_pairs: list[float] = []
    for i in range(1, len(snaps)):
        if snaps[i].section_type != snaps[i - 1].section_type:
            contrast_pairs.append(_jaccard_distance(snaps[i].active_roles, snaps[i - 1].active_roles))
    metrics.section_contrast_score = (
        round(sum(contrast_pairs) / len(contrast_pairs), 3) if contrast_pairs else 0.0
    )
    if metrics.section_contrast_score < 0.25:
        metrics.warnings.append(
            f"section_contrast_score={metrics.section_contrast_score:.2f} is below 0.25 "
            "— adjacent sections may sound identical"
        )

    # ---- repetition_variation_score ----
    repeated_by_type: dict[str, list[list[str]]] = {}
    for snap in snaps:
        repeated_by_type.setdefault(snap.section_type, []).append(snap.active_roles)

    variation_scores: list[float] = []
    for stype, role_lists in repeated_by_type.items():
        if len(role_lists) < 2:
            continue
        for j in range(1, len(role_lists)):
            variation_scores.append(_jaccard_distance(role_lists[j], role_lists[j - 1]))

    metrics.repetition_variation_score = (
        round(sum(variation_scores) / len(variation_scores), 3) if variation_scores else 1.0
    )
    if repeated_by_type and variation_scores and metrics.repetition_variation_score < 0.15:
        metrics.warnings.append(
            f"repetition_variation_score={metrics.repetition_variation_score:.2f} — "
            "repeated sections are near-identical"
        )

    # ---- transition_impact_score ----
    # We proxy this by checking whether adjacent section type changes occur
    # with a meaningful role-set difference (> 0.30 Jaccard distance).
    boundary_count = 0
    impactful_count = 0
    for i in range(1, len(snaps)):
        if snaps[i].section_type != snaps[i - 1].section_type:
            boundary_count += 1
            if _jaccard_distance(snaps[i].active_roles, snaps[i - 1].active_roles) >= 0.30:
                impactful_count += 1
    metrics.transition_impact_score = (
        round(impactful_count / boundary_count, 3) if boundary_count else 1.0
    )
    if boundary_count > 0 and metrics.transition_impact_score < 0.50:
        metrics.warnings.append(
            f"transition_impact_score={metrics.transition_impact_score:.2f} — "
            "many section transitions lack material role changes"
        )

    # ---- role_choreography_score ----
    choreography_changes = 0
    for i in range(1, len(snaps)):
        lead_prev = snaps[i - 1].active_roles[0] if snaps[i - 1].active_roles else None
        lead_curr = snaps[i].active_roles[0] if snaps[i].active_roles else None
        if lead_curr and lead_curr != lead_prev:
            choreography_changes += 1
    metrics.role_choreography_score = (
        round(choreography_changes / (len(snaps) - 1), 3) if len(snaps) > 1 else 1.0
    )
    if metrics.role_choreography_score < 0.40:
        metrics.warnings.append(
            f"role_choreography_score={metrics.role_choreography_score:.2f} — "
            "lead role rarely changes across sections"
        )

    # ---- payoff_strength_score ----
    verse_densities = [len(s.active_roles) for s in snaps if s.section_type == "verse"]
    hook_densities = [len(s.active_roles) for s in snaps if s.section_type in {"hook", "drop", "chorus"}]
    if verse_densities and hook_densities:
        avg_verse = sum(verse_densities) / len(verse_densities)
        avg_hook = sum(hook_densities) / len(hook_densities)
        ratio = avg_hook / max(1, avg_verse)
        metrics.payoff_strength_score = round(min(1.0, ratio - 1.0), 3)  # 0 if equal, 1 if hook is 2x verse
        metrics.payoff_strength_score = max(0.0, metrics.payoff_strength_score)
    else:
        metrics.payoff_strength_score = 0.5  # Not enough data

    if hook_densities and verse_densities and metrics.payoff_strength_score <= 0.0:
        metrics.warnings.append(
            "payoff_strength_score <= 0 — hooks are no denser than verses"
        )

    return metrics


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _jaccard_distance(a: list[str], b: list[str]) -> float:
    """Return 1 - Jaccard similarity for two role lists."""
    set_a = set(a)
    set_b = set(b)
    union = set_a | set_b
    if not union:
        return 0.0
    intersection = set_a & set_b
    return 1.0 - (len(intersection) / len(union))
