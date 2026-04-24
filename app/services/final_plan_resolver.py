"""
Final Plan Resolver — merges all engine outputs into a single canonical
:class:`~app.services.resolved_render_plan.ResolvedRenderPlan`.

Usage::

    resolver = FinalPlanResolver(render_plan, available_roles=["drums", "bass"])
    resolved = resolver.resolve()

The resolver enforces these merge rules:

1. Section structure (name, type, bar_start, bars, energy) comes from
   ``render_plan["sections"]`` — established by arranger_v2 / legacy planner.
2. Role set starts from ``section["instruments"]`` (or ``active_stem_roles``),
   then:
   a. Decision Engine ``blocked_roles`` are subtracted.
   b. Decision Engine ``required_reentries`` are added back.
3. Boundary events are collected from *both* ``section["boundary_events"]`` and
   Drop Engine ``primary_drop_event``/``support_events``.  Events with the same
   ``event_type`` are deduplicated — the Drop Engine version wins when the same
   type appears in both.
4. Pattern events come from ``section["timeline_events"]`` (injected by the
   Pattern Variation primary pass).
5. Groove events come from ``section["_groove_events"]`` (injected by the Groove
   Engine primary pass).
6. Motif treatment comes from ``section["_motif_treatment"]`` (injected by the
   Motif Engine primary pass).
7. Any engine metadata that did not affect the final section state is recorded
   as a no-op annotation.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)

logger = logging.getLogger(__name__)

# Resolver version — bump when merge semantics change.
_RESOLVER_VERSION = 1

# Instrument Activation Rules: section-type → target fullness label.
_SECTION_FULLNESS: Dict[str, str] = {
    "HOOK": "full",
    "PRE_HOOK": "high",
    "VERSE": "medium",
    "BRIDGE": "medium",
    "INTRO": "sparse",
    "OUTRO": "sparse",
}

# Boundary event types from _BOUNDARY_TRANSITION_EVENT_TYPES in render_executor.
# Kept here so the resolver can route boundary vs. variation events correctly.
_BOUNDARY_TRANSITION_EVENT_TYPES: frozenset[str] = frozenset({
    "pre_hook_silence_drop",
    "drum_fill",
    "snare_pickup",
    "riser_fx",
    "reverse_cymbal",
    "crash_hit",
    "bridge_strip",
    "outro_strip",
    "pre_hook_drum_mute",
    "bass_pause",
    "silence_drop_before_hook",
    "final_hook_expansion",
    "reverse_fx",
    "silence_gap",
    "subtractive_entry",
    "re_entry_accent",
})

# Drop engine event-type to boundary event-type mapping.
_DROP_TO_BOUNDARY_TYPE: Dict[str, str] = {
    "pre_drop_silence": "silence_gap",
    "kick_fakeout": "drum_fill",
    "bass_dropout": "bass_pause",
    "riser_build": "riser_fx",
    "reverse_fx_entry": "reverse_fx",
    "re_entry_accent": "re_entry_accent",
    "staggered_reentry": "subtractive_entry",
    "crash_hit": "crash_hit",
    "delayed_drop": "silence_drop_before_hook",
    "filtered_pre_drop": "pre_hook_drum_mute",
    "snare_pickup": "snare_pickup",
    "silence_tease": "pre_hook_silence_drop",
}

# FX_TRANSITION rule type → boundary event type mapping.
_FX_RULE_TO_BOUNDARY_TYPE: Dict[str, str] = {
    "riser":   "riser_fx",
    "impact":  "crash_hit",
    "fade":    "outro_strip",
    "texture": "bridge_strip",
    "ambient": "pre_hook_silence_drop",
}


class FinalPlanResolver:
    """Merge all planning-engine outputs into one :class:`ResolvedRenderPlan`.

    Parameters
    ----------
    render_plan:
        The raw render plan dict as built by ``run_arrangement_job`` (contains
        ``sections``, ``_decision_plan``, ``_drop_plan``, etc.).
    available_roles:
        Full list of roles available in the source material.
    source_quality:
        Source quality mode string (``"true_stems"`` / ``"ai_separated"`` /
        ``"stereo_fallback"``).
    arrangement_id:
        Used only for log messages.
    genre:
        Genre hint passed to the Instrument Activation Rules engine for
        genre-aware density/complexity modifiers.
    vibe:
        Vibe/mood hint passed to the Instrument Activation Rules engine.
    variation_seed:
        Optional integer seed for deterministic per-arrangement rule variation.
    """

    def __init__(
        self,
        render_plan: Dict[str, Any],
        *,
        available_roles: Optional[List[str]] = None,
        source_quality: str = "stereo_fallback",
        arrangement_id: int = 0,
        genre: str = "generic",
        vibe: str = "",
        variation_seed: Optional[int] = None,
    ) -> None:
        self._plan = render_plan
        self._available_roles: List[str] = list(available_roles or [])
        self._source_quality = source_quality
        self._arrangement_id = arrangement_id
        self._noop_annotations: List[dict] = []
        self._genre = str(genre or "generic").lower().strip()
        self._vibe = str(vibe or "").lower().strip()
        self._variation_seed = variation_seed

        # Lazily import to avoid circular imports and allow test patching.
        self._rules_engine = self._init_rules_engine()  # type: ignore[assignment]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self) -> ResolvedRenderPlan:
        """Produce the canonical :class:`ResolvedRenderPlan`.

        Returns
        -------
        ResolvedRenderPlan
            Never raises — falls back to a minimal section list on error.
        """
        try:
            return self._build()
        except Exception as exc:  # pragma: no cover
            logger.exception(
                "FinalPlanResolver [arr=%d] resolve() failed: %s — falling back",
                self._arrangement_id,
                exc,
            )
            return self._fallback_resolved_plan()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build(self) -> ResolvedRenderPlan:
        plan = self._plan
        sections_raw: List[dict] = list(plan.get("sections") or [])
        bpm = float(plan.get("bpm") or 120.0)
        key = str(plan.get("key") or "C")
        total_bars = int(
            plan.get("total_bars")
            or sum(int(s.get("bars") or 0) for s in sections_raw)
        )
        render_profile: dict = dict(plan.get("render_profile") or {})
        genre = str(render_profile.get("genre_profile") or plan.get("genre") or "generic")

        # Decision Engine plan (per-section decisions)
        dec_plan: dict = plan.get("_decision_plan") or {}
        section_decisions: List[dict] = list(
            (dec_plan.get("section_decisions") or [])
        )

        # Drop Engine plan (per-boundary events)
        drop_plan: dict = plan.get("_drop_plan") or {}
        drop_boundaries: List[dict] = list(drop_plan.get("boundaries") or [])

        resolved_sections: List[ResolvedSection] = []
        for idx, raw_sec in enumerate(sections_raw):
            resolved = self._resolve_section(
                section_index=idx,
                raw_sec=raw_sec,
                section_decisions=section_decisions,
                drop_boundaries=drop_boundaries,
            )
            resolved_sections.append(resolved)

        return ResolvedRenderPlan(
            resolved_sections=resolved_sections,
            bpm=bpm,
            key=key,
            total_bars=total_bars,
            source_quality=self._source_quality,
            available_roles=list(self._available_roles),
            genre=genre,
            render_profile=render_profile,
            resolver_version=_RESOLVER_VERSION,
            noop_annotations=list(self._noop_annotations),
            rules_applied=self._rules_engine is not None and self._rules_engine.is_loaded,
            rule_set_version=(
                self._rules_engine.version
                if self._rules_engine and self._rules_engine.is_loaded
                else None
            ),
            rule_modifiers=(
                {"genre": self._genre, "vibe": self._vibe}
                if self._rules_engine and self._rules_engine.is_loaded
                else {}
            ),
        )

    # ------------------------------------------------------------------
    # Per-section resolution
    # ------------------------------------------------------------------

    def _resolve_section(
        self,
        section_index: int,
        raw_sec: dict,
        section_decisions: List[dict],
        drop_boundaries: List[dict],
    ) -> ResolvedSection:
        section_name = str(raw_sec.get("name") or raw_sec.get("type") or f"Section {section_index + 1}")
        section_type = str(raw_sec.get("type") or raw_sec.get("section_type") or "verse").strip().lower()
        bar_start = int(raw_sec.get("bar_start") or 0)
        bars = int(raw_sec.get("bars") or 8)
        energy = float(raw_sec.get("energy") or 0.6)

        # --- Step 1: derive base role set ---
        base_roles: List[str] = list(
            raw_sec.get("active_stem_roles")
            or raw_sec.get("instruments")
            or []
        )

        # --- Step 2: apply Decision Engine subtractions / reentries ---
        decision = self._find_section_decision(section_name, section_index, section_decisions)
        blocked_roles: List[str] = []
        reentry_roles: List[str] = []

        if decision:
            blocked_roles = list(decision.get("blocked_roles") or [])
            # Collect reentry role names
            reentry_roles = [
                a["target_role"]
                for a in (decision.get("required_reentries") or [])
                if a.get("target_role") and a.get("action_type") == "reintroduce_role"
            ]
            # Collect hold-back roles from required_subtractions
            held_back = [
                a["target_role"]
                for a in (decision.get("required_subtractions") or [])
                if a.get("target_role") and a.get("action_type") in (
                    "hold_back_role", "remove_role", "strip_to_core",
                    "pre_hook_subtraction",
                )
            ]
            blocked_roles = _ordered_unique(blocked_roles + held_back)

        # Apply subtractions
        active_roles = [r for r in base_roles if r not in blocked_roles]

        # Apply reentries (only roles in available_roles)
        for role in reentry_roles:
            if role not in active_roles and (
                not self._available_roles or role in self._available_roles
            ):
                active_roles.append(role)

        # Record no-ops from Decision Engine (blocked roles not in base_roles)
        for role in blocked_roles:
            if role not in base_roles:
                self._noop_annotations.append({
                    "engine_name": "decision",
                    "section": section_name,
                    "planned_action": f"block_role:{role}",
                    "reason_not_applied": f"role '{role}' was not in section base roles",
                })

        # --- Step 3: collect boundary events ---
        boundary_events = self._merge_boundary_events(
            raw_sec=raw_sec,
            section_name=section_name,
            bar_start=bar_start,
            drop_boundaries=drop_boundaries,
            section_type=section_type,
        )

        # --- Step 4: collect pattern events from timeline_events ---
        pattern_events = self._extract_pattern_events(raw_sec)

        # --- Step 5: collect groove events ---
        groove_events = list(raw_sec.get("_groove_events") or [])
        if not groove_events and raw_sec.get("groove_events"):
            groove_events = list(raw_sec["groove_events"])

        # --- Step 6: motif treatment ---
        motif_treatment: Optional[dict] = raw_sec.get("_motif_treatment") or None

        # --- Step 7: apply Instrument Activation Rules ---
        rule_snapshot, target_fullness, iar_blocked, extra_pattern_events = (
            self._apply_iar_to_section(section_type, section_name, active_roles)
        )
        if iar_blocked:
            active_roles = [r for r in active_roles if r not in iar_blocked]
            blocked_roles = _ordered_unique(blocked_roles + iar_blocked)
        pattern_events = pattern_events + extra_pattern_events

        return ResolvedSection(
            section_name=section_name,
            section_type=section_type,
            bar_start=bar_start,
            bars=bars,
            energy=energy,
            final_active_roles=active_roles,
            final_blocked_roles=blocked_roles,
            final_reentries=reentry_roles,
            final_boundary_events=boundary_events,
            final_pattern_events=pattern_events,
            final_groove_events=groove_events,
            final_motif_treatment=motif_treatment,
            timeline_events=list(raw_sec.get("timeline_events") or []),
            loop_variant=raw_sec.get("loop_variant"),
            phrase_plan=raw_sec.get("phrase_plan"),
            hook_evolution=raw_sec.get("hook_evolution"),
            variations=list(raw_sec.get("variations") or []),
            rule_snapshot=rule_snapshot,
            target_fullness=target_fullness,
        )

    # ------------------------------------------------------------------
    # Instrument Activation Rules integration
    # ------------------------------------------------------------------

    def _init_rules_engine(self):  # type: ignore[return]
        """Load the IAR engine; return ``None`` on any failure (fallback mode)."""
        try:
            from app.services.instrument_activation_rules import InstrumentActivationRules  # noqa: PLC0415
            engine = InstrumentActivationRules()
            if not engine.is_loaded:
                logger.warning(
                    "FinalPlanResolver [arr=%d]: IAR engine loaded with failure: %s "
                    "— invalid_rule_fallback mode active",
                    self._arrangement_id,
                    engine._load_failure,
                )
            return engine
        except Exception as exc:
            logger.warning(
                "FinalPlanResolver [arr=%d]: IAR engine could not be initialised: %s "
                "— invalid_rule_fallback mode active",
                self._arrangement_id,
                exc,
            )
            return None

    def _apply_iar_to_section(
        self,
        section_type: str,
        section_name: str,
        active_roles: List[str],
    ):
        """Apply Instrument Activation Rules to one section.

        Returns
        -------
        tuple
            ``(rule_snapshot, target_fullness, iar_blocked_roles, extra_pattern_events)``

        Falls back gracefully to empty outputs when the rules engine is
        unavailable or the section type is not found.
        """
        _empty = (None, None, [], [])

        engine = self._rules_engine
        if engine is None or not engine.is_loaded:
            return _empty

        try:
            rules = engine.get_rules_for_section(section_type)
            if self._genre or self._vibe:
                rules = engine.apply_genre_vibe_modifiers(
                    rules, genre=self._genre, vibe=self._vibe
                )
            if self._variation_seed is not None:
                rules = engine.apply_variation_seed(rules, seed=self._variation_seed)

            roles_data: dict = rules.get("roles") or {}

            # Determine which active roles IAR wants to block.
            iar_blocked: List[str] = [
                role
                for role, rule in roles_data.items()
                if isinstance(rule, dict) and not rule.get("active", True)
                and role in active_roles
            ]

            # Extra pattern events driven by rule flags.
            extra_pattern_events: List[dict] = []
            # PRE_HOOK drop_kick: remove kick accent from drums pattern.
            canonical = section_type.upper().replace("-", "_")
            if canonical in ("PRE_HOOK", "PRE_CHORUS", "BUILDUP", "BUILD"):
                drums_rule = roles_data.get("drums") or {}
                if drums_rule.get("drop_kick"):
                    extra_pattern_events.append({
                        "action": "drop_kick",
                        "source": "instrument_activation_rules",
                        "bar": 0,
                        "intensity": float(drums_rule.get("density") or 0.75),
                    })

            # target_fullness from section type.
            target_fullness = _SECTION_FULLNESS.get(canonical, "medium")

            # Capture the final rule values as a snapshot.
            rule_snapshot: Dict[str, Any] = {
                "roles": {role: dict(rule) for role, rule in roles_data.items()},
                "section_type": rules.get("section_type", section_type),
            }
            if rules.get("_modifiers_applied") is not None:
                rule_snapshot["_modifiers_applied"] = rules["_modifiers_applied"]
                logger.info(
                    "FinalPlanResolver [arr=%d] section='%s': rule_override_applied %s",
                    self._arrangement_id,
                    section_name,
                    rules["_modifiers_applied"],
                )
            if rules.get("_variation_seed") is not None:
                rule_snapshot["_variation_seed"] = rules["_variation_seed"]

            if iar_blocked:
                logger.debug(
                    "FinalPlanResolver [arr=%d] section='%s': IAR blocked roles %s",
                    self._arrangement_id,
                    section_name,
                    iar_blocked,
                )

            return rule_snapshot, target_fullness, iar_blocked, extra_pattern_events

        except Exception as exc:
            logger.warning(
                "FinalPlanResolver [arr=%d] section='%s': IAR application failed: %s "
                "— invalid_rule_fallback applied",
                self._arrangement_id,
                section_name,
                exc,
            )
            return _empty

    # ------------------------------------------------------------------
    # Boundary event merging / deduplication
    # ------------------------------------------------------------------

    def _merge_boundary_events(
        self,
        raw_sec: dict,
        section_name: str,
        bar_start: int,
        drop_boundaries: List[dict],
        section_type: str,
    ) -> List[ResolvedBoundaryEvent]:
        """Collect and deduplicate boundary events for *raw_sec*.

        Deduplication rule: when the same ``event_type`` appears from multiple
        sources, the Drop Engine version wins (it's the most intentional), then
        the section's own ``boundary_events``.  Duplicates are recorded as
        no-op annotations.
        """
        seen_types: Dict[str, ResolvedBoundaryEvent] = {}

        def _add(evt: ResolvedBoundaryEvent, source: str) -> None:
            if evt.event_type in seen_types:
                # Duplicate — record no-op
                self._noop_annotations.append({
                    "engine_name": source,
                    "section": section_name,
                    "planned_action": f"boundary_event:{evt.event_type}",
                    "reason_not_applied": (
                        f"duplicate of event_type '{evt.event_type}' already registered "
                        f"from engine '{seen_types[evt.event_type].source_engine}'"
                    ),
                })
                return
            seen_types[evt.event_type] = evt

        # Drop Engine events first (highest priority)
        for boundary in drop_boundaries:
            target_section = str(boundary.get("to_section") or "")
            if not _section_type_matches(target_section, section_type, section_name):
                continue
            for evt_dict in _all_drop_events(boundary):
                drop_type = str(evt_dict.get("event_type") or "")
                boundary_type = _DROP_TO_BOUNDARY_TYPE.get(drop_type, drop_type)
                _add(
                    ResolvedBoundaryEvent(
                        event_type=boundary_type,
                        source_engine="drop",
                        placement=str(evt_dict.get("placement") or "boundary"),
                        intensity=float(evt_dict.get("intensity") or 0.7),
                        bar=bar_start,
                        params=dict(evt_dict.get("parameters") or {}),
                    ),
                    source="drop",
                )

        # Section-level boundary_events second
        for evt_dict in raw_sec.get("boundary_events") or []:
            event_type = str(evt_dict.get("type") or evt_dict.get("event_type") or "")
            if not event_type:
                continue
            _add(
                ResolvedBoundaryEvent(
                    event_type=event_type,
                    source_engine="section",
                    placement=str(evt_dict.get("placement") or "boundary"),
                    intensity=float(evt_dict.get("intensity") or 0.7),
                    bar=int(evt_dict.get("bar") or bar_start),
                    params=dict(evt_dict.get("params") or {}),
                ),
                source="section",
            )

        return list(seen_types.values())

    # ------------------------------------------------------------------
    # Pattern events
    # ------------------------------------------------------------------

    def _extract_pattern_events(self, raw_sec: dict) -> List[dict]:
        """Extract pattern-variation events from section timeline_events."""
        pattern_actions = {
            "drop_kick", "add_syncopated_kick", "snare_fill", "hat_density_up",
            "hat_density_down", "perc_fill", "half_time_switch", "pre_drop_silence",
            "delayed_melody_entry", "melody_dropout", "call_response",
            "counter_melody_add", "bass_dropout", "808_reentry", "octave_lift",
            "syncopated_bass_push",
        }
        events: List[dict] = []
        for evt in raw_sec.get("timeline_events") or []:
            action = str(evt.get("action") or evt.get("type") or "").strip().lower()
            if action in pattern_actions:
                events.append(dict(evt))
        return events

    # ------------------------------------------------------------------
    # Section decision lookup
    # ------------------------------------------------------------------

    def _find_section_decision(
        self,
        section_name: str,
        section_index: int,
        section_decisions: List[dict],
    ) -> Optional[dict]:
        """Return the Decision Engine SectionDecision dict for *section_name*."""
        name_lower = section_name.strip().lower()
        # Try exact match first
        for d in section_decisions:
            if str(d.get("section_name") or "").strip().lower() == name_lower:
                return d
        # Try type prefix match (e.g. "hook_1" → "hook", "verse_2" → "verse")
        section_type_prefix = name_lower.split("_")[0] if "_" in name_lower else name_lower
        for d in section_decisions:
            decision_name = str(d.get("section_name") or "").strip().lower()
            if decision_name.startswith(section_type_prefix):
                return d
        return None

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback_resolved_plan(self) -> ResolvedRenderPlan:
        """Return a minimal resolved plan when building fails."""
        sections_raw = list(self._plan.get("sections") or [])
        resolved_sections = []
        for idx, raw_sec in enumerate(sections_raw):
            section_name = str(raw_sec.get("name") or f"Section {idx + 1}")
            resolved_sections.append(
                ResolvedSection(
                    section_name=section_name,
                    section_type=str(raw_sec.get("type") or "verse"),
                    bar_start=int(raw_sec.get("bar_start") or 0),
                    bars=int(raw_sec.get("bars") or 8),
                    energy=float(raw_sec.get("energy") or 0.6),
                    final_active_roles=list(
                        raw_sec.get("instruments") or raw_sec.get("active_stem_roles") or []
                    ),
                )
            )
        return ResolvedRenderPlan(
            resolved_sections=resolved_sections,
            bpm=float(self._plan.get("bpm") or 120.0),
            key=str(self._plan.get("key") or "C"),
            total_bars=int(
                self._plan.get("total_bars")
                or sum(int(s.get("bars") or 0) for s in sections_raw)
            ),
            source_quality=self._source_quality,
            available_roles=list(self._available_roles),
            resolver_version=_RESOLVER_VERSION,
            noop_annotations=[],
        )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _ordered_unique(items: List[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for item in items:
        if item and item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _section_type_matches(
    drop_target: str, section_type: str, section_name: str
) -> bool:
    """Return True when the drop boundary targets *section_type* / *section_name*."""
    if not drop_target:
        return False
    drop_lower = drop_target.strip().lower()
    sec_lower = section_type.strip().lower()
    name_lower = section_name.strip().lower()
    # Exact type match
    if drop_lower == sec_lower:
        return True
    # Partial name match (e.g., "hook_1" matches "hook")
    if sec_lower.startswith(drop_lower) or name_lower.startswith(drop_lower):
        return True
    # Alias maps
    aliases = {"chorus": "hook", "drop": "hook", "pre-hook": "pre_hook",
               "buildup": "pre_hook", "break": "breakdown"}
    if aliases.get(drop_lower, drop_lower) == sec_lower:
        return True
    return False


def _all_drop_events(boundary: dict) -> List[dict]:
    """Return all events (primary + support) from a DropBoundaryPlan dict."""
    events: List[dict] = []
    primary = boundary.get("primary_drop_event")
    if primary:
        events.append(primary)
    events.extend(boundary.get("support_events") or [])
    return events
