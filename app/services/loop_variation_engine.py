"""Loop variation engine for generating musically distinct loop variants from stems."""

from __future__ import annotations

import hashlib
import logging
import random
from typing import Iterable

from pydub import AudioSegment

logger = logging.getLogger(__name__)


_VARIANT_NAMES = ("intro", "verse", "pre_hook", "hook", "bridge", "outro")


def _repeat_to_duration(audio: AudioSegment, target_ms: int) -> AudioSegment:
    if target_ms <= 0:
        return AudioSegment.silent(duration=0)
    if len(audio) == 0:
        return AudioSegment.silent(duration=target_ms)
    repeats = (target_ms // len(audio)) + 1
    return (audio * repeats)[:target_ms]


def _mix_selected_stems(
    stems: dict[str, AudioSegment],
    active_stems: Iterable[str],
    target_ms: int,
    gains: dict[str, float] | None = None,
) -> AudioSegment:
    gains = gains or {}
    mixed = AudioSegment.silent(duration=target_ms)

    for stem_name in active_stems:
        stem_audio = stems.get(stem_name)
        if stem_audio is None:
            continue
        stem_layer = _repeat_to_duration(stem_audio, target_ms)
        stem_layer = stem_layer + float(gains.get(stem_name, 0.0))
        mixed = mixed.overlay(stem_layer)

    return mixed


def _apply_silence_gaps(audio: AudioSegment, bar_duration_ms: int, gap_ms: int = 90) -> AudioSegment:
    if len(audio) == 0:
        return audio
    chunk_ms = max(1, bar_duration_ms)
    output = AudioSegment.silent(duration=0)
    bars = max(1, len(audio) // chunk_ms)
    for bar_idx in range(bars):
        start = bar_idx * chunk_ms
        end = min(len(audio), start + chunk_ms)
        bar = audio[start:end]
        if bar_idx % 2 == 1 and len(bar) > (gap_ms * 2):
            bar = bar[:gap_ms] + AudioSegment.silent(duration=gap_ms) + bar[(gap_ms * 2):]
        output += bar
    if len(output) < len(audio):
        output += audio[len(output):]
    return output[: len(audio)]


def _apply_transient_softening(audio: AudioSegment, slice_ms: int = 70, attack_cut_ms: int = 12) -> AudioSegment:
    if len(audio) == 0:
        return audio
    softened = AudioSegment.silent(duration=0)
    for pos in range(0, len(audio), max(1, slice_ms)):
        chunk = audio[pos : pos + slice_ms]
        if len(chunk) <= attack_cut_ms:
            softened += chunk - 2
            continue
        softened += (chunk[:attack_cut_ms] - 6) + chunk[attack_cut_ms:]
    return softened[: len(audio)]


def _apply_hat_density_variation(audio: AudioSegment, bar_duration_ms: int) -> AudioSegment:
    if len(audio) == 0:
        return audio
    top = audio.high_pass_filter(6000)
    step_ms = max(20, int(bar_duration_ms / 32))
    rolled = AudioSegment.silent(duration=0)
    for pos in range(0, len(top), step_ms):
        chunk = top[pos : pos + step_ms]
        if ((pos // step_ms) % 3) == 0:
            rolled += chunk + 5
        elif ((pos // step_ms) % 3) == 1:
            rolled += AudioSegment.silent(duration=len(chunk))
        else:
            rolled += chunk - 3
    return audio.overlay(rolled[: len(audio)], gain_during_overlay=-5)


def _progressive_drum_removal(base: AudioSegment, drums: AudioSegment | None, bar_duration_ms: int) -> AudioSegment:
    if drums is None or len(base) == 0:
        return base.fade_out(min(len(base), max(500, bar_duration_ms)))

    bars = max(1, len(base) // max(1, bar_duration_ms))
    drums_full = _repeat_to_duration(drums, len(base))
    output = AudioSegment.silent(duration=0)

    for bar_idx in range(bars):
        start = bar_idx * bar_duration_ms
        end = min(len(base), start + bar_duration_ms)
        seg = base[start:end]
        drums_seg = drums_full[start:end]

        if bar_idx >= bars - 1:
            output += seg - 6
            continue

        removal_ratio = bar_idx / max(1, bars - 1)
        drum_gain = -2 - (removal_ratio * 16)
        output += seg.overlay(drums_seg + drum_gain, gain_during_overlay=-3)

    if len(output) < len(base):
        output += base[len(output):]

    return output[: len(base)].fade_out(min(len(base), max(500, bar_duration_ms)))


def generate_sub_variants(
    base_variant: AudioSegment,
    variant_name: str,
    count: int = 3,
    bpm: float = 120.0,
) -> dict[str, AudioSegment]:
    """
    Generate N sub-variants from a base variant using deterministic DSP transformations.
    
    Each sub-variant applies:
    - Unique 3-band EQ curve (±4dB per band)
    - Optional stereo width variation
    - Optional brightness boost
    - Optional transient emphasis
    
    Args:
        base_variant: The base audio (e.g., "hook" variant)
        variant_name: Name like "hook", "verse" for sub-variant naming
        count: Number of sub-variants to generate (default 3)
        bpm: BPM for timing calculations
    
    Returns:
        Dict like {"hook_A": audio, "hook_B": audio, "hook_C": audio}
    """
    sub_variants = {}
    sub_names = ["A", "B", "C", "D", "E"][:count]
    
    for i, sub_name in enumerate(sub_names):
        # Deterministic seed based on variant name + index
        seed = int(hashlib.md5(f"{variant_name}_{i}".encode()).hexdigest()[:8], 16)
        random.seed(seed)
        
        # Start with base variant
        sub_audio = base_variant
        
        # Strategy 1: Unique 3-band EQ curve — wider range for more audible distinction
        low_gain = -8 + (random.random() * 16)    # -8dB to +8dB
        mid_gain = -8 + (random.random() * 16)
        high_gain = -8 + (random.random() * 16)
        
        # Apply EQ bands
        if len(sub_audio) > 0:
            # Low frequencies (0-250Hz)
            low_band = sub_audio.low_pass_filter(250)
            # Mid frequencies (250-2500Hz)
            mid_band = sub_audio.high_pass_filter(250).low_pass_filter(2500)
            # High frequencies (2500Hz+)
            high_band = sub_audio.high_pass_filter(2500)
            
            # Mix bands with gains
            sub_audio = (low_band + low_gain).overlay(mid_band + mid_gain).overlay(high_band + high_gain)
        
        # Strategy 2: Stereo width variation (30% chance)
        if random.random() < 0.3 and sub_audio.channels == 2:
            width_shift = -3 + (random.random() * 6)  # -3dB to +3dB
            try:
                channels = sub_audio.split_to_mono()
                if len(channels) == 2:
                    left = channels[0] + (width_shift / 2)
                    right = channels[1] - (width_shift / 2)
                    sub_audio = AudioSegment.from_mono_audiosegments(left, right)
            except Exception as e:
                logger.debug("Stereo width adjustment skipped: %s", e)
        
        # Strategy 3: Brightness variation (40% chance)
        if random.random() < 0.4 and len(sub_audio) > 0:
            brightness = -2 + (random.random() * 6)  # -2dB to +4dB
            bright_layer = sub_audio.high_pass_filter(4000) + brightness
            sub_audio = sub_audio.overlay(bright_layer, gain_during_overlay=-2)
        
        # Strategy 4: Subtle compression via gain staging (30% chance)
        if random.random() < 0.3:
            compress_gain = -1 + (random.random() * 3)  # -1dB to +2dB
            sub_audio = sub_audio + compress_gain
        
        # Strategy 5: Transient emphasis (25% chance)
        if random.random() < 0.25 and len(sub_audio) > 0:
            # Emphasize high frequencies briefly
            emphasis = sub_audio.high_pass_filter(8000) + 4
            sub_audio = sub_audio.overlay(emphasis, gain_during_overlay=-6)
        
        # Store sub-variant
        sub_key = f"{variant_name}_{sub_name}"
        sub_variants[sub_key] = sub_audio
        
        logger.debug(
            "Generated sub-variant %s: low=%+.1fdB mid=%+.1fdB high=%+.1fdB",
            sub_key, low_gain, mid_gain, high_gain
        )
    
    return sub_variants


def generate_loop_variations(
    loop_audio: AudioSegment,
    stems: dict[str, AudioSegment] | None,
    bpm: float,
) -> tuple[dict[str, AudioSegment], dict]:
    """Generate intro/verse/hook/bridge/outro variants from stem layers."""
    bar_duration_ms = int((60.0 / float(bpm or 120.0)) * 4.0 * 1000)
    target_ms = len(loop_audio)
    stems = stems or {}

    if target_ms <= 0:
        raise ValueError("loop audio is empty")

    drums = stems.get("drums")
    bass = stems.get("bass")
    melody = stems.get("melody")
    vocal = stems.get("vocal")

    # Intro: melody-focused, filtered, no drums
    intro = _mix_selected_stems(
        stems,
        active_stems=("melody", "vocal"),
        target_ms=target_ms,
        gains={"melody": -4, "vocal": -8},
    )
    if intro.rms == 0:
        intro = loop_audio.low_pass_filter(1200) - 10
    intro = intro.low_pass_filter(1800).fade_in(min(target_ms, int(bar_duration_ms * 2)))

    # Verse: reduced drums + simplified melody + lower energy + gaps
    verse = _mix_selected_stems(
        stems,
        active_stems=("drums", "bass", "melody"),
        target_ms=target_ms,
        gains={"drums": -6, "melody": -7, "bass": -1},
    )
    if verse.rms == 0:
        # No-stems fallback: noticeably stripped — heavier LPF and quieter so
        # it contrasts clearly with the hook's brightness.
        verse = (loop_audio - 6).low_pass_filter(4000)
    verse = _apply_transient_softening(verse)
    verse = _apply_silence_gaps(verse, bar_duration_ms=bar_duration_ms)

    # Pre-hook: tension-building — bass-forward, slightly gated, no sparkle.
    # Without stems, use HPF to remove sub-bass rumble and slight mid-forward
    # character so it feels tighter / more expectant than the verse.
    pre_hook = _mix_selected_stems(
        stems,
        active_stems=("bass", "drums", "percussion"),
        target_ms=target_ms,
        gains={"bass": 2, "drums": -1, "percussion": 0},
    )
    if pre_hook.rms == 0:
        # No-stems fallback: remove deep sub and cap highs so it sounds edgier
        # and more driving than the verse without being as full as the hook.
        pre_hook = loop_audio.high_pass_filter(130).low_pass_filter(5500) - 2
    pre_hook = _apply_silence_gaps(pre_hook, bar_duration_ms=bar_duration_ms, gap_ms=60)

    # Hook: full stems + louder drums + hi-hat density variation
    hook = _mix_selected_stems(
        stems,
        active_stems=("drums", "bass", "melody", "vocal"),
        target_ms=target_ms,
        gains={"drums": 4, "bass": 1, "melody": 2, "vocal": 1},
    )
    if hook.rms == 0:
        # No-stems fallback: brighter and louder — clear contrast from verse.
        hook = loop_audio + 4
        # Add a high-frequency presence layer so the hook is audibly brighter.
        presence = hook.high_pass_filter(2000)
        hook = hook.overlay(presence + 1, gain_during_overlay=-3)
    hook = _apply_hat_density_variation(hook, bar_duration_ms=bar_duration_ms)

    # Bridge: remove bass + filtered melody + ambient sparse feel
    bridge = _mix_selected_stems(
        stems,
        active_stems=("melody", "vocal"),
        target_ms=target_ms,
        gains={"melody": -3, "vocal": -6},
    )
    if bridge.rms == 0:
        bridge = loop_audio - 8
    bridge = bridge.low_pass_filter(1400).high_pass_filter(180)
    bridge = _apply_silence_gaps(bridge, bar_duration_ms=bar_duration_ms, gap_ms=140)

    # Outro: progressive removal of drums + melody fade
    outro_base = _mix_selected_stems(
        stems,
        active_stems=("drums", "bass", "melody"),
        target_ms=target_ms,
        gains={"drums": -2, "bass": -3, "melody": -4},
    )
    if outro_base.rms == 0:
        outro_base = loop_audio - 4
    outro = _progressive_drum_removal(outro_base, drums=drums, bar_duration_ms=bar_duration_ms)
    outro = outro.fade_out(min(target_ms, int(bar_duration_ms * 2)))

    # Base variants
    base_variants = {
        "intro": intro,
        "verse": verse,
        "pre_hook": pre_hook,
        "hook": hook,
        "bridge": bridge,
        "outro": outro,
    }

    # Generate sub-variants for repeatable section types.
    # Hook typically repeats 2-3 times, verse 2 times, pre_hook 2 times.
    hook_sub_variants = generate_sub_variants(hook, "hook", count=3, bpm=bpm)
    verse_sub_variants = generate_sub_variants(verse, "verse", count=2, bpm=bpm)
    pre_hook_sub_variants = generate_sub_variants(pre_hook, "pre_hook", count=2, bpm=bpm)

    # Optional: Generate bridge sub-variants if bridge might repeat
    bridge_sub_variants = generate_sub_variants(bridge, "bridge", count=2, bpm=bpm)

    # Combine base + sub-variants
    variants = {
        **base_variants,
        **hook_sub_variants,       # Adds hook_A, hook_B, hook_C
        **verse_sub_variants,      # Adds verse_A, verse_B
        **pre_hook_sub_variants,   # Adds pre_hook_A, pre_hook_B
        **bridge_sub_variants,     # Adds bridge_A, bridge_B
    }

    # Update manifest to include sub-variant names
    all_variant_names = (
        list(_VARIANT_NAMES) +  # intro, verse, pre_hook, hook, bridge, outro
        list(hook_sub_variants.keys()) +
        list(verse_sub_variants.keys()) +
        list(pre_hook_sub_variants.keys()) +
        list(bridge_sub_variants.keys())
    )

    manifest = {
        "active": True,
        "count": len(variants),
        "names": all_variant_names,
        "files": {name: f"loop_{name}.wav" for name in all_variant_names},
        "stems_used": bool(stems),
        "sub_variants_enabled": True,
    }

    logger.info(
        "LoopVariationEngine generated %d variants (including %d sub-variants): %s (stems_used=%s)",
        len(variants),
        len(hook_sub_variants) + len(verse_sub_variants) + len(pre_hook_sub_variants) + len(bridge_sub_variants),
        all_variant_names,
        manifest["stems_used"],
    )

    return variants, manifest


def assign_section_variants(sections: list[dict], manifest: dict | None) -> list[dict]:
    """
    Assign loop variant names/files to sections based on section type.
    
    For repeated section types (hook, verse, bridge), assigns different sub-variants
    to each instance to create musical evolution across the arrangement.
    
    Example:
        Hook #1 -> hook_A
        Hook #2 -> hook_B
        Hook #3 -> hook_C
    """
    if not manifest:
        return sections

    files = manifest.get("files") or {}
    available = set((manifest.get("names") or list(_VARIANT_NAMES)))
    sub_variants_enabled = manifest.get("sub_variants_enabled", False)

    def _base_variant_for_section(section_type: str) -> str:
        """Determine base variant type (hook, verse, pre_hook, etc.)"""
        section_type = (section_type or "verse").strip().lower()
        if section_type in {"intro"}:
            return "intro"
        if section_type in {"hook", "chorus", "drop"}:
            return "hook"
        if section_type in {"pre_hook", "buildup", "build_up", "build"}:
            return "pre_hook"
        if section_type in {"bridge", "breakdown", "break"}:
            return "bridge"
        if section_type in {"outro"}:
            return "outro"
        return "verse"

    # Track which sections use each base variant type
    section_type_counters = {}  # {"hook": 0, "verse": 0, ...}
    section_instance_tracker = {}  # Track instance numbers for reporting
    
    mapped: list[dict] = []
    for section_idx, section in enumerate(sections):
        copied = dict(section)
        section_type_raw = str(copied.get("type") or copied.get("section_type") or "verse")
        base_variant = _base_variant_for_section(section_type_raw)
        
        # Check if sub-variants available for this base type
        sub_variant_names = [name for name in available if name.startswith(f"{base_variant}_")]
        sub_variant_names = sorted(sub_variant_names)  # Sort for consistent rotation order
        
        if sub_variants_enabled and sub_variant_names:
            # Use sub-variants in rotation (hook_A, hook_B, hook_C, ...)
            counter = section_type_counters.get(base_variant, 0)
            variant_name = sub_variant_names[counter % len(sub_variant_names)]
            section_type_counters[base_variant] = counter + 1
            
            # Track instance number for this section type
            instance_num = counter + 1
            section_instance_tracker[section_idx] = instance_num
            
            logger.debug(
                "Assigned sub-variant '%s' to section #%d '%s' (type=%s, instance #%d)",
                variant_name, section_idx, copied.get("name", "?"), section_type_raw, instance_num
            )
        else:
            # No sub-variants, use base variant (intro, outro, or fallback)
            variant_name = base_variant if base_variant in available else "verse"
            section_instance_tracker[section_idx] = 1
        
        if variant_name not in available:
            variant_name = "verse" if "verse" in available else next(iter(available), "verse")
        
        copied["loop_variant"] = variant_name
        copied["loop_variant_file"] = files.get(variant_name, f"loop_{variant_name}.wav")
        copied["base_variant"] = base_variant
        copied["section_instance"] = section_instance_tracker.get(section_idx, 1)
        mapped.append(copied)
    
    # Log assignment summary
    variant_usage = {}
    for sec in mapped:
        v = sec["loop_variant"]
        variant_usage[v] = variant_usage.get(v, 0) + 1
    logger.info("Section variant assignment: %s", variant_usage)
    
    return mapped


def validate_variation_plan_usage(render_plan: dict) -> None:
    """
    Validate that the render plan uses sufficient variation.
    
    Checks:
    - At least 3 different variants used
    - Repeated section types use different sub-variants
    - No excessive variant reuse
    """
    sections = render_plan.get("sections") or []
    if not sections:
        raise ValueError("render_plan has no sections for variation validation")

    section_variants = [
        str(section.get("loop_variant") or section.get("loop_variant_file") or "").strip().lower()
        for section in sections
    ]
    unique_variants = {name for name in section_variants if name}

    if not unique_variants:
        missing_detail = [
            str(section.get("name") or section.get("type") or f"section[{i}]")
            for i, section in enumerate(sections)
            if not (section.get("loop_variant") or section.get("loop_variant_file"))
        ]
        raise ValueError(
            f"render_plan missing loop variation references on sections — "
            f"all {len(sections)} section(s) lack loop_variant/loop_variant_file. "
            f"Sections without assignment: {missing_detail[:10]}. "
            "Ensure attach_loops_to_sections() is called before validation."
        )

    if len(unique_variants) == 1:
        raise ValueError("render failed: every section uses the exact same audio loop")

    if len(unique_variants) < 3:
        raise ValueError(f"render failed: variation count < 3 (found {len(unique_variants)})")
    
    # Check for repeated section types using same variant (anti-pattern)
    base_variants_by_type = {}
    for section in sections:
        section_type = str(section.get("type") or section.get("section_type") or "").strip().lower()
        variant = str(section.get("loop_variant") or "").strip().lower()
        
        if section_type not in base_variants_by_type:
            base_variants_by_type[section_type] = []
        base_variants_by_type[section_type].append(variant)
    
    # Warn if repeated hooks/verses use identical variants
    for section_type, variants_used in base_variants_by_type.items():
        if len(variants_used) > 1 and len(set(variants_used)) == 1:
            logger.warning(
                "Section type '%s' repeats %d times but uses same variant '%s' - this may sound repetitive",
                section_type, len(variants_used), variants_used[0]
            )
