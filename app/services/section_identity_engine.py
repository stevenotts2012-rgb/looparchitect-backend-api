"""
Section Identity Engine — full-stack arrangement differentiation.

Root causes fixed here:
1. section_type role selection was occurrence-blind — verse 2 == verse 1.
2. No forbidden-role enforcement (intro had drums, bridge had full groove).
3. Repeated sections got identical role sets with no evolution strategy.
4. Transitions existed as string labels only; no material handoff logic.
5. No inspectable quality metrics — couldn't detect "fake arrangement" output.
6. No role hierarchy (leader/support/suppressed) — just density shifts.
7. No intra-section phrase variation — sections internally static for their duration.
8. Repeated-section evolution too weak — support roles never rotated.

This module provides:
- SECTION_PROFILES: per-section identity rules (priorities, forbidden, density, contrast).
- select_roles_for_section(): deterministic, occurrence-aware role selector.
- SectionChoreography + get_section_choreography(): per-section role hierarchy.
- select_roles_with_choreography(): role selection enforcing leader/support/suppressed hierarchy.
- PhraseVariationPlan + get_phrase_variation_plan(): intra-section phrase-level splits.
- compute_arrangement_quality(): inspectable quality metrics for QA/logging.
- get_transition_events(): deterministic transition event generator per section boundary.
- SECTION_IDENTITY_ENGINE_VERSION: version string for rollout traceability.

Integration points:
- arrangement_planner.py  → _roles_for_section()
- arrangement_jobs.py     → _apply_stem_primary_section_states()
- Both gated by PRODUCER_SECTION_IDENTITY_V2 feature flag.
- Choreography + phrase variation additionally gated by SECTION_CHOREOGRAPHY_V2 flag.

Design principles:
- Fully deterministic for the same inputs (no random, no LLM).
- Inspectable — every decision logged to ArrangementQualityMetrics.
- Backward-compatible — all public APIs accept the same types as callers use today.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------------------
# Named constants — avoids magic-number repetition
# ---------------------------------------------------------------------------

# Jaccard distance below which consecutive same-type sections are considered
# "too similar to hear as different" and the choreography rotation is triggered.
_CHOREOGRAPHY_ROTATION_THRESHOLD: float = 0.25

# Minimum Jaccard distance between consecutive same-type sections for the
# repeat_distinction_score QA metric to consider them audibly distinct.
MIN_REPEAT_DISTINCTION_THRESHOLD: float = 0.20

# Minimum Jaccard distance between adjacent different-type section pairs for the
# audible_contrast_score QA metric to pass.
_AUDIBLE_CONTRAST_THRESHOLD: float = 0.35

SECTION_IDENTITY_ENGINE_VERSION = "2.0"

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


def get_effective_profile(section_type: str, preset_name: str | None = None) -> SectionProfile:
    """Return a ``SectionProfile`` for *section_type* with optional preset overrides applied.

    When *preset_name* is ``None`` or unrecognised the base profile from
    ``SECTION_PROFILES`` is returned unchanged.  When a valid preset is given,
    only the fields explicitly set in the preset's ``PresetSectionOverride`` for
    this section type are replaced; all other fields keep their base values.
    """
    base = _profile(section_type)
    if not preset_name:
        return base

    try:
        from app.services.arrangement_presets import get_preset_config
    except ImportError:
        return base

    preset = get_preset_config(preset_name)
    if not preset:
        return base

    override = preset.section_overrides.get(str(section_type).strip().lower())
    if not override:
        return base

    return SectionProfile(
        role_priorities=(
            override.role_priorities
            if override.role_priorities is not None
            else base.role_priorities
        ),
        forbidden_roles=(
            override.forbidden_roles
            if override.forbidden_roles is not None
            else base.forbidden_roles
        ),
        density_min=(
            override.density_min
            if override.density_min is not None
            else base.density_min
        ),
        density_max=(
            override.density_max
            if override.density_max is not None
            else base.density_max
        ),
        # contrast_vs_adjacent, escalation_per_repeat, and subtract_on_repeat are
        # intentionally NOT exposed as preset overrides.  They govern algorithmic
        # evolution behaviour (adjacent-section contrast enforcement, per-repeat
        # density escalation, and subtractive-tension rules) that are
        # section-type invariants and should remain consistent regardless of the
        # genre preset in order to preserve the QA metrics baselines.
        contrast_vs_adjacent=base.contrast_vs_adjacent,
        escalation_per_repeat=base.escalation_per_repeat,
        subtract_on_repeat=base.subtract_on_repeat,
        default_transition_in=(
            override.default_transition_in
            if override.default_transition_in is not None
            else base.default_transition_in
        ),
        default_transition_out=(
            override.default_transition_out
            if override.default_transition_out is not None
            else base.default_transition_out
        ),
    )


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
    preset_name: Optional[str] = None,
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
    preset_name:
        Optional arrangement preset name (e.g. ``"trap"``, ``"cinematic"``).
        When provided, role priorities, density bounds, and forbidden roles are
        taken from the preset rather than the default ``SECTION_PROFILES``.

    Returns
    -------
    list[str]
        Ordered list of active roles (subset of available_roles).
    """
    if not available_roles:
        return []

    profile = get_effective_profile(section_type, preset_name)
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
    is_repeat: bool = False,
    available_roles: Optional[list[str]] = None,
    source_quality: Optional[str] = None,
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
    is_repeat:
        True when the incoming section type has appeared before.  Repeated
        sections use different transition types to avoid same-entry syndrome.
    available_roles:
        Optional list of available stem roles.  Transition intensity is
        raised when richer stem sources are available (fx, drums, etc.).
    source_quality:
        Optional source quality hint (e.g. "true_stems", "ai_separated").
        Higher quality enables stronger transition DSP.

    Returns
    -------
    list[TransitionEvent]
        Empty if no transition is warranted; otherwise 1–4 events.
        Placement values:
          "end_of_section"   — applied to the LAST bar of prev_section
          "start_of_section" — applied to the FIRST bar of next_section
    """
    events: list[TransitionEvent] = []
    prev = str(prev_section_type).strip().lower()
    nxt = str(next_section_type).strip().lower()
    roles = set(available_roles or [])
    has_fx = "fx" in roles
    has_drums = "drums" in roles or "percussion" in roles
    is_stem_rich = source_quality in {"true_stems", "zip_stems"} or len(roles) >= 3

    # ------------------------------------------------------------------
    # HOOK ENTRY — highest-priority transition.
    # Hooks must feel like a clear lift / re-entry regardless of source.
    # Repeated hooks use a different accent so they don't recycle the same
    # entry sensation.
    # ------------------------------------------------------------------
    if nxt in {"hook", "drop", "chorus"}:
        # Stronger riser when coming from a bridge/breakdown (wider energy gap).
        coming_from_sparse = prev in {"bridge", "breakdown", "intro"}
        riser_intensity = 0.90 if coming_from_sparse else 0.82
        crash_intensity = 0.92 if coming_from_sparse else 0.88

        # Pre-hook silence gap to create anticipation.
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="silence_drop_before_hook",
            placement="end_of_section",
            intensity=0.85 if not is_repeat else 0.78,
            description="Brief silence before hook entry for impact",
        ))

        # Riser FX to build energy into the hook.
        if has_fx or is_stem_rich:
            events.append(TransitionEvent(
                bar=max(0, next_start_bar - 1),
                event_type="riser_fx",
                placement="end_of_section",
                intensity=riser_intensity,
                description="FX riser into hook",
            ))
        elif coming_from_sparse:
            # No FX stem but a sparse predecessor — use a reverse_fx instead.
            events.append(TransitionEvent(
                bar=max(0, next_start_bar - 1),
                event_type="reverse_fx",
                placement="end_of_section",
                intensity=0.75,
                description="Reverse FX build into hook from sparse section",
            ))

        # Drum fill at end of outgoing section (if drums exist and we're not
        # coming from an already percussion-sparse section).
        if has_drums and prev not in {"bridge", "breakdown", "intro"}:
            events.append(TransitionEvent(
                bar=max(0, prev_end_bar),
                event_type="drum_fill",
                placement="end_of_section",
                intensity=0.80,
                description=f"Drum fill exiting {prev} into hook",
            ))

        # Crash hit at the hook downbeat — the actual re-entry accent.
        # Repeated hooks use re_entry_accent to avoid same-entry recycling.
        if is_repeat and occurrence_of_next >= 2:
            events.append(TransitionEvent(
                bar=next_start_bar,
                event_type="re_entry_accent",
                placement="start_of_section",
                intensity=crash_intensity,
                params={"hook_occurrence": occurrence_of_next},
                description=f"Hook re-entry accent (occurrence {occurrence_of_next})",
            ))
        else:
            events.append(TransitionEvent(
                bar=next_start_bar,
                event_type="crash_hit",
                placement="start_of_section",
                intensity=crash_intensity,
                description="Hook entry crash",
            ))

        # Extra expansion for third hook or later.
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

    # ------------------------------------------------------------------
    # PRE-HOOK ENTRY — build tension before the hook
    # ------------------------------------------------------------------
    if nxt == "pre_hook":
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="snare_pickup" if not is_repeat else "drum_fill",
            placement="end_of_section",
            intensity=0.80,
            description="Rhythmic pickup leading into pre-hook",
        ))
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="riser_fx",
            placement="end_of_section",
            intensity=0.78,
            description="FX riser into pre-hook",
        ))
        return events

    # ------------------------------------------------------------------
    # BRIDGE / BREAKDOWN ENTRY — reduce density smoothly, no hard cut
    # ------------------------------------------------------------------
    if nxt in {"bridge", "breakdown"}:
        # Silence gap: brief but noticeable "drop" to signal the energy reduction.
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="silence_gap",
            placement="end_of_section",
            intensity=0.80,
            description=f"Silence gap before {nxt} for smooth density reduction",
        ))
        # Reverse FX sweep to signal the energy going down.
        events.append(TransitionEvent(
            bar=max(0, next_start_bar - 1),
            event_type="reverse_fx",
            placement="end_of_section",
            intensity=0.72,
            description=f"Reverse FX sweep into {nxt}",
        ))
        # Subtractive entry at the start of bridge/breakdown so it opens gently.
        events.append(TransitionEvent(
            bar=next_start_bar,
            event_type="subtractive_entry",
            placement="start_of_section",
            intensity=0.70,
            description=f"Subtractive entry into {nxt}",
        ))
        return events

    # ------------------------------------------------------------------
    # OUTRO ENTRY — resolve naturally
    # ------------------------------------------------------------------
    if nxt == "outro":
        events.append(TransitionEvent(
            bar=next_start_bar,
            event_type="subtractive_entry",
            placement="start_of_section",
            intensity=0.65,
            description="Subtractive entry into outro for natural resolution",
        ))
        return events

    # ------------------------------------------------------------------
    # HOOK → VERSE — release energy without a hard reset
    # ------------------------------------------------------------------
    if prev in {"hook", "drop", "chorus"} and nxt == "verse":
        if has_drums:
            events.append(TransitionEvent(
                bar=max(0, prev_end_bar),
                event_type="drum_fill",
                placement="end_of_section",
                intensity=0.72,
                description="Drum fill exiting hook into verse",
            ))
        # Subtractive entry so verse opens with slightly reduced density,
        # giving the impression of energy release rather than a hard stop.
        events.append(TransitionEvent(
            bar=next_start_bar,
            event_type="subtractive_entry",
            placement="start_of_section",
            intensity=0.60,
            description="Soft verse re-entry after hook (energy release)",
        ))
        return events

    # ------------------------------------------------------------------
    # VERSE EXIT / INTRO EXIT — drum fill when moving forward
    # ------------------------------------------------------------------
    if prev in {"verse", "intro"} and nxt not in {"outro", "breakdown", "bridge", "pre_hook"}:
        events.append(TransitionEvent(
            bar=max(0, prev_end_bar),
            event_type="drum_fill" if has_drums else "snare_pickup",
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

    Legacy metrics (v1.0):
      section_contrast_score, repetition_variation_score, transition_impact_score,
      role_choreography_score, payoff_strength_score

    New metrics (v2.0):
      section_identity_score, repeat_distinction_score, phrase_variation_score,
      arrangement_motion_score, audible_contrast_score
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

    # ---- Phase 5 / v2.0 metrics ----

    section_identity_score: float = 0.0
    """Fraction of sections whose active roles contain no profile-forbidden roles."""

    repeat_distinction_score: float = 0.0
    """Average Jaccard distance between consecutive occurrences of the same section type.
    A value >= 0.20 means repeated sections are audibly distinguishable."""

    phrase_variation_score: float = 0.0
    """Fraction of sections > 4 bars that carry a phrase-level variation plan.
    A value of 1.0 means every eligible section has internal first/second-half contrast."""

    arrangement_motion_score: float = 0.0
    """Fraction of adjacent section pairs where at least one role was ADDED and at least
    one was REMOVED.  Pure density shifts (add-only or remove-only) do not count."""

    audible_contrast_score: float = 0.0
    """Fraction of adjacent different-type section pairs where the role Jaccard distance
    exceeds 0.35 — the threshold below which most listeners cannot reliably detect the
    section change."""

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

    # ---- section_identity_score (v2.0) ----
    # Fraction of sections whose active roles contain no profile-forbidden roles.
    identity_ok = 0
    for snap in snaps:
        profile = SECTION_PROFILES.get(snap.section_type)
        if profile is None:
            identity_ok += 1  # Unknown section type: treat as ok
            continue
        if not any(r in profile.forbidden_roles for r in snap.active_roles):
            identity_ok += 1
    metrics.section_identity_score = round(identity_ok / len(snaps), 3)
    if metrics.section_identity_score < 1.0:
        violations = len(snaps) - identity_ok
        metrics.warnings.append(
            f"section_identity_score={metrics.section_identity_score:.2f} — "
            f"{violations} section(s) contain forbidden roles for their type"
        )

    # ---- repeat_distinction_score (v2.0) ----
    # Average Jaccard distance between consecutive same-type occurrences.
    repeat_pairs: list[float] = []
    prev_occurrence_roles: dict[str, list[str]] = {}
    for snap in snaps:
        if snap.section_type in prev_occurrence_roles:
            dist = _jaccard_distance(snap.active_roles, prev_occurrence_roles[snap.section_type])
            repeat_pairs.append(dist)
        prev_occurrence_roles[snap.section_type] = snap.active_roles
    metrics.repeat_distinction_score = (
        round(sum(repeat_pairs) / len(repeat_pairs), 3) if repeat_pairs else 1.0
    )
    if repeat_pairs and metrics.repeat_distinction_score < 0.20:
        metrics.warnings.append(
            f"repeat_distinction_score={metrics.repeat_distinction_score:.2f} — "
            "consecutive repeated sections sound near-identical (target >= 0.20)"
        )

    # ---- phrase_variation_score (v2.0) ----
    # Fraction of sections > 4 bars that carry a phrase_plan dict.
    eligible_for_phrase = [s for s in sections if int(s.get("bars", 0) or 0) > 4]
    if eligible_for_phrase:
        has_phrase_plan = sum(1 for s in eligible_for_phrase if s.get("phrase_plan"))
        metrics.phrase_variation_score = round(has_phrase_plan / len(eligible_for_phrase), 3)
    else:
        metrics.phrase_variation_score = 1.0  # No eligible sections; not a problem
    if eligible_for_phrase and metrics.phrase_variation_score < 0.50:
        metrics.warnings.append(
            f"phrase_variation_score={metrics.phrase_variation_score:.2f} — "
            "most sections > 4 bars lack intra-section phrase variation"
        )

    # ---- arrangement_motion_score (v2.0) ----
    # Fraction of adjacent pairs where at least one role is added AND one is removed.
    motion_pairs = 0
    motion_count = 0
    for i in range(1, len(snaps)):
        a = set(snaps[i - 1].active_roles)
        b = set(snaps[i].active_roles)
        motion_pairs += 1
        if (b - a) and (a - b):  # Both additions and removals
            motion_count += 1
    metrics.arrangement_motion_score = (
        round(motion_count / motion_pairs, 3) if motion_pairs else 1.0
    )
    if motion_pairs > 0 and metrics.arrangement_motion_score < 0.30:
        metrics.warnings.append(
            f"arrangement_motion_score={metrics.arrangement_motion_score:.2f} — "
            "arrangement mostly shifts density; too few real role swaps"
        )

    # ---- audible_contrast_score (v2.0) ----
    # Stricter Jaccard threshold (> 0.35) on adjacent different-type boundaries.
    audible_pairs = 0
    audible_count = 0
    for i in range(1, len(snaps)):
        if snaps[i].section_type != snaps[i - 1].section_type:
            audible_pairs += 1
            if _jaccard_distance(snaps[i].active_roles, snaps[i - 1].active_roles) > _AUDIBLE_CONTRAST_THRESHOLD:
                audible_count += 1
    metrics.audible_contrast_score = (
        round(audible_count / audible_pairs, 3) if audible_pairs else 1.0
    )
    if audible_pairs > 0 and metrics.audible_contrast_score < 0.50:
        metrics.warnings.append(
            f"audible_contrast_score={metrics.audible_contrast_score:.2f} — "
            f"section boundaries may not be audible enough (target > {_AUDIBLE_CONTRAST_THRESHOLD} Jaccard)"
        )

    return metrics


# ---------------------------------------------------------------------------
# Phase 1 — Section Choreography
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SectionChoreography:
    """Role hierarchy for one section occurrence.

    Describes *how* roles are arranged within a section — not just which are
    present.  The renderer uses this to apply differential treatment (e.g.,
    leader gets slightly more headroom, support sits behind, suppressed are
    absent even when available).
    """

    leader_roles: tuple[str, ...]      # Roles that carry this section prominently
    support_roles: tuple[str, ...]     # Present but secondary; mix slightly behind
    suppressed_roles: tuple[str, ...]  # Absent by design (stronger than forbidden)
    contrast_roles: tuple[str, ...]    # Optional roles that add harmonic interest
    rotation_note: str = ""            # Human-readable annotation for diagnostics


# Per-section choreography templates indexed by occurrence (0-based, wraps around).
# Each list entry represents one distinct occurrence; the list cycles for extra repeats.
_CHOREOGRAPHY_TEMPLATES: dict[str, list[SectionChoreography]] = {
    "intro": [
        SectionChoreography(
            leader_roles=("pads", "fx"),
            support_roles=("melody",),
            suppressed_roles=("drums", "bass", "percussion"),
            contrast_roles=("arp",),
            rotation_note="Atmospheric entry — pads and FX carry",
        ),
    ],
    "verse": [
        # Occurrence 1: rhythm backbone carries, melody floats
        SectionChoreography(
            leader_roles=("drums", "bass"),
            support_roles=("melody",),
            suppressed_roles=("synth", "arp"),
            contrast_roles=("vocal",),
            rotation_note="Verse 1 — rhythm leads, melody supports",
        ),
        # Occurrence 2: melody promoted to co-leader, support rotated
        SectionChoreography(
            leader_roles=("melody", "bass"),
            support_roles=("drums",),
            suppressed_roles=("arp",),
            contrast_roles=("vocal", "pads"),
            rotation_note="Verse 2 — melody co-leads, support rotated",
        ),
        # Occurrence 3: synth enters as contrast, arp adds texture
        SectionChoreography(
            leader_roles=("drums", "melody"),
            support_roles=("bass", "synth"),
            suppressed_roles=(),
            contrast_roles=("arp",),
            rotation_note="Verse 3 — synth contrast layer added",
        ),
    ],
    "pre_hook": [
        # Occurrence 1: rhythmic edge, bass drives; melody stays as harmonic support
        SectionChoreography(
            leader_roles=("bass", "percussion"),
            support_roles=("melody", "arp"),
            suppressed_roles=("pads",),
            contrast_roles=("fx",),
            rotation_note="Pre-hook 1 — tension through bass/perc lead, melody supports",
        ),
        # Occurrence 2: melody promoted to co-lead; drums suppressed for tension-through-absence
        SectionChoreography(
            leader_roles=("melody", "bass"),
            support_roles=("arp", "fx"),
            suppressed_roles=("drums", "percussion"),
            contrast_roles=("synth",),
            rotation_note="Pre-hook 2 — melody co-leads, drums absent for tension-through-absence",
        ),
    ],
    "hook": [
        # Occurrence 1: full groove, melody+synth support
        SectionChoreography(
            leader_roles=("drums", "bass"),
            support_roles=("melody", "synth"),
            suppressed_roles=(),
            contrast_roles=("vocal", "percussion"),
            rotation_note="Hook 1 — full groove, melody+synth support",
        ),
        # Occurrence 2: melody elevated to co-leader, texture expands
        SectionChoreography(
            leader_roles=("drums", "melody"),
            support_roles=("bass", "synth"),
            suppressed_roles=(),
            contrast_roles=("vocal", "pads", "fx"),
            rotation_note="Hook 2 — melody co-leads, texture expands",
        ),
        # Occurrence 3: maximum density, all contrast roles join
        SectionChoreography(
            leader_roles=("drums", "melody"),
            support_roles=("bass", "synth", "pads"),
            suppressed_roles=(),
            contrast_roles=("vocal", "arp", "fx"),
            rotation_note="Hook 3 — maximum payoff, all contrast roles",
        ),
    ],
    "bridge": [
        SectionChoreography(
            leader_roles=("pads", "melody"),
            support_roles=("fx",),
            suppressed_roles=("drums", "bass", "percussion"),
            contrast_roles=("vocal", "arp"),
            rotation_note="Bridge — melodic/textural, groove suppressed",
        ),
    ],
    "breakdown": [
        SectionChoreography(
            leader_roles=("pads", "fx"),
            support_roles=("vocal",),
            suppressed_roles=("drums", "bass", "percussion"),
            contrast_roles=("arp", "melody"),
            rotation_note="Breakdown — atmosphere only, groove absent",
        ),
    ],
    "outro": [
        SectionChoreography(
            leader_roles=("pads", "melody"),
            support_roles=("fx",),
            suppressed_roles=("drums", "bass", "percussion"),
            contrast_roles=("arp",),
            rotation_note="Outro — resolution, groove stripped",
        ),
    ],
}

_FALLBACK_CHOREOGRAPHY = SectionChoreography(
    leader_roles=(),
    support_roles=(),
    suppressed_roles=(),
    contrast_roles=(),
    rotation_note="Fallback — no choreography rule for this section type",
)


def get_section_choreography(
    section_type: str,
    occurrence: int,
    available_roles: list[str],
) -> SectionChoreography:
    """Return the deterministic role hierarchy for a section occurrence.

    Parameters
    ----------
    section_type:
        Canonical section type string.
    occurrence:
        1-based occurrence counter for this section type in the arrangement.
    available_roles:
        All roles present in the source material.  Used to filter the
        leader/support/contrast lists to only roles that exist.

    Returns
    -------
    SectionChoreography
        Choreography with leader/support/suppressed/contrast filtered to
        only the roles present in available_roles.
    """
    templates = _CHOREOGRAPHY_TEMPLATES.get(
        str(section_type).strip().lower(),
        None,
    )
    if not templates:
        return _FALLBACK_CHOREOGRAPHY

    idx = (max(1, occurrence) - 1) % len(templates)
    template = templates[idx]

    available_set = set(available_roles)
    return SectionChoreography(
        leader_roles=tuple(r for r in template.leader_roles if r in available_set),
        support_roles=tuple(r for r in template.support_roles if r in available_set),
        # suppressed_roles intentionally NOT filtered — they should be absent even
        # if they exist in the source.
        suppressed_roles=template.suppressed_roles,
        contrast_roles=tuple(r for r in template.contrast_roles if r in available_set),
        rotation_note=template.rotation_note,
    )


def select_roles_with_choreography(
    section_type: str,
    available_roles: list[str],
    occurrence: int = 1,
    prev_same_type_roles: Optional[list[str]] = None,
    next_section_type: Optional[str] = None,
    prev_adjacent_roles: Optional[list[str]] = None,
    preset_name: Optional[str] = None,
) -> tuple[list[str], SectionChoreography]:
    """Select active roles AND compute the role hierarchy for one section occurrence.

    Extends ``select_roles_for_section`` by also enforcing the occurrence-based
    suppression and leader rotation defined in ``_CHOREOGRAPHY_TEMPLATES``.  The
    choreography object is returned alongside the role list so callers can use it
    for render-time DSP decisions (e.g., boost leader by +1 dB).

    Parameters
    ----------
    section_type, available_roles, occurrence, prev_same_type_roles,
    next_section_type, prev_adjacent_roles:
        Same semantics as ``select_roles_for_section``.
    preset_name:
        Optional arrangement preset name.  When provided, the effective
        profile (role priorities, density, forbidden roles) is derived from
        the preset rather than the base ``SECTION_PROFILES``.

    Returns
    -------
    (active_roles, choreography):
        active_roles — ordered list of active roles for this section.
        choreography — SectionChoreography with role hierarchy metadata.
    """
    if not available_roles:
        return [], _FALLBACK_CHOREOGRAPHY

    choreography = get_section_choreography(section_type, occurrence, available_roles)

    profile = get_effective_profile(section_type, preset_name)
    available_set = set(available_roles)

    # Merge profile's forbidden with choreography's suppressed roles.
    effective_forbidden = profile.forbidden_roles | frozenset(choreography.suppressed_roles)
    permitted = [r for r in available_roles if r not in effective_forbidden]

    # Build the preference order: leaders first, then support, then contrast,
    # then profile priority order, then anything remaining.
    order_map: dict[str, int] = {}
    for i, r in enumerate(choreography.leader_roles):
        order_map[r] = i
    base = len(choreography.leader_roles)
    for i, r in enumerate(choreography.support_roles):
        order_map.setdefault(r, base + i)
    base += len(choreography.support_roles)
    for i, r in enumerate(choreography.contrast_roles):
        order_map.setdefault(r, base + i)
    base += len(choreography.contrast_roles)
    for i, r in enumerate(profile.role_priorities):
        order_map.setdefault(r, base + i)

    preferred_order = sorted(
        [r for r in permitted if r in order_map],
        key=lambda r: order_map[r],
    )
    for r in permitted:
        if r not in set(preferred_order):
            preferred_order.append(r)

    if not preferred_order:
        # All roles forbidden/suppressed — return least harmful.
        return ([available_roles[0]] if available_roles else []), choreography

    target_count = _target_density(profile, occurrence, len(preferred_order))
    candidates = preferred_order[:target_count]

    # Apply support-role rotation using choreography-aware evolution.
    candidates = _apply_choreography_evolution(
        profile=profile,
        occurrence=occurrence,
        candidates=candidates,
        preferred_order=preferred_order,
        prev_same_type_roles=prev_same_type_roles or [],
        choreography=choreography,
    )

    if prev_adjacent_roles:
        candidates = _enforce_adjacent_contrast(
            profile=profile,
            candidates=candidates,
            preferred_order=preferred_order,
            prev_adjacent_roles=prev_adjacent_roles,
            available_roles=available_roles,
        )

    # Prefer isolated roles over full_mix.
    non_full = [r for r in candidates if r != "full_mix"]
    if len(non_full) >= 2:
        candidates = non_full

    candidates = candidates[: profile.density_max]
    if len(candidates) < profile.density_min and preferred_order:
        extra = [r for r in preferred_order if r not in set(candidates)]
        candidates.extend(extra[: profile.density_min - len(candidates)])

    candidates = [r for r in candidates if r in available_set]
    if not candidates:
        candidates = preferred_order[:1] if preferred_order else []

    return candidates, choreography


def _apply_choreography_evolution(
    profile: SectionProfile,
    occurrence: int,
    candidates: list[str],
    preferred_order: list[str],
    prev_same_type_roles: list[str],
    choreography: SectionChoreography,
) -> list[str]:
    """Rotate support roles between repeated sections for audible distinction.

    Unlike the base ``_apply_evolution`` (which only forces a change when sets
    are identical), this version also rotates when the Jaccard distance between
    the current candidates and the previous occurrence is below 0.25 — even if
    the sets are not strictly equal.
    """
    if occurrence <= 1 or not prev_same_type_roles:
        return candidates

    prev_set = set(prev_same_type_roles)
    current_set = set(candidates)

    jaccard = _jaccard_distance(list(current_set), list(prev_set))

    if jaccard < _CHOREOGRAPHY_ROTATION_THRESHOLD:
        # Sets are too similar — rotate support roles.
        # Find roles NOT in the previous occurrence (fresh choices).
        fresh_roles = [r for r in preferred_order if r not in prev_set]
        # Roles shared between previous and current (candidates for swapping out).
        shared_roles = [c for c in candidates if c in prev_set]

        # Prefer swapping support-tier roles (not leaders) to preserve section identity.
        leader_set = set(choreography.leader_roles)
        non_leader_shared = [r for r in shared_roles if r not in leader_set]
        swap_targets = non_leader_shared if non_leader_shared else shared_roles

        # Rotation index: deterministic, advances by 1 per occurrence so
        # the same pair of candidates is never chosen twice in a row.
        rotation_index = max(0, occurrence - 2)

        if fresh_roles and swap_targets:
            swap_in = fresh_roles[rotation_index % len(fresh_roles)]
            swap_out = swap_targets[rotation_index % len(swap_targets)]
            candidates = [c for c in candidates if c != swap_out] + [swap_in]
        elif fresh_roles and len(candidates) < profile.density_max:
            candidates = list(candidates) + [fresh_roles[rotation_index % len(fresh_roles)]]

    # subtract_on_repeat: pre_hook loses drums on every repeat for tension.
    if profile.subtract_on_repeat and occurrence >= 2:
        for r in ("drums", "percussion"):
            if r in set(candidates) and len(candidates) > profile.density_min:
                candidates = [c for c in candidates if c != r]
                break

    return candidates


# ---------------------------------------------------------------------------
# Phase 2 — Intra-Section Phrase Variation
# ---------------------------------------------------------------------------


@dataclass
class PhraseVariationPlan:
    """Intra-section phrase variation for sections longer than 4 bars.

    Splits the section into two phrases at ``split_bar`` and assigns
    independent role sets to each half.  When the render pipeline has this
    data it builds each phrase from separate stems, creating real audible
    movement inside a single section.
    """

    section_type: str
    total_bars: int
    split_bar: int                         # Relative bar index where second phrase starts
    first_phrase_roles: list[str]          # Active stems for bars [0, split_bar)
    second_phrase_roles: list[str]         # Active stems for bars [split_bar, total_bars)
    lead_entry_delay_bars: int = 0         # Bars before lead role enters (0 = immediate)
    end_dropout_bars: int = 0              # Bars at section end where some roles drop
    end_dropout_roles: list[str] = field(default_factory=list)
    description: str = ""


def get_phrase_variation_plan(
    section_type: str,
    active_roles: list[str],
    section_bars: int,
    occurrence: int = 1,
    available_roles: Optional[list[str]] = None,
) -> Optional[PhraseVariationPlan]:
    """Return a phrase variation plan for sections longer than 4 bars.

    Creates meaningful internal movement inside a section rather than a
    static repeated loop.  Returns ``None`` for sections ≤ 4 bars (too
    short for audible phrase structure) or when active_roles has fewer
    than 2 roles.

    Parameters
    ----------
    section_type:
        Canonical section type string.
    active_roles:
        Roles selected for this section occurrence (output of role selector).
    section_bars:
        Total number of bars in this section.
    occurrence:
        1-based occurrence counter for this section type.
    available_roles:
        All roles in the source (used to fill second-half hook expansion).
    """
    if section_bars <= 4:
        return None  # Too short for phrase-level variation
    if len(active_roles) < 2:
        return None  # Need at least 2 roles to vary

    stype = str(section_type).strip().lower()
    active_set = set(active_roles)
    # Cap split_bar at 4 so melody/harmony never disappears for more than 4 bars.
    # For sections ≤ 8 bars this has no effect (section_bars // 2 ≤ 4 already);
    # for sections > 8 bars (e.g. 16-bar verse) it prevents 8-bar no-melody zones.
    split_bar = min(section_bars // 2, 4)

    if stype == "verse":
        # First phrase: rhythm backbone only (drums + bass).
        # Second phrase: full role set (adds melody/lead at bar split_bar).
        rhythmic = [r for r in active_roles if r in {"drums", "bass", "percussion"}]
        melodic_in_active = [r for r in active_roles if r in {"melody", "vocal", "synth", "arp"}]
        support = [r for r in active_roles if r not in set(rhythmic) and r not in set(melodic_in_active)]

        # For repeated verses whose active_roles were capped to reserve headroom for hooks,
        # the section may only contain rhythmic stems.  Pull melodic roles from available_roles
        # into the second phrase so the verse still has its "melody enters mid-section" arc.
        bonus_melodic: list[str] = []
        if occurrence >= 2 and available_roles:
            bonus_melodic = [
                r for r in available_roles
                if r in {"melody", "vocal", "synth", "arp"}
                and r not in active_set
            ]

        all_melodic = melodic_in_active + bonus_melodic

        if rhythmic and all_melodic:
            first_phrase = list(rhythmic) + list(support)
            second_phrase = list(active_roles) + bonus_melodic
            # End dropout: remove atmospheric roles in last bar
            end_drop = [r for r in ["pads", "synth", "arp"] if r in active_set]
            bonus_note = (f" (bonus melodic from available: {bonus_melodic})" if bonus_melodic else "")
            return PhraseVariationPlan(
                section_type=stype,
                total_bars=section_bars,
                split_bar=split_bar,
                first_phrase_roles=first_phrase,
                second_phrase_roles=second_phrase,
                lead_entry_delay_bars=0,
                end_dropout_bars=1,
                end_dropout_roles=end_drop[:1],
                description=(
                    f"Verse {occurrence} phrase split bar {split_bar}: "
                    f"rhythm-only first half → full second half{bonus_note}"
                ),
            )

    elif stype == "hook":
        # Hook 1: Only create a phrase plan when there are genuinely more stems
        # available in the second half than the first (core → core+extra).
        # When all available stems are already in active_roles the two halves
        # would be identical, so return None — let the hook hit full immediately
        # for maximum wall-of-sound impact.  This contrasts with verse 2, which
        # always has an internal build (rhythm-only → full).
        if occurrence == 1:
            core = [r for r in active_roles if r in {"drums", "bass", "melody", "vocal"}]
            extra_in_active = [r for r in active_roles if r not in set(core)]
            extra_available = [
                r for r in (available_roles or [])
                if r not in active_set and r not in {"full_mix"}
            ]
            if core:
                second = list(active_roles)
                if extra_available and len(second) < 5:
                    second = second + [extra_available[0]]
                # Only return a plan when first and second halves are meaningfully different.
                if set(core + extra_in_active) == set(second):
                    return None  # No extra contrast available; hit full immediately.
                return PhraseVariationPlan(
                    section_type=stype,
                    total_bars=section_bars,
                    split_bar=split_bar,
                    first_phrase_roles=core + extra_in_active,
                    second_phrase_roles=second,
                    lead_entry_delay_bars=0,
                    end_dropout_bars=0,
                    description=(
                        f"Hook 1 phrase split bar {split_bar}: "
                        f"core first half → expanded second half"
                    ),
                )
            return None

        # Hook 2: "anticipation drop → re-explosion" phrase structure.
        # First half strips to rhythmic core (drums+bass), creating a brief
        # "drop" feeling before melody and full texture crash back at split_bar.
        # This makes hook 2 feel distinct from hook 1's straight-blast feel,
        # while the hook_evolution DSP layer adds the extra energy/presence.
        if occurrence == 2:
            rhythmic = [r for r in active_roles if r in {"drums", "bass", "percussion"}]
            # For the "explosion" half, also pull any available melodic roles not
            # yet in active_roles (happens when verse post-pass capped stems).
            bonus_explosion: list[str] = []
            if available_roles:
                bonus_explosion = [
                    r for r in available_roles
                    if r not in active_set and r not in {"full_mix"}
                    and r in {"melody", "vocal", "synth", "arp", "pads", "fx"}
                ]
            full_set = list(active_roles) + bonus_explosion[:1]
            # Hook 2 "anticipation drop": first phrase is purely rhythmic (no melody),
            # so melody crashes back at split_bar for the "re-explosion" effect.
            # This creates an audible distinction from hook 1's straight full-blast.
            melodic_in_active = [r for r in active_roles if r in {"melody", "vocal", "synth", "arp"}]
            first_phrase = list(rhythmic)
            if first_phrase and melodic_in_active and set(first_phrase) != set(full_set):
                return PhraseVariationPlan(
                    section_type=stype,
                    total_bars=section_bars,
                    split_bar=split_bar,
                    first_phrase_roles=first_phrase,
                    second_phrase_roles=full_set,
                    lead_entry_delay_bars=0,
                    end_dropout_bars=0,
                    description=(
                        f"Hook 2 phrase split bar {split_bar}: "
                        f"lean first half ({', '.join(first_phrase)}) "
                        f"→ full re-explosion ({', '.join(full_set)}) at bar {split_bar}"
                    ),
                )
            return None

        # Hook 3+: Return None — let hook_evolution DSP deliver the climax.
        # Adding a phrase split here would thin the opening bars and undermine
        # the "maximum impact" feel expected from the final hook.
        return None

    elif stype == "pre_hook":
        # Full roles first half; single-bar dropout of rhythmic roles at section end
        # for a brief tension beat.  Previously used min(2, section_bars // 2) which
        # could remove drums for up to half the section.
        end_drop = [r for r in ["drums", "percussion"] if r in active_set]
        return PhraseVariationPlan(
            section_type=stype,
            total_bars=section_bars,
            split_bar=split_bar,
            first_phrase_roles=list(active_roles),
            second_phrase_roles=list(active_roles),
            lead_entry_delay_bars=0,
            end_dropout_bars=1,
            end_dropout_roles=end_drop[:1],
            description=(
                f"Pre-hook {occurrence}: tension via dropout of "
                f"{', '.join(end_drop[:1]) or 'none'} in last bar"
            ),
        )

    elif stype in {"bridge", "breakdown"}:
        # Delayed lead entry: atmospheric roles fill first phrase, melodic enters second.
        atmospheric = [r for r in active_roles if r in {"pads", "fx", "arp"}]
        melodic_parts = [r for r in active_roles if r in {"melody", "vocal", "synth"}]
        if atmospheric and melodic_parts:
            return PhraseVariationPlan(
                section_type=stype,
                total_bars=section_bars,
                split_bar=split_bar,
                first_phrase_roles=atmospheric,
                second_phrase_roles=list(active_roles),
                lead_entry_delay_bars=split_bar,
                end_dropout_bars=0,
                description=(
                    f"{stype.title()} {occurrence} phrase split bar {split_bar}: "
                    f"atmosphere first → melody enters at bar {split_bar}"
                ),
            )

    elif stype == "outro":
        # Progressive strip: full roles first half, one role removed in second half.
        # end_dropout_bars capped at section_bars // 3 (at most ~2 bars) to avoid
        # stripping melody for half the outro, which previously sounded like a cut-off.
        second = active_roles[:max(1, len(active_roles) - 1)]
        return PhraseVariationPlan(
            section_type=stype,
            total_bars=section_bars,
            split_bar=split_bar,
            first_phrase_roles=list(active_roles),
            second_phrase_roles=second,
            lead_entry_delay_bars=0,
            end_dropout_bars=min(2, section_bars // 3),
            end_dropout_roles=list(active_roles[-1:]),
            description=f"Outro {occurrence}: progressive strip in second half",
        )

    return None


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
