"""Shared render executor for all render-plan-driven audio rendering paths."""

import json
import logging
from pathlib import Path
from typing import Any

from pydub import AudioSegment
from app.services.mastering import apply_mastering

logger = logging.getLogger(__name__)

_RENDER_MOVE_EVENT_TYPES = {
    "variation",
    "beat_switch",
    "halftime_drop",
    "stop_time",
    "drum_fill",
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
}


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
            "variations": [],
        }
        normalized_sections.append(normalized)

    for event in events:
        event_type = str(event.get("type", "")).strip().lower()
        if event_type not in _RENDER_MOVE_EVENT_TYPES:
            continue
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
        Dict with timeline_json, summary, and postprocess info
    """
    if isinstance(render_plan_json, str):
        try:
            render_plan = json.loads(render_plan_json)
        except Exception as e:
            raise ValueError(f"Invalid render_plan_json: {e}") from e
    else:
        render_plan = render_plan_json

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

    mastering_result = apply_mastering(
        output_audio,
        genre=producer_payload.get("genre") or render_plan.get("render_profile", {}).get("genre_profile"),
    )
    output_audio = mastering_result.audio

    output_path = Path(output_path)
    output_audio.export(str(output_path), format="wav")

    return {
        "timeline_json": timeline_json,
        "summary": summary,
        "postprocess": {
            "mastering": {
                "applied": mastering_result.applied,
                "profile": mastering_result.profile,
                "peak_dbfs_before": mastering_result.peak_dbfs_before,
                "peak_dbfs_after": mastering_result.peak_dbfs_after,
            }
        },
    }
