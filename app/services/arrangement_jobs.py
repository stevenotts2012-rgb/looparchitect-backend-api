"""
Background job processing for arrangement generation.

Handles the async workflow of generating arrangements and updating database records.
"""

import io
import json
import logging
import math
import os
import tempfile
import time
import uuid
import subprocess
import shutil
from pathlib import Path

import httpx
import numpy as np
from pydub import AudioSegment

from app.db import SessionLocal
from app.config import settings
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.audit_logging import log_feature_event
from app.services.loop_variation_engine import (
    assign_section_variants,
    generate_loop_variations,
    validate_variation_plan_usage,
)
from app.services.producer_moves_engine import ProducerMovesEngine
from app.services.render_executor import render_from_plan
from app.services.storage import storage
from app.services.transition_engine import build_transition_plan

logger = logging.getLogger(__name__)

# Section index offset applied to the second phrase when building split-section audio.
# Ensures the second phrase starts the stem loop at a different position than the first,
# creating audible variation across the phrase boundary.
_PHRASE_SPLIT_SECTION_IDX_OFFSET = 100

_ISOLATED_STEM_ROLES = {
    "drums",
    "percussion",
    "bass",
    "melody",
    "harmony",
    "pads",
    "fx",
    "accent",
    "vocal",
    "vocals",
}

_SECTION_ROLE_PREFERENCES: dict[str, tuple[tuple[str, ...], ...]] = {
    "intro": (("melody", "vocals", "vocal"), ("pads", "harmony"), ("fx", "accent")),
    "verse": (("drums", "percussion"), ("bass",)),
    "pre_hook": (("percussion", "drums"), ("bass",), ("fx", "accent"), ("melody", "vocals", "vocal")),
    "hook": (("drums", "percussion"), ("bass",), ("melody", "vocals", "vocal"), ("pads", "harmony"), ("fx", "accent")),
    "bridge": (("pads", "harmony"), ("melody", "vocals", "vocal"), ("fx", "accent")),
    "breakdown": (("pads", "harmony"), ("fx", "accent"), ("melody", "vocals", "vocal")),
    "outro": (("melody", "vocals", "vocal"), ("pads", "harmony"), ("fx", "accent"), ("bass",)),
}

_SECTION_MIN_LAYERS = {
    "intro": 1,
    "verse": 2,
    "pre_hook": 2,
    "hook": 3,
    "bridge": 1,
    "breakdown": 1,
    "outro": 1,
}

_SECTION_MAX_LAYERS = {
    "intro": 3,
    "verse": 3,
    "pre_hook": 3,
    "hook": 5,
    "bridge": 2,
    "breakdown": 2,
    "outro": 2,
}

_SECTION_ROLE_EXCLUSIONS = {
    "intro": {"drums", "percussion", "bass"},
    "verse": set(),
    "pre_hook": {"drums"},
    "hook": set(),
    "bridge": {"drums", "percussion", "bass"},
    "breakdown": {"drums", "percussion", "bass"},
    "outro": set(),
}

_PREMIX_GAIN_DB = {
    "drums": -5.0,
    "percussion": -6.0,
    "bass": -6.0,
    "melody": -7.0,
    "vocals": -7.0,
    "vocal": -7.0,
    "harmony": -8.0,
    "pads": -8.5,
    "fx": -10.0,
    "accent": -9.0,
    "full_mix": -9.0,
}


def _ordered_unique_roles(roles: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for role in roles:
        normalized = str(role or "").strip().lower()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _pick_available_role(available_roles: list[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in available_roles:
            return candidate
    return None


def _normalize_section_type(section_type: str) -> str:
    value = str(section_type or "verse").strip().lower()
    if value in {"chorus", "drop"}:
        return "hook"
    if value in {"buildup", "build_up", "build", "prehook", "pre-hook"}:
        return "pre_hook"
    # "break" is a short-form alias for "breakdown"; do NOT collapse "breakdown" into
    # "bridge" — they are musically distinct section types with separate identity profiles.
    if value == "break":
        return "breakdown"
    return value


def _material_difference_ratio(left: list[str], right: list[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set and not right_set:
        return 0.0
    intersection = len(left_set & right_set)
    union = len(left_set | right_set)
    if union <= 0:
        return 0.0
    return 1.0 - (intersection / union)


def _select_section_stem_roles(
    section_type: str,
    available_roles: list[str],
    *,
    verse_count: int = 0,
) -> list[str]:
    section_type = _normalize_section_type(section_type)
    isolated_roles = [role for role in available_roles if role in _ISOLATED_STEM_ROLES]
    full_mix_available = "full_mix" in available_roles
    sufficient_isolated = len(isolated_roles) >= 2
    role_source = isolated_roles if sufficient_isolated else available_roles

    excluded_roles = _SECTION_ROLE_EXCLUSIONS.get(section_type, set())
    role_source = [role for role in role_source if role not in excluded_roles]

    selected: list[str] = []
    for candidates in _SECTION_ROLE_PREFERENCES.get(section_type, _SECTION_ROLE_PREFERENCES["verse"]):
        role = _pick_available_role(role_source, candidates)
        if role and role not in selected:
            selected.append(role)

    if section_type == "verse" and verse_count > 1 and "melody" in role_source and "melody" not in selected:
        selected.append("melody")

    min_layers = _SECTION_MIN_LAYERS.get(section_type, 1)
    max_layers = _SECTION_MAX_LAYERS.get(section_type, max(1, len(selected)))
    if not sufficient_isolated and full_mix_available and len(selected) < min_layers:
        return ["full_mix"]

    if sufficient_isolated:
        selected = [role for role in selected if role != "full_mix"]

    if len(selected) > max_layers:
        selected = selected[:max_layers]

    if not selected:
        if isolated_roles:
            fallback_roles = [role for role in isolated_roles if role not in excluded_roles]
            if fallback_roles:
                return fallback_roles[:max(1, min_layers)]
            return isolated_roles[:max(1, min_layers)]
        if full_mix_available:
            return ["full_mix"]

    return selected


def _stem_premix_gain_db(stem_name: str, stem_count: int) -> float:
    base_gain = _PREMIX_GAIN_DB.get(stem_name, -7.0)
    stacked_layer_penalty = max(0, stem_count - 1) * 0.75
    return base_gain - stacked_layer_penalty


def _apply_headroom_ceiling(audio: AudioSegment, target_peak_dbfs: float = -6.0) -> AudioSegment:
    peak = float(audio.max_dBFS)
    if peak == float("-inf") or peak <= target_peak_dbfs:
        return audio
    return audio - (peak - target_peak_dbfs)


def _rms_dbfs(audio: AudioSegment) -> float:
    """Return RMS in dBFS with silence-safe floor."""
    rms = int(audio.rms or 0)
    if rms <= 0:
        return -120.0
    full_scale = float(1 << (8 * audio.sample_width - 1))
    return float(20.0 * np.log10(max(rms, 1) / full_scale))


def _stabilize_section_loudness(
    current: AudioSegment,
    previous: AudioSegment | None,
    section_type: str,
    previous_section_type: str | None = None,
) -> AudioSegment:
    """Limit abrupt adjacent section loudness swings that sound like pumping."""
    if previous is None:
        return current

    prev_type = str(previous_section_type or "").strip().lower()
    current_type = str(section_type or "").strip().lower()

    current_rms = _rms_dbfs(current)
    previous_rms = _rms_dbfs(previous)
    delta_db = current_rms - previous_rms

    up_limit = 2.5
    down_limit = -2.5

    if current_type in {"hook", "drop", "chorus"}:
        # Only constrain the known problematic ramp into hook sections.
        if prev_type in {"pre_hook", "buildup", "build_up", "build"}:
            up_limit = 4.0
            down_limit = -4.0
        else:
            return current

    if current_type in {"intro", "outro", "breakdown", "bridge", "break"}:
        up_limit = 1.5
        down_limit = -4.0

    clamped_delta = min(up_limit, max(down_limit, delta_db))
    correction_db = clamped_delta - delta_db

    if abs(correction_db) >= 0.25:
        return current.apply_gain(correction_db)
    return current


def debug_render_report(arrangement_id: int) -> list[dict]:
    """
    Produce a section-by-section render diagnostics report for one arrangement.

    Returns a list of dicts, one per section, each containing:
      - section_name, section_type, bars, bar_start
      - requested_instruments (from render_plan_json)
      - active_stem_roles (after role selection)
      - stems_used (list of keys actually passed to audio builder)
      - pre_dsp_peak_dbfs (peak after stem mix, before section DSP)
      - post_dsp_peak_dbfs (peak after section DSP)
      - full_mix_active (bool)
      - gain_applied_per_stem (dict: stem_name -> dBFS applied)
      - clip_detected (bool: post_dsp_peak >= 0.0 dBFS)

    This function loads audio from storage, so it should only be called when
    the arrangement's render_plan_json and loop stems are available.

    Usage::
        from app.services.arrangement_jobs import debug_render_report
        report = debug_render_report(arrangement_id=42)
        for row in report:
            print(row)
    """
    from app.db import SessionLocal
    from app.models.arrangement import Arrangement
    from app.models.loop import Loop
    from app.services.stem_loader import StemLoadError, load_stems_from_metadata, normalize_stem_durations, map_instruments_to_stems

    db = SessionLocal()
    report: list[dict] = []
    try:
        arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
        if not arrangement:
            raise ValueError(f"Arrangement {arrangement_id} not found")
        loop = db.query(Loop).filter(Loop.id == arrangement.loop_id).first()
        if not loop:
            raise ValueError(f"Loop {arrangement.loop_id} not found for arrangement {arrangement_id}")

        render_plan_raw = arrangement.render_plan_json
        if not render_plan_raw:
            raise ValueError(f"Arrangement {arrangement_id} has no render_plan_json")
        render_plan = json.loads(render_plan_raw)

        bpm = float(render_plan.get("bpm") or loop.bpm or 120.0)
        bar_duration_ms = int((60.0 / bpm) * 4.0 * 1000)

        stem_metadata = _parse_stem_metadata_from_loop(loop)
        stems: dict[str, AudioSegment] | None = None
        if stem_metadata and stem_metadata.get("enabled") and stem_metadata.get("succeeded"):
            try:
                stems = load_stems_from_metadata(stem_metadata, timeout_seconds=60.0)
                stems = normalize_stem_durations(stems)
                logger.info(
                    "debug_render_report: loaded stems %s for arrangement %d",
                    list(stems.keys()), arrangement_id,
                )
            except StemLoadError as e:
                logger.warning("debug_render_report: stem load failed: %s", e)

        for section_idx, section in enumerate(render_plan.get("sections") or []):
            section_name = section.get("name", f"Section {section_idx + 1}")
            section_type = str(section.get("type") or section.get("section_type") or "verse").strip().lower()
            bar_start = int(section.get("bar_start") or 0)
            section_bars = int(section.get("bars") or 8)
            requested_instruments: list[str] = list(section.get("instruments") or [])
            active_roles: list[str] = list(section.get("active_stem_roles") or requested_instruments)

            row: dict = {
                "section_idx": section_idx,
                "section_name": section_name,
                "section_type": section_type,
                "bar_start": bar_start,
                "bars": section_bars,
                "requested_instruments": requested_instruments,
                "active_stem_roles": active_roles,
                "stems_used": [],
                "gain_applied_per_stem_db": {},
                "pre_dsp_peak_dbfs": None,
                "post_dsp_peak_dbfs": None,
                "full_mix_active": False,
                "clip_detected": False,
                "mode": "stems" if stems else "stereo_fallback",
            }

            if stems:
                enabled_stems = map_instruments_to_stems(active_roles, stems)
                if not enabled_stems:
                    enabled_stems = stems

                row["stems_used"] = list(enabled_stems.keys())
                row["full_mix_active"] = "full_mix" in enabled_stems

                stem_count = max(1, len(enabled_stems))
                gain_map: dict[str, float] = {}
                for stem_name in enabled_stems:
                    gain_map[stem_name] = _stem_premix_gain_db(stem_name, stem_count)
                row["gain_applied_per_stem_db"] = gain_map

                section_ms = section_bars * bar_duration_ms
                section_audio = _build_section_audio_from_stems(
                    stems=enabled_stems,
                    section_bars=section_bars,
                    bar_duration_ms=bar_duration_ms,
                    section_idx=section_idx,
                )[:section_ms]

                row["pre_dsp_peak_dbfs"] = round(float(section_audio.max_dBFS), 2)

                # Apply same DSP as _render_producer_arrangement so peak is comparable
                if section_type == "intro":
                    section_audio = section_audio - 4
                elif section_type in {"drop", "hook", "chorus"}:
                    section_audio = section_audio + 4.0
                    section_audio = _apply_headroom_ceiling(section_audio, target_peak_dbfs=-1.5)
                elif section_type in {"breakdown", "bridge"}:
                    section_audio = section_audio - 6
                elif section_type == "outro":
                    section_audio = section_audio - 4
                else:
                    energy = float(section.get("energy") or 0.6)
                    energy_db = max(-5.0, min(0.0, -5.0 + (energy * 5.0)))
                    section_audio = section_audio + energy_db

                row["post_dsp_peak_dbfs"] = round(float(section_audio.max_dBFS), 2)
                row["clip_detected"] = row["post_dsp_peak_dbfs"] >= 0.0

            report.append(row)
            logger.info(
                "DEBUG_RENDER_REPORT [%d] %s type=%s stems=%s pre=%.1f post=%.1f clip=%s",
                section_idx, section_name, section_type,
                row["stems_used"],
                row["pre_dsp_peak_dbfs"] if row["pre_dsp_peak_dbfs"] is not None else float("nan"),
                row["post_dsp_peak_dbfs"] if row["post_dsp_peak_dbfs"] is not None else float("nan"),
                row["clip_detected"],
            )
    finally:
        db.close()

    return report


def get_render_spec_summary(arrangement_id: int) -> dict:
    """Return the render-spec summary stored inside an arrangement's timeline JSON.

    This is the Phase 6 production-safe debug entry point.  The summary is built
    by ``_build_render_spec_summary()`` at render time and persisted inside
    ``arrangement.arrangement_json``.

    Returns a dict with keys:
      - sections_count
      - distinct_stem_set_count  — 1 means every section used the same stems (bad)
      - most_reused_stem_set_count
      - phrase_split_count        — how many sections had intra-section phrase splits
      - hook_stages               — list of hook stage strings rendered
      - transition_event_count
      - section_role_map          — per-section role/phrase detail

    Raises ``ValueError`` if arrangement not found or has no timeline data.
    """
    from app.db import SessionLocal
    from app.models.arrangement import Arrangement

    db = SessionLocal()
    try:
        arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement_id).first()
        if not arrangement:
            raise ValueError(f"Arrangement {arrangement_id} not found")
        if not arrangement.arrangement_json:
            raise ValueError(f"Arrangement {arrangement_id} has no timeline data yet")
        timeline = json.loads(arrangement.arrangement_json)
        summary = timeline.get("render_spec_summary")
        if not summary:
            raise ValueError(
                f"Arrangement {arrangement_id} timeline has no render_spec_summary "
                "(was rendered before this feature was added)"
            )
        return summary
    finally:
        db.close()


def _parse_style_sections(raw_json: str | None) -> list[dict] | None:
    """
    Parse style sections from arrangement_json.
    Supports both legacy format (array) and new format (object with seed + sections).
    Returns sections list only.
    """
    if not raw_json:
        return None

    try:
        payload = json.loads(raw_json)
    except Exception:
        return None

    # Handle new format: {"seed": 123, "sections": [...]}
    if isinstance(payload, dict):
        sections_data = payload.get("sections")
        if not isinstance(sections_data, list):
            return None
        payload = sections_data

    # Handle legacy format: [...]
    if not isinstance(payload, list):
        return None

    sections: list[dict] = []
    current_bar = 0
    for item in payload:
        if not isinstance(item, dict):
            continue
        bars = int(item.get("bars", 0) or 0)
        if bars <= 0:
            continue
        name = str(item.get("name", "section"))
        energy = float(item.get("energy", 0.6) or 0.6)
        sections.append(
            {
                "name": name,
                "bars": bars,
                "energy": max(0.0, min(1.0, energy)),
                "start_bar": current_bar,
                "end_bar": current_bar + bars - 1,
            }
        )
        current_bar += bars

    return sections or None


def _parse_seed_from_json(raw_json: str | None) -> int | None:
    """Extract seed from arrangement_json if present."""
    if not raw_json:
        return None

    try:
        payload = json.loads(raw_json)
        if isinstance(payload, dict):
            seed = payload.get("seed")
            if seed is not None:
                return int(seed)
    except Exception:
        pass

    return None


def _parse_style_profile(style_profile_json: str | None) -> dict | None:
    """
    Parse StyleProfile from JSON.
    Returns dict with resolved_params (style parameters for rendering).
    """
    if not style_profile_json:
        return None

    try:
        profile = json.loads(style_profile_json)
        return profile
    except Exception as e:
        logger.warning("Failed to parse style_profile_json: %s", e)
        return None


def _parse_producer_arrangement(producer_arrangement_json: str | None) -> dict | None:
    """
    Parse ProducerArrangement from JSON.
    Returns dict with full producer arrangement structure.
    """
    if not producer_arrangement_json:
        return None

    try:
        payload = json.loads(producer_arrangement_json)
        # Handle both direct format and wrapped format
        if isinstance(payload, dict):
            if "producer_arrangement" in payload:
                return payload["producer_arrangement"]
            # If it looks like a ProducerArrangement dict directly
            if "sections" in payload and "tracks" in payload:
                return payload
        return payload
    except Exception as e:
        logger.warning("Failed to parse producer_arrangement_json: %s", e)
        return None


def _parse_stem_metadata_from_loop(loop: Loop) -> dict | None:
    """Extract stem metadata from loop.analysis_json when available."""
    if not loop or not loop.analysis_json:
        return None
    try:
        payload = json.loads(loop.analysis_json)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    stem_meta = payload.get("stem_separation")
    if not isinstance(stem_meta, dict):
        return None
    return stem_meta


def _validate_render_plan_quality(render_plan: dict) -> None:
    """
    Validate render plan meets minimum quality standards before rendering.
    
    Ensures plan is not just "repeated loop with volume changes" syndrome.
    Checks:
    - At least 3 sections
    - At least 10 meaningful events
    - Section type variety (intro/verse/hook/outro)
    
    Args:
        render_plan: The render plan dict
    
    Raises:
        ValueError: If plan fails critical quality checks
    """
    sections = render_plan.get("sections", [])
    events = render_plan.get("events", [])
    
    # Check 1: At least 3 sections
    if len(sections) < 3:
        raise ValueError(
            f"render_plan has only {len(sections)} sections - need at least 3 for real arrangement"
        )
    
    # Check 2: At least 10 meaningful events to avoid "repeated loop" syndrome
    meaningful_event_types = {
        "variation", "beat_switch", "halftime_drop", "stop_time", "drum_fill", "fill",
        "snare_roll", "pre_hook_silence", "riser_fx", "crash_hit", "reverse_cymbal", "drop_kick", "bass_pause",
        "enable_stem", "disable_stem", "stem_gain_change", "stem_filter", "silence_drop",
        "pre_hook_mute", "fill_event", "texture_lift", "hook_expansion", "bridge_strip", "outro_strip",
        "pre_hook_drum_mute", "silence_drop_before_hook", "hat_density_variation",
        "end_section_fill", "verse_melody_reduction", "bridge_bass_removal",
        "final_hook_expansion", "outro_strip_down", "call_response_variation",
    }
    
    meaningful_events = [
        e for e in events
        if e.get("type") in meaningful_event_types
    ]
    
    if len(meaningful_events) < 10:
        logger.warning(
            f"⚠️ Only {len(meaningful_events)} meaningful events in render plan - "
            f"may sound repetitive (need at least 10)"
        )
    
    # Check 3: Section type variety
    section_types = [s.get("type", "unknown") for s in sections]
    unique_types = set(section_types)
    
    if len(unique_types) < 2:
        raise ValueError(
            f"render_plan has only {len(unique_types)} unique section types - "
            f"need at least intro/verse/hook/outro"
        )
    
    logger.info(
        f"✅ Render plan quality validation passed: {len(sections)} sections, "
        f"{len(meaningful_events)} events, {len(unique_types)} section types"
    )

    scorecard = render_plan.get("producer_scorecard") or {}
    verdict = str(scorecard.get("verdict", "pass")).strip().lower()
    if verdict == "reject":
        raise ValueError(
            f"render_plan rejected by live producer scorecard: total={scorecard.get('total', 0)}"
        )
    if verdict == "warn":
        logger.warning(
            "⚠️ Live producer scorecard warning: total=%s warnings=%s",
            scorecard.get("total", 0),
            scorecard.get("warnings", []),
        )

    validate_variation_plan_usage(render_plan)


def _repeat_to_duration(audio: AudioSegment, target_ms: int) -> AudioSegment:
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)
    repeats = (target_ms // len(audio)) + 1
    return (audio * repeats)[:target_ms]


def _apply_stem_primary_section_states(sections: list[dict], stem_metadata: dict | None) -> list[dict]:
    if not stem_metadata or not stem_metadata.get("enabled") or not stem_metadata.get("succeeded"):
        return sections

    available_roles = _ordered_unique_roles([
        str(role).strip().lower()
        for role in (stem_metadata.get("roles_detected") or (stem_metadata.get("stem_s3_keys") or {}).keys())
        if str(role).strip()
    ])
    if not available_roles:
        return sections

    use_identity_engine = settings.feature_producer_section_identity_v2
    use_choreography = bool(
        getattr(settings, "feature_section_choreography_v2", False)
        and use_identity_engine
    )

    if use_identity_engine:
        if use_choreography:
            from app.services.section_identity_engine import (
                select_roles_with_choreography,
                get_transition_events,
                get_phrase_variation_plan,
            )
        else:
            from app.services.section_identity_engine import select_roles_for_section, get_transition_events  # type: ignore[assignment]
        occurrence_counter: dict[str, int] = {}
        prev_same_type_roles: dict[str, list[str]] = {}
        prev_adjacent_roles: list[str] = []

        for section_idx, section in enumerate(sections):
            section_type = _normalize_section_type(section.get("type") or "verse")
            occurrence_counter[section_type] = occurrence_counter.get(section_type, 0) + 1
            occurrence = occurrence_counter[section_type]

            if use_choreography:
                active_roles, choreography = select_roles_with_choreography(
                    section_type=section_type,
                    available_roles=available_roles,
                    occurrence=occurrence,
                    prev_same_type_roles=prev_same_type_roles.get(section_type),
                    prev_adjacent_roles=prev_adjacent_roles if section_idx > 0 else None,
                )
                section["choreography"] = {
                    "leader_roles": list(choreography.leader_roles),
                    "support_roles": list(choreography.support_roles),
                    "suppressed_roles": list(choreography.suppressed_roles),
                    "contrast_roles": list(choreography.contrast_roles),
                    "rotation_note": choreography.rotation_note,
                }
            else:
                active_roles = select_roles_for_section(
                    section_type=section_type,
                    available_roles=available_roles,
                    occurrence=occurrence,
                    prev_same_type_roles=prev_same_type_roles.get(section_type),
                    prev_adjacent_roles=prev_adjacent_roles if section_idx > 0 else None,
                )

            if not active_roles and available_roles:
                active_roles = available_roles[:1]

            # Derive transition_out from the next section type (if known).
            next_section_type = None
            if section_idx + 1 < len(sections):
                next_section_type = _normalize_section_type(sections[section_idx + 1].get("type") or "verse")

            transition_out_map = {
                "intro": "filter_open",
                "verse": "lift",
                "pre_hook": "riser",
                "hook": "impact",
                "bridge": "riser",
                "breakdown": "riser",
                "outro": "fade",
            }
            transition_out = transition_out_map.get(section_type, "cut")

            section["instruments"] = active_roles
            section["active_stem_roles"] = active_roles
            section["stem_primary"] = True
            section["transition_out"] = transition_out
            section["type"] = section_type

            # Inject intra-section phrase variation plan (SECTION_CHOREOGRAPHY_V2).
            if use_choreography:
                section_bars = int(section.get("bars", 1) or 1)
                phrase_plan = get_phrase_variation_plan(
                    section_type=section_type,
                    active_roles=active_roles,
                    section_bars=section_bars,
                    occurrence=occurrence,
                    available_roles=available_roles,
                )
                if phrase_plan is not None:
                    section["phrase_plan"] = {
                        "split_bar": phrase_plan.split_bar,
                        "first_phrase_roles": phrase_plan.first_phrase_roles,
                        "second_phrase_roles": phrase_plan.second_phrase_roles,
                        "lead_entry_delay_bars": phrase_plan.lead_entry_delay_bars,
                        "end_dropout_bars": phrase_plan.end_dropout_bars,
                        "end_dropout_roles": phrase_plan.end_dropout_roles,
                        "description": phrase_plan.description,
                    }

            # Inject deterministic transition boundary events.
            baseline_variations: list[dict] = list(section.get("variations") or [])
            boundary_events: list[dict] = list(section.get("boundary_events") or [])

            bar_start = int(section.get("bar_start", 0) or 0)
            section_bars = int(section.get("bars", 1) or 1)
            prev_end_bar = bar_start + section_bars - 1

            if next_section_type:
                next_bar_start = bar_start + section_bars
                transition_events = get_transition_events(
                    prev_section_type=section_type,
                    next_section_type=next_section_type,
                    prev_end_bar=prev_end_bar,
                    next_start_bar=next_bar_start,
                    occurrence_of_next=occurrence_counter.get(next_section_type, 0) + 1,
                )
                for te in transition_events:
                    if te.placement == "end_of_section":
                        baseline_variations.append({
                            "variation_type": te.event_type,
                            "bar_start": te.bar,
                            "duration_bars": 1,
                            "intensity": te.intensity,
                            "params": te.params,
                        })
                        boundary_events.append({
                            "type": te.event_type,
                            "bar": te.bar,
                            "placement": te.placement,
                            "intensity": te.intensity,
                            "params": te.params,
                        })

            # Section-specific baseline variations (always applied).
            if section_type == "pre_hook":
                baseline_variations.extend([
                    {
                        "variation_type": "pre_hook_drum_mute",
                        "bar_start": max(0, bar_start + section_bars - 1),
                        "duration_bars": 1,
                        "intensity": 0.85,
                        "params": {"pause_bars": 0.5},
                    },
                    {
                        "variation_type": "bass_pause",
                        "bar_start": max(0, bar_start + section_bars - 1),
                        "duration_bars": 1,
                        "intensity": 0.8,
                        "params": {"pause_bars": 0.5},
                    },
                ])
                boundary_events.append({
                    "type": "snare_pickup",
                    "bar": max(0, bar_start + section_bars - 1),
                    "placement": "end_of_section",
                    "intensity": 0.82,
                    "params": {},
                })

            if section_type in {"bridge", "breakdown"}:
                baseline_variations.append({
                    "variation_type": "bridge_strip",
                    "bar_start": bar_start,
                    "duration_bars": max(1, section_bars),
                    "intensity": 0.82,
                    "params": {"strip": ["drums", "bass"]},
                })

            if section_type == "outro":
                baseline_variations.append({
                    "variation_type": "outro_strip_down",
                    "bar_start": bar_start,
                    "duration_bars": max(1, section_bars),
                    "intensity": 0.8,
                    "params": {"pause_bars": 1.0},
                })

            if baseline_variations:
                section["variations"] = baseline_variations
            if boundary_events:
                section["boundary_events"] = boundary_events

            if section_type in {"hook", "chorus", "drop"}:
                hook_count = occurrence_counter.get("hook", occurrence_counter.get("chorus", occurrence_counter.get("drop", 1)))
                stage = "hook1"
                if hook_count == 2:
                    stage = "hook2"
                elif hook_count >= 3:
                    stage = "hook3"
                section["hook_evolution"] = {
                    "stage": stage,
                    "density": 0.75 + min(0.2, (hook_count - 1) * 0.1),
                    "stereo_width": 1.0 + min(0.16, (hook_count - 1) * 0.08),
                }

            prev_same_type_roles[section_type] = active_roles
            prev_adjacent_roles = active_roles

        return sections

    # --- Legacy path (PRODUCER_SECTION_IDENTITY_V2 disabled) ---
    hook_count = 0
    verse_count = 0
    previous_roles: list[str] = []

    for section in sections:
        section_type = _normalize_section_type(section.get("type") or "verse")
        active_roles: list[str] = []
        transition_out = "cut"

        if section_type == "intro":
            active_roles = _select_section_stem_roles(section_type, available_roles, verse_count=verse_count)
            transition_out = "filter_open"
        elif section_type == "verse":
            verse_count += 1
            active_roles = _select_section_stem_roles(section_type, available_roles, verse_count=verse_count)
            transition_out = "lift"
        elif section_type == "pre_hook":
            active_roles = _select_section_stem_roles(section_type, available_roles, verse_count=verse_count)
            transition_out = "riser"
        elif section_type in {"hook", "chorus", "drop"}:
            hook_count += 1
            active_roles = _select_section_stem_roles("hook", available_roles, verse_count=verse_count)
            transition_out = "impact"
        elif section_type in {"bridge", "breakdown"}:
            active_roles = _select_section_stem_roles(section_type, available_roles, verse_count=verse_count)
            transition_out = "riser"
        elif section_type == "outro":
            active_roles = _select_section_stem_roles(section_type, available_roles, verse_count=verse_count)
            transition_out = "fade"

        if not active_roles:
            active_roles = _select_section_stem_roles(section_type, available_roles, verse_count=verse_count)

        # Prevent near-identical section stem sets so contrast is not just volume-based.
        if previous_roles and _material_difference_ratio(previous_roles, active_roles) < 0.25:
            if section_type == "hook":
                for hook_role in ("fx", "pads", "harmony", "melody"):
                    if hook_role in available_roles and hook_role not in active_roles:
                        active_roles.append(hook_role)
                        break
            elif section_type in {"bridge", "breakdown", "outro", "intro", "pre_hook"}:
                for removable in ("drums", "percussion", "bass"):
                    if removable in active_roles and len(active_roles) > 1:
                        active_roles = [role for role in active_roles if role != removable]
                        break
            elif section_type == "verse":
                for removable in ("pads", "fx", "harmony"):
                    if removable in active_roles and len(active_roles) > 2:
                        active_roles = [role for role in active_roles if role != removable]
                        break

        section["instruments"] = active_roles
        section["active_stem_roles"] = active_roles
        section["stem_primary"] = True
        section["transition_out"] = transition_out
        section["type"] = section_type

        baseline_variations: list[dict] = []
        boundary_events: list[dict] = list(section.get("boundary_events") or [])

        if section_type == "pre_hook":
            baseline_variations.extend(
                [
                    {
                        "variation_type": "pre_hook_drum_mute",
                        "bar_start": max(0, int(section.get("bar_start", 0) or 0) + int(section.get("bars", 1) or 1) - 1),
                        "duration_bars": 1,
                        "intensity": 0.85,
                        "params": {"pause_bars": 0.5},
                    },
                    {
                        "variation_type": "bass_pause",
                        "bar_start": max(0, int(section.get("bar_start", 0) or 0) + int(section.get("bars", 1) or 1) - 1),
                        "duration_bars": 1,
                        "intensity": 0.8,
                        "params": {"pause_bars": 0.5},
                    },
                ]
            )
            boundary_events.append(
                {
                    "type": "snare_pickup",
                    "bar": max(0, int(section.get("bar_start", 0) or 0) + int(section.get("bars", 1) or 1) - 1),
                    "placement": "end_of_section",
                    "intensity": 0.82,
                    "params": {},
                }
            )

        if section_type in {"bridge", "breakdown"}:
            baseline_variations.append(
                {
                    "variation_type": "bridge_strip",
                    "bar_start": int(section.get("bar_start", 0) or 0),
                    "duration_bars": max(1, int(section.get("bars", 1) or 1)),
                    "intensity": 0.82,
                    "params": {"strip": ["drums", "bass"]},
                }
            )

        if section_type == "outro":
            baseline_variations.append(
                {
                    "variation_type": "outro_strip_down",
                    "bar_start": int(section.get("bar_start", 0) or 0),
                    "duration_bars": max(1, int(section.get("bars", 1) or 1)),
                    "intensity": 0.8,
                    "params": {"pause_bars": 1.0},
                }
            )

        if baseline_variations:
            section.setdefault("variations", [])
            section["variations"].extend(baseline_variations)
        if boundary_events:
            section["boundary_events"] = boundary_events

        if section_type in {"hook", "chorus", "drop"}:
            stage = "hook1"
            if hook_count == 2:
                stage = "hook2"
            elif hook_count >= 3:
                stage = "hook3"
            section["hook_evolution"] = {
                "stage": stage,
                "density": 0.75 + min(0.2, (hook_count - 1) * 0.1),
                "stereo_width": 1.0 + min(0.16, (hook_count - 1) * 0.08),
            }

        previous_roles = list(active_roles)

    return sections


def _build_varied_section_audio(
    loop_audio: AudioSegment,
    section_bars: int,
    bar_duration_ms: int,
    section_idx: int,
    section_type: str,
) -> AudioSegment:
    """Create a section from loop audio with per-bar variation so output is not a static repeat.
    
    Applies audible effects per section type:
    - Intro: Subtle filtered start
    - Verse: Thin EQ + rhythmic gaps every 4 bars for variation
    - Hook/Drop: Bright, punchy high-frequency emphasis  
    - Breakdown/Bridge: Sparse gaps, filtered
    - Outro: Fading diminishment
    """
    section_audio = AudioSegment.silent(duration=0)
    loop_len = len(loop_audio)
    quarter = max(1, loop_len // 4)

    for bar_idx in range(max(1, section_bars)):
        bar_source = loop_audio
        # Rotate source position per bar/section to avoid identical loop restarts.
        offset = ((section_idx * 3) + bar_idx) * quarter % loop_len
        if offset > 0:
            bar_source = loop_audio[offset:] + loop_audio[:offset]

        bar_audio = _repeat_to_duration(bar_source, bar_duration_ms)

        # Add audible rhythmic contrast per section type
        if section_type in {"intro"}:
            # Intro: Gentle filtering for soft start
            if bar_idx == 0:
                bar_audio = bar_audio.low_pass_filter(1000)  # Filtered first bar
            
        elif section_type in {"hook", "drop", "chorus"}:
            # Hook: Bright and punchy with high-frequency emphasis
            if bar_idx % 2 == 0:
                # Even bars: brighten with high-pass filter + boost
                accent = bar_audio.high_pass_filter(150) + 3
                bar_audio = bar_audio.overlay(accent, gain_during_overlay=-3)  # Boost HF
            else:
                # Odd bars: add extra punch
                bar_audio = bar_audio + 2  # Small additional boost
            
        elif section_type in {"verse"}:
            # Verse: Create texture variation with filtered gaps
            if bar_idx % 6 == 4:
                # Every 4-6 bars: Insert half-bar silence for rhythmic surprise
                quarter_bar = max(1, bar_duration_ms // 4)
                bar_audio = bar_audio[:quarter_bar] + AudioSegment.silent(duration=quarter_bar * 2) + bar_audio[quarter_bar * 3:]
                bar_audio = bar_audio - 1  # Slight volume reduction to emphasize the gap
            elif bar_idx % 4 == 0:
                # Every 4 bars: Apply thin EQ by boosting mids, cutting lows/highs
                bar_audio = bar_audio.high_pass_filter(200)  # Cut low bass
                bar_audio = bar_audio.low_pass_filter(6000)  # Cut harsh highs
                bar_audio = bar_audio - 3  # Slight reduction
            else:
                # Normal verses: light processing for warmth
                pass
                
        elif section_type in {"breakdown", "bridge", "break"}:
            # Breakdown: Sparse with strong filtering
            if len(section_audio) > 4000 or bar_idx > 0:  # After first bar
                half_bar = max(1, bar_duration_ms // 2)
                bar_audio = bar_audio[:half_bar] + AudioSegment.silent(duration=half_bar)
            # Add filtering for ambient feel
            bar_audio = bar_audio.low_pass_filter(1500)
            
        elif section_type == "outro":
            # Outro: Progressive diminishment
            fade_db = -(bar_idx * 1.5)  # Progressive volume reduction (-1.5dB per bar)
            bar_audio = bar_audio + fade_db

        section_audio += bar_audio

    return section_audio


_PRODUCER_MOVE_TYPES = {
    "enable_stem",
    "disable_stem",
    "stem_gain_change",
    "stem_filter",
    "drum_fill",
    "snare_roll",
    "pre_hook_silence",
    "riser_fx",
    "crash_hit",
    "reverse_cymbal",
    "drop_kick",
    "bass_pause",
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
}


def _apply_producer_move_effect(
    segment: AudioSegment,
    move_type: str,
    intensity: float,
    stem_available: bool,
    bar_duration_ms: int,
    params: dict | None = None,
) -> AudioSegment:
    """Apply audible producer move effects using stems when available, DSP fallback otherwise."""
    intensity = max(0.1, min(1.0, float(intensity or 0.7)))
    params = params or {}

    if move_type == "enable_stem":
        boosted = segment + (2 + 3 * intensity)
        if "hats" in str(params.get("stems", "")).lower() or "fx" in str(params.get("stems", "")).lower():
            boosted = boosted.overlay(segment.high_pass_filter(2500) + 3, gain_during_overlay=-2)
        return boosted

    if move_type == "drum_fill":
        fill_len = int(min(len(segment), bar_duration_ms * 0.55))
        fill_start = max(0, len(segment) - fill_len)
        fill = segment[fill_start:].high_pass_filter(2300) + (4 + 3 * intensity)
        return segment[:fill_start] + fill

    if move_type == "snare_pickup":
        pickup_len = int(min(len(segment), bar_duration_ms * 0.4))
        pickup_start = max(0, len(segment) - pickup_len)
        pickup = segment[pickup_start:].high_pass_filter(1800)
        grid = max(20, pickup_len // 10)
        rebuilt = AudioSegment.silent(duration=0)
        for ms in range(0, len(pickup), grid):
            chunk = pickup[ms: min(len(pickup), ms + grid)]
            rebuilt += chunk + (5 if (ms // grid) % 2 == 0 else 1)
        return segment[:pickup_start] + rebuilt

    if move_type == "snare_roll":
        roll_len = int(min(len(segment), bar_duration_ms * 0.5))
        roll = segment[max(0, len(segment) - roll_len):].high_pass_filter(1800)
        grid = max(20, int(bar_duration_ms / (24 + int(10 * intensity))))
        stutter = AudioSegment.silent(duration=0)
        for ms in range(0, len(roll), grid):
            chunk = roll[ms: min(len(roll), ms + grid)]
            stutter += chunk + (4 if (ms // grid) % 2 == 0 else -2)
        return segment[:max(0, len(segment) - roll_len)] + stutter

    if move_type == "pre_hook_silence":
        mute_ms = int(min(len(segment), bar_duration_ms * (0.45 + 0.3 * intensity)))
        return AudioSegment.silent(duration=mute_ms) + segment[mute_ms:]

    if move_type == "pre_hook_silence_drop":
        gap_ms = int(min(len(segment), bar_duration_ms * (1.0 if stem_available else 0.5)))
        gap_ms = max(1, gap_ms)
        lead = segment[:-gap_ms] if gap_ms < len(segment) else AudioSegment.silent(duration=0)
        source_tail = segment[-gap_ms:] if gap_ms < len(segment) else segment
        if stem_available:
            tail = source_tail.high_pass_filter(240) - 10
        else:
            tail = source_tail.reverse().fade_in(max(1, gap_ms // 4)).low_pass_filter(1800) - 8
        return lead + AudioSegment.silent(duration=gap_ms // 2) + tail[: max(0, gap_ms - (gap_ms // 2))]

    if move_type == "riser_fx":
        tail_len = int(min(len(segment), bar_duration_ms * 0.75))
        start = max(0, len(segment) - tail_len)
        tail = segment[start:].high_pass_filter(250)
        tail = tail.fade_in(max(1, tail_len // 3)) + (4 + 3 * intensity if stem_available else 2 + 3 * intensity)
        return segment[:start] + tail

    if move_type == "crash_hit":
        hit = segment.high_pass_filter(2200) + (5 + 2 * intensity)
        hit_window = min(len(hit), int(bar_duration_ms * 0.2))
        if hit_window <= 0:
            return segment
        return hit[:hit_window].overlay(segment[:hit_window], gain_during_overlay=-4) + segment[hit_window:]

    if move_type == "reverse_cymbal":
        rev_len = int(min(len(segment), bar_duration_ms * 0.75))
        start = max(0, len(segment) - rev_len)
        rev = segment[start:].reverse().high_pass_filter(1600) + (3 if stem_available else 1)
        return segment[:start] + rev

    if move_type == "drop_kick":
        pause_bars = float(params.get("pause_bars", 0.35) or 0.35)
        drop_len = int(min(len(segment), bar_duration_ms * max(0.1, pause_bars)))
        return AudioSegment.silent(duration=drop_len) + segment[drop_len:]

    if move_type == "bass_pause":
        pause_bars = float(params.get("pause_bars", 0.5) or 0.5)
        pause_len = int(min(len(segment), bar_duration_ms * max(0.1, pause_bars)))
        head = segment[:pause_len].high_pass_filter(260) - (5 if stem_available else 3)
        return head + segment[pause_len:]

    if move_type == "disable_stem":
        reduced = segment - (4 + 4 * intensity)
        if any(x in str(params.get("stems", "")).lower() for x in ("kick", "bass")):
            reduced = reduced.high_pass_filter(180)
        if any(x in str(params.get("stems", "")).lower() for x in ("hats", "snare")):
            reduced = reduced.low_pass_filter(3500)
        return reduced

    if move_type == "stem_gain_change":
        gain_db = float(params.get("gain_db", -3))
        shaped = segment + gain_db
        if gain_db < 0:
            return shaped.low_pass_filter(5000)
        return shaped.overlay(segment.high_pass_filter(2200), gain_during_overlay=-3)

    if move_type == "stem_filter":
        filter_type = str(params.get("filter", "")).strip().lower()
        if filter_type == "lowpass":
            cutoff = int(params.get("cutoff_hz", 1400) or 1400)
            return segment.low_pass_filter(cutoff)
        if filter_type == "highshelf":
            gain_db = float(params.get("gain_db", 4) or 4)
            return segment.overlay(segment.high_pass_filter(2200) + gain_db, gain_during_overlay=-3)
        if filter_type == "bandpass":
            low_hz = int(params.get("low_hz", 200) or 200)
            high_hz = int(params.get("high_hz", 3000) or 3000)
            return segment.high_pass_filter(low_hz).low_pass_filter(high_hz)

    if move_type == "silence_drop":
        pause_bars = float(params.get("pause_bars", 0.22 + (0.2 * intensity)) or (0.22 + (0.2 * intensity)))
        gap_ms = int(min(len(segment), bar_duration_ms * max(0.1, pause_bars)))
        return AudioSegment.silent(duration=gap_ms) + segment[gap_ms:]

    if move_type == "pre_hook_mute":
        mute_ms = int(min(len(segment), bar_duration_ms * (0.40 + 0.25 * intensity)))
        return AudioSegment.silent(duration=mute_ms) + segment[mute_ms:]

    if move_type == "fill_event":
        fill_len = int(min(len(segment), bar_duration_ms * 0.6))
        fill_start = max(0, len(segment) - fill_len)
        fill = segment[fill_start:]
        fill_type = str(params.get("fill_type", "drum_fill")).strip().lower()
        if fill_type == "chop_fill":
            chop = AudioSegment.silent(duration=0)
            grid = max(40, int(fill_len / 8))
            for pos in range(0, len(fill), grid):
                chunk = fill[pos: pos + grid]
                chop += chunk + (4 if (pos // grid) % 2 == 0 else -3)
            fill = chop
        else:
            fill = fill.high_pass_filter(2400) + (4 + 2 * intensity)
        return segment[:fill_start] + fill

    if move_type == "texture_lift":
        transient = segment.high_pass_filter(1700) + (2 + 2 * intensity)
        return segment.overlay(transient, gain_during_overlay=-3)

    if move_type == "hook_expansion":
        expanded = segment + (3 + 2 * intensity)
        width = expanded.overlay(expanded.high_pass_filter(2500) + 3, gain_during_overlay=-3)
        return width

    if move_type == "bridge_strip":
        stripped = segment.high_pass_filter(220 if stem_available else 180).low_pass_filter(2400 if stem_available else 2800) - (4 + 2 * intensity)
        return stripped

    if move_type == "outro_strip":
        strip = segment.low_pass_filter(1800 if stem_available else 2200) - (4 + 3 * intensity)
        return strip.fade_out(min(len(strip), int(bar_duration_ms * 0.85)))

    if move_type == "pre_hook_drum_mute":
        pause_bars = float(params.get("pause_bars", 0.45 + (0.35 * intensity)) or (0.45 + (0.35 * intensity)))
        mute_ms = int(min(len(segment), bar_duration_ms * max(0.2, pause_bars)))
        return AudioSegment.silent(duration=mute_ms) + segment[mute_ms:]

    if move_type == "silence_drop_before_hook":
        gap_ms = int(min(len(segment), bar_duration_ms * (0.30 + 0.30 * intensity)))
        tail = segment[gap_ms:] + (4 * intensity)
        return AudioSegment.silent(duration=gap_ms) + tail

    if move_type == "hat_density_variation":
        top_band = segment.high_pass_filter(5500)
        grid = max(30, int(bar_duration_ms / (16 + int(8 * intensity))))
        rolled = AudioSegment.silent(duration=0)
        for ms in range(0, len(top_band), grid):
            slice_end = min(len(top_band), ms + grid)
            chunk = top_band[ms:slice_end]
            if (ms // grid) % 2 == 0:
                rolled += chunk + 5
            else:
                rolled += chunk - 2
        return segment.overlay(rolled, gain_during_overlay=-4)

    if move_type == "end_section_fill":
        fill_len = int(min(len(segment), bar_duration_ms * 0.5))
        fill_start = max(0, len(segment) - fill_len)
        fill = segment[fill_start:]
        fill = fill.high_pass_filter(2500) + (4 + 3 * intensity)
        return segment[:fill_start] + fill

    if move_type == "verse_melody_reduction":
        if stem_available:
            melody_band = segment.high_pass_filter(700).low_pass_filter(5000)
            return segment.overlay(melody_band - (10 + 5 * intensity), gain_during_overlay=0)
        return segment.low_pass_filter(4200) - (2 + 2 * intensity)

    if move_type == "bridge_bass_removal":
        if stem_available:
            return segment.high_pass_filter(220)
        return segment.high_pass_filter(140) - 1

    if move_type == "final_hook_expansion":
        expanded = segment + (3 + 2 * intensity)
        bright = expanded.high_pass_filter(1800) + (2 + 2 * intensity)
        body = expanded.low_pass_filter(250) + (1 + intensity)
        return expanded.overlay(bright).overlay(body)

    if move_type == "outro_strip_down":
        stripped = segment.low_pass_filter(2200) - (4 + 3 * intensity)
        return stripped.fade_out(min(len(stripped), int(bar_duration_ms * 0.8)))

    if move_type == "call_response_variation":
        quarter = max(1, bar_duration_ms // 4)
        call = segment[:quarter * 2]
        response = segment[quarter * 2: quarter * 3] - 8
        tail = segment[quarter * 3:]
        return call + response + tail

    return segment


def _build_section_audio_from_stems(
    stems: dict[str, AudioSegment],
    section_bars: int,
    bar_duration_ms: int,
    section_idx: int,
) -> AudioSegment:
    """
    Build section audio by repeating and mixing enabled stems.
    
    This creates REAL layer-based arrangement by:
    - Only mixing the stems that should be active in this section
    - Other stems are completely absent (not just filtered)
    - Creates actual producer-style layer control
    
    Args:
        stems: Dict of stem name to AudioSegment (only enabled stems)
        section_bars: Number of bars in section
        bar_duration_ms: Duration of one bar in milliseconds
        section_idx: Section index (for variation)
    
    Returns:
        Mixed audio for this section with only specified stems
    """
    if not stems:
        # Shouldn't happen, but fallback to silence
        return AudioSegment.silent(duration=section_bars * bar_duration_ms)
    
    target_ms = section_bars * bar_duration_ms
    
    # Mix all enabled stems with per-bar offset variation
    mixed = AudioSegment.silent(duration=target_ms)
    stem_count = max(1, len(stems))
    
    for stem_name, stem_audio in stems.items():
        # Repeat stem to fill section duration
        stem_repeated = _repeat_to_duration(stem_audio, target_ms)
        
        # Apply per-bar offset for variation (same as stereo mode)
        stem_len = len(stem_audio)
        if stem_len > 0:
            quarter = max(1, stem_len // 4)
            offset = (section_idx * 3) * quarter % stem_len
            if offset > 0:
                stem_repeated = stem_repeated[offset:] + stem_repeated[:offset]
                stem_repeated = stem_repeated[:target_ms]

        stem_repeated = stem_repeated.apply_gain(_stem_premix_gain_db(stem_name, stem_count))
        
        # Mix this stem in
        mixed = mixed.overlay(stem_repeated)
        logger.debug(f"    Mixed stem '{stem_name}' into section (duration: {len(stem_repeated)}ms)")

    return _apply_headroom_ceiling(mixed, target_peak_dbfs=-6.0)


def _build_render_spec_summary(timeline_sections: list[dict]) -> dict:
    """Build a production-safe inspectable summary of what the renderer actually did.

    This is persisted in the timeline_json so post-render audits can confirm:
    - How many distinct stem sets were used (if this equals 1, sections sounded identical)
    - How many phrase splits were executed
    - Which hook stages were rendered
    - Total applied transition/event count
    - The actual render path used (stems / loop_variations / stereo_fallback)
    - unique_render_signature_count — definitive measure of audible variety
    - unique_phrase_signature_count — number of sections with distinct phrase splits

    Parameters
    ----------
    timeline_sections:
        List of section dicts as populated by ``_render_producer_arrangement``.

    Returns
    -------
    dict
        Compact summary suitable for logging and API exposure.
    """
    stem_sets: list[frozenset] = []
    phrase_split_count = 0
    hook_stages: list[str] = []
    transition_event_count = 0
    section_role_rows: list[dict] = []
    render_signatures: list[str] = []
    phrase_signatures: list[tuple] = []

    for section in timeline_sections:
        stems_used = frozenset(section.get("runtime_active_stems") or section.get("active_stem_roles") or [])
        stem_sets.append(stems_used)

        # Collect hard-truth render signature (what was ACTUALLY built).
        sig = str(section.get("actual_render_signature") or "")
        render_signatures.append(sig)

        if section.get("phrase_plan_used"):
            phrase_split_count += 1
            pp = section.get("phrase_plan") or {}
            first = tuple(sorted(pp.get("first_phrase_roles") or []))
            second = tuple(sorted(pp.get("second_phrase_roles") or []))
            phrase_signatures.append((first, second))

        hook_ev = section.get("hook_evolution")
        if isinstance(hook_ev, dict) and hook_ev.get("stage"):
            hook_stages.append(str(hook_ev["stage"]))

        transition_event_count += len(section.get("applied_events") or [])

        section_role_rows.append({
            "section_index": len(section_role_rows),
            "section_type": section.get("type", ""),
            "stems": sorted(stems_used),
            "actual_render_signature": sig,
            "phrase_split": bool(section.get("phrase_plan_used")),
            "hook_stage": (hook_ev or {}).get("stage") if isinstance(hook_ev, dict) else None,
            "first_phrase_roles": (section.get("phrase_plan") or {}).get("first_phrase_roles"),
            "second_phrase_roles": (section.get("phrase_plan") or {}).get("second_phrase_roles"),
            "boundary_event_count": len(section.get("boundary_events") or []),
        })

    # Count stem sets that appear more than once to flag identical-render syndrome.
    from collections import Counter
    stem_set_counts = Counter(stem_sets)
    distinct_count = len(stem_set_counts)
    most_common_entry = stem_set_counts.most_common(1)
    most_reused = most_common_entry[0][1] if most_common_entry else 0

    # --- unique_render_signature_count ---
    # Counts distinct actual_render_signature values — the most honest measure of audible
    # variety.  If this equals 1, every section produced identical audio regardless of planned
    # roles.  A value >= 2 proves different audio was actually assembled per section.
    unique_render_sigs = set(s for s in render_signatures if s)
    unique_render_signature_count = len(unique_render_sigs)

    # --- unique_phrase_signature_count ---
    # Number of distinct (first_roles, second_roles) phrase-split combinations used.
    unique_phrase_signature_count = len(set(phrase_signatures))

    # --- render_path_used ---
    # Determine the dominant render path across all sections.
    if render_signatures:
        if all(s.startswith("stem") for s in render_signatures if s):
            render_path_used = "stems"
        elif all(s.startswith("stereo") for s in render_signatures if s):
            render_path_used = "stereo_fallback"
        elif any(s.startswith("loop_variant") for s in render_signatures if s):
            render_path_used = "loop_variations"
        else:
            render_path_used = "mixed"
    else:
        render_path_used = "unknown"

    is_stereo_fallback = render_path_used == "stereo_fallback"

    return {
        "sections_count": len(timeline_sections),
        "distinct_stem_set_count": distinct_count,
        "most_reused_stem_set_count": most_reused,
        "phrase_split_count": phrase_split_count,
        "hook_stages": hook_stages,
        "transition_event_count": transition_event_count,
        "section_role_map": section_role_rows,
        # --- Phase 2 / Phase 6 hard-truth metrics ---
        "unique_render_signature_count": unique_render_signature_count,
        "unique_phrase_signature_count": unique_phrase_signature_count,
        "render_path_used": render_path_used,
        "is_stereo_fallback": is_stereo_fallback,
        "render_signatures": sorted(unique_render_sigs),
    }


def _render_producer_arrangement(
    loop_audio: AudioSegment,
    producer_arrangement: dict,
    bpm: float,
    stems: dict[str, AudioSegment] | None = None,
    loop_variations: dict[str, AudioSegment] | None = None,
) -> tuple[AudioSegment, str]:
    """
    Render audio using ProducerArrangement structure for professional-quality arrangements.
    
    This applies DRAMATIC processing to create distinct sections:
    - Intro: Low volume, filtered, fade in
    - Buildup: Gradual volume increase, building energy
    - Drop: FULL VOLUME, maximum impact
    - Breakdown: Quiet, sparse, filtered breakdown
    - Outro: Fade out, reduced energy
    
    When stems are available, uses real layer muting/enabling per section.
    When stems unavailable, falls back to DSP processing on full stereo loop.
    
    Args:
        loop_audio: Source loop audio (full stereo mix)
        producer_arrangement: Parsed ProducerArrangement dict
        bpm: Tempo in BPM
        stems: Optional dict of {"drums": AudioSegment, "bass": AudioSegment, ...}
    
    Returns:
        Tuple of (arranged_audio, timeline_json)
    """
    use_stems = bool(stems and len(stems) > 0)
    use_loop_variations = bool(loop_variations and len(loop_variations) > 0)
    logger.info(
        f"Rendering with ProducerArrangement structure "
        f"(loop_variations={'ENABLED' if use_loop_variations else 'DISABLED'}, "
        f"stems={'ENABLED' if use_stems else 'DISABLED - using stereo fallback'})"
    )
    
    if use_stems:
        logger.info(f"Available stems: {list(stems.keys())}")
        # Normalize stems to same duration
        from app.services.stem_loader import normalize_stem_durations, validate_stem_sync
        if not validate_stem_sync(stems, tolerance_ms=200):
            logger.warning("Stem sync validation failed, normalizing durations")
        stems = normalize_stem_durations(stems)
    
    sections = producer_arrangement.get("sections", [])
    tracks = producer_arrangement.get("tracks", [])
    transitions = producer_arrangement.get("transitions", [])
    energy_curve = producer_arrangement.get("energy_curve", [])
    total_bars = producer_arrangement.get("total_bars", 96)
    
    logger.info(
        f"ProducerArrangement: {len(sections)} sections, {len(tracks)} tracks, "
        f"{len(transitions)} transitions, {total_bars} total bars"
    )
    
    bar_duration_ms = int((60.0 / bpm) * 4.0 * 1000)
    arranged = AudioSegment.silent(duration=0)
    
    timeline_events = []
    timeline_sections = []
    producer_debug_report: list[dict] = []
    previous_section_context: dict | None = None
    previous_section_audio: AudioSegment | None = None
    
    for section_idx, section in enumerate(sections):
        section_name = section.get("name", f"Section {section_idx + 1}")
        section_type = _normalize_section_type(section.get("section_type") or section.get("type") or "verse")
        bar_start = int(section.get("bar_start", 0) or 0)
        section_bars = int(section.get("bars", 0) or 0)
        if section_bars <= 0:
            bar_end_value = section.get("bar_end")
            if bar_end_value is not None:
                section_bars = max(1, int(bar_end_value) - bar_start)
            else:
                section_bars = 8
        bar_end = bar_start + section_bars
        section_energy = float(section.get("energy_level", section.get("energy", 0.6)) or 0.6)
        
        section_ms = section_bars * bar_duration_ms
        
        # ==================================================================== 
        # BUILD SECTION AUDIO - USE STEMS IF AVAILABLE
        # ====================================================================
        
        section_loop_variant = str(section.get("loop_variant") or "").strip().lower()

        if use_stems:
            # STEM MODE: Mix only the stems specified in section instruments list
            from app.services.stem_loader import map_instruments_to_stems
            from app.services.section_identity_engine import SECTION_PROFILES, _FALLBACK_PROFILE as _SIE_FALLBACK

            section_instruments = section.get("instruments", [])
            enabled_stems = map_instruments_to_stems(section_instruments, stems)

            if not enabled_stems:
                # Fallback: exclude stems that correspond to forbidden roles for this section type
                # so that bridge/intro/breakdown never silently reactivate drums or bass.
                _sie_profile = SECTION_PROFILES.get(section_type, _SIE_FALLBACK)
                forbidden_stem_names = set(_sie_profile.forbidden_roles)
                fallback_stems = {k: v for k, v in stems.items() if k not in forbidden_stem_names}
                if fallback_stems:
                    logger.warning(
                        "STEM_FALLBACK section='%s' type=%s instruments=%s "
                        "no-match — using role-filtered fallback %s (excluded forbidden: %s)",
                        section_name, section_type, section_instruments,
                        sorted(fallback_stems.keys()),
                        sorted(forbidden_stem_names & set(stems.keys())),
                    )
                    enabled_stems = fallback_stems
                else:
                    # All stems are forbidden (e.g. source material is drums-only) — accept all
                    logger.warning(
                        "STEM_FALLBACK section='%s' type=%s instruments=%s "
                        "no-match and all stems are forbidden — using all stems as last resort",
                        section_name, section_type, section_instruments,
                    )
                    enabled_stems = stems

            logger.info(
                "STEM_SECTION_RENDER section='%s' type=%s requested=%s active=%s full_mix_active=%s",
                section_name,
                section_type,
                section_instruments,
                list(enabled_stems.keys()),
                "full_mix" in enabled_stems,
            )

            # ----------------------------------------------------------------
            # PHRASE SPLIT: if a phrase_plan exists, build each half from its
            # own stem set.  This creates real audible intra-section movement.
            # ----------------------------------------------------------------
            phrase_plan = section.get("phrase_plan") if isinstance(section.get("phrase_plan"), dict) else None
            if phrase_plan and section_bars > 4:
                split_bar = int(phrase_plan.get("split_bar", section_bars // 2) or (section_bars // 2))
                split_bar = max(1, min(section_bars - 1, split_bar))
                split_ms = split_bar * bar_duration_ms
                remaining_bars = section_bars - split_bar

                # First phrase stems
                first_roles = phrase_plan.get("first_phrase_roles") or section_instruments
                first_stems = map_instruments_to_stems(first_roles, stems) if first_roles else enabled_stems
                if not first_stems:
                    first_stems = enabled_stems

                # Second phrase stems
                second_roles = phrase_plan.get("second_phrase_roles") or section_instruments
                second_stems = map_instruments_to_stems(second_roles, stems) if second_roles else enabled_stems
                if not second_stems:
                    second_stems = enabled_stems

                first_audio = _build_section_audio_from_stems(
                    stems=first_stems,
                    section_bars=split_bar,
                    bar_duration_ms=bar_duration_ms,
                    section_idx=section_idx,
                )[:split_ms]

                second_audio = _build_section_audio_from_stems(
                    stems=second_stems,
                    section_bars=remaining_bars,
                    bar_duration_ms=bar_duration_ms,
                    section_idx=section_idx + _PHRASE_SPLIT_SECTION_IDX_OFFSET,
                )[:remaining_bars * bar_duration_ms]

                section_audio = (first_audio + second_audio)[:section_ms]
                # Track both phrase role sets for diagnostics.
                active_role_snapshot = list(dict.fromkeys(list(first_roles) + list(second_roles)))
                # Render signature captures both phrase halves so phrase-split sections
                # with different role pairs produce distinct signatures.
                actual_render_signature = (
                    f"stem_phrase:{','.join(sorted(first_stems.keys()))}"
                    f"|{','.join(sorted(second_stems.keys()))}"
                )
                logger.info(
                    "PHRASE_SPLIT section='%s' split_bar=%d first=%s second=%s desc='%s'",
                    section_name, split_bar, first_roles, second_roles,
                    phrase_plan.get("description", ""),
                )
            else:
                section_audio = _build_section_audio_from_stems(
                    stems=enabled_stems,
                    section_bars=section_bars,
                    bar_duration_ms=bar_duration_ms,
                    section_idx=section_idx,
                )[:section_ms]
                active_role_snapshot = list(enabled_stems.keys())
                actual_render_signature = f"stem:{','.join(sorted(enabled_stems.keys()))}"

        elif use_loop_variations and section_loop_variant in (loop_variations or {}):
            variation_source = (loop_variations or {})[section_loop_variant]
            section_audio = _repeat_to_duration(variation_source, section_ms)
            
            # Apply per-instance randomization to prevent repetitive sound
            # Each time the same variant is used, apply subtle DSP variations
            import hashlib
            instance_seed = int(hashlib.md5(f"{section_name}_{section_idx}_{bar_start}".encode()).hexdigest()[:8], 16)
            variation_intensity = (instance_seed % 100) / 100.0  # 0.0-1.0
            
            # Subtle EQ variation (±2dB on different frequency bands)
            eq_shift = -2 + (variation_intensity * 4)  # -2dB to +2dB
            if instance_seed % 3 == 0:
                section_audio = section_audio.low_pass_filter(8000) + eq_shift
            elif instance_seed % 3 == 1:
                section_audio = section_audio.high_pass_filter(120) + eq_shift
            else:
                section_audio = section_audio + eq_shift
            
            # Apply subtle stereo width variation for non-intro sections
            if section_type not in {"intro", "outro"}:
                if instance_seed % 4 == 0:
                    # Slightly wider
                    left = section_audio.split_to_mono()[0] + 1
                    right = section_audio.split_to_mono()[1] + 1
                    section_audio = AudioSegment.from_mono_audiosegments(left, right)
                elif instance_seed % 4 == 2:
                    # Slightly narrower (more mono)
                    section_audio = section_audio - 1
            
            logger.info(
                "  Section '%s' using loop variant '%s' with instance variation (seed=%d, intensity=%.2f)",
                section_name,
                section_loop_variant,
                instance_seed,
                variation_intensity,
            )
            active_role_snapshot = list(section.get("instruments") or section.get("active_stem_roles") or [])
            actual_render_signature = f"loop_variant:{section_loop_variant}:{section_type}"
        else:
            # STEREO FALLBACK MODE: Use full loop with DSP variation.
            # Apply phrase variation even here so the two halves of a section
            # receive audibly different DSP treatment rather than a flat repeat.
            phrase_plan = section.get("phrase_plan") if isinstance(section.get("phrase_plan"), dict) else None
            if phrase_plan and section_bars > 4:
                split_bar = int(phrase_plan.get("split_bar", section_bars // 2) or (section_bars // 2))
                split_bar = max(1, min(section_bars - 1, split_bar))
                split_ms = split_bar * bar_duration_ms
                remaining_bars = section_bars - split_bar

                # First half: more filtered/restrained
                first_audio = _build_varied_section_audio(
                    loop_audio=loop_audio,
                    section_bars=split_bar,
                    bar_duration_ms=bar_duration_ms,
                    section_idx=section_idx,
                    section_type=section_type,
                )[:split_ms]
                first_audio = first_audio.low_pass_filter(3200) - 2

                # Second half: full DSP path with an offset index so the two halves
                # start from different loop positions and receive different per-bar processing
                second_audio = _build_varied_section_audio(
                    loop_audio=loop_audio,
                    section_bars=remaining_bars,
                    bar_duration_ms=bar_duration_ms,
                    section_idx=section_idx + _PHRASE_SPLIT_SECTION_IDX_OFFSET,
                    section_type=section_type,
                )[:remaining_bars * bar_duration_ms]

                section_audio = (first_audio + second_audio)[:section_ms]
                actual_render_signature = f"stereo_phrase:{section_type}:{split_bar}"
                logger.info(
                    "STEREO_PHRASE_SPLIT section='%s' split_bar=%d desc='%s'",
                    section_name, split_bar, phrase_plan.get("description", ""),
                )
            else:
                section_audio = _build_varied_section_audio(
                    loop_audio=loop_audio,
                    section_bars=section_bars,
                    bar_duration_ms=bar_duration_ms,
                    section_idx=section_idx,
                    section_type=section_type,
                )[:section_ms]
                actual_render_signature = f"stereo_fallback:{section_type}"
            active_role_snapshot = list(section.get("instruments") or section.get("active_stem_roles") or [])

        logger.info(
            f"Processing section [{section_idx}] {section_name}: type={section_type} (raw={section.get('section_type') or section.get('type')}), bars={section_bars}, energy={section_energy}"
        )
        
        # ====================================================================
        # DRAMATIC SECTION-SPECIFIC PROCESSING
        # ====================================================================
        
        pre_dsp_peak = float(section_audio.max_dBFS)
        if section_type == "intro":
            # INTRO: Gentle entry — moderate level reduction + subtle LPF so stems remain audible
            logger.info(f"Processing INTRO section: {section_name} (pre_dsp_peak={pre_dsp_peak:.1f} dBFS)")
            section_audio = section_audio - 4   # -4 dB: stems already stripped to melody+pads
            section_audio = section_audio.low_pass_filter(3500)  # Gentle air-cut, not mud
            section_audio = section_audio.fade_in(min(4000, section_ms // 2))
            logger.info(f"  INTRO post_dsp_peak={float(section_audio.max_dBFS):.1f} dBFS")
            
        elif section_type in {"buildup", "build_up", "build"}:
            # BUILDUP: Gradual volume increase, building tension
            logger.info(f"Processing BUILDUP section: {section_name}")
            # Create dramatic buildup by gradually increasing volume
            buildup_segments = []
            num_segments = 4
            segment_length = len(section_audio) // num_segments
            
            for i in range(num_segments):
                start_pos = i * segment_length
                end_pos = start_pos + segment_length if i < num_segments - 1 else len(section_audio)
                segment = section_audio[start_pos:end_pos]
                
                # Progressive volume boost
                boost = -8 + (i * 4)  # Goes from -8dB to +4dB
                segment = segment + boost
                
                # Apply high-pass filter that opens up as build progresses
                cutoff_freq = 200 + (i * 150)  # 200Hz -> 650Hz
                segment = segment.high_pass_filter(cutoff_freq)
                
                buildup_segments.append(segment)
            
            section_audio = sum(buildup_segments)
            
        elif section_type in {"drop", "hook", "chorus"}:
            # HOOK: Full energy, headroom-safe boost
            logger.info(f"Processing HOOK section: {section_name} (pre_dsp_peak={pre_dsp_peak:.1f} dBFS)")
            hook_evolution = section.get("hook_evolution") if isinstance(section.get("hook_evolution"), dict) else {}
            hook_stage = str(hook_evolution.get("stage") or "hook1").strip().lower()

            # Add brief pre-hook gap for impact (unless first section)
            if bar_start > 0 and section_idx > 0:
                silence_gap = int(bar_duration_ms * 0.25)  # Quarter-bar gap
                arranged += AudioSegment.silent(duration=silence_gap)
                logger.info(f"  Added pre-hook silence: {silence_gap}ms before {section_name}")

            # Boost to near ceiling — do NOT exceed -2 dBFS to avoid post-mastering clip.
            # Stems already at -6 dBFS; +4 dB = -2 dBFS, which is safe.
            boost_db = 3.0
            if hook_stage == "hook2":
                boost_db = 3.5
            elif hook_stage == "hook3":
                boost_db = 4.0
            section_audio = section_audio + boost_db
            # Guard rail: never let this escape -1 dBFS before it hits mastering
            section_audio = _apply_headroom_ceiling(section_audio, target_peak_dbfs=-1.5)
            logger.info(f"  HOOK post_dsp_peak={float(section_audio.max_dBFS):.1f} dBFS (stage={hook_stage})")

        elif section_type in {"pre_hook", "buildup", "build_up", "build"}:
            logger.info(f"Processing PRE_HOOK section: {section_name} (pre_dsp_peak={pre_dsp_peak:.1f} dBFS)")
            section_audio = section_audio.high_pass_filter(180) + 1
            section_audio = section_audio.low_pass_filter(5000)
            pre_hook_tail = min(len(section_audio), int(bar_duration_ms))
            if pre_hook_tail > 0:
                lead = section_audio[:-pre_hook_tail]
                tail = section_audio[-pre_hook_tail:].high_pass_filter(600) + 2
                section_audio = lead + tail
            logger.info(f"  PRE_HOOK post_dsp_peak={float(section_audio.max_dBFS):.1f} dBFS")
            
        elif section_type in {"breakdown", "bridge"}:
            # BREAKDOWN/BRIDGE: Stripped, ambient — keep stems intact, apply mild EQ + gain
            logger.info(f"Processing BREAKDOWN section: {section_name} (pre_dsp_peak={pre_dsp_peak:.1f} dBFS)")
            section_audio = section_audio - 6  # Moderate reduction (-6 dB)
            section_audio = section_audio.low_pass_filter(7000)  # Air reduction only, keep body
            section_audio = section_audio.high_pass_filter(60)   # Remove sub rumble
            section_audio = section_audio - 2
            # NOTE: do NOT chunk/slice the audio — that creates abrupt cuts in loops
            logger.info(f"  BREAKDOWN post_dsp_peak={float(section_audio.max_dBFS):.1f} dBFS")
                
        elif section_type == "outro":
            # OUTRO: Fade out, reduced energy
            logger.info(f"Processing OUTRO section: {section_name} (pre_dsp_peak={pre_dsp_peak:.1f} dBFS)")
            section_audio = section_audio - 4   # Slightly quieter (-4 dB)
            section_audio = section_audio.low_pass_filter(2600)
            section_audio = section_audio.fade_out(min(4000, section_ms // 2))
            logger.info(f"  OUTRO post_dsp_peak={float(section_audio.max_dBFS):.1f} dBFS")

        else:
            # VERSE/STANDARD: Energy-based gain. Range: -5 dB (low energy) to 0 dB (high energy)
            # Clamp to +0 to avoid verses ever adding headroom violations.
            energy_db = max(-5.0, min(0.0, -5.0 + (section_energy * 5.0)))
            logger.info(
                f"Processing {section_type.upper()} section: {section_name} "
                f"(pre_dsp_peak={pre_dsp_peak:.1f} dBFS energy={section_energy:.2f} gain={energy_db:+.1f}dB)"
            )
            section_audio = section_audio + energy_db
            logger.info(f"  {section_type.upper()} post_dsp_peak={float(section_audio.max_dBFS):.1f} dBFS")
        
        # ====================================================================
        # APPLY VARIATIONS (FILLS, ROLLS, DROPS)
        # ====================================================================
        section_applied_events: list[str] = []
        
        # stem_available drives DSP intensity in producer-move effects.
        # Derive from the actual stems argument (use_stems), not only from render
        # profile metadata — so that when real stems are passed the effects are
        # at full strength even when metadata is missing.
        stem_available = bool(use_stems)

        variations = section.get("variations", [])
        if not variations and isinstance(producer_arrangement.get("all_variations"), list):
            for variation in producer_arrangement.get("all_variations", []):
                target_section = variation.get("section", variation.get("section_index"))
                if isinstance(target_section, str) and target_section.isdigit():
                    target_section = int(target_section)
                if target_section in {section_idx, section_name, section_type}:
                    variations.append(variation)
        for variation in variations:
            var_bar_start = int(
                variation.get("bar_start", variation.get("start_bar", variation.get("bar", bar_start)))
                or bar_start
            )
            var_length = variation.get("bars") or variation.get("duration_bars") or variation.get("length_bars")
            if var_length is not None:
                var_bar_end = var_bar_start + int(var_length)
            else:
                var_bar_end = int(variation.get("bar_end", var_bar_start + 1) or (var_bar_start + 1))
            var_type = (variation.get("variation_type") or variation.get("type") or "none").strip().lower()
            var_intensity = variation.get("intensity", 0.5)
            
            # Calculate timing
            var_start_ms = (var_bar_start - bar_start) * bar_duration_ms
            var_end_ms = (var_bar_end - bar_start) * bar_duration_ms
            
            # Apply variation effects
            if var_end_ms > var_start_ms and var_start_ms >= 0 and var_end_ms <= len(section_audio):
                variation_segment = section_audio[var_start_ms:var_end_ms]
                
                if var_type in {"hats_roll", "fill", "hi_hat_stutter"}:
                    # Hat rolls and fills: volume boost
                    variation_segment = variation_segment + 4
                elif var_type in {"snare_fill", "drum_fill", "kick_fill"}:
                    # Snare fills: heavy boost
                    variation_segment = variation_segment + 5
                elif var_type in {"bass_drop", "drop", "bass_glide"}:
                    # Drops: add silence then huge impact
                    drop_gap = min(200, len(variation_segment) // 4)
                    variation_segment = AudioSegment.silent(duration=drop_gap) + variation_segment[drop_gap:] + 5
                elif var_type == "reverse":
                    # Reverse effect
                    variation_segment = variation_segment.reverse()
                elif var_type in _PRODUCER_MOVE_TYPES:
                    var_params = variation.get("params") if isinstance(variation.get("params"), dict) else {}
                    variation_segment = _apply_producer_move_effect(
                        segment=variation_segment,
                        move_type=var_type,
                        intensity=float(var_intensity or 0.7),
                        stem_available=stem_available,
                        bar_duration_ms=bar_duration_ms,
                        params=var_params,
                    )
                    section_applied_events.append(var_type)
                
                # Splice back in
                section_audio = section_audio[:var_start_ms] + variation_segment + section_audio[var_end_ms:]

        section_boundary_events = section.get("boundary_events") if isinstance(section.get("boundary_events"), list) else []
        for boundary_event in section_boundary_events:
            event_type = str(boundary_event.get("type") or "").strip().lower()
            event_bar = int(boundary_event.get("bar", bar_start) or bar_start)
            relative_bar = max(0, min(section_bars - 1, event_bar - bar_start))
            placement = str(boundary_event.get("placement") or "end_of_section").strip().lower()
            intensity = float(boundary_event.get("intensity", 0.7) or 0.7)
            params = boundary_event.get("params") if isinstance(boundary_event.get("params"), dict) else {}

            if placement == "on_downbeat":
                event_start_ms = 0
                event_end_ms = min(len(section_audio), bar_duration_ms)
            elif placement == "mid_section":
                event_start_ms = max(0, relative_bar * bar_duration_ms)
                event_end_ms = min(len(section_audio), event_start_ms + bar_duration_ms)
            else:
                event_end_ms = len(section_audio)
                event_start_ms = max(0, event_end_ms - bar_duration_ms)

            if event_end_ms <= event_start_ms:
                continue

            boundary_segment = section_audio[event_start_ms:event_end_ms]
            boundary_segment = _apply_producer_move_effect(
                segment=boundary_segment,
                move_type=event_type,
                intensity=intensity,
                stem_available=stem_available,
                bar_duration_ms=bar_duration_ms,
                params=params,
            )
            section_applied_events.append(event_type)
            section_audio = section_audio[:event_start_ms] + boundary_segment + section_audio[event_end_ms:]
        
        # ====================================================================
        # APPLY TRANSITIONS BETWEEN SECTIONS
        # ====================================================================
        
        transition_info = next(
            (
                t for t in transitions
                if t.get("bar_position") == bar_end
                or t.get("from_section") == section_idx
                or t.get("from_bar") == bar_end
            ),
            None,
        )
        if transition_info:
            trans_type = (transition_info.get("transition_type") or transition_info.get("type") or "none").strip().lower()
            trans_duration_bars = int(transition_info.get("duration_bars", transition_info.get("bars", 0)) or 0)
            trans_duration_ms = trans_duration_bars * bar_duration_ms
            
            if trans_duration_ms > 0 and trans_duration_ms <= len(section_audio):
                if trans_type in {"sweep", "filter_sweep", "crossfade"}:
                    # Filter sweep: fade out highs
                    sweep_start = max(0, len(section_audio) - trans_duration_ms)
                    pre_sweep = section_audio[:sweep_start]
                    sweep_part = section_audio[sweep_start:]
                    sweep_part = sweep_part.low_pass_filter(500).fade_out(len(sweep_part))
                    section_audio = pre_sweep + sweep_part
                    
                elif trans_type in {"riser", "build", "drum_fill"}:
                    # Riser: dramatic volume increase
                    riser_start = max(0, len(section_audio) - trans_duration_ms)
                    pre_riser = section_audio[:riser_start]
                    riser_part = section_audio[riser_start:]
                    # Create riser effect with volume automation
                    riser_part = riser_part + 6  # Controlled boost
                    riser_part = riser_part.high_pass_filter(300)  # Filter lows
                    section_audio = pre_riser + riser_part
                    
                elif trans_type == "impact" or trans_type == "hit":
                    # Impact: silence then hit
                    impact_gap = min(500, trans_duration_ms)
                    section_audio = section_audio[:-impact_gap] + AudioSegment.silent(duration=impact_gap)
                section_applied_events.append(f"transition:{trans_type}")

        section_audio = _stabilize_section_loudness(
            current=section_audio,
            previous=previous_section_audio,
            section_type=section_type,
            previous_section_type=(previous_section_context or {}).get("section_type"),
        )
        section_audio = _apply_headroom_ceiling(section_audio, target_peak_dbfs=-1.5)
        previous_section_audio = section_audio
        
        arranged += section_audio
        
        # Track section for timeline
        start_seconds = (bar_start * 4 * 60.0) / bpm
        end_seconds = (bar_end * 4 * 60.0) / bpm
        
        timeline_sections.append({
            "name": section_name,
            "type": section_type,
            "loop_variant": section_loop_variant or "verse",
            "bars": section_bars,
            "energy": section_energy,
            "active_stem_roles": section.get("active_stem_roles") or section.get("instruments") or [],
            "runtime_active_stems": active_role_snapshot,
            "applied_events": section_applied_events,
            "transition_out": section.get("transition_out") or (
                (transition_info.get("transition_type") or transition_info.get("type")) if transition_info else "none"
            ),
            "boundary_events": [
                {
                    "type": str(event.get("type") or ""),
                    "placement": event.get("placement"),
                    "boundary": event.get("boundary"),
                }
                for event in (section.get("boundary_events") or [])
            ],
            "hook_evolution": section.get("hook_evolution"),
            "start_bar": bar_start,
            "end_bar": bar_end,
            "start_seconds": round(start_seconds, 3),
            "end_seconds": round(end_seconds, 3),
            # Render-spec fields for Phase 6 debug visibility.
            "phrase_plan_used": bool(section.get("phrase_plan") and section_bars > 4),
            "phrase_plan": section.get("phrase_plan"),
            "choreography": section.get("choreography"),
            # Hard-truth render signature — encodes what was ACTUALLY used to build audio,
            # not just what was planned.  Distinct values prove audibly different output.
            "actual_render_signature": actual_render_signature,
        })

        difference_reasons: list[str] = []
        if previous_section_context is None:
            difference_reasons.append("First section establishes baseline arrangement layer state")
        else:
            if previous_section_context.get("section_type") != section_type:
                difference_reasons.append(
                    f"Section role changed: {previous_section_context.get('section_type')} -> {section_type}"
                )
            previous_roles = set(previous_section_context.get("active_roles") or [])
            current_roles = set(active_role_snapshot or [])
            added_roles = sorted(current_roles - previous_roles)
            removed_roles = sorted(previous_roles - current_roles)
            if added_roles:
                difference_reasons.append(f"Added stems: {', '.join(added_roles)}")
            if removed_roles:
                difference_reasons.append(f"Removed stems: {', '.join(removed_roles)}")
            energy_delta = section_energy - float(previous_section_context.get("energy", section_energy))
            if abs(energy_delta) >= 0.08:
                direction = "up" if energy_delta > 0 else "down"
                difference_reasons.append(f"Energy moved {direction} by {energy_delta:+.2f}")
            if section_applied_events:
                difference_reasons.append(
                    f"Inserted transition/move events: {', '.join(sorted(set(section_applied_events))[:6])}"
                )

        producer_debug_report.append(
            {
                "section_index": section_idx,
                "section_name": section_name,
                "section_type": section_type,
                "active_stems": active_role_snapshot,
                "actual_render_signature": actual_render_signature,
                "transition_events_inserted": sorted(set(section_applied_events)),
                "difference_from_previous": difference_reasons,
            }
        )

        previous_section_context = {
            "section_type": section_type,
            "active_roles": active_role_snapshot,
            "energy": section_energy,
        }
        
        timeline_events.append({
            "type": "section_start",
            "section_name": section_name,
            "section_type": section_type,
            "bar": bar_start,
            "time_seconds": round(start_seconds, 3),
            "energy": section_energy,
        })

    # Build render-spec summary (Phase 6 — production-safe debug inspection).
    render_spec_summary = _build_render_spec_summary(timeline_sections)
    logger.info(
        "RENDER_SPEC_SUMMARY sections=%d phrase_splits=%d distinct_stem_sets=%d "
        "unique_render_signatures=%d unique_phrase_signatures=%d render_path=%s "
        "is_stereo_fallback=%s hook_stages=%s transition_events=%d",
        render_spec_summary["sections_count"],
        render_spec_summary["phrase_split_count"],
        render_spec_summary["distinct_stem_set_count"],
        render_spec_summary["unique_render_signature_count"],
        render_spec_summary["unique_phrase_signature_count"],
        render_spec_summary["render_path_used"],
        render_spec_summary["is_stereo_fallback"],
        render_spec_summary["hook_stages"],
        render_spec_summary["transition_event_count"],
    )
    if render_spec_summary["is_stereo_fallback"]:
        logger.warning(
            "STEREO_FALLBACK_USED arrangement rendered without real stems — "
            "section differences are DSP-only, not stem-layer based. "
            "Provide stem-separated audio for true audible section contrast."
        )
    if render_spec_summary["unique_render_signature_count"] <= 1 and render_spec_summary["sections_count"] > 1:
        logger.warning(
            "unique_render_signature_count=%d for %d sections — "
            "all sections produced identical audio (density-only syndrome).",
            render_spec_summary["unique_render_signature_count"],
            render_spec_summary["sections_count"],
        )

    # Build timeline JSON
    timeline_json = json.dumps({
        "bpm": bpm,
        "render_profile": {
            "genre_profile": producer_arrangement.get("genre", "generic"),
            "producer_arrangement_used": True,
            "tracks_count": len(tracks),
            "transitions_count": len(transitions),
        },
        "sections": timeline_sections,
        "events": timeline_events,
        "section_boundaries": producer_arrangement.get("section_boundaries") or [],
        "producer_debug_report": producer_debug_report,
        "render_spec_summary": render_spec_summary,
        "metadata": {
            "total_bars": total_bars,
            "key": producer_arrangement.get("key", "C"),
            "drum_style": producer_arrangement.get("drum_style", "acoustic"),
            "melody_style": producer_arrangement.get("melody_style", "melodic"),
            "bass_style": producer_arrangement.get("bass_style", "synth"),
        },
    })
    
    logger.info(
        f"ProducerArrangement rendered: {len(arranged)}ms, {len(timeline_sections)} sections, "
        f"{len(timeline_events)} events"
    )
    
    return arranged, timeline_json


def _extract_correlation_id(arrangement_json: str | None) -> str | None:
    """Extract correlation id from arrangement JSON payload if present."""
    if not arrangement_json:
        return None
    try:
        payload = json.loads(arrangement_json)
        if isinstance(payload, dict):
            correlation_id = payload.get("correlation_id")
            if correlation_id:
                return str(correlation_id)
    except Exception:
        return None
    return None


def _build_render_plan_artifact(
    arrangement_id: int,
    bpm: float,
    target_seconds: int,
    timeline_json: str,
) -> dict:
    """Build a normalized render plan artifact for debug and acceptance checks."""
    timeline = {}
    try:
        timeline = json.loads(timeline_json) if timeline_json else {}
    except Exception:
        timeline = {}

    sections = timeline.get("sections") if isinstance(timeline, dict) else []
    events = timeline.get("events") if isinstance(timeline, dict) else []
    render_profile = timeline.get("render_profile") if isinstance(timeline, dict) else {}

    return {
        "arrangement_id": arrangement_id,
        "bpm": bpm,
        "target_seconds": target_seconds,
        "sections": sections or [],
        "events": events or [],
        "sections_count": len(sections or []),
        "events_count": len(events or []),
        "render_profile": render_profile or {},
    }


def _build_pre_render_plan(
    arrangement_id: int,
    bpm: float,
    target_seconds: int,
    producer_arrangement: dict | None,
    style_sections: list[dict] | None,
    genre_hint: str | None,
    stem_metadata: dict | None = None,
    loop_variation_manifest: dict | None = None,
) -> dict:
    """Build render_plan_json before rendering begins so all render paths consume the same plan."""

    def _build_default_structured_sections(total_bars: int) -> list[dict]:
        """Create a musically structured fallback when no style/producer sections exist."""
        total_bars = max(1, int(total_bars))
        templates = [
            ("Intro", "intro", 4, 0.35, ["melody"]),
            ("Buildup 1", "buildup", 4, 0.55, ["kick", "snare"]),
            ("Hook", "hook", 8, 0.90, ["kick", "snare", "bass", "melody"]),
            ("Verse", "verse", 8, 0.60, ["kick", "snare", "bass"]),
            ("Buildup 2", "buildup", 4, 0.70, ["kick", "snare", "bass"]),
            ("Hook 2", "hook", 8, 0.95, ["kick", "snare", "bass", "melody"]),
            ("Bridge", "bridge", 8, 0.50, ["bass", "melody"]),
            ("Buildup 3", "buildup", 4, 0.75, ["kick", "snare", "bass"]),
            ("Final Hook", "hook", 8, 1.0, ["kick", "snare", "bass", "melody"]),
            ("Outro", "outro", 4, 0.40, ["melody"]),
        ]

        sections: list[dict] = []
        remaining = total_bars
        current_bar = 0

        for name, section_type, preferred_bars, energy, instruments in templates:
            if remaining <= 0:
                break
            bars = min(preferred_bars, remaining)
            if bars <= 0:
                continue
            sections.append(
                {
                    "name": name,
                    "type": section_type,
                    "bar_start": current_bar,
                    "bars": bars,
                    "energy": float(energy),
                    "instruments": list(instruments),
                }
            )
            current_bar += bars
            remaining -= bars

        if remaining > 0:
            sections.append(
                {
                    "name": "Extension",
                    "type": "hook" if remaining >= 4 else "outro",
                    "bar_start": current_bar,
                    "bars": remaining,
                    "energy": 0.82 if remaining >= 4 else 0.45,
                    "instruments": ["kick", "snare", "bass", "melody"] if remaining >= 4 else ["kick", "bass"],
                }
            )

        return sections

    if producer_arrangement and producer_arrangement.get("sections"):
        sections = []
        events = []
        for section in producer_arrangement.get("sections", []):
            section_type = section.get("section_type") or section.get("type") or "verse"
            section_record = {
                "name": section.get("name") or section_type,
                "type": section_type,
                "bar_start": int(section.get("bar_start", 0) or 0),
                "bars": int(section.get("bars", 1) or 1),
                "energy": float(section.get("energy_level", section.get("energy", 0.6)) or 0.6),
                "instruments": section.get("instruments") or [],
            }
            sections.append(section_record)
            events.append(
                {
                    "type": "section_start",
                    "bar": section_record["bar_start"],
                    "description": f"{section_record['name']} starts",
                }
            )
            for variation in section.get("variations", []) or []:
                events.append(
                    {
                        "type": variation.get("variation_type") or variation.get("type") or "variation",
                        "bar": int(
                            variation.get("bar", variation.get("bar_start", section_record["bar_start"]))
                            or section_record["bar_start"]
                        ),
                        "description": variation.get("description") or "section variation",
                    }
                )

        total_bars = int(producer_arrangement.get("total_bars") or sum(int(s["bars"]) for s in sections))
        key = producer_arrangement.get("key", "C")
        tracks = producer_arrangement.get("tracks") or []
    else:
        sections = []
        source_sections = style_sections or []
        for section in source_sections:
            name = str(section.get("name") or "section")
            sections.append(
                {
                    "name": name,
                    "type": name.lower(),
                    "bar_start": int(section.get("start_bar", 0) or 0),
                    "bars": int(section.get("bars", 1) or 1),
                    "energy": float(section.get("energy", 0.6) or 0.6),
                    "instruments": ["kick", "snare", "bass"],
                }
            )

        if not sections:
            bar_duration_seconds = (60.0 / bpm) * 4.0
            total_bars = max(1, int(round(target_seconds / bar_duration_seconds)))
            sections = _build_default_structured_sections(total_bars)
        total_bars = int(sum(int(s.get("bars", 1) or 1) for s in sections))
        key = "C"
        tracks = []
        events = [
            {
                "type": "section_start",
                "bar": int(s.get("bar_start", 0) or 0),
                "description": f"{s.get('name', 'section')} starts",
            }
            for s in sections
        ]

    sections = _apply_stem_primary_section_states(sections, stem_metadata)
    sections = assign_section_variants(sections, loop_variation_manifest)
    transition_payload = build_transition_plan(
        sections=sections,
        energy_curve=producer_arrangement.get("energy_curve") if producer_arrangement else None,
        stem_metadata=stem_metadata,
    )
    transition_boundaries = transition_payload.get("boundaries") or []
    transition_events = transition_payload.get("events") or []
    events.extend(transition_events)

    render_plan = {
        "arrangement_id": arrangement_id,
        "bpm": bpm,
        "target_seconds": target_seconds,
        "key": key,
        "total_bars": total_bars,
        "sections": sections,
        "events": events,
        "section_boundaries": transition_boundaries,
        "transitions": transition_boundaries,
        "sections_count": len(sections),
        "events_count": len(events),
        "tracks": tracks,
        "loop_variations": loop_variation_manifest
        or {
            "active": False,
            "count": 0,
            "names": [],
            "files": {},
            "stems_used": False,
        },
        "render_profile": {
            "genre_profile": genre_hint or "generic",
            "producer_arrangement_used": bool(producer_arrangement),
            "loop_variations": loop_variation_manifest
            or {
                "active": False,
                "count": 0,
                "names": [],
                "files": {},
                "stems_used": False,
            },
            "stem_separation": stem_metadata or {
                "enabled": False,
                "succeeded": False,
                "reason": "not_available",
            },
            "stem_primary_mode": bool(stem_metadata and stem_metadata.get("enabled") and stem_metadata.get("succeeded")),
        },
    }

    return ProducerMovesEngine.inject(render_plan)


def _build_dev_fallback_plan(arrangement_id: int, bpm: float, target_seconds: int) -> dict:
    """Build a minimal fallback render plan used only when DEV_FALLBACK_LOOP_ONLY is enabled."""
    bar_duration_seconds = (60.0 / bpm) * 4.0
    bars = max(1, int(round(target_seconds / bar_duration_seconds)))
    return {
        "arrangement_id": arrangement_id,
        "bpm": bpm,
        "target_seconds": target_seconds,
        "key": "C",
        "total_bars": bars,
        "sections": [
            {
                "name": "Fallback Loop",
                "type": "verse",
                "bar_start": 0,
                "bars": bars,
                "energy": 0.55,
                "instruments": ["kick", "snare", "bass"],
            }
        ],
        "events": [
            {
                "type": "variation",
                "bar": idx,
                "description": "dev fallback variation",
            }
            for idx in range(0, bars, 4)
        ],
        "sections_count": 1,
        "events_count": len(list(range(0, bars, 4))),
        "tracks": [],
        "render_profile": {
            "genre_profile": "fallback_loop_only",
            "fallback_used": True,
        },
    }


def _decode_with_ffmpeg_cli(audio_bytes: bytes, input_format: str | None = None) -> AudioSegment:
    """Decode arbitrary audio bytes to WAV using ffmpeg CLI (no ffprobe dependency)."""
    converter = getattr(AudioSegment, "converter", None) or shutil.which("ffmpeg") or "ffmpeg"

    cmd = [converter, "-hide_banner", "-loglevel", "error"]
    if input_format:
        cmd.extend(["-f", input_format])
    cmd.extend(["-i", "pipe:0", "-f", "wav", "pipe:1"])

    try:
        result = subprocess.run(
            cmd,
            input=audio_bytes,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception as e:
        raise ValueError(f"ffmpeg process launch failed: {e}") from e

    if result.returncode != 0 or not result.stdout:
        stderr = (result.stderr or b"").decode("utf-8", errors="ignore")[:200]
        raise ValueError(f"ffmpeg decode failed (code={result.returncode}): {stderr or 'no stderr'}")

    try:
        return AudioSegment.from_wav(io.BytesIO(result.stdout))
    except Exception as e:
        raise ValueError(f"ffmpeg produced invalid WAV output: {e}") from e


def _load_audio_segment_from_wav_bytes(wav_bytes: bytes) -> AudioSegment:
    """Load WAV/audio bytes with multiple fallback strategies."""
    if not wav_bytes or len(wav_bytes) < 44:
        raise ValueError(f"Audio file too small: {len(wav_bytes)} bytes")

    errors = {}

    try:
        logger.info("Attempting audio load with format auto-detection...")
        return AudioSegment.from_file(io.BytesIO(wav_bytes))
    except Exception as e:
        errors['auto_detect'] = str(e)[:100]
        logger.warning("Auto-detection failed: %s. Trying explicit WAV format...", errors['auto_detect'])

    try:
        logger.info("Attempting audio load with explicit WAV format...")
        return AudioSegment.from_file(io.BytesIO(wav_bytes), format="wav")
    except Exception as e:
        errors['wav'] = str(e)[:100]
        logger.warning("Explicit WAV format failed: %s. Trying MP3 format...", errors['wav'])

    try:
        logger.info("Attempting audio load with MP3 format...")
        return AudioSegment.from_file(io.BytesIO(wav_bytes), format="mp3")
    except Exception as e:
        errors['mp3'] = str(e)[:100]
        logger.warning("MP3 format failed: %s", errors['mp3'])

    try:
        logger.info("Attempting audio load with OGG format...")
        return AudioSegment.from_file(io.BytesIO(wav_bytes), format="ogg")
    except Exception as e:
        errors['ogg'] = str(e)[:100]
        logger.warning("OGG format failed: %s", errors['ogg'])

    try:
        logger.info("Attempting ffmpeg CLI fallback decode...")
        sig = wav_bytes[:4]
        inferred_format = "mp3" if sig[:3] == b"ID3" else None
        return _decode_with_ffmpeg_cli(wav_bytes, input_format=inferred_format)
    except Exception as e:
        errors['ffmpeg_cli'] = str(e)[:160]
        logger.warning("ffmpeg CLI fallback failed: %s", errors['ffmpeg_cli'])

    error_details = (
        f"Auto-detect: {errors.get('auto_detect', 'N/A')} | "
        f"WAV: {errors.get('wav', 'N/A')} | "
        f"MP3: {errors.get('mp3', 'N/A')} | "
        f"OGG: {errors.get('ogg', 'N/A')} | "
        f"FFMPEG_CLI: {errors.get('ffmpeg_cli', 'N/A')}"
    )
    logger.error("Audio decoding failed after all strategies. Details: %s", error_details)

    sig = wav_bytes[:4].hex() if len(wav_bytes) >= 4 else "???"
    logger.error("Audio file signature (first 4 bytes): %s", sig)

    raise ValueError(f"Cannot decode audio file in any supported format. File signature: {sig}. Errors: {error_details}")


def run_arrangement_job(arrangement_id: int):
    """
    Background job to generate an arrangement.

    This runs asynchronously in a BackgroundTask and:
    1. Loads the Arrangement and Loop records
    2. Downloads the loop audio from S3 via presigned URL
    3. Builds the arrangement timeline and audio
    4. Uploads the output WAV to S3
    5. Updates the Arrangement with results
    6. Handles errors gracefully

    Args:
        arrangement_id: ID of the Arrangement record to process
    """
    db = SessionLocal()

    try:
        arrangement = (
            db.query(Arrangement)
            .filter(Arrangement.id == arrangement_id)
            .first()
        )

        if not arrangement:
            logger.error(f"Arrangement {arrangement_id} not found")
            return

        logger.info(f"Starting arrangement generation for ID {arrangement_id}")
        correlation_id = _extract_correlation_id(arrangement.arrangement_json) or str(uuid.uuid4())
        started_at = time.time()
        log_feature_event(
            logger,
            event="render_started",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            loop_id=arrangement.loop_id,
        )

        arrangement.status = "processing"
        arrangement.progress = 0.0
        arrangement.progress_message = "Starting generation..."
        db.commit()

        loop = db.query(Loop).filter(Loop.id == arrangement.loop_id).first()
        if not loop:
            raise ValueError(f"Loop {arrangement.loop_id} not found")
        if not loop.file_key:
            raise ValueError(f"Loop {arrangement.loop_id} missing file_key")

        if storage.use_s3:
            # Create presigned URL to fetch the loop audio
            input_url = storage.create_presigned_get_url(loop.file_key, expires_seconds=3600)

            # Download audio from S3
            with httpx.Client(timeout=60.0) as client:
                response = client.get(input_url)
                response.raise_for_status()
                input_bytes = response.content

            logger.info(
                "Downloaded audio from S3: key=%s, size=%d bytes, first 4 bytes (hex)=%s",
                loop.file_key,
                len(input_bytes),
                input_bytes[:4].hex() if len(input_bytes) >= 4 else "???"
            )

            # Load audio with multi-strategy decoder
            try:
                loop_audio = _load_audio_segment_from_wav_bytes(input_bytes)
            except ValueError as decode_error:
                logger.error("All decoding strategies failed for loop %s: %s", arrangement.loop_id, decode_error)
                raise ValueError(f"Cannot decode loop audio: {decode_error}") from decode_error
        else:
            # Local fallback for development
            filename = loop.file_key.split("/")[-1]
            local_path = storage.upload_dir / filename
            if not local_path.exists():
                raise FileNotFoundError(f"Loop file not found: {local_path}")
            with open(local_path, "rb") as local_audio_file:
                input_bytes = local_audio_file.read()
            logger.info(
                "Loaded audio from local file: path=%s, size=%d bytes",
                local_path,
                len(input_bytes)
            )
            loop_audio = _load_audio_segment_from_wav_bytes(input_bytes)

        # Render arrangement
        bpm = float(loop.bpm or loop.tempo or 120.0)
        target_seconds = int(arrangement.target_seconds or 180)
        style_sections = None
        seed = None
        style_params = None
        
        # V2: Parse style profile if using LLM-based styling
        if arrangement.ai_parsing_used and arrangement.style_profile_json:
            try:
                style_profile = _parse_style_profile(arrangement.style_profile_json)
                if style_profile:
                    style_params = style_profile.get("resolved_params")
                    if style_params is None:
                        style_params = {}
                    else:
                        style_params = dict(style_params)

                    intent = style_profile.get("intent") or {}
                    style_params["__archetype"] = intent.get("archetype")
                    style_params["__raw_input"] = intent.get("raw_input")

                    genre_hint = arrangement.genre or loop.genre
                    if genre_hint:
                        style_params["__genre_hint"] = genre_hint

                    seed = style_profile.get("seed")
                    style_sections = style_profile.get("sections")
                    logger.info(
                        "Using V2 style profile for arrangement %s (archetype: %s, confidence: %.2f)",
                        arrangement_id,
                        style_profile.get("intent", {}).get("archetype", "unknown"),
                        style_profile.get("intent", {}).get("confidence", 0.0),
                    )
            except Exception as style_error:
                logger.warning("Failed to load V2 style profile: %s", style_error)
                # Fall through to V1 parsing
        
        # V1: Parse style from arrangement_json (fallback)
        if settings.feature_style_engine and not style_sections:
            style_sections = _parse_style_sections(arrangement.arrangement_json)
            if not seed:
                seed = _parse_seed_from_json(arrangement.arrangement_json)
            if style_sections:
                logger.info("Applying V1 style section plan for arrangement %s", arrangement_id)
            if seed is not None:
                logger.info("Using seed %s for pattern generation in arrangement %s", seed, arrangement_id)

        # V3: Check for ProducerArrangement (most advanced)
        producer_arrangement = None
        if arrangement.producer_arrangement_json:
            producer_arrangement = _parse_producer_arrangement(arrangement.producer_arrangement_json)
            if producer_arrangement:
                logger.info(
                    "Using ProducerArrangement for arrangement %s (sections: %d, tracks: %d)",
                    arrangement_id,
                    len(producer_arrangement.get("sections", [])),
                    len(producer_arrangement.get("tracks", [])),
                )

        # ========================================================================
        # LOAD STEMS + GENERATE LOOP VARIATIONS (between stem separation and producer decisions)
        # ========================================================================
        stem_metadata = _parse_stem_metadata_from_loop(loop)
        loaded_stems: dict[str, AudioSegment] | None = None

        if stem_metadata and stem_metadata.get("enabled") and stem_metadata.get("succeeded"):
            logger.info("Attempting to load stem audio files for arrangement %s", arrangement_id)
            try:
                from app.services.stem_loader import StemLoadError, load_stems_from_metadata

                loaded_stems = load_stems_from_metadata(stem_metadata, timeout_seconds=60.0)

                logger.info(
                    "✅ STEMS LOADED: %s - using loop variation engine",
                    list(loaded_stems.keys()),
                )

                log_feature_event(
                    logger,
                    event="stems_loaded",
                    correlation_id=correlation_id,
                    arrangement_id=arrangement_id,
                    stem_count=len(loaded_stems),
                    stem_names=list(loaded_stems.keys()),
                )

            except StemLoadError as stem_error:
                logger.warning(
                    "⚠️ Stems could not be loaded for arrangement %s: %s. Falling back to stereo.",
                    arrangement_id,
                    stem_error,
                )
                loaded_stems = None
                log_feature_event(
                    logger,
                    event="stem_load_failed_fallback_to_stereo",
                    correlation_id=correlation_id,
                    arrangement_id=arrangement_id,
                    reason=str(stem_error),
                )

            except Exception as unexpected_error:
                logger.exception(
                    "❌ Unexpected error loading stems for arrangement %s. Falling back to stereo.",
                    arrangement_id,
                )
                loaded_stems = None
                log_feature_event(
                    logger,
                    event="stem_load_error_fallback_to_stereo",
                    correlation_id=correlation_id,
                    arrangement_id=arrangement_id,
                    error=str(unexpected_error),
                )
        else:
            logger.info(
                "Stems not available for arrangement %s - using stereo loop with fallback variations",
                arrangement_id,
            )
            log_feature_event(
                logger,
                event="stems_not_available_using_stereo",
                correlation_id=correlation_id,
                arrangement_id=arrangement_id,
                reason="stem_metadata missing or disabled",
            )

        loop_variations, loop_variation_manifest = generate_loop_variations(
            loop_audio=loop_audio,
            stems=loaded_stems,
            bpm=bpm,
        )

        # Build render plan AFTER variation generation so sections reference loop variants.
        render_plan = _build_pre_render_plan(
            arrangement_id=arrangement_id,
            bpm=bpm,
            target_seconds=target_seconds,
            producer_arrangement=producer_arrangement,
            style_sections=style_sections,
            genre_hint=(arrangement.genre or loop.genre),
            stem_metadata=stem_metadata,
            loop_variation_manifest=loop_variation_manifest,
        )
        arrangement.render_plan_json = json.dumps(render_plan)
        db.commit()

        log_feature_event(
            logger,
            event="render_plan_built",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            sections_count=render_plan.get("sections_count", 0),
            events_count=render_plan.get("events_count", 0),
            variation_count=(render_plan.get("loop_variations") or {}).get("count", 0),
        )

        _validate_render_plan_quality(render_plan)

        try:
            fd, temp_wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                render_result = render_from_plan(
                    render_plan_json=arrangement.render_plan_json,
                    audio_source=loop_audio,
                    output_path=temp_wav_path,
                    stems=loaded_stems,
                    loop_variations=loop_variations,
                )
                timeline_json = render_result["timeline_json"]
                postprocess = render_result.get("postprocess") or {}
                if postprocess:
                    render_plan.setdefault("render_profile", {})["postprocess"] = postprocess

                with open(temp_wav_path, "rb") as temp_audio_file:
                    output_bytes = temp_audio_file.read()
            finally:
                try:
                    Path(temp_wav_path).unlink(missing_ok=True)
                except PermissionError:
                    logger.warning("Could not remove temporary file: %s", temp_wav_path)
        except Exception as render_error:
            if settings.dev_fallback_loop_only and not settings.is_production:
                logger.warning(
                    "DEV_FALLBACK_LOOP_ONLY enabled - using fallback render plan for arrangement %s: %s",
                    arrangement_id,
                    render_error,
                )
                log_feature_event(
                    logger,
                    event="fallback_loop_only_used",
                    correlation_id=correlation_id,
                    arrangement_id=arrangement_id,
                    reason=str(render_error),
                )
                render_plan = _build_dev_fallback_plan(
                    arrangement_id=arrangement_id,
                    bpm=bpm,
                    target_seconds=target_seconds,
                )
                arrangement.render_plan_json = json.dumps(render_plan)
                db.commit()

                fd, temp_wav_path = tempfile.mkstemp(suffix=".wav")
                os.close(fd)
                try:
                    render_result = render_from_plan(
                        render_plan_json=arrangement.render_plan_json,
                        audio_source=loop_audio,
                        output_path=temp_wav_path,
                    )
                    timeline_json = render_result["timeline_json"]
                    postprocess = render_result.get("postprocess") or {}
                    if postprocess:
                        render_plan.setdefault("render_profile", {})["postprocess"] = postprocess
                    with open(temp_wav_path, "rb") as temp_audio_file:
                        output_bytes = temp_audio_file.read()
                finally:
                    try:
                        Path(temp_wav_path).unlink(missing_ok=True)
                    except PermissionError:
                        logger.warning("Could not remove temporary file: %s", temp_wav_path)
            else:
                raise

        output_key = f"arrangements/{arrangement_id}.wav"
        storage.upload_file(
            file_bytes=output_bytes,
            content_type="audio/wav",
            key=output_key,
        )
        log_feature_event(
            logger,
            event="storage_uploaded",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            storage_backend="s3" if storage.use_s3 else "local",
            output_key=output_key,
        )

        if not storage.use_s3:
            debug_plan_path = Path.cwd() / "uploads" / f"{arrangement_id}_render_plan.json"
            debug_plan_path.parent.mkdir(parents=True, exist_ok=True)
            debug_plan_path.write_text(json.dumps(render_plan, indent=2), encoding="utf-8")
            logger.info("Wrote local render plan artifact: %s", debug_plan_path)

        output_url = storage.create_presigned_get_url(
            output_key,
            expires_seconds=3600,
            download_filename=f"arrangement_{arrangement_id}.wav",
        )

        arrangement.status = "done"
        arrangement.progress = 100.0
        arrangement.progress_message = "Generation complete"
        arrangement.output_s3_key = output_key
        arrangement.output_url = output_url
        arrangement.arrangement_json = timeline_json
        arrangement.render_plan_json = json.dumps(render_plan)
        arrangement.error_message = None
        db.commit()

        # Extract render-spec summary from timeline JSON for the ARRANGEMENT_DONE log.
        try:
            _tl = json.loads(timeline_json) if timeline_json else {}
            _rss = _tl.get("render_spec_summary") or {}
        except Exception:
            _rss = {}

        logger.info(
            "ARRANGEMENT_DONE arrangement_id=%s loop_id=%s output_s3_key=%s "
            "render_path=%s unique_render_signatures=%s is_stereo_fallback=%s "
            "api_response_field=output_url",
            arrangement_id,
            arrangement.loop_id,
            output_key,
            _rss.get("render_path_used", "unknown"),
            _rss.get("unique_render_signature_count", "?"),
            _rss.get("is_stereo_fallback", "?"),
        )
        if _rss.get("is_stereo_fallback"):
            logger.warning(
                "SOURCE_MATERIAL_LIMITATION arrangement_id=%s — no stems available; "
                "sections differentiated by DSP only. Upload a loop with stem-separated files "
                "to unlock true layer-based section contrast.",
                arrangement_id,
            )
        log_feature_event(
            logger,
            event="render_finished",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            duration_sec=round(time.time() - started_at, 3),
            render_path=_rss.get("render_path_used", "unknown"),
            unique_render_signatures=_rss.get("unique_render_signature_count"),
            is_stereo_fallback=_rss.get("is_stereo_fallback"),
        )

    except Exception as e:
        logger.exception("Error generating arrangement %s", arrangement_id)

        try:
            arrangement.status = "failed"
            arrangement.error_message = str(e)
            db.commit()
        except Exception as db_error:
            logger.error(f"Failed to update arrangement error status: {str(db_error)}")

    finally:
        db.close()
