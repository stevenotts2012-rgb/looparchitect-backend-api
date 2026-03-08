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
from pydub import AudioSegment

from app.db import SessionLocal
from app.config import settings
from app.models.arrangement import Arrangement
from app.models.loop import Loop
from app.services.audit_logging import log_feature_event
from app.services.render_executor import render_from_plan
from app.services.storage import storage

logger = logging.getLogger(__name__)


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


def _repeat_to_duration(audio: AudioSegment, target_ms: int) -> AudioSegment:
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)
    repeats = (target_ms // len(audio)) + 1
    return (audio * repeats)[:target_ms]


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
            fade_factor = 1.0 - (bar_idx / max(1, section_bars))
            bar_audio = bar_audio * fade_factor  # Gradual fade
            if bar_idx > 0:
                bar_audio = bar_audio - (bar_idx * 1.5)  # Progressive volume reduction

        section_audio += bar_audio

    return section_audio


def _render_producer_arrangement(
    loop_audio: AudioSegment,
    producer_arrangement: dict,
    bpm: float,
) -> tuple[AudioSegment, str]:
    """
    Render audio using ProducerArrangement structure for professional-quality arrangements.
    
    This applies DRAMATIC processing to create distinct sections:
    - Intro: Low volume, filtered, fade in
    - Buildup: Gradual volume increase, building energy
    - Drop: FULL VOLUME, maximum impact
    - Breakdown: Quiet, sparse, filtered breakdown
    - Outro: Fade out, reduced energy
    
    Args:
        loop_audio: Source loop audio
        producer_arrangement: Parsed ProducerArrangement dict
        bpm: Tempo in BPM
    
    Returns:
        Tuple of (arranged_audio, timeline_json)
    """
    logger.info("Rendering with ProducerArrangement structure (professional mode)")
    
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
    
    for section_idx, section in enumerate(sections):
        section_name = section.get("name", f"Section {section_idx + 1}")
        section_type = (section.get("section_type") or section.get("type") or "verse").strip().lower()
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
        section_audio = _build_varied_section_audio(
            loop_audio=loop_audio,
            section_bars=section_bars,
            bar_duration_ms=bar_duration_ms,
            section_idx=section_idx,
            section_type=section_type,
        )[:section_ms]
        
        logger.info(
            f"Processing section [{section_idx}] {section_name}: type={section_type} (raw={section.get('section_type') or section.get('type')}), bars={section_bars}, energy={section_energy}"
        )
        
        # ====================================================================
        # DRAMATIC SECTION-SPECIFIC PROCESSING
        # ====================================================================
        
        if section_type == "intro":
            # INTRO: Very quiet start, heavy filtering, fade in
            logger.info(f"Processing INTRO section: {section_name}")
            # Log audio level BEFORE processing
            samples_before = section_audio.get_array_of_samples()
            rms_before = int((sum(s*s for s in samples_before) / len(samples_before)) ** 0.5) if samples_before else 0
            db_before = 20 * (rms_before / 32767) if rms_before > 0 else -999
            
            section_audio = section_audio - 12  # Much quieter (-12dB)
            section_audio = section_audio.low_pass_filter(800)  # Heavy low-pass filter
            section_audio = section_audio.fade_in(min(4000, section_ms // 2))  # Long fade in
            
            # Log audio level AFTER processing
            samples_after = section_audio.get_array_of_samples()
            rms_after = int((sum(s*s for s in samples_after) / len(samples_after)) ** 0.5) if samples_after else 0
            db_after = 20 * (rms_after / 32767) if rms_after > 0 else -999
            logger.info(f"  INTRO processing: BEFORE={db_before:+.1f}dB → AFTER={db_after:+.1f}dB (expected -12dB reduction)")
            
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
            # DROP/HOOK: MAXIMUM IMPACT - full volume, no filtering, hard hit
            logger.info(f"Processing DROP section: {section_name}")
            
            # Add dramatic silence before hook for impact (unless it's the very first section)
            if bar_start > 0 and section_idx > 0:
                # Create pre-hook silence - at least 1/2 bar for dramatic pause
                silence_gap = int(bar_duration_ms * 0.5)  # Half-bar silence
                
                # Check if previous section exists and if we should cut
                if len(arranged) > silence_gap:
                    # Remove end of previous section and insert silence
                    arranged = arranged[:-int(bar_duration_ms * 0.25)]  # Trim trailing quarter-bar
                    arranged += AudioSegment.silent(duration=silence_gap)
                    logger.info(f"  Added pre-hook silence: {silence_gap}ms before {section_name}")
            
            section_audio = section_audio + 8  # LOUD (+8dB from normal, even louder than before)
            # No filtering - full frequency range for maximum impact
            
            # Add slight brightness for punch on hook sections
            if section_type in {"hook", "chorus"}:
                # Overlay a bright signal for extra punch
                bright = section_audio.high_pass_filter(100) + 2
                section_audio = section_audio.overlay(bright, gain_during_overlay=-2)
            
        elif section_type in {"breakdown", "bridge", "break"}:
            # BREAKDOWN: Very quiet, sparse, ambient
            logger.info(f"Processing BREAKDOWN section: {section_name}")
            section_audio = section_audio - 10  # Much quieter (-10dB)
            section_audio = section_audio.low_pass_filter(1200)  # Filter out highs
            section_audio = section_audio.high_pass_filter(100)  # Filter out some lows
            
            # Make it sparse by adding gaps
            if len(section_audio) > 4000:
                # Split into chunks with gaps
                chunk_size = len(section_audio) // 4
                sparse_audio = AudioSegment.silent(duration=0)
                for i in range(4):
                    chunk_start = i * chunk_size
                    chunk_end = chunk_start + (chunk_size // 2)  # Only use half
                    sparse_audio += section_audio[chunk_start:chunk_end]
                    if i < 3:  # Add gap between chunks
                        sparse_audio += AudioSegment.silent(duration=chunk_size // 2)
                section_audio = sparse_audio
                
        elif section_type == "outro":
            # OUTRO: Fade out, reduced energy
            logger.info(f"Processing OUTRO section: {section_name}")
            section_audio = section_audio - 6  # Quieter (-6dB)
            section_audio = section_audio.fade_out(min(4000, section_ms // 2))  # Long fade out
            
        else:
            # VERSE/STANDARD: Apply energy-based volume (quieter baseline than drop)
            # This makes the verse feel different from the punch of the hook
            energy_db = -8 + (section_energy * 9)  # Range: -8dB (low) to +1dB (high energy verses only)
            logger.info(f"Processing {section_type.upper()} section: {section_name} (energy={section_energy:.2f}, volume={energy_db:+.1f}dB)")
            
            # Verses get a slightly thinner texture by HF reduction
            if section_type == "verse":
                section_audio = section_audio.low_pass_filter(7000)  # Slight HF reduction for warmth
            
            section_audio = section_audio + energy_db
        
        # ====================================================================
        # APPLY VARIATIONS (FILLS, ROLLS, DROPS)
        # ====================================================================
        
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
                    variation_segment = variation_segment + 8
                elif var_type in {"snare_fill", "drum_fill", "kick_fill"}:
                    # Snare fills: heavy boost
                    variation_segment = variation_segment + 10
                elif var_type in {"bass_drop", "drop", "bass_glide"}:
                    # Drops: add silence then huge impact
                    drop_gap = min(200, len(variation_segment) // 4)
                    variation_segment = AudioSegment.silent(duration=drop_gap) + variation_segment[drop_gap:] + 12
                elif var_type == "reverse":
                    # Reverse effect
                    variation_segment = variation_segment.reverse()
                
                # Splice back in
                section_audio = section_audio[:var_start_ms] + variation_segment + section_audio[var_end_ms:]
        
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
                    riser_part = riser_part + 12  # Huge volume boost
                    riser_part = riser_part.high_pass_filter(300)  # Filter lows
                    section_audio = pre_riser + riser_part
                    
                elif trans_type == "impact" or trans_type == "hit":
                    # Impact: silence then hit
                    impact_gap = min(500, trans_duration_ms)
                    section_audio = section_audio[:-impact_gap] + AudioSegment.silent(duration=impact_gap)
        
        arranged += section_audio
        
        # Track section for timeline
        start_seconds = (bar_start * 4 * 60.0) / bpm
        end_seconds = (bar_end * 4 * 60.0) / bpm
        
        timeline_sections.append({
            "name": section_name,
            "type": section_type,
            "bars": section_bars,
            "energy": section_energy,
            "start_bar": bar_start,
            "end_bar": bar_end,
            "start_seconds": round(start_seconds, 3),
            "end_seconds": round(end_seconds, 3),
        })
        
        timeline_events.append({
            "type": "section_start",
            "section_name": section_name,
            "section_type": section_type,
            "bar": bar_start,
            "time_seconds": round(start_seconds, 3),
            "energy": section_energy,
        })
    
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
) -> dict:
    """Build render_plan_json before rendering begins so all render paths consume the same plan."""

    def _build_default_structured_sections(total_bars: int) -> list[dict]:
        """Create a musically structured fallback when no style/producer sections exist."""
        total_bars = max(1, int(total_bars))
        templates = [
            ("Intro", "intro", 4, 0.35, ["kick", "bass"]),
            ("Verse", "verse", 8, 0.58, ["kick", "snare", "bass"]),
            ("Hook", "hook", 8, 0.86, ["kick", "snare", "bass", "melody"]),
            ("Verse 2", "verse", 8, 0.62, ["kick", "snare", "bass"]),
            ("Hook 2", "hook", 8, 0.90, ["kick", "snare", "bass", "melody"]),
            ("Bridge", "bridge", 4, 0.50, ["bass", "melody"]),
            ("Final Hook", "hook", 8, 0.95, ["kick", "snare", "bass", "melody"]),
            ("Outro", "outro", 4, 0.42, ["kick", "bass"]),
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

    return {
        "arrangement_id": arrangement_id,
        "bpm": bpm,
        "target_seconds": target_seconds,
        "key": key,
        "total_bars": total_bars,
        "sections": sections,
        "events": events,
        "sections_count": len(sections),
        "events_count": len(events),
        "tracks": tracks,
        "render_profile": {
            "genre_profile": genre_hint or "generic",
            "producer_arrangement_used": bool(producer_arrangement),
        },
    }


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

        # Build render plan BEFORE rendering so all paths consume render_plan_json.
        render_plan = _build_pre_render_plan(
            arrangement_id=arrangement_id,
            bpm=bpm,
            target_seconds=target_seconds,
            producer_arrangement=producer_arrangement,
            style_sections=style_sections,
            genre_hint=(arrangement.genre or loop.genre),
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
        )

        try:
            fd, temp_wav_path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            try:
                render_result = render_from_plan(
                    render_plan_json=arrangement.render_plan_json,
                    audio_source=loop_audio,
                    output_path=temp_wav_path,
                )
                timeline_json = render_result["timeline_json"]

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

        logger.info(f"Successfully completed arrangement {arrangement_id}")
        log_feature_event(
            logger,
            event="render_finished",
            correlation_id=correlation_id,
            arrangement_id=arrangement_id,
            duration_sec=round(time.time() - started_at, 3),
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
