"""Genre-aware arrangement template pack.

Defines 20 deterministic arrangement templates (5 per genre) for:
- trap
- drill
- rnb
- rage

Each template specifies an ordered list of sections with their type and
length in bars.  Templates are validated on import so invalid entries are
caught immediately.

Section name normalisation
--------------------------
Equivalent section names are canonicalised before validation:

  PRE_CHORUS  →  pre_hook
  CHORUS      →  hook
  BREAK       →  breakdown

Public API
----------
GENRE_TEMPLATES          : dict[str, list[ArrangementTemplate]]
ALL_TEMPLATES            : list[ArrangementTemplate]
get_templates_for_genre  : (genre) -> list[ArrangementTemplate]
normalize_section_name   : (name) -> str
validate_template        : (template) -> list[str]   # returns warning strings
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

VALID_SECTION_TYPES: FrozenSet[str] = frozenset({
    "intro",
    "verse",
    "pre_hook",
    "hook",
    "bridge",
    "breakdown",
    "outro",
})

VALID_GENRES: FrozenSet[str] = frozenset({"trap", "drill", "rnb", "rage"})

# Minimum total bars before a template must be flagged short_form=True
MIN_TOTAL_BARS_DEFAULT = 24

# Section name aliases – keys are lower-cased before lookup
_SECTION_ALIASES: dict[str, str] = {
    "pre_chorus": "pre_hook",
    "chorus": "hook",
    "break": "breakdown",
}


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TemplateSection:
    """A single section within an arrangement template."""

    section_type: str   # canonical, lower-case
    length_bars: int


@dataclass(frozen=True)
class ArrangementTemplate:
    """Complete arrangement template for a specific genre."""

    id: str
    genre: str
    sections: tuple[TemplateSection, ...]
    # Selector hints
    vibe: tuple[str, ...]           # e.g. ("dark", "aggressive")
    energy: float                   # 0.0 – 1.0
    melodic_richness: float         # 0.0 – 1.0
    complexity_class: str           # "simple" | "medium" | "complex"
    short_form: bool = False        # True when total bars < MIN_TOTAL_BARS_DEFAULT
    no_hook_allowed: bool = False   # True when genre intentionally omits a hook

    @property
    def total_bars(self) -> int:
        return sum(s.length_bars for s in self.sections)


# ---------------------------------------------------------------------------
# Section name normalisation
# ---------------------------------------------------------------------------

def normalize_section_name(name: str) -> str:
    """Return the canonical section type for *name*.

    Applies lower-casing and alias substitution so that legacy names
    (PRE_CHORUS, CHORUS, BREAK) map to their canonical equivalents.

    Raises ValueError for names that are not recognisable after normalisation.
    """
    key = name.strip().lower()
    canonical = _SECTION_ALIASES.get(key, key)
    if canonical not in VALID_SECTION_TYPES:
        raise ValueError(
            f"Unknown section name {name!r}. "
            f"Valid types: {sorted(VALID_SECTION_TYPES)}. "
            f"Aliases accepted: {sorted(_SECTION_ALIASES)}"
        )
    return canonical


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_template(template: ArrangementTemplate) -> list[str]:
    """Validate *template* and return a list of warning strings.

    Returns an empty list when the template is fully valid.  Callers may
    treat a non-empty list as an error or simply log the warnings.
    """
    warnings: list[str] = []

    if not template.sections:
        warnings.append(f"[{template.id}] template has no sections")
        return warnings

    for idx, sec in enumerate(template.sections):
        if sec.section_type not in VALID_SECTION_TYPES:
            warnings.append(
                f"[{template.id}] section[{idx}] has invalid type {sec.section_type!r}"
            )
        if sec.length_bars <= 0:
            warnings.append(
                f"[{template.id}] section[{idx}] ({sec.section_type}) "
                f"has non-positive length_bars={sec.length_bars}"
            )

    has_hook = any(s.section_type == "hook" for s in template.sections)
    if not has_hook and not template.no_hook_allowed:
        warnings.append(
            f"[{template.id}] template has no 'hook' section "
            "(set no_hook_allowed=True to suppress)"
        )

    if template.total_bars < MIN_TOTAL_BARS_DEFAULT and not template.short_form:
        warnings.append(
            f"[{template.id}] total_bars={template.total_bars} is below the "
            f"minimum of {MIN_TOTAL_BARS_DEFAULT} "
            "(set short_form=True to suppress)"
        )

    return warnings


# ---------------------------------------------------------------------------
# Template definitions
# ---------------------------------------------------------------------------

def _sec(section_type: str, length_bars: int) -> TemplateSection:
    """Convenience constructor that normalises the section type name."""
    return TemplateSection(
        section_type=normalize_section_name(section_type),
        length_bars=length_bars,
    )


# ---- TRAP ------------------------------------------------------------------

_TRAP_TEMPLATES: list[ArrangementTemplate] = [
    # trap_A – Classic trap, balanced energy, medium complexity
    ArrangementTemplate(
        id="trap_A",
        genre="trap",
        sections=(
            _sec("intro", 8),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("balanced", "classic"),
        energy=0.70,
        melodic_richness=0.50,
        complexity_class="medium",
    ),
    # trap_B – Dark, extended hook, minimal verse transitions
    ArrangementTemplate(
        id="trap_B",
        genre="trap",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("hook", 16),
            _sec("verse", 8),
            _sec("hook", 16),
            _sec("outro", 4),
        ),
        vibe=("dark", "hook_heavy"),
        energy=0.80,
        melodic_richness=0.35,
        complexity_class="simple",
    ),
    # trap_C – Short-form, high-energy, lean structure
    ArrangementTemplate(
        id="trap_C",
        genre="trap",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("energetic", "punchy"),
        energy=0.85,
        melodic_richness=0.45,
        complexity_class="simple",
        short_form=True,
    ),
    # trap_D – Dark minimal with breakdown before final hook
    ArrangementTemplate(
        id="trap_D",
        genre="trap",
        sections=(
            _sec("intro", 8),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("breakdown", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("dark", "minimal", "moody"),
        energy=0.65,
        melodic_richness=0.30,
        complexity_class="medium",
    ),
    # trap_E – Full arrangement with bridge for richer storytelling
    ArrangementTemplate(
        id="trap_E",
        genre="trap",
        sections=(
            _sec("intro", 8),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("bridge", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("melodic", "structured"),
        energy=0.72,
        melodic_richness=0.65,
        complexity_class="complex",
    ),
]

# ---- DRILL -----------------------------------------------------------------

_DRILL_TEMPLATES: list[ArrangementTemplate] = [
    # drill_A – Classic UK drill pacing
    ArrangementTemplate(
        id="drill_A",
        genre="drill",
        sections=(
            _sec("intro", 8),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("aggressive", "syncopated"),
        energy=0.82,
        melodic_richness=0.40,
        complexity_class="medium",
    ),
    # drill_B – Extended verse dominance, minimal hook
    ArrangementTemplate(
        id="drill_B",
        genre="drill",
        sections=(
            _sec("intro", 8),
            _sec("verse", 16),
            _sec("hook", 8),
            _sec("verse", 16),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("lyric_focused", "streetwise"),
        energy=0.75,
        melodic_richness=0.30,
        complexity_class="simple",
    ),
    # drill_C – High energy, short form, back-to-back hooks
    ArrangementTemplate(
        id="drill_C",
        genre="drill",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("aggressive", "energetic"),
        energy=0.90,
        melodic_richness=0.25,
        complexity_class="simple",
        short_form=True,
    ),
    # drill_D – With breakdown before return hook
    ArrangementTemplate(
        id="drill_D",
        genre="drill",
        sections=(
            _sec("intro", 8),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("breakdown", 4),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("dark", "cinematic"),
        energy=0.78,
        melodic_richness=0.35,
        complexity_class="medium",
    ),
    # drill_E – Bridge variant for more dynamic range
    ArrangementTemplate(
        id="drill_E",
        genre="drill",
        sections=(
            _sec("intro", 8),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("bridge", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("cinematic", "dynamic"),
        energy=0.80,
        melodic_richness=0.45,
        complexity_class="complex",
    ),
]

# ---- RNB -------------------------------------------------------------------

_RNB_TEMPLATES: list[ArrangementTemplate] = [
    # rnb_A – Classic R&B with long atmospheric intro
    ArrangementTemplate(
        id="rnb_A",
        genre="rnb",
        sections=(
            _sec("intro", 16),
            _sec("verse", 16),
            _sec("pre_hook", 8),
            _sec("hook", 16),
            _sec("verse", 16),
            _sec("hook", 16),
            _sec("outro", 8),
        ),
        vibe=("smooth", "soulful"),
        energy=0.55,
        melodic_richness=0.80,
        complexity_class="complex",
    ),
    # rnb_B – With bridge for emotional peak
    ArrangementTemplate(
        id="rnb_B",
        genre="rnb",
        sections=(
            _sec("intro", 8),
            _sec("verse", 16),
            _sec("pre_hook", 8),
            _sec("hook", 16),
            _sec("verse", 16),
            _sec("bridge", 8),
            _sec("hook", 16),
            _sec("outro", 8),
        ),
        vibe=("emotional", "melodic"),
        energy=0.60,
        melodic_richness=0.85,
        complexity_class="complex",
    ),
    # rnb_C – Short-form, accessible R&B
    ArrangementTemplate(
        id="rnb_C",
        genre="rnb",
        sections=(
            _sec("intro", 8),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("chill", "accessible"),
        energy=0.50,
        melodic_richness=0.70,
        complexity_class="simple",
        short_form=True,
    ),
    # rnb_D – Breakdown centred, space for vocal ad-libs
    ArrangementTemplate(
        id="rnb_D",
        genre="rnb",
        sections=(
            _sec("intro", 8),
            _sec("verse", 16),
            _sec("hook", 16),
            _sec("breakdown", 8),
            _sec("hook", 16),
            _sec("outro", 8),
        ),
        vibe=("soulful", "dynamic"),
        energy=0.62,
        melodic_richness=0.75,
        complexity_class="medium",
    ),
    # rnb_E – Melodic extended sections with long bridge
    ArrangementTemplate(
        id="rnb_E",
        genre="rnb",
        sections=(
            _sec("intro", 16),
            _sec("verse", 16),
            _sec("pre_hook", 8),
            _sec("hook", 16),
            _sec("bridge", 16),
            _sec("hook", 16),
            _sec("outro", 8),
        ),
        vibe=("melodic", "epic", "soulful"),
        energy=0.65,
        melodic_richness=0.90,
        complexity_class="complex",
    ),
]

# ---- RAGE ------------------------------------------------------------------

_RAGE_TEMPLATES: list[ArrangementTemplate] = [
    # rage_A – High energy, lean and fast
    ArrangementTemplate(
        id="rage_A",
        genre="rage",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("energetic", "aggressive"),
        energy=0.90,
        melodic_richness=0.30,
        complexity_class="simple",
        short_form=True,
    ),
    # rage_B – Classic rage with tight breakdown
    ArrangementTemplate(
        id="rage_B",
        genre="rage",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("breakdown", 4),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("aggressive", "dark"),
        energy=0.88,
        melodic_richness=0.25,
        complexity_class="simple",
        short_form=True,
    ),
    # rage_C – Minimal ultra-short burst
    ArrangementTemplate(
        id="rage_C",
        genre="rage",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("minimal", "raw"),
        energy=0.92,
        melodic_richness=0.20,
        complexity_class="simple",
        short_form=True,
    ),
    # rage_D – Extended rage with pre-hook tension
    ArrangementTemplate(
        id="rage_D",
        genre="rage",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("pre_hook", 4),
            _sec("hook", 8),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("energetic", "structured"),
        energy=0.87,
        melodic_richness=0.35,
        complexity_class="medium",
    ),
    # rage_E – Rage with brief bridge for contrast
    ArrangementTemplate(
        id="rage_E",
        genre="rage",
        sections=(
            _sec("intro", 4),
            _sec("verse", 8),
            _sec("hook", 8),
            _sec("bridge", 4),
            _sec("hook", 8),
            _sec("outro", 4),
        ),
        vibe=("dynamic", "aggressive"),
        energy=0.85,
        melodic_richness=0.30,
        complexity_class="medium",
        short_form=True,
    ),
]

# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

GENRE_TEMPLATES: dict[str, list[ArrangementTemplate]] = {
    "trap": _TRAP_TEMPLATES,
    "drill": _DRILL_TEMPLATES,
    "rnb": _RNB_TEMPLATES,
    "rage": _RAGE_TEMPLATES,
}

ALL_TEMPLATES: list[ArrangementTemplate] = [
    t for templates in GENRE_TEMPLATES.values() for t in templates
]

# ---------------------------------------------------------------------------
# Validate all templates eagerly at import time
# ---------------------------------------------------------------------------

_import_warnings: list[str] = []
for _tmpl in ALL_TEMPLATES:
    _import_warnings.extend(validate_template(_tmpl))

if _import_warnings:
    import warnings as _warnings
    _warnings.warn(
        "genre_templates: validation issues found on import:\n"
        + "\n".join(_import_warnings),
        stacklevel=1,
    )

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def get_templates_for_genre(genre: str) -> list[ArrangementTemplate]:
    """Return all templates for *genre* (case-insensitive).

    Raises ``ValueError`` for unrecognised genres.
    """
    key = genre.strip().lower()
    if key not in GENRE_TEMPLATES:
        raise ValueError(
            f"Unknown genre {genre!r}. Valid genres: {sorted(GENRE_TEMPLATES)}"
        )
    return list(GENRE_TEMPLATES[key])
