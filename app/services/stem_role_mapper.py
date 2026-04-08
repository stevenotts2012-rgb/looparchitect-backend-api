"""Canonical role mapper — maps filenames, ZIP contents, and AI-separated outputs
into the shared canonical stem roles defined in canonical_stem_manifest.

Features
--------
- Alias matching: "bd", "bassdrum", "kik" → kick; "hh", "hat" → hi_hat; etc.
- Confidence scoring with multi-hit bonus
- Source-type tagging
- Low-confidence fallback grouping (no silent stem loss)
- All stems are assigned a role; uncertain stems get fallback=True
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.services.canonical_stem_manifest import (
    CANONICAL_TO_BROAD,
    SOURCE_AI_SEPARATED,
    SOURCE_UPLOADED_STEM,
    SOURCE_ZIP_STEM,
)

# ---------------------------------------------------------------------------
# Alias table  (alias_string → canonical_role, base_confidence)
# Compound aliases are matched by requiring ALL tokens present in the name.
# Single-token aliases are matched exactly in the token set, or as a substring
# (with a -0.05 penalty).
# ---------------------------------------------------------------------------

_ALIAS_TABLE: list[tuple[str, str, float]] = [
    # ── kick ───────────────────────────────────────────────────────────────
    ("kick",           "kick",       0.95),
    ("kik",            "kick",       0.88),
    ("bd",             "kick",       0.90),
    ("bassdrum",       "kick",       0.92),
    ("bass drum",      "kick",       0.92),
    ("kick drum",      "kick",       0.95),
    # ── snare ──────────────────────────────────────────────────────────────
    ("snare",          "snare",      0.95),
    ("snr",            "snare",      0.88),
    ("sd",             "snare",      0.85),
    ("snare drum",     "snare",      0.95),
    # ── clap ───────────────────────────────────────────────────────────────
    ("clap",           "clap",       0.95),
    ("clps",           "clap",       0.88),
    # ── hi_hat ─────────────────────────────────────────────────────────────
    ("hihat",          "hi_hat",     0.95),
    ("hi hat",         "hi_hat",     0.95),
    ("hi-hat",         "hi_hat",     0.95),
    ("hat",            "hi_hat",     0.90),
    ("hh",             "hi_hat",     0.88),
    ("open hat",       "hi_hat",     0.92),
    ("closed hat",     "hi_hat",     0.92),
    # ── cymbals ────────────────────────────────────────────────────────────
    ("cymbal",         "cymbals",    0.92),
    ("cymbals",        "cymbals",    0.95),
    ("crash",          "cymbals",    0.88),
    ("ride",           "cymbals",    0.88),
    ("overhead",       "cymbals",    0.85),
    # ── percussion (non-kick/snare) ─────────────────────────────────────────
    ("perc",           "percussion", 0.90),
    ("percussion",     "percussion", 0.95),
    ("perc loop",      "percussion", 0.95),
    ("conga",          "percussion", 0.92),
    ("bongo",          "percussion", 0.90),
    ("shaker",         "percussion", 0.90),
    ("tambourine",     "percussion", 0.90),
    ("rim",            "percussion", 0.88),
    ("tom",            "percussion", 0.88),
    # ── drum fallback (broad) ──────────────────────────────────────────────
    ("drum",           "drums",      0.80),
    ("drums",          "drums",      0.82),
    ("drum loop",      "drums",      0.82),
    ("loop drums",     "drums",      0.82),
    # ── bass ───────────────────────────────────────────────────────────────
    ("bass",           "bass",       0.92),
    ("sub",            "bass",       0.85),
    ("sub bass",       "bass",       0.95),
    ("bass line",      "bass",       0.92),
    ("bass loop",      "bass",       0.92),
    ("low",            "bass",       0.80),
    ("lowend",         "bass",       0.85),
    ("low end",        "bass",       0.88),
    # ── 808 ────────────────────────────────────────────────────────────────
    ("808",            "808",        0.95),
    ("eight oh eight", "808",        0.92),
    # ── piano ──────────────────────────────────────────────────────────────
    ("piano",          "piano",      0.95),
    ("epiano",         "piano",      0.92),
    ("electric piano", "piano",      0.95),
    # ── keys ───────────────────────────────────────────────────────────────
    ("keys",           "keys",       0.92),
    ("synth key",      "keys",       0.92),
    ("keyboard",       "keys",       0.88),
    ("organ",          "keys",       0.88),
    ("rhodes",         "keys",       0.90),
    ("wurlitzer",      "keys",       0.88),
    ("key",            "keys",       0.80),
    # ── guitar ─────────────────────────────────────────────────────────────
    ("guitar",         "guitar",     0.95),
    ("gtr",            "guitar",     0.90),
    ("gtrs",           "guitar",     0.88),
    ("guitar lead",    "guitar",     0.95),
    ("guitar rhythm",  "guitar",     0.92),
    # ── pads ───────────────────────────────────────────────────────────────
    ("pad",            "pads",       0.92),
    ("pads",           "pads",       0.95),
    ("atmosphere",     "pads",       0.82),
    ("texture",        "pads",       0.80),
    # ── strings ────────────────────────────────────────────────────────────
    ("string",         "strings",    0.92),
    ("strings",        "strings",    0.95),
    ("violin",         "strings",    0.92),
    ("cello",          "strings",    0.92),
    ("orchestra",      "strings",    0.85),
    # ── synth ──────────────────────────────────────────────────────────────
    ("synth",          "synth",      0.92),
    ("synthesizer",    "synth",      0.90),
    ("lead synth",     "synth",      0.92),
    # ── arp ────────────────────────────────────────────────────────────────
    ("arp",            "arp",        0.95),
    ("arpegg",         "arp",        0.88),
    ("arpeggio",       "arp",        0.95),
    ("sequence",       "arp",        0.78),
    # ── melody / lead ───────────────────────────────────────────────────────
    ("melody",         "melody",     0.95),
    ("lead",           "melody",     0.88),
    ("hook",           "melody",     0.85),
    ("riff",           "melody",     0.85),
    ("pluck",          "melody",     0.85),
    ("bell",           "melody",     0.88),
    ("bell melody",    "melody",     0.95),
    ("flute",          "melody",     0.90),
    ("sax",            "melody",     0.88),
    ("trumpet",        "melody",     0.88),
    ("marimba",        "melody",     0.88),
    ("vibes",          "melody",     0.85),
    # ── fx ─────────────────────────────────────────────────────────────────
    ("fx",             "fx",         0.95),
    ("sfx",            "fx",         0.92),
    ("riser",          "fx",         0.90),
    ("riser fx",       "fx",         0.95),
    ("sweep",          "fx",         0.88),
    ("sweep fx",       "fx",         0.92),
    ("impact",         "fx",         0.85),
    ("downlifter",     "fx",         0.88),
    ("reverse",        "fx",         0.82),
    ("noise",          "fx",         0.80),
    ("transition",     "fx",         0.82),
    ("ambience",       "fx",         0.80),
    # ── vocal ───────────────────────────────────────────────────────────────
    ("vocal",          "vocal",      0.95),
    ("vocals",         "vocal",      0.95),
    ("vox",            "vocal",      0.92),
    ("vox chop",       "vocal",      0.92),
    ("voice",          "vocal",      0.90),
    ("chop",           "vocal",      0.80),
    ("adlib",          "vocal",      0.85),
    ("rap",            "vocal",      0.85),
    ("sing",           "vocal",      0.85),
    # ── harmony / chords ───────────────────────────────────────────────────
    ("harmony",        "harmony",    0.92),
    ("chord",          "harmony",    0.88),
    ("chords",         "harmony",    0.88),
    ("stab",           "harmony",    0.82),
    ("stabs",          "harmony",    0.82),
    # ── accent ─────────────────────────────────────────────────────────────
    ("accent",         "accent",     0.92),
    ("accent hit",     "accent",     0.95),
    ("one shot",       "accent",     0.85),
    ("oneshot",        "accent",     0.85),
    ("hit",            "accent",     0.78),
    # ── full_mix fallback ───────────────────────────────────────────────────
    ("full",           "full_mix",   0.80),
    ("full mix",       "full_mix",   0.92),
    ("mix",            "full_mix",   0.78),
    ("stereo",         "full_mix",   0.78),
    ("master",         "full_mix",   0.80),
    ("bounce",         "full_mix",   0.78),
    ("mixdown",        "full_mix",   0.82),
]

# AI-separated stem names (Demucs-style) → initial broad canonical role
_AI_STEM_MAP: dict[str, str] = {
    "drums":  "drums",
    "bass":   "bass",
    "vocals": "vocal",
    "vocal":  "vocal",
    "other":  "melody",   # second-stage classifier may refine further
    "melody": "melody",
    "piano":  "piano",
    "guitar": "guitar",
}

# Low-confidence fallback: role → safer grouped role
_LOW_CONF_FALLBACK: dict[str, str] = {
    "piano":    "melody",
    "guitar":   "melody",
    "synth":    "melody",
    "arp":      "melody",
    "strings":  "pads",
    "keys":     "harmony",
    "kick":     "drums",
    "snare":    "drums",
    "clap":     "drums",
    "hi_hat":   "drums",
    "cymbals":  "drums",
    "808":      "bass",
}

# Confidence thresholds
_CONFIDENCE_LOW: float = 0.55
_MAX_CONFIDENCE: float = 0.98
_MULTI_MATCH_BONUS: float = 0.03
_SUBSTR_PENALTY: float = 0.05


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RoleMapResult:
    """Result of mapping a filename or stem name to a canonical role."""

    canonical_role: str
    broad_role: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    fallback: bool = False
    parent_broad_stem: str | None = None
    source_type: str = SOURCE_UPLOADED_STEM


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _normalize(name: str) -> str:
    """Lowercase, strip non-alphanumeric runs → single spaces."""
    return re.sub(r"[^a-z0-9]+", " ", name.lower()).strip()


def _accumulate(
    scores: dict[str, float],
    kw_hits: dict[str, list[str]],
    role: str,
    conf: float,
    keyword: str,
) -> None:
    """Accumulate role scores and keyword hits.

    The score for a role is always the highest confidence seen so far.
    Keywords are accumulated independently so the multi-hit bonus can count
    how many distinct aliases fired for this role.
    """
    if role not in scores or conf > scores[role]:
        scores[role] = conf
    kw_hits.setdefault(role, [])
    if keyword not in kw_hits[role]:
        kw_hits[role].append(keyword)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def map_filename_to_role(
    filename: str,
    source_type: str = SOURCE_UPLOADED_STEM,
) -> RoleMapResult:
    """Map a stem filename to a canonical role.

    Parameters
    ----------
    filename:
        Original filename (basename or full path).
    source_type:
        One of SOURCE_UPLOADED_STEM, SOURCE_ZIP_STEM, SOURCE_AI_SEPARATED.

    Returns
    -------
    RoleMapResult — never raises; uncertain stems get fallback=True.
    """
    stem_name = Path(filename).stem
    norm = _normalize(stem_name)
    tokens = set(norm.split())

    scores: dict[str, float] = {}
    kw_hits: dict[str, list[str]] = {}

    for alias, role, base_conf in _ALIAS_TABLE:
        alias_norm = _normalize(alias)
        alias_tokens = alias_norm.split()

        if len(alias_tokens) > 1:
            # Compound alias: all sub-tokens must appear in the token set
            if all(t in tokens for t in alias_tokens):
                _accumulate(scores, kw_hits, role, base_conf, alias)
        else:
            t = alias_tokens[0]
            if t in tokens:
                _accumulate(scores, kw_hits, role, base_conf, alias)
            elif t in norm:
                # Substring match — lower confidence
                _accumulate(scores, kw_hits, role, base_conf - _SUBSTR_PENALTY, alias)

    if not scores:
        return RoleMapResult(
            canonical_role="full_mix",
            broad_role="full_mix",
            confidence=0.40,
            fallback=True,
            source_type=source_type,
        )

    # Multi-hit bonus (capped)
    for role in scores:
        extra = len(kw_hits[role]) - 1
        scores[role] = min(_MAX_CONFIDENCE, scores[role] + extra * _MULTI_MATCH_BONUS)

    best_role = max(scores, key=lambda r: scores[r])
    confidence = scores[best_role]

    # Low-confidence fallback: degrade to a safer grouped role
    fallback = False
    if confidence < _CONFIDENCE_LOW and best_role in _LOW_CONF_FALLBACK:
        best_role = _LOW_CONF_FALLBACK[best_role]
        confidence = max(confidence, 0.50)
        fallback = True

    broad = CANONICAL_TO_BROAD.get(best_role, best_role)
    parent = broad if broad != best_role else None

    return RoleMapResult(
        canonical_role=best_role,
        broad_role=broad,
        confidence=round(confidence, 4),
        matched_keywords=kw_hits.get(best_role, []),
        fallback=fallback,
        parent_broad_stem=parent,
        source_type=source_type,
    )


def map_ai_stem_to_role(
    stem_name: str,
    confidence: float = 0.72,
) -> RoleMapResult:
    """Map an AI-separated stem name (e.g. Demucs output) to a canonical role.

    AI separation produces broad names (drums, bass, vocals, other).
    These are mapped to broad canonical roles; a second-stage classifier
    can optionally refine them into sub-roles.

    Parameters
    ----------
    stem_name:
        Name of the AI-separated stem (e.g. "drums", "other").
    confidence:
        Base confidence from the separation stage (default 0.72).
    """
    norm = _normalize(stem_name)
    role = _AI_STEM_MAP.get(norm, "melody")
    broad = CANONICAL_TO_BROAD.get(role, role)
    parent = broad if broad != role else None

    return RoleMapResult(
        canonical_role=role,
        broad_role=broad,
        confidence=round(confidence, 4),
        fallback=False,
        parent_broad_stem=parent,
        source_type=SOURCE_AI_SEPARATED,
    )
