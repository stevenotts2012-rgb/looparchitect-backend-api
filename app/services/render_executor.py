"""Shared render executor for all render-plan-driven audio rendering paths."""

import json
import logging
from pathlib import Path
from typing import Any

from pydub import AudioSegment
from app.services.mastering import apply_mastering

logger = logging.getLogger(__name__)


def _apply_master_headroom(audio: AudioSegment, target_peak_dbfs: float = -6.0) -> AudioSegment:
    peak = float(audio.max_dBFS)
    if peak == float("-inf") or peak <= target_peak_dbfs:
        return audio
    return audio - (peak - target_peak_dbfs)

_RENDER_MOVE_EVENT_TYPES = {
    "variation",
    "beat_switch",
    "halftime_drop",
    "stop_time",
    "drum_fill",
    "snare_roll",
    "pre_hook_silence",
    "riser_fx",
    "crash_hit",
    "reverse_cymbal",
    "drop_kick",
    "bass_pause",
    "fill",
    "enable_stem",
    "disable_stem",
    "stem_gain_change",
    "stem_filter",
    "silence_drop",
    "pre_hook_mute",
    "fill_event",
    "texture_lift",
    "hook_expansion",
    "bridge_strip",
    "outro_strip",
    "pre_hook_drum_mute",
    "silence_drop_before_hook",
    "hat_density_variation",
    "end_section_fill",
    "verse_melody_reduction",
    "bridge_bass_removal",
    "final_hook_expansion",
    "outro_strip_down",
    "call_response_variation",
    "pre_hook_silence_drop",
    "snare_pickup",
    "reverse_fx",
    "silence_gap",
    "subtractive_entry",
    "re_entry_accent",
    # Producer SUPPORTED_RENDER_ACTIONS — these are emitted by the
    # GenerativeProducerOrchestrator and must be preserved here so that
    # _build_producer_arrangement_from_render_plan does not silently discard them.
    "mute_role",
    "unmute_role",
    "filter_role",
    "chop_role",
    "reverse_slice",
    "add_hat_roll",
    "add_drum_fill",
    "bass_pattern_variation",
    "add_fx_riser",
    "add_impact",
    "fade_role",
    "widen_role",
    "delay_role",
    "reverb_tail",
}

# Subset of _RENDER_MOVE_EVENT_TYPES that represent section-boundary transitions
# (as opposed to within-section variations like stem_gain_change or enable_stem).
# Events in this set are promoted to boundary_events so that observability
# tracking in _build_render_spec_summary can correctly measure plan-vs-actual
# transition match.  This must stay in sync with SUPPORTED_BOUNDARY_EVENTS in
# transition_engine.py.
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


def extract_producer_moves(events: list[dict]) -> list[str]:
    """Extract producer move hints from render plan events."""
    moves: list[str] = []
    for event in events:
        event_type = str(event.get("type", "")).strip().lower()
        description = str(event.get("description", "")).strip().lower()

        if event_type in _RENDER_MOVE_EVENT_TYPES:
            moves.append(event_type)

        for token in ("beat switch", "halftime", "stop time", "drum fill", "drop", "roll"):
            if token in description:
                moves.append(token.replace(" ", "_"))

    seen = set()
    ordered: list[str] = []
    for move in moves:
        if move not in seen:
            seen.add(move)
            ordered.append(move)
    return ordered


def section_layer_counts(sections: list[dict]) -> dict[str, int]:
    """Return section-name to active layer counts from render plan sections."""
    counts: dict[str, int] = {}
    for section in sections:
        name = str(section.get("name") or section.get("type") or "section").lower()
        instruments = section.get("instruments") or []
        if isinstance(instruments, list):
            counts[name] = len(instruments)
    return counts


def _build_producer_arrangement_from_render_plan(render_plan: dict, fallback_bpm: float) -> tuple[dict, dict]:
    """Convert render_plan_json into producer-arrangement-like payload for rendering."""
    sections = render_plan.get("sections") or []
    events = render_plan.get("events") or []
    render_profile = render_plan.get("render_profile") or {}

    if not sections:
        raise ValueError("render_plan_json has no sections")

    normalized_sections: list[dict] = []
    for raw_section in sections:
        bar_start = int(raw_section.get("bar_start", raw_section.get("start_bar", 0)) or 0)
        bars = int(raw_section.get("bars", 1) or 1)
        normalized = {
            "name": raw_section.get("name") or raw_section.get("type") or "Section",
            "type": raw_section.get("type") or raw_section.get("section_type") or "verse",
            "bar_start": bar_start,
            "bars": bars,
            "energy": float(raw_section.get("energy", 0.6) or 0.6),
            "instruments": raw_section.get("instruments") or [],
            "loop_variant": raw_section.get("loop_variant"),
            "loop_variant_file": raw_section.get("loop_variant_file"),
            # Seed from section-level variations so bridge_strip, outro_strip_down, etc.
            # survive the JSON round-trip.  Event-based variations are appended below.
            "variations": list(raw_section.get("variations") or []),
            "boundary_events": list(raw_section.get("boundary_events") or []),
            # Preserve phrase variation plan so intra-section phrase splits are rendered.
            "phrase_plan": raw_section.get("phrase_plan"),
            # Preserve hook evolution stage so hook1/hook2/hook3 processing is distinct.
            "hook_evolution": raw_section.get("hook_evolution"),
            # Preserve active_stem_roles for diagnostics / debug_render_report.
            "active_stem_roles": raw_section.get("active_stem_roles") or raw_section.get("instruments") or [],
            # Preserve timeline events injected by the Timeline Engine primary pass so
            # downstream planners (pattern variation, groove engine) can reference them
            # without running a separate planner pass.
            "timeline_events": list(raw_section.get("timeline_events") or []),
        }
        normalized_sections.append(normalized)

    logger.info(
        "PRODUCER_PLAN_EVENTS_COUNT total=%d recognized=%d",
        len(events),
        sum(1 for e in events if str(e.get("type", "")).strip().lower() in _RENDER_MOVE_EVENT_TYPES),
    )
    converted_count = 0
    for event in events:
        event_type = str(event.get("type", "")).strip().lower()
        if event_type not in _RENDER_MOVE_EVENT_TYPES:
            continue
        converted_count += 1
        event_bar = int(event.get("bar", 0) or 0)
        target = None
        for section in sorted(normalized_sections, key=lambda s: int(s["bar_start"])):
            start = int(section["bar_start"])
            end = start + int(section["bars"])
            if start <= event_bar < end:
                target = section
                break
        if target is None and normalized_sections:
            target = normalized_sections[-1]
        if target is not None:
            # Boundary transition event types must ONLY go into boundary_events, never
            # into variations.  Adding a boundary-type event to both paths causes the
            # same DSP to run twice on the same audio window (double-application),
            # producing compound silence or stacked gain that sounds like broken audio.
            existing_boundary_types = {
                str(e.get("type") or "") for e in target.get("boundary_events", [])
            }
            if event_type in _BOUNDARY_TRANSITION_EVENT_TYPES:
                # Register only in boundary_events (single application path).
                if event_type not in existing_boundary_types:
                    target.setdefault("boundary_events", []).append(
                        {
                            "type": event_type,
                            "bar": event_bar,
                            "placement": event.get("placement"),
                            "boundary": event.get("boundary"),
                            "intensity": float(event.get("intensity", 0.7) or 0.7),
                            "params": event.get("params") if isinstance(event.get("params"), dict) else {},
                        }
                    )
            else:
                # Non-boundary event types (stem enables, gain changes, etc.) go into
                # variations as before.
                target["variations"].append(
                    {
                        "bar": event_bar,
                        "variation_type": event_type,
                        "intensity": float(event.get("intensity", 0.7) or 0.7),
                        "duration_bars": event.get("duration_bars"),
                        "description": event.get("description", ""),
                        "params": event.get("params") if isinstance(event.get("params"), dict) else {},
                    }
                )

    loop_variants_used = sorted(
        {
            str(section.get("loop_variant") or "").strip().lower()
            for section in normalized_sections
            if section.get("loop_variant")
        }
    )

    logger.info(
        "PRODUCER_EVENTS_CONVERTED count=%d out_of=%d",
        converted_count,
        len(events),
    )

    summary = {
        "sections_count": len(normalized_sections),
        "events_count": len(events),
        "producer_moves": extract_producer_moves(events),
        "layer_counts": section_layer_counts(normalized_sections),
        "loop_variants_used": loop_variants_used,
    }

    producer_arrangement = {
        "tempo": float(render_plan.get("bpm") or fallback_bpm),
        "key": render_plan.get("key", "C"),
        "total_bars": int(render_plan.get("total_bars") or sum(int(s["bars"]) for s in normalized_sections)),
        "sections": normalized_sections,
        "tracks": render_plan.get("tracks") or [],
        "transitions": render_plan.get("transitions") or [],
        "section_boundaries": render_plan.get("section_boundaries") or [],
        "energy_curve": render_plan.get("energy_curve") or [],
        "genre": render_profile.get("genre_profile", "generic"),
        "render_profile": render_profile,
        "stem_separation": render_profile.get("stem_separation") or {},
        "loop_variations": render_plan.get("loop_variations") or render_profile.get("loop_variations") or {},
    }

    return producer_arrangement, summary


def render_from_plan(
    render_plan_json: str | dict[str, Any],
    audio_source: AudioSegment,
    output_path: str | Path,
    stems: dict[str, AudioSegment] | None = None,
    loop_variations: dict[str, AudioSegment] | None = None,
) -> dict[str, Any]:
    """Render audio from render_plan_json and export output to output_path.
    
    Args:
        render_plan_json: Render plan JSON string or dict  
        audio_source: Full stereo loop audio (fallback when stems unavailable)
        output_path: Path to write output WAV file
        stems: Optional dict of stem audio files for real layer-based rendering
    
    Returns:
        Dict with timeline_json, summary, postprocess, and render_observability.
        render_observability contains Phase 3 fields:
          render_path_used, source_quality_mode_used, fallback_triggered_count,
          fallback_reasons, section_execution_report, render_signatures,
          unique_render_signature_count, phrase_split_count, mastering_applied,
          mastering_profile, planned_stem_map_by_section, actual_stem_map_by_section.
    """
    if isinstance(render_plan_json, str):
        try:
            render_plan = json.loads(render_plan_json)
        except Exception as e:
            raise ValueError(f"Invalid render_plan_json: {e}") from e
    else:
        render_plan = render_plan_json

    # Determine render path before execution so it's always set even on failure.
    render_path_used = "stem_render_executor" if stems else "stereo_fallback"

    # Derive source quality mode from render plan metadata.
    render_profile = render_plan.get("render_profile") or {}
    stem_sep = render_profile.get("stem_separation") or {}
    source_quality_mode_used = _derive_source_quality_mode(render_plan, stems, stem_sep)

    # Resolved render plan merge — applies authoritative resolved fields from
    # FinalPlanResolver back into the raw section dicts so that
    # _build_producer_arrangement_from_render_plan uses canonical roles and events.
    #
    # Two modes:
    #   RESOLVED_PLAN_PRIMARY=false (default): lightweight merge, roles only.
    #   RESOLVED_PLAN_PRIMARY=true:  full primary cutover — all resolved fields
    #     take precedence with per-field fallback to legacy when absent.
    resolved_dict = render_plan.get("_resolved_render_plan")
    _resolved_plan_primary_used = False
    _resolved_plan_primary_fallback_used = False
    _render_mismatch_count = 0

    if resolved_dict:
        from app.config import settings as _settings
        if _settings.feature_resolved_plan_primary:
            # Full primary cutover path
            _primary_used, _fallback_used, _mismatch_count = _apply_resolved_plan_primary(
                render_plan=render_plan,
                resolved_dict=resolved_dict,
            )
            _resolved_plan_primary_used = _primary_used
            _resolved_plan_primary_fallback_used = _fallback_used
            _render_mismatch_count = _mismatch_count
        else:
            # Legacy lightweight merge: only overwrite instruments/active_stem_roles.
            try:
                resolved_sections = resolved_dict.get("resolved_sections") or []
                raw_sections = render_plan.get("sections") or []
                if len(resolved_sections) == len(raw_sections):
                    for raw_sec, res_sec in zip(raw_sections, resolved_sections):
                        final_roles = res_sec.get("final_active_roles")
                        if final_roles is not None:
                            raw_sec["instruments"] = list(final_roles)
                            raw_sec["active_stem_roles"] = list(final_roles)
                    logger.info(
                        "render_executor: applied resolved_render_plan role map "
                        "(%d sections)", len(raw_sections)
                    )
                else:
                    logger.warning(
                        "render_executor: resolved_sections length %d != raw_sections %d "
                        "— skipping resolved plan role injection",
                        len(resolved_sections),
                        len(raw_sections),
                    )
            except Exception as _merge_exc:
                logger.warning(
                    "render_executor: resolved plan merge failed (non-blocking): %s",
                    _merge_exc,
                )

    producer_payload, summary = _build_producer_arrangement_from_render_plan(
        render_plan=render_plan,
        fallback_bpm=float(render_plan.get("bpm") or 120.0),
    )

    logger.info(
        "render_plan loaded: section_count=%s event_count=%s producer_moves=%s stems=%s loop_variants=%s",
        summary["sections_count"],
        summary["events_count"],
        summary["producer_moves"],
        "ENABLED" if stems else "DISABLED",
        summary.get("loop_variants_used") or [],
    )

    from app.services.arrangement_jobs import _render_producer_arrangement

    output_audio, timeline_json = _render_producer_arrangement(
        loop_audio=audio_source,
        producer_arrangement=producer_payload,
        bpm=float(producer_payload.get("tempo", 120.0)),
        stems=stems,
        loop_variations=loop_variations,
    )
    output_audio = _apply_master_headroom(output_audio, target_peak_dbfs=-1.0)

    mastering_result = apply_mastering(
        output_audio,
        genre=producer_payload.get("genre") or render_plan.get("render_profile", {}).get("genre_profile"),
    )
    output_audio = mastering_result.audio

    output_path = Path(output_path)
    output_audio.export(str(output_path), format="wav")

    # Build Phase 3 observability from timeline and mastering results.
    render_observability = _build_render_observability(
        timeline_json=timeline_json,
        render_path_used=render_path_used,
        source_quality_mode_used=source_quality_mode_used,
        mastering_result=mastering_result,
        render_plan_sections=render_plan.get("sections") or [],
    )

    logger.info(
        "RENDER_OBSERVABILITY render_path=%s source_quality=%s fallbacks=%d "
        "unique_signatures=%d phrase_splits=%d mastering_applied=%s "
        "resolved_plan_primary=%s fallback_used=%s mismatches=%d",
        render_observability.get("render_path_used"),
        render_observability.get("source_quality_mode_used"),
        render_observability.get("fallback_triggered_count", 0),
        render_observability.get("unique_render_signature_count", 0),
        render_observability.get("phrase_split_count", 0),
        render_observability.get("mastering_applied"),
        _resolved_plan_primary_used,
        _resolved_plan_primary_fallback_used,
        _render_mismatch_count,
    )

    return {
        "timeline_json": timeline_json,
        "summary": summary,
        "render_observability": render_observability,
        "resolved_plan_primary_used": _resolved_plan_primary_used,
        "resolved_plan_primary_fallback_used": _resolved_plan_primary_fallback_used,
        "render_mismatch_count": _render_mismatch_count,
        "postprocess": {
            "mastering": {
                "applied": mastering_result.applied,
                "profile": mastering_result.profile,
                "peak_dbfs_before": mastering_result.peak_dbfs_before,
                "peak_dbfs_after": mastering_result.peak_dbfs_after,
            }
        },
    }


def _apply_resolved_plan_primary(
    render_plan: dict,
    resolved_dict: dict,
) -> tuple[bool, bool, int]:
    """Apply the ResolvedRenderPlan as the primary source of truth for rendering.

    This implements the full RESOLVED_PLAN_PRIMARY cutover:

    * ``final_active_roles``    → ``section["instruments"]`` and
                                   ``section["active_stem_roles"]``
    * ``final_blocked_roles``   → removed from instruments (track muting)
    * ``final_reentries``       → added to instruments (role reintroduction)
    * ``final_boundary_events`` → replaces ``section["boundary_events"]``
    * ``final_pattern_events``  → injected into ``section["timeline_events"]``
    * ``final_groove_events``   → injected as ``section["_groove_events"]``
    * ``final_motif_treatment`` → injected as ``section["_motif_treatment"]``

    Per-field fallback: when a resolved field is absent (``None`` or not present)
    the legacy value already in the raw section is preserved unmodified.

    Structural fallback: if the resolved section count does not match the raw
    section count the function returns ``(False, True, 0)`` and leaves the render
    plan unchanged — the caller falls through to the legacy lightweight merge or
    stereo fallback.

    Mismatch detection (no-op detection): after applying ``final_blocked_roles``,
    any role that was supposed to be blocked but is still present in the active
    instrument list is recorded as a ``render_mismatch`` log event.

    Parameters
    ----------
    render_plan:
        The raw render plan dict (mutated in-place for each section).
    resolved_dict:
        The serialised :class:`ResolvedRenderPlan` dict stored under
        ``render_plan["_resolved_render_plan"]``.

    Returns
    -------
    tuple[bool, bool, int]
        ``(primary_used, fallback_used, mismatch_count)``
    """
    resolved_sections: list[dict] = resolved_dict.get("resolved_sections") or []
    raw_sections: list[dict] = render_plan.get("sections") or []

    # --- Structural validation ---
    if not resolved_sections or not raw_sections:
        logger.warning(
            "render_executor[primary]: resolved plan has no sections or raw plan "
            "has no sections — falling back to legacy merge"
        )
        return False, True, 0

    if len(resolved_sections) != len(raw_sections):
        logger.warning(
            "render_executor[primary]: resolved_sections count %d != raw_sections "
            "count %d — structural mismatch, falling back to legacy merge",
            len(resolved_sections),
            len(raw_sections),
        )
        return False, True, 0

    mismatch_count = 0
    any_fallback_field = False

    try:
        for raw_sec, res_sec in zip(raw_sections, resolved_sections):
            section_name = str(
                raw_sec.get("name") or raw_sec.get("type") or "unknown"
            )

            # ------------------------------------------------------------------
            # 1. Active roles — primary source of truth for what plays
            # ------------------------------------------------------------------
            final_active_roles: list[str] | None = res_sec.get("final_active_roles")
            if final_active_roles is not None:
                raw_sec["instruments"] = list(final_active_roles)
                raw_sec["active_stem_roles"] = list(final_active_roles)
            else:
                any_fallback_field = True
                logger.debug(
                    "render_executor[primary]: section='%s' final_active_roles absent "
                    "— keeping legacy instruments",
                    section_name,
                )

            # ------------------------------------------------------------------
            # 2. Blocked roles — mute / remove layers
            # ------------------------------------------------------------------
            final_blocked_roles: list[str] = res_sec.get("final_blocked_roles") or []
            if final_blocked_roles:
                current_instruments: list[str] = list(raw_sec.get("instruments") or [])
                new_instruments = [r for r in current_instruments if r not in final_blocked_roles]
                raw_sec["instruments"] = new_instruments
                raw_sec["active_stem_roles"] = new_instruments

                # Mismatch / no-op detection: a role is a no-op mismatch when
                # the resolver listed it in BOTH final_active_roles AND
                # final_blocked_roles — the plan is internally inconsistent.
                # blocked_roles takes precedence (role is removed), but the
                # conflict is surfaced as a render_mismatch event so operators
                # can diagnose resolver bugs.
                if final_active_roles is not None:
                    for role in final_blocked_roles:
                        if role in final_active_roles:
                            mismatch_count += 1
                            logger.warning(
                                "render_mismatch section='%s': blocked role '%s' was also "
                                "in final_active_roles — resolver plan is inconsistent; "
                                "blocked_roles takes precedence",
                                section_name,
                                role,
                            )

            # ------------------------------------------------------------------
            # 3. Reentry roles — roles reintroduced mid-section
            # ------------------------------------------------------------------
            final_reentries: list[str] = res_sec.get("final_reentries") or []
            if final_reentries:
                current_instruments = list(raw_sec.get("instruments") or [])
                for role in final_reentries:
                    if role not in current_instruments:
                        current_instruments.append(role)
                raw_sec["instruments"] = current_instruments
                raw_sec["active_stem_roles"] = current_instruments

            # ------------------------------------------------------------------
            # 4. Boundary events — drive drop / transition behaviour
            #    Replace section boundary_events with the deduplicated resolved
            #    list.  Each resolved event is converted back to the legacy dict
            #    shape that _render_producer_arrangement expects.
            # ------------------------------------------------------------------
            final_boundary_events: list[dict] | None = res_sec.get("final_boundary_events")
            if final_boundary_events is not None:
                raw_sec["boundary_events"] = [
                    {
                        "type": evt.get("event_type", ""),
                        "bar": evt.get("bar", raw_sec.get("bar_start", 0)),
                        "placement": evt.get("placement", "boundary"),
                        "intensity": evt.get("intensity", 0.7),
                        "params": dict(evt.get("params") or {}),
                        "_source_engine": evt.get("source_engine", "resolved"),
                    }
                    for evt in final_boundary_events
                    if evt.get("event_type")
                ]
            else:
                any_fallback_field = True
                logger.debug(
                    "render_executor[primary]: section='%s' final_boundary_events absent "
                    "— keeping legacy boundary_events",
                    section_name,
                )

            # ------------------------------------------------------------------
            # 5. Pattern events — intra-section variation events
            #    Injected into timeline_events so the existing DSP path picks
            #    them up without modification.
            # ------------------------------------------------------------------
            final_pattern_events: list[dict] | None = res_sec.get("final_pattern_events")
            if final_pattern_events is not None:
                existing_timeline: list[dict] = list(raw_sec.get("timeline_events") or [])
                # Only inject events that are not already present (by action/type key).
                existing_actions = {
                    str(e.get("action") or e.get("type") or "")
                    for e in existing_timeline
                }
                for evt in final_pattern_events:
                    action_key = str(evt.get("action") or evt.get("type") or "")
                    if action_key and action_key not in existing_actions:
                        existing_timeline.append(dict(evt))
                        existing_actions.add(action_key)
                raw_sec["timeline_events"] = existing_timeline
            else:
                any_fallback_field = True

            # ------------------------------------------------------------------
            # 6. Groove events — groove engine events applied in this section
            # ------------------------------------------------------------------
            final_groove_events: list[dict] | None = res_sec.get("final_groove_events")
            if final_groove_events is not None:
                raw_sec["_groove_events"] = list(final_groove_events)
            else:
                any_fallback_field = True

            # ------------------------------------------------------------------
            # 7. Motif treatment — motif engine treatment dict
            # ------------------------------------------------------------------
            final_motif_treatment: dict | None = res_sec.get("final_motif_treatment")
            if final_motif_treatment is not None:
                raw_sec["_motif_treatment"] = dict(final_motif_treatment)
            # When None: preserve legacy _motif_treatment if already present; no fallback flag
            # because None is an expected state when motif engine was not run.

        logger.info(
            "render_executor[primary]: resolved plan primary applied "
            "(%d sections, %d mismatches, fallback_fields=%s)",
            len(raw_sections),
            mismatch_count,
            any_fallback_field,
        )
        return True, any_fallback_field, mismatch_count

    except Exception as exc:
        logger.warning(
            "render_executor[primary]: resolved plan primary application failed "
            "(non-blocking): %s — falling back to legacy merge",
            exc,
            exc_info=True,
        )
        return False, True, 0


def _derive_source_quality_mode(
    render_plan: dict,
    stems: dict | None,
    stem_sep: dict,
) -> str:
    """Determine the source quality mode that was actually used during render."""
    if not stems:
        return "stereo_fallback"

    # Check for ZIP stem source
    loop_variations = render_plan.get("loop_variations") or {}
    if loop_variations.get("stems_used"):
        return "zip_stems"

    # Check stem separation metadata for AI-separated vs true stems
    sep_method = str(stem_sep.get("method") or stem_sep.get("backend") or "").strip().lower()
    if sep_method in {"demucs", "spleeter", "builtin", "ai_separated", "ai"}:
        return "ai_separated"

    # Stems present without separation metadata → uploaded as true stems
    stem_keys = list(stems.keys()) if stems else []
    if stem_keys and not sep_method:
        return "true_stems"

    return "unknown"


def _build_render_observability(
    timeline_json: str,
    render_path_used: str,
    source_quality_mode_used: str,
    mastering_result: Any,
    render_plan_sections: list,
) -> dict:
    """Build the Phase 3 observability payload from timeline and execution data.

    All values reflect REAL execution — planned stem maps come from the render
    plan, actual stem maps come from what ``_render_producer_arrangement``
    recorded in ``runtime_active_stems``.
    """
    import hashlib

    try:
        timeline = json.loads(timeline_json) if isinstance(timeline_json, str) else timeline_json or {}
    except Exception:
        timeline = {}

    timeline_sections: list = timeline.get("sections") or []
    render_spec = timeline.get("render_spec_summary") or {}

    # --- planned stem map (from render plan sections) ---
    planned_stem_map: list[dict] = []
    for idx, sec in enumerate(render_plan_sections):
        planned_stem_map.append({
            "section_index": idx,
            "section_type": str(sec.get("type") or sec.get("section_type") or "unknown"),
            "roles": list(sec.get("instruments") or sec.get("active_stem_roles") or []),
        })

    # --- actual stem map + section execution report from timeline ---
    actual_stem_map: list[dict] = []
    section_execution_report: list[dict] = []
    fallback_triggered_count = 0
    fallback_reasons: list[str] = []
    phrase_split_count = int(render_spec.get("phrase_split_count") or 0)
    render_signatures: list[str] = []
    phrase_signatures: list[tuple] = []

    for idx, ts in enumerate(timeline_sections):
        actual_roles = list(ts.get("runtime_active_stems") or ts.get("active_stem_roles") or [])
        planned_roles = list(ts.get("active_stem_roles") or [])
        phrase_used = bool(ts.get("phrase_plan_used"))

        # Fallback detection: section marked with _stem_fallback_all flag.
        # This flag is now propagated from the render loop into timeline_sections.
        sec_fallback = bool(ts.get("_stem_fallback_all"))
        fallback_used = sec_fallback
        fallback_reason = ts.get("_stem_fallback_reason") or ""
        if sec_fallback:
            fallback_triggered_count += 1
            effective_reason = fallback_reason or "missing_required_stem_role"
            if effective_reason not in fallback_reasons:
                fallback_reasons.append(effective_reason)

        # Detect stereo fallback path at section level
        if not actual_roles and render_path_used == "stereo_fallback":
            fallback_used = True
            if "full_mix_only_available" not in fallback_reasons:
                fallback_reasons.append("full_mix_only_available")

        # Dropped roles (planned but not actually rendered)
        dropped_roles = [r for r in planned_roles if r not in actual_roles]
        if dropped_roles and "missing_required_stem_role" not in fallback_reasons:
            fallback_reasons.append("missing_required_stem_role")

        # Deterministic render signature for this section
        sig_material = "|".join(sorted(actual_roles)) + f"|{ts.get('type', '')}|{render_path_used}"
        sig = hashlib.md5(sig_material.encode()).hexdigest()[:12]
        render_signatures.append(sig)

        # Phrase signature: unique tuple of (first_phrase_stems, second_phrase_stems).
        # Only collect when a phrase split was actually executed.
        if phrase_used:
            first_p = tuple(sorted(ts.get("runtime_first_phrase_stems") or []))
            second_p = tuple(sorted(ts.get("runtime_second_phrase_stems") or []))
            phrase_signatures.append((first_p, second_p))

        actual_stem_map.append({
            "section_index": idx,
            "section_type": str(ts.get("type") or "unknown"),
            "roles": actual_roles,
            "fallback": fallback_used,
        })

        section_execution_report.append({
            "section_index": idx,
            "section_type": str(ts.get("type") or "unknown"),
            "planned_roles": planned_roles,
            "actual_roles": actual_roles,
            "dropped_roles": dropped_roles,
            "fallback_used": fallback_used,
            "fallback_reason": fallback_reason or None,
            "phrase_split_used": phrase_used,
            "render_signature": sig,
            "applied_events": list(ts.get("applied_events") or []),
        })

    # If the whole render was stereo fallback, note that globally
    if render_path_used == "stereo_fallback" and "full_mix_only_available" not in fallback_reasons:
        fallback_reasons.append("full_mix_only_available")
        fallback_triggered_count = len(timeline_sections)

    unique_render_signature_count = len(set(render_signatures))
    # phrase_split_count from the timeline reflects actual distinct-stem phrase
    # executions (not just the presence of a phrase_plan dict).
    phrase_split_count_actual = sum(1 for ts in timeline_sections if ts.get("phrase_plan_used"))
    unique_phrase_signature_count = len(set(phrase_signatures))

    # Mastering fields (never faked — sourced directly from MasteringResult)
    mastering_applied = bool(getattr(mastering_result, "applied", False))
    mastering_profile = str(getattr(mastering_result, "profile", "unknown"))
    mastering_peak_before = getattr(mastering_result, "peak_dbfs_before", None)
    mastering_peak_after = getattr(mastering_result, "peak_dbfs_after", None)

    return {
        "render_path_used": render_path_used,
        "source_quality_mode_used": source_quality_mode_used,
        "fallback_triggered_count": fallback_triggered_count,
        "fallback_sections_count": fallback_triggered_count,
        "fallback_reasons": fallback_reasons,
        "planned_stem_map_by_section": planned_stem_map,
        "actual_stem_map_by_section": actual_stem_map,
        "section_execution_report": section_execution_report,
        "render_signatures": render_signatures,
        "unique_render_signature_count": unique_render_signature_count,
        "phrase_split_count": phrase_split_count_actual,
        "unique_phrase_signature_count": unique_phrase_signature_count,
        "mastering_applied": mastering_applied,
        "mastering_profile": mastering_profile,
        "mastering_peak_dbfs_before": mastering_peak_before,
        "mastering_peak_dbfs_after": mastering_peak_after,
        "distinct_stem_set_count": int(render_spec.get("distinct_stem_set_count") or unique_render_signature_count),
        "hook_stages_rendered": list(render_spec.get("hook_stages") or []),
        "transition_event_count": int(render_spec.get("transition_event_count") or 0),
    }
