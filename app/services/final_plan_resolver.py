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
        generative_producer_primary: bool = False,
    ) -> None:
        self._plan = render_plan
        self._available_roles: List[str] = list(available_roles or [])
        self._source_quality = source_quality
        self._arrangement_id = arrangement_id
        self._noop_annotations: List[dict] = []
        self._genre = str(genre or "generic").lower().strip()
        self._vibe = str(vibe or "").lower().strip()
        self._variation_seed = variation_seed
        self._generative_producer_primary = generative_producer_primary

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

        # Generative Producer Primary pass — merges GP events into resolved sections.
        gp_primary_used = False
        gp_fallback_used = False
        gp_fallback_reason = ""
        gp_applied = 0
        gp_skipped = 0

        if self._generative_producer_primary:
            gp_applied, gp_skipped, gp_fallback_used, gp_fallback_reason = (
                self._apply_generative_producer_primary(resolved_sections)
            )
            gp_primary_used = not gp_fallback_used

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
            generative_producer_primary_used=gp_primary_used,
            generative_producer_primary_fallback_used=gp_fallback_used,
            generative_producer_primary_fallback_reason=gp_fallback_reason,
            generative_producer_events_applied=gp_applied,
            generative_producer_events_skipped=gp_skipped,
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

    def _init_rules_engine(self) -> Optional[Any]:
        """Load the IAR engine; return ``None`` on any failure (fallback mode)."""
        try:
            from app.services.instrument_activation_rules import (  # noqa: PLC0415
                InstrumentActivationRules,
                _normalise_section,
            )
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
            from app.services.instrument_activation_rules import _normalise_section  # noqa: PLC0415

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
            canonical = _normalise_section(section_type)
            if canonical == "PRE_HOOK":
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
    # Generative Producer Primary pass
    # ------------------------------------------------------------------

    # Render actions that map to boundary events (ResolvedBoundaryEvent).
    _GP_BOUNDARY_ACTIONS: frozenset = frozenset({
        "add_fx_riser",
        "add_impact",
        "fade_role",
        "reverb_tail",
        "reverse_slice",
    })

    # Render actions that map to pattern events (List[dict]).
    _GP_PATTERN_ACTIONS: frozenset = frozenset({
        "filter_role",
        "chop_role",
        "add_hat_roll",
        "add_drum_fill",
        "bass_pattern_variation",
        "delay_role",
    })

    # Render actions that map to groove events (List[dict]).
    _GP_GROOVE_ACTIONS: frozenset = frozenset({
        "widen_role",
    })

    # render_action → boundary event_type mapping.
    _GP_ACTION_TO_BOUNDARY_TYPE: Dict[str, str] = {
        "add_fx_riser": "riser_fx",
        "add_impact": "crash_hit",
        "fade_role": "outro_strip",
        "reverb_tail": "reverse_fx",
        "reverse_slice": "reverse_fx",
    }

    def _apply_generative_producer_primary(
        self,
        resolved_sections: List[ResolvedSection],
    ) -> "tuple[int, int, bool, str]":
        """Merge Generative Producer events into *resolved_sections* in-place.

        Reads ``_generative_producer_events`` from the raw render plan and
        applies each event to the matching resolved section according to the
        render_action → resolved-field mapping.

        Rules enforced:
        1. Only events whose render_action is in ``SUPPORTED_RENDER_ACTIONS``
           (defined in generative_producer_system.types) are processed; others
           are skipped with a reason.
        2. Decision Engine ``blocked_roles`` are respected — ``unmute_role``
           cannot override a role that the Decision Engine has blocked.
        3. Instrument Activation Rules: events targeting roles absent from
           ``available_roles`` are skipped.
        4. Deduplication: events whose output would duplicate an event already
           present from another engine are skipped (no double-application).
        5. Malformed events (missing required fields) are skipped without raising.

        Returns
        -------
        tuple (applied_count, skipped_count, fallback_used, fallback_reason)
        """
        gp_events: List[dict] = list(self._plan.get("_generative_producer_events") or [])

        if not gp_events:
            if resolved_sections:
                logger.debug(
                    "FinalPlanResolver [arr=%d] GP primary: no events in "
                    "_generative_producer_events — fallback (no changes)",
                    self._arrangement_id,
                )
                return 0, 0, True, "no generative producer events available"
            return 0, 0, False, ""

        # Build a name→section index for fast lookup.
        section_by_name: Dict[str, int] = {
            sec.section_name.strip().lower(): idx
            for idx, sec in enumerate(resolved_sections)
        }

        # Supported render actions (import lazily to keep circular-import safe).
        try:
            from app.services.generative_producer_system.types import (  # noqa: PLC0415
                SUPPORTED_RENDER_ACTIONS as _GPS_SUPPORTED,
            )
        except Exception:
            _GPS_SUPPORTED = frozenset()  # type: ignore[assignment]

        applied = 0
        skipped = 0

        for raw_evt in gp_events:
            try:
                skip_reason = self._apply_single_gp_event(
                    raw_evt=raw_evt,
                    resolved_sections=resolved_sections,
                    section_by_name=section_by_name,
                    supported_render_actions=_GPS_SUPPORTED,
                )
            except Exception as exc:
                skip_reason = f"malformed event: {exc}"
                logger.debug(
                    "FinalPlanResolver [arr=%d] GP primary: skipping malformed event %r — %s",
                    self._arrangement_id,
                    raw_evt,
                    exc,
                )
            if skip_reason:
                skipped += 1
                self._noop_annotations.append({
                    "engine_name": "generative_producer_primary",
                    "section": str(raw_evt.get("section_name") or ""),
                    "planned_action": str(raw_evt.get("render_action") or raw_evt.get("event_type") or ""),
                    "reason_not_applied": skip_reason,
                })
            else:
                applied += 1

        logger.info(
            "FinalPlanResolver [arr=%d] GP primary: applied=%d skipped=%d",
            self._arrangement_id,
            applied,
            skipped,
        )
        return applied, skipped, False, ""

    def _apply_single_gp_event(
        self,
        raw_evt: dict,
        resolved_sections: List[ResolvedSection],
        section_by_name: Dict[str, int],
        supported_render_actions: frozenset,
    ) -> str:
        """Apply one GP event to the matching section.

        Returns an empty string on success, or a non-empty skip reason string.
        Modifies *resolved_sections* in-place on success.
        """
        # --- Validate required fields ---
        render_action = str(raw_evt.get("render_action") or "").strip()
        event_type = str(raw_evt.get("event_type") or "").strip()
        target_role = str(raw_evt.get("target_role") or "").strip()
        section_name = str(raw_evt.get("section_name") or "").strip()
        bar_start = raw_evt.get("bar_start")
        bar_end = raw_evt.get("bar_end")
        intensity = float(raw_evt.get("intensity") or 0.7)
        parameters: dict = dict(raw_evt.get("parameters") or {})
        event_id = str(raw_evt.get("event_id") or "")

        if not render_action:
            return "missing render_action"
        if not target_role:
            return "missing target_role"
        if not section_name:
            return "missing section_name"

        # --- Check render_action is supported ---
        if supported_render_actions and render_action not in supported_render_actions:
            return f"unsupported render_action={render_action!r}"

        # --- Find matching section ---
        idx = section_by_name.get(section_name.lower())
        if idx is None:
            # Try prefix match (e.g. "hook 1" → "hook")
            name_lower = section_name.lower()
            for sec_name_key, sec_idx in section_by_name.items():
                if sec_name_key.startswith(name_lower) or name_lower.startswith(sec_name_key):
                    idx = sec_idx
                    break
        if idx is None:
            return f"section {section_name!r} not found in resolved plan"

        section = resolved_sections[idx]

        # --- Rule 2: Instrument Activation Rules — skip if role absent ---
        if self._available_roles and target_role not in self._available_roles:
            return (
                f"target_role={target_role!r} not in available_roles — "
                "Instrument Activation Rules"
            )

        # --- Dispatch by render_action ---
        if render_action == "mute_role":
            return self._gp_apply_mute_role(section, target_role)
        elif render_action == "unmute_role":
            return self._gp_apply_unmute_role(section, target_role)
        elif render_action in self._GP_PATTERN_ACTIONS:
            return self._gp_apply_pattern_event(
                section, render_action, target_role, event_type,
                bar_start, bar_end, intensity, parameters, event_id,
            )
        elif render_action in self._GP_BOUNDARY_ACTIONS:
            return self._gp_apply_boundary_event(
                section, render_action, target_role, event_type,
                bar_start, intensity, parameters,
            )
        elif render_action in self._GP_GROOVE_ACTIONS:
            return self._gp_apply_groove_event(
                section, render_action, target_role, event_type,
                bar_start, bar_end, intensity, parameters, event_id,
            )
        else:
            return f"render_action={render_action!r} has no resolver mapping"

    # --- GP sub-action appliers ---

    def _gp_apply_mute_role(self, section: ResolvedSection, target_role: str) -> str:
        """Block *target_role* in *section*. Returns skip reason or ''."""
        # Already blocked by Decision Engine or a prior GP event — no-op.
        if target_role in section.final_blocked_roles:
            return (
                f"target_role={target_role!r} already in final_blocked_roles "
                "(Decision Engine or prior GP mute)"
            )
        # Not in active roles — nothing to mute.
        if target_role not in section.final_active_roles:
            return (
                f"target_role={target_role!r} not in final_active_roles — nothing to mute"
            )
        # Apply: remove from active, add to blocked.
        section.final_active_roles = [r for r in section.final_active_roles if r != target_role]
        if target_role not in section.final_blocked_roles:
            section.final_blocked_roles = list(section.final_blocked_roles) + [target_role]
        return ""

    def _gp_apply_unmute_role(self, section: ResolvedSection, target_role: str) -> str:
        """Add *target_role* back to *section*. Returns skip reason or ''."""
        # Decision Engine has blocked this role — GP must not override.
        if target_role in section.final_blocked_roles:
            return (
                f"target_role={target_role!r} is blocked by Decision Engine — "
                "GP unmute_role cannot override"
            )
        # Already active — deduplication.
        if target_role in section.final_active_roles:
            return (
                f"target_role={target_role!r} already in final_active_roles — dedup"
            )
        # Apply: add to active_roles and reentries.
        section.final_active_roles = list(section.final_active_roles) + [target_role]
        if target_role not in section.final_reentries:
            section.final_reentries = list(section.final_reentries) + [target_role]
        return ""

    def _gp_apply_pattern_event(
        self,
        section: ResolvedSection,
        render_action: str,
        target_role: str,
        event_type: str,
        bar_start: Any,
        bar_end: Any,
        intensity: float,
        parameters: dict,
        event_id: str,
    ) -> str:
        """Append a pattern event to *section.final_pattern_events*."""
        action_key = render_action
        # Deduplication: skip if same action+role already present.
        for existing in section.final_pattern_events:
            if (
                str(existing.get("action") or existing.get("type") or "") == action_key
                and str(existing.get("role") or existing.get("target_role") or "") == target_role
            ):
                return (
                    f"pattern event action={action_key!r} role={target_role!r} "
                    "already in final_pattern_events — dedup"
                )
        evt: Dict[str, Any] = {
            "action": action_key,
            "source": "generative_producer_primary",
            "target_role": target_role,
            "event_type": event_type,
            "intensity": round(intensity, 4),
            "parameters": parameters,
        }
        if bar_start is not None:
            evt["bar_start"] = int(bar_start)
        if bar_end is not None:
            evt["bar_end"] = int(bar_end)
        if event_id:
            evt["event_id"] = event_id
        section.final_pattern_events = list(section.final_pattern_events) + [evt]
        return ""

    def _gp_apply_boundary_event(
        self,
        section: ResolvedSection,
        render_action: str,
        target_role: str,
        event_type: str,
        bar_start: Any,
        intensity: float,
        parameters: dict,
    ) -> str:
        """Add a boundary event to *section.final_boundary_events*."""
        boundary_type = self._GP_ACTION_TO_BOUNDARY_TYPE.get(render_action, render_action)
        # Deduplication: skip if same event_type already present.
        existing_types = {evt.event_type for evt in section.final_boundary_events}
        if boundary_type in existing_types:
            return (
                f"boundary event_type={boundary_type!r} already in "
                "final_boundary_events — dedup"
            )
        new_evt = ResolvedBoundaryEvent(
            event_type=boundary_type,
            source_engine="generative_producer_primary",
            placement="boundary",
            intensity=round(intensity, 4),
            bar=int(bar_start) if bar_start is not None else section.bar_start,
            params=dict(parameters),
        )
        section.final_boundary_events = list(section.final_boundary_events) + [new_evt]
        return ""

    def _gp_apply_groove_event(
        self,
        section: ResolvedSection,
        render_action: str,
        target_role: str,
        event_type: str,
        bar_start: Any,
        bar_end: Any,
        intensity: float,
        parameters: dict,
        event_id: str,
    ) -> str:
        """Append a groove event to *section.final_groove_events*."""
        action_key = render_action
        for existing in section.final_groove_events:
            if (
                str(existing.get("action") or existing.get("type") or "") == action_key
                and str(existing.get("role") or existing.get("target_role") or "") == target_role
            ):
                return (
                    f"groove event action={action_key!r} role={target_role!r} "
                    "already in final_groove_events — dedup"
                )
        evt: Dict[str, Any] = {
            "action": action_key,
            "source": "generative_producer_primary",
            "target_role": target_role,
            "event_type": event_type,
            "intensity": round(intensity, 4),
            "parameters": parameters,
        }
        if bar_start is not None:
            evt["bar_start"] = int(bar_start)
        if bar_end is not None:
            evt["bar_end"] = int(bar_end)
        if event_id:
            evt["event_id"] = event_id
        section.final_groove_events = list(section.final_groove_events) + [evt]
        return ""

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
