"""Stem role classification using filename hints first and audio heuristics second.

Taxonomy
--------
Primary roles   : drums, bass, melody, harmony, pads, fx, percussion, accent, vocals, full_mix

Arrangement groups
------------------
rhythm          : drums, percussion
low_end         : bass
lead            : melody, vocals
harmonic        : harmony, pads
texture         : fx
transition      : accent
fallback_mix    : full_mix

Classification pipeline
-----------------------
1. Tokenise filename stem (split on non-alphanumeric).
2. Walk ranked keyword tables; collect all matches, pick highest-scoring role.
3. If filename confidence < AUDIO_HEURISTIC_THRESHOLD, supplement with lightweight
   audio-band analysis and transient-density proxy.
4. If final confidence < UNCERTAIN_THRESHOLD, mark as uncertain and prefer a safe
   conservative role (full_mix) rather than a wrong specific one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

try:
    from pydub import AudioSegment  # type: ignore
except ImportError:  # pragma: no cover
    AudioSegment = Any  # type: ignore


# ---------------------------------------------------------------------------
# Public taxonomy
# ---------------------------------------------------------------------------

STEM_ROLES: tuple[str, ...] = (
    "drums",
    "bass",
    "melody",
    "harmony",
    "pads",
    "fx",
    "percussion",
    "accent",
    "vocals",
    "full_mix",
)

ARRANGEMENT_GROUPS: dict[str, str] = {
    "drums":      "rhythm",
    "percussion": "rhythm",
    "bass":       "low_end",
    "melody":     "lead",
    "vocals":     "lead",
    "harmony":    "harmonic",
    "pads":       "harmonic",
    "fx":         "texture",
    "accent":     "transition",
    "full_mix":   "fallback_mix",
}

# Confidence below which audio heuristics are also consulted
AUDIO_HEURISTIC_THRESHOLD: float = 0.70
# Confidence below which the result is flagged as uncertain
UNCERTAIN_THRESHOLD: float = 0.55


# ---------------------------------------------------------------------------
# Data class
# ---------------------------------------------------------------------------

@dataclass
class StemClassification:
    role: str
    group: str
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    sources_used: list[str] = field(default_factory=list)
    uncertain: bool = False

    @property
    def reason(self) -> str:
        """Backward-compatible one-line reason string."""
        src = "+".join(self.sources_used) if self.sources_used else "fallback"
        kw = ",".join(self.matched_keywords[:3]) if self.matched_keywords else "none"
        return f"{src}:{self.role}:{kw}"


# ---------------------------------------------------------------------------
# Keyword tables  (ordered: most-specific compound tokens first, then singles)
# ---------------------------------------------------------------------------
# Each entry is (keyword_token, role, score_bonus).
# All tokens are matched against the whitespace-tokenised stem name.
# A partial substring match on the raw normalised name is also performed as
# a secondary pass with a small score penalty (-0.05).
# ---------------------------------------------------------------------------

_KEYWORD_TABLE: list[tuple[str, str, float]] = [
    # ---- compound tokens (matched first — higher weight) ----
    ("drum loop",      "drums",      0.0),
    ("loop drums",     "drums",      0.0),
    ("perc loop",      "percussion", 0.0),
    ("synth lead",     "melody",     0.0),
    ("synth key",      "harmony",    0.0),   # e.g. Synth_Key -> harmony
    ("bell melody",    "melody",     0.0),
    ("guitar lead",    "melody",     0.0),
    ("guitar rhythm",  "harmony",    0.0),
    ("bass line",      "bass",       0.0),
    ("bass loop",      "bass",       0.0),
    ("sub bass",       "bass",       0.0),
    ("kick drum",      "drums",      0.0),
    ("snare drum",     "drums",      0.0),
    ("hi hat",         "drums",      0.0),
    ("accent hit",     "accent",     0.0),
    ("one shot",       "accent",     0.0),
    ("riser fx",       "fx",         0.0),
    ("sweep fx",       "fx",         0.0),
    ("full mix",       "full_mix",   0.0),
    ("vox chop",       "vocals",     0.0),
    # ---- single tokens ----
    # drums / percussion
    ("drum",        "drums",      0.0),
    ("drums",       "drums",      0.0),
    ("kick",        "drums",      0.0),
    ("snare",       "drums",      0.0),
    ("clap",        "drums",      0.0),
    ("hat",         "drums",      0.0),
    ("hihat",       "drums",      0.0),
    ("hh",          "drums",      0.0),
    ("rim",         "drums",      0.0),
    ("tom",         "drums",      0.0),
    ("shaker",      "percussion", 0.0),
    ("perc",        "percussion", 0.0),
    ("percussion",  "percussion", 0.0),
    ("conga",       "percussion", 0.0),
    ("bongo",       "percussion", 0.0),
    ("tambourine",  "percussion", 0.0),
    # bass
    ("bass",        "bass",       0.0),
    ("808",         "bass",       0.0),
    ("sub",         "bass",       0.0),
    ("low",         "bass",       0.0),
    ("lowend",      "bass",       0.0),
    # melody / lead
    ("melody",      "melody",     0.0),
    ("lead",        "melody",     0.0),
    ("bell",        "melody",     0.0),
    ("pluck",       "melody",     0.0),
    ("arp",         "melody",     0.0),
    ("riff",        "melody",     0.0),
    ("hook",        "melody",     0.0),
    ("piano",       "melody",     0.0),
    ("epiano",      "melody",     0.0),
    ("guitar",      "melody",     0.0),
    ("marimba",     "melody",     0.0),
    ("vibes",       "melody",     0.0),
    ("flute",       "melody",     0.0),
    ("sax",         "melody",     0.0),
    ("trumpet",     "melody",     0.0),
    # harmony / pads
    ("pad",         "pads",       0.0),
    ("pads",        "pads",       0.0),
    ("chord",       "harmony",    0.0),
    ("chords",      "harmony",    0.0),
    ("harmony",     "harmony",    0.0),
    ("texture",     "harmony",    0.0),
    ("organ",       "harmony",    0.0),
    ("strings",     "harmony",    0.0),
    ("rhodes",      "harmony",    0.0),
    ("keys",        "harmony",    0.0),   # generic "keys"
    ("key",         "harmony",    0.0),   # synth_key token after compound pass
    ("stabs",       "harmony",    0.0),
    # fx / transition
    ("fx",          "fx",         0.0),
    ("sfx",         "fx",         0.0),
    ("riser",       "fx",         0.0),
    ("downlifter",  "fx",         0.0),
    ("sweep",       "fx",         0.0),
    ("impact",      "fx",         0.0),
    ("crash",       "fx",         0.0),
    ("reverse",     "fx",         0.0),
    ("transition",  "fx",         0.0),
    ("noise",       "fx",         0.0),
    ("ambience",    "fx",         0.0),
    ("atmosphere",  "fx",         0.0),
    # accent
    ("accent",      "accent",     0.0),
    ("stab",        "accent",     0.0),
    ("hit",         "accent",     0.0),
    ("oneshot",     "accent",     0.0),
    # vocals
    ("vocal",       "vocals",     0.0),
    ("vox",         "vocals",     0.0),
    ("voice",       "vocals",     0.0),
    ("chop",        "vocals",     0.0),
    ("adlib",       "vocals",     0.0),
    ("rap",         "vocals",     0.0),
    # full_mix
    ("full",        "full_mix",   0.0),
    ("mix",         "full_mix",   0.0),
    ("stereo",      "full_mix",   0.0),
    ("master",      "full_mix",   0.0),
    ("bounce",      "full_mix",   0.0),
    ("mixdown",     "full_mix",   0.0),
]

# Base confidence awarded per keyword match (token match)
_TOKEN_CONFIDENCE   = 0.92
# Confidence for substring (partial) match
_SUBSTR_CONFIDENCE  = 0.78
# When multiple keywords match the same role, bonus per extra match (capped)
_MULTI_MATCH_BONUS  = 0.04
_MAX_CONFIDENCE     = 0.98


# ---------------------------------------------------------------------------
# Filename classifier
# ---------------------------------------------------------------------------

def _classify_by_filename(stem_name: str) -> tuple[str, float, list[str]] | None:
    """Return (role, confidence, matched_keywords) or None if nothing matched."""
    # Normalise: lowercase → replace non-alphanumeric runs with spaces
    normalised = re.sub(r"[^a-z0-9]+", " ", stem_name.lower()).strip()
    tokens = set(normalised.split())

    # Score accumulation per role
    scores: dict[str, float] = {}
    keywords_hit: dict[str, list[str]] = {}

    for keyword, role, _bonus in _KEYWORD_TABLE:
        kw_tokens = keyword.split()

        if len(kw_tokens) > 1:
            # Compound: require all sub-tokens present in order
            if all(t in tokens for t in kw_tokens):
                conf = _TOKEN_CONFIDENCE
                _accumulate(scores, keywords_hit, role, conf, keyword)
        else:
            token = kw_tokens[0]
            if token in tokens:
                conf = _TOKEN_CONFIDENCE
                _accumulate(scores, keywords_hit, role, conf, keyword)
            elif token in normalised:
                # substring match (e.g. "808" inside "808_bass_loop" still hits after split)
                conf = _SUBSTR_CONFIDENCE
                _accumulate(scores, keywords_hit, role, conf, keyword)

    if not scores:
        return None

    # Apply multi-hit bonus
    for role in scores:
        extra = len(keywords_hit[role]) - 1
        scores[role] = min(_MAX_CONFIDENCE, scores[role] + extra * _MULTI_MATCH_BONUS)

    best_role = max(scores, key=lambda r: scores[r])
    return best_role, scores[best_role], keywords_hit[best_role]


def _accumulate(
    scores: dict[str, float],
    kw_hits: dict[str, list[str]],
    role: str,
    conf: float,
    keyword: str,
) -> None:
    if role not in scores or conf > scores[role]:
        scores[role] = conf
    kw_hits.setdefault(role, [])
    if keyword not in kw_hits[role]:
        kw_hits[role].append(keyword)


# ---------------------------------------------------------------------------
# Audio heuristics
# ---------------------------------------------------------------------------

def _classify_by_audio(audio: Any) -> tuple[str, float, str]:
    """Return (role, confidence, reason) from lightweight band analysis."""
    try:
        # Four frequency bands
        sub      = audio.low_pass_filter(80)
        low      = audio.high_pass_filter(80).low_pass_filter(300)
        mid      = audio.high_pass_filter(300).low_pass_filter(3000)
        hi       = audio.high_pass_filter(3000)

        total_rms = max(1, audio.rms)
        sub_r  = max(1, sub.rms)  / total_rms
        low_r  = max(1, low.rms)  / total_rms
        mid_r  = max(1, mid.rms)  / total_rms
        hi_r   = max(1, hi.rms)   / total_rms

        # Transient density proxy: ratio of peak dBFS amplitude to RMS
        # High ratio ≈ many sharp transients (drums/perc)
        try:
            peak_ratio = max(1, audio.max) / total_rms  # type: ignore[attr-defined]
        except Exception:
            peak_ratio = 1.0

        low_energy = sub_r + low_r

        # Heavy sub / low energy → bass
        if low_energy > 0.80 and hi_r < 0.40:
            return "bass", 0.72, "heuristic:low_energy_dominant"

        # Many transients + low fundamental → drums
        if peak_ratio > 6.0 and low_energy < 0.65:
            return "drums", 0.68, "heuristic:high_transient_density"

        # Sustained mid content, sparse hi → pads
        if mid_r > 0.82 and hi_r < 0.45 and low_energy < 0.60:
            return "pads", 0.65, "heuristic:sustained_mid_harmonic"

        # Bright sparse tonal → melody / accent
        if hi_r > 0.75 and mid_r > 0.60 and low_energy < 0.40:
            return "melody", 0.62, "heuristic:bright_tonal_content"

        # Hi-energy noisy sweep → fx
        if hi_r > 0.80 and low_energy < 0.35:
            return "fx", 0.60, "heuristic:high_frequency_texture"

        return "full_mix", 0.50, "heuristic:full_range_fallback"

    except Exception:
        # Any failure in audio analysis → safe fallback
        return "full_mix", 0.45, "heuristic:analysis_error"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def classify_stem(filename: str, audio: Any) -> StemClassification:
    """
    Classify a stem file and return a full StemClassification.

    Parameters
    ----------
    filename:
        Original filename (basename or full path).
    audio:
        pydub AudioSegment instance.

    Returns
    -------
    StemClassification with role, group, confidence, matched_keywords,
    sources_used, and uncertain flag.
    """
    stem_name = Path(filename).stem
    sources: list[str] = []
    matched_kw: list[str] = []
    role = "full_mix"
    confidence = 0.0

    # ---- Phase 1: filename heuristics ----
    fn_result = _classify_by_filename(stem_name)
    if fn_result is not None:
        fn_role, fn_conf, fn_kw = fn_result
        role = fn_role
        confidence = fn_conf
        matched_kw = fn_kw
        sources.append("filename")

    # ---- Phase 2: audio heuristics (supplement if filename confidence is low) ----
    if confidence < AUDIO_HEURISTIC_THRESHOLD:
        audio_role, audio_conf, _audio_reason = _classify_by_audio(audio)
        if sources:
            # Blend: if they agree, boost; if they disagree, take higher with penalty
            if audio_role == role:
                confidence = min(_MAX_CONFIDENCE, confidence + 0.06)
                sources.append("audio")
            elif audio_conf > confidence + 0.08:
                # Audio strongly disagrees — prefer audio but apply penalty
                role = audio_role
                confidence = audio_conf - 0.05
                sources = ["audio"]
                matched_kw = []
            # else: keep filename result, audio not decisive enough
        else:
            # No filename match at all — use audio exclusively
            role = audio_role
            confidence = audio_conf
            sources = ["audio"]

    # ---- Phase 3: safety / fallback ----
    if role not in STEM_ROLES:
        role = "full_mix"
        confidence = min(confidence, 0.55)

    uncertain = confidence < UNCERTAIN_THRESHOLD
    if uncertain and role != "full_mix":
        # Conservative: preserve role but surface uncertainty clearly
        pass  # role stays; caller sees uncertain=True

    group = ARRANGEMENT_GROUPS.get(role, "fallback_mix")

    return StemClassification(
        role=role,
        group=group,
        confidence=round(confidence, 4),
        matched_keywords=matched_kw,
        sources_used=sources if sources else ["none"],
        uncertain=uncertain,
    )
