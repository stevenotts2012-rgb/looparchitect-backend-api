"""Stem role classification using filename hints first and audio heuristics second."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re

from pydub import AudioSegment


STEM_ROLES = ("drums", "bass", "melody", "harmony", "fx", "full_mix")


@dataclass
class StemClassification:
    role: str
    confidence: float
    reason: str


_FILENAME_HINTS: dict[str, tuple[str, ...]] = {
    "drums": ("drum", "drums", "kick", "snare", "perc", "percussion", "hat", "hihat", "clap", "top"),
    "bass": ("bass", "sub", "808", "lowend"),
    "melody": ("melody", "lead", "arp", "pluck", "riff", "hook", "synth", "guitar", "piano"),
    "harmony": ("pad", "pads", "chord", "chords", "harmony", "keys", "strings", "rhodes", "organ"),
    "fx": ("fx", "sfx", "riser", "impact", "sweep", "transition", "ambience", "texture", "noise"),
}


def classify_stem(filename: str, audio: AudioSegment) -> StemClassification:
    lowered = re.sub(r"[^a-z0-9]+", " ", Path(filename).stem.lower())
    for role, hints in _FILENAME_HINTS.items():
        if any(hint in lowered for hint in hints):
            return StemClassification(role=role, confidence=0.98, reason=f"filename_hint:{role}")

    # Audio heuristics fallback
    low = audio.low_pass_filter(180)
    mid = audio.high_pass_filter(180).low_pass_filter(2500)
    high = audio.high_pass_filter(2500)

    low_rms = max(1, low.rms)
    mid_rms = max(1, mid.rms)
    high_rms = max(1, high.rms)
    total = max(1, audio.rms)

    low_ratio = low_rms / total
    mid_ratio = mid_rms / total
    high_ratio = high_rms / total

    # Bass-heavy, low-frequency concentrated
    if low_ratio > 0.82 and high_ratio < 0.45:
        return StemClassification(role="bass", confidence=0.72, reason="heuristic:low_frequency_dominant")

    # FX-heavy, high frequency dominant and often quieter
    if high_ratio > 0.78 and low_ratio < 0.42:
        return StemClassification(role="fx", confidence=0.68, reason="heuristic:high_frequency_texture")

    # Harmony tends to sit in sustained mids with less sub weight
    if mid_ratio > 0.86 and low_ratio < 0.62 and high_ratio < 0.7:
        return StemClassification(role="harmony", confidence=0.64, reason="heuristic:midrange_sustain")

    # Melody tends to be mid/high focused with more definition than pads
    if mid_ratio > 0.75 and high_ratio > 0.52:
        return StemClassification(role="melody", confidence=0.62, reason="heuristic:mid_high_focus")

    # Default fallback for full-range/unclassified material
    return StemClassification(role="full_mix", confidence=0.55, reason="heuristic:full_mix_fallback")
