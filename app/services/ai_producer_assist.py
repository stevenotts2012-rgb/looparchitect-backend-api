"""
AI Co-Producer Assist Layer — Phase 4.

Architecture: AI proposes → rules validate → engine executes → QA verifies.

This module provides:
    AIProducerSuggestion  — structured schema for AI suggestions
    AIProducerAssistService — generates suggestions and validates them against rules

Feature flags:
    AI_PRODUCER_ASSIST=true/false        (master switch)
    AI_STYLE_INTERPRETATION=true/false   (style-specific AI reasoning)

When the LLM is unavailable or produces invalid output the service falls
back gracefully and returns an empty suggestion with fallback_used=True.
No raw AI output ever drives rendering without rule validation.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants for plan quality enforcement
# ---------------------------------------------------------------------------

# Minimum Jaccard distance required between repeated sections of the same type.
_MIN_JACCARD_CONTRAST: float = 0.20

# Minimum novelty score (0.0–1.0) for a plan to be accepted; plans scoring below
# this threshold are considered too generic and trigger deterministic fallback.
_MIN_NOVELTY_SCORE: float = 0.30

# Phrases that indicate the AI is producing vague, non-actionable planning notes.
_VAGUE_PHRASES: frozenset[str] = frozenset([
    "add more energy",
    "make it bigger",
    "keep it the same but stronger",
    "more energy",
    "just like before",
    "same as before",
    "keep the same",
    "same but stronger",
    "make it louder",
    "just louder",
    "more intense",
    "similar to before",
    "repeat the same",
])


# ---------------------------------------------------------------------------
# Suggestion schema
# ---------------------------------------------------------------------------


@dataclass
class SuggestedSectionEntry:
    """A single section suggestion from the AI co-producer.

    All fields must be explicit — vague descriptions or missing contrast data
    will cause the plan to be rejected.
    """

    section_type: str           # "intro" | "verse" | "pre_hook" | "hook" | "bridge" | "breakdown" | "outro"
    bars: int
    energy: int                 # 1–5
    active_roles: List[str] = field(default_factory=list)
    notes: str = ""

    # Strict planning fields (required for contrast-driven planning)
    target_density: str = "medium"          # sparse | medium | full
    transition_in: str = "none"             # how the section enters
    transition_out: str = "none"            # how the section exits
    variation_strategy: str = "none"        # none | role_rotation | drop_kick | support_swap | add_percussion | change_pattern
    introduced_elements: List[str] = field(default_factory=list)   # new roles vs. prev same-type section
    dropped_elements: List[str] = field(default_factory=list)      # removed roles vs. prev same-type section


@dataclass
class AIProducerSuggestion:
    """
    Structured output from the AI co-producer assist layer.

    The schema is validated against hard rules before being used.
    Fields marked *confidence* are 0.0–1.0 floats.
    """

    # Section plan proposal
    suggested_sections: List[SuggestedSectionEntry] = field(default_factory=list)

    # Meta
    confidence: float = 0.0             # 0.0–1.0 overall confidence
    reasoning: str = ""                 # Why the AI made these suggestions
    style_guess: str = ""               # Detected/inferred style
    producer_notes: List[str] = field(default_factory=list)   # Actionable hints

    # Provenance
    model_used: Optional[str] = None
    fallback_used: bool = False
    validation_passed: bool = False
    validation_errors: List[str] = field(default_factory=list)

    # AI planning observability
    ai_plan_raw: str = ""                           # Raw LLM output before parsing
    ai_plan_rejected_reason: str = ""               # Why the plan was rejected (if any)
    ai_section_deltas: List[dict] = field(default_factory=list)  # Diffs between repeated sections
    ai_novelty_score: float = 0.0                   # 0.0–1.0 plan novelty/contrast score
    ai_plan_vs_actual_match: Optional[float] = None  # Fraction of sections where plan == actual

    def to_dict(self) -> dict:
        return {
            "suggested_sections": [
                {
                    "section_type": s.section_type,
                    "bars": s.bars,
                    "energy": s.energy,
                    "active_roles": s.active_roles,
                    "notes": s.notes,
                    "target_density": s.target_density,
                    "transition_in": s.transition_in,
                    "transition_out": s.transition_out,
                    "variation_strategy": s.variation_strategy,
                    "introduced_elements": s.introduced_elements,
                    "dropped_elements": s.dropped_elements,
                }
                for s in self.suggested_sections
            ],
            "confidence": self.confidence,
            "reasoning": self.reasoning,
            "style_guess": self.style_guess,
            "producer_notes": self.producer_notes,
            "model_used": self.model_used,
            "fallback_used": self.fallback_used,
            "validation_passed": self.validation_passed,
            "validation_errors": self.validation_errors,
            "ai_plan_raw": self.ai_plan_raw,
            "ai_plan_rejected_reason": self.ai_plan_rejected_reason,
            "ai_section_deltas": self.ai_section_deltas,
            "ai_novelty_score": self.ai_novelty_score,
            "ai_plan_vs_actual_match": self.ai_plan_vs_actual_match,
        }


# ---------------------------------------------------------------------------
# Vague phrase detection
# ---------------------------------------------------------------------------


def _contains_vague_phrase(text: str) -> bool:
    """Return True if *text* contains a known vague producer instruction.

    Vague instructions (e.g. "add more energy", "make it bigger") give the
    renderer nothing concrete to act on and cause arrangements to collapse
    into identical-sounding sections.
    """
    if not text:
        return False
    lower = text.strip().lower()
    return any(phrase in lower for phrase in _VAGUE_PHRASES)


# ---------------------------------------------------------------------------
# Plan novelty scorer
# ---------------------------------------------------------------------------


def score_ai_plan(
    suggestion: AIProducerSuggestion,
) -> tuple[float, list[dict]]:
    """Score an AI plan for novelty and audible contrast.

    Returns ``(novelty_score, section_deltas)`` where:

    * ``novelty_score`` — 0.0–1.0 float.  Plans below :data:`_MIN_NOVELTY_SCORE`
      are considered too generic and trigger deterministic fallback.
    * ``section_deltas`` — list of dicts describing role/energy changes between
      consecutive occurrences of the same section type.

    Scoring components (weighted average):

    1. *Repeated-section contrast* (weight 0.40):
       Mean sufficient-contrast fraction across all repeated-section pairs.
       A pair is "sufficient" when their Jaccard role-set distance >=
       :data:`_MIN_JACCARD_CONTRAST` OR the absolute energy delta >= 1.

    2. *Energy curve variance* (weight 0.30):
       Normalised variance of the energy curve.  Flat curves (all same energy)
       score 0.0; a curve spanning the full 1-5 range scores >= 1.0 (capped).

    3. *Hook novelty* (weight 0.30):
       Fraction of hooks that have at least one ``introduced_elements`` entry.
       When no hooks are present the component is skipped.
    """
    sections = suggestion.suggested_sections
    if not sections:
        return 0.0, []

    # Group by section type in order of occurrence.
    by_type: dict[str, list[SuggestedSectionEntry]] = {}
    for s in sections:
        by_type.setdefault(s.section_type, []).append(s)

    section_deltas: list[dict] = []
    contrast_scores: list[float] = []

    # --- Component 1: repeated-section contrast ---
    for stype, instances in by_type.items():
        if len(instances) < 2:
            continue
        for i in range(1, len(instances)):
            a = instances[i - 1]
            b = instances[i]
            prev_set = set(a.active_roles)
            curr_set = set(b.active_roles)
            union = prev_set | curr_set
            if union:
                jaccard = 1.0 - len(prev_set & curr_set) / len(union)
            else:
                jaccard = 0.0
            energy_delta = b.energy - a.energy
            roles_added = sorted(curr_set - prev_set)
            roles_removed = sorted(prev_set - curr_set)
            sufficient = jaccard >= _MIN_JACCARD_CONTRAST or abs(energy_delta) >= 1

            section_deltas.append({
                "section_type": stype,
                "occurrence_a": i,
                "occurrence_b": i + 1,
                "roles_added": roles_added,
                "roles_removed": roles_removed,
                "energy_delta": energy_delta,
                "jaccard_distance": round(jaccard, 3),
                "sufficient_contrast": sufficient,
            })
            contrast_scores.append(1.0 if sufficient else 0.0)

    # --- Component 2: energy curve variance ---
    energies = [s.energy for s in sections]
    if len(energies) >= 2:
        mean_e = sum(energies) / len(energies)
        variance = sum((e - mean_e) ** 2 for e in energies) / len(energies)
        energy_score = min(1.0, variance / 2.0)
    else:
        energy_score = 0.5

    # --- Component 3: hook novelty ---
    hooks = by_type.get("hook", [])
    hook_novelty_score: Optional[float]
    if hooks:
        hooks_with_intro = sum(1 for h in hooks if h.introduced_elements)
        hook_novelty_score = min(1.0, hooks_with_intro / len(hooks))
    else:
        hook_novelty_score = None  # no hooks — skip component

    # --- Weighted combination ---
    weights: list[float] = []
    values: list[float] = []

    if contrast_scores:
        weights.append(0.40)
        values.append(sum(contrast_scores) / len(contrast_scores))

    weights.append(0.30)
    values.append(energy_score)

    if hook_novelty_score is not None:
        weights.append(0.30)
        values.append(hook_novelty_score)

    if not weights:
        return 0.5, section_deltas

    total_weight = sum(weights)
    final_score = sum(w * v for w, v in zip(weights, values)) / total_weight
    return round(final_score, 3), section_deltas


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

_ALLOWED_SECTION_TYPES = frozenset(
    ["intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"]
)


def validate_ai_suggestion(
    suggestion: AIProducerSuggestion,
    available_roles: list[str],
) -> tuple[bool, list[str]]:
    """
    Validate an AIProducerSuggestion against hard structural rules.

    Returns (is_valid, list_of_errors).

    Hard rules checked:
    - Section types must be known.
    - Hook energy must exceed every verse energy.
    - Intro energy must be <= 3.
    - Suggested roles must be a subset of available_roles.
    - Bar counts must be positive multiples of 4.
    - Confidence must be 0.0-1.0.
    - Repeated verses/hooks must have at least ``_MIN_JACCARD_CONTRAST``
      role-set distance OR an energy delta >= 1 (audible contrast required).
    - Bridge/breakdown sections must reduce density (energy <= 2).
    - Outro sections must simplify (energy <= 2).
    - Section notes must not contain vague generic phrases.
    """
    errors: list[str] = []

    if not suggestion.suggested_sections:
        errors.append("AI suggestion contains no sections")
        return False, errors

    hooks = [s for s in suggestion.suggested_sections if s.section_type == "hook"]
    verses = [s for s in suggestion.suggested_sections if s.section_type == "verse"]

    # Rule: section types must be known
    for sec in suggestion.suggested_sections:
        if sec.section_type not in _ALLOWED_SECTION_TYPES:
            errors.append(f"Unknown section type in AI suggestion: '{sec.section_type}'")

    # Rule: hook energy > verse energy
    if hooks and verses:
        max_verse_energy = max(s.energy for s in verses)
        for hook in hooks:
            if hook.energy <= max_verse_energy:
                errors.append(
                    f"AI suggestion: hook energy ({hook.energy}) must exceed "
                    f"verse energy ({max_verse_energy})"
                )

    # Rule: intro must not be full (energy > 3)
    intros = [s for s in suggestion.suggested_sections if s.section_type == "intro"]
    for intro in intros:
        if intro.energy > 3:
            errors.append(
                f"AI suggestion: intro energy ({intro.energy}) too high — must be <= 3"
            )

    # Rule: bridge/breakdown must reduce density (energy <= 2)
    for sec in suggestion.suggested_sections:
        if sec.section_type in {"bridge", "breakdown"} and sec.energy > 2:
            errors.append(
                f"AI suggestion: '{sec.section_type}' must reduce density "
                f"(energy must be <= 2, got {sec.energy})"
            )

    # Rule: outro must simplify (energy <= 2)
    for outro in [s for s in suggestion.suggested_sections if s.section_type == "outro"]:
        if outro.energy > 2:
            errors.append(
                f"AI suggestion: 'outro' must simplify "
                f"(energy must be <= 2, got {outro.energy})"
            )

    # Rule: suggested roles must be a subset of available_roles
    if available_roles:
        available_set = set(available_roles)
        for sec in suggestion.suggested_sections:
            bad_roles = [r for r in sec.active_roles if r not in available_set]
            if bad_roles:
                errors.append(
                    f"AI suggestion section '{sec.section_type}' references unavailable "
                    f"roles: {bad_roles}"
                )

    # Rule: bar counts must be positive multiples of 4
    for sec in suggestion.suggested_sections:
        if sec.bars <= 0 or sec.bars % 4 != 0:
            errors.append(
                f"AI suggestion section '{sec.section_type}' has invalid bar count: {sec.bars} "
                "(must be a positive multiple of 4)"
            )

    # Rule: confidence must be 0–1
    if not (0.0 <= suggestion.confidence <= 1.0):
        errors.append(f"AI suggestion confidence {suggestion.confidence} out of range [0, 1]")

    # Rule: repeated sections must have audible contrast
    by_type: dict[str, list[SuggestedSectionEntry]] = {}
    for s in suggestion.suggested_sections:
        by_type.setdefault(s.section_type, []).append(s)

    for stype, instances in by_type.items():
        if stype in {"intro", "outro"}:
            # intro/outro are allowed to be similar — they bracket the arrangement
            continue
        if len(instances) < 2:
            continue
        for i in range(1, len(instances)):
            a = instances[i - 1]
            b = instances[i]
            prev_set = set(a.active_roles)
            curr_set = set(b.active_roles)
            union = prev_set | curr_set
            jaccard = (
                1.0 - len(prev_set & curr_set) / len(union)
                if union
                else 0.0
            )
            energy_delta = abs(b.energy - a.energy)
            if jaccard < _MIN_JACCARD_CONTRAST and energy_delta < 1:
                errors.append(
                    f"AI suggestion: repeated '{stype}' sections {i} and {i + 1} are "
                    f"too similar (Jaccard={jaccard:.2f}, energy_delta={energy_delta}) — "
                    "at least 2 meaningful differences are required between repeated sections"
                )

    # Rule: section notes must not be vague
    for sec in suggestion.suggested_sections:
        if _contains_vague_phrase(sec.notes):
            errors.append(
                f"AI suggestion: section '{sec.section_type}' notes are too vague: '{sec.notes}'"
            )

    is_valid = len(errors) == 0
    return is_valid, errors


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class AIProducerAssistService:
    """
    Generates AI co-producer suggestions and validates them before use.

    When AI_PRODUCER_ASSIST is disabled or AI is unavailable, the service
    returns an empty suggestion with fallback_used=True rather than raising.

    Usage::

        service = AIProducerAssistService(
            api_key=settings.openai_api_key,
            model=settings.openai_model,
        )
        suggestion = await service.assist(
            available_roles=["drums", "bass", "melody"],
            genre="trap",
            tempo=140.0,
            style_text="dark aggressive trap",
            feature_enabled=settings.feature_ai_producer_assist,
        )
    """

    def __init__(
        self,
        api_key: str = "",
        model: str = "gpt-4",
        base_url: str = "https://api.openai.com/v1",
        timeout: int = 30,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self.timeout = timeout
        self._client = None

        if api_key:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=api_key,
                    base_url=base_url if base_url != "https://api.openai.com/v1" else None,
                )
            except Exception:
                logger.warning("AIProducerAssistService: failed to init OpenAI client", exc_info=True)

    async def assist(
        self,
        available_roles: list[str],
        genre: str = "generic",
        tempo: float = 120.0,
        style_text: str = "",
        target_bars: int = 64,
        feature_enabled: bool = False,
        style_interpretation_enabled: bool = False,
    ) -> AIProducerSuggestion:
        """
        Generate and validate AI suggestions.

        Returns a validated AIProducerSuggestion.  On any failure,
        fallback_used=True and suggested_sections=[].
        """
        if not feature_enabled:
            return AIProducerSuggestion(
                fallback_used=True,
                reasoning="AI_PRODUCER_ASSIST feature flag is disabled",
            )

        if not self._client:
            return AIProducerSuggestion(
                fallback_used=True,
                reasoning="OpenAI client unavailable — check OPENAI_API_KEY",
            )

        try:
            raw_suggestion = await self._call_llm(
                available_roles=available_roles,
                genre=genre,
                tempo=tempo,
                style_text=style_text,
                target_bars=target_bars,
                style_interpretation_enabled=style_interpretation_enabled,
            )
        except Exception:
            logger.warning("AIProducerAssistService: LLM call failed", exc_info=True)
            return AIProducerSuggestion(
                fallback_used=True,
                reasoning="LLM call failed — using fallback arrangement logic",
            )

        # Validate against hard rules
        is_valid, errors = validate_ai_suggestion(raw_suggestion, available_roles)
        raw_suggestion.validation_passed = is_valid
        raw_suggestion.validation_errors = errors

        if not is_valid:
            logger.warning(
                "AIProducerAssistService: suggestion failed validation (%d errors) — "
                "falling back to rules-only path",
                len(errors),
            )
            rejected_reason = f"Validation errors: {'; '.join(errors)}"
            return AIProducerSuggestion(
                fallback_used=True,
                reasoning=f"AI suggestion failed validation: {'; '.join(errors)}",
                validation_errors=errors,
                model_used=self.model,
                ai_plan_raw=raw_suggestion.ai_plan_raw,
                ai_plan_rejected_reason=rejected_reason,
            )

        # Score the plan — reject plans that are too generic
        novelty_score, section_deltas = score_ai_plan(raw_suggestion)
        raw_suggestion.ai_novelty_score = novelty_score
        raw_suggestion.ai_section_deltas = section_deltas

        if novelty_score < _MIN_NOVELTY_SCORE:
            rejected_reason = (
                f"Novelty score too low: {novelty_score:.3f} < {_MIN_NOVELTY_SCORE} — "
                "plan is too generic; falling back to deterministic arrangement"
            )
            logger.warning("AIProducerAssistService: %s", rejected_reason)
            return AIProducerSuggestion(
                fallback_used=True,
                reasoning=rejected_reason,
                model_used=self.model,
                ai_plan_raw=raw_suggestion.ai_plan_raw,
                ai_plan_rejected_reason=rejected_reason,
                ai_novelty_score=novelty_score,
                ai_section_deltas=section_deltas,
            )

        raw_suggestion.model_used = self.model
        return raw_suggestion

    async def _call_llm(
        self,
        available_roles: list[str],
        genre: str,
        tempo: float,
        style_text: str,
        target_bars: int,
        style_interpretation_enabled: bool,
    ) -> AIProducerSuggestion:
        import asyncio

        prompt = self._build_prompt(
            available_roles=available_roles,
            genre=genre,
            tempo=tempo,
            style_text=style_text,
            target_bars=target_bars,
            style_interpretation_enabled=style_interpretation_enabled,
        )

        response = await asyncio.to_thread(
            self._client.chat.completions.create,
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an expert music producer assistant. "
                        "Return strict JSON only, no markdown."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1200,
            response_format={"type": "json_object"},
            timeout=self.timeout,
        )

        raw_text = (response.choices[0].message.content or "").strip()
        payload = json.loads(raw_text)
        suggestion = self._parse_response(payload)
        suggestion.ai_plan_raw = raw_text  # capture raw LLM output for observability
        return suggestion

    def _build_prompt(
        self,
        available_roles: list[str],
        genre: str,
        tempo: float,
        style_text: str,
        target_bars: int,
        style_interpretation_enabled: bool,
    ) -> str:
        style_instruction = (
            f"Interpret the style description and reflect it in your suggestions: '{style_text}'"
            if style_interpretation_enabled and style_text
            else ""
        )

        return (
            "You are an AI music production co-producer. "
            "Propose a strict, deterministic, contrast-driven section-by-section arrangement plan.\n"
            "HARD RULES (MUST follow — plans violating these are rejected):\n"
            "- Use only roles from available_roles list.\n"
            "- Hook energy must be strictly greater than verse energy.\n"
            "- Intro energy must be <= 3.\n"
            "- Bridge and breakdown energy must be <= 2 (density reduction required).\n"
            "- Outro energy must be <= 2 (simplification required).\n"
            "- Bar counts must be positive multiples of 4.\n"
            "- Confidence must be 0.0 to 1.0.\n"
            "- Repeated sections (verse 1 vs verse 2, hook 1 vs hook 2) MUST differ: "
            "use different active_roles (Jaccard distance >= 0.20) OR an energy difference of at least 1.\n"
            "- DO NOT use vague notes like 'add more energy', 'make it bigger', "
            "'keep it the same but stronger'. Be specific about WHAT changes.\n"
            f"- Target approximately {target_bars} total bars.\n"
            f"{style_instruction}\n"
            "Output JSON with keys: suggested_sections (list), confidence, reasoning, "
            "style_guess, producer_notes (list of strings).\n"
            "Each section MUST include ALL of these keys: "
            "section_type, bars, energy (1-5), active_roles (list), notes (specific action), "
            "target_density (sparse|medium|full), transition_in (none|drum_fill|fx_rise|fx_hit|"
            "mute_drop|bass_drop|vocal_chop|arp_lift|percussion_fill), "
            "transition_out (same choices), "
            "variation_strategy (none|role_rotation|drop_kick|support_swap|add_percussion|change_pattern), "
            "introduced_elements (list of new roles vs prev occurrence), "
            "dropped_elements (list of removed roles vs prev occurrence).\n"
            f"available_roles: {json.dumps(available_roles)}\n"
            f"genre: {genre}\n"
            f"tempo: {tempo} BPM\n"
        )

    @staticmethod
    def _parse_response(payload: dict) -> AIProducerSuggestion:
        """Parse raw LLM JSON payload into AIProducerSuggestion."""
        sections_raw = payload.get("suggested_sections", [])
        sections: list[SuggestedSectionEntry] = []

        for sec in sections_raw:
            if not isinstance(sec, dict):
                continue
            sections.append(
                SuggestedSectionEntry(
                    section_type=str(sec.get("section_type", "verse")).lower(),
                    bars=max(4, int(sec.get("bars", 8))),
                    energy=max(1, min(5, int(sec.get("energy", 3)))),
                    active_roles=[str(r) for r in sec.get("active_roles", [])],
                    notes=str(sec.get("notes", "")),
                    target_density=str(sec.get("target_density", "medium")).lower(),
                    transition_in=str(sec.get("transition_in", "none")).lower(),
                    transition_out=str(sec.get("transition_out", "none")).lower(),
                    variation_strategy=str(sec.get("variation_strategy", "none")).lower(),
                    introduced_elements=[str(r) for r in sec.get("introduced_elements", [])],
                    dropped_elements=[str(r) for r in sec.get("dropped_elements", [])],
                )
            )

        return AIProducerSuggestion(
            suggested_sections=sections,
            confidence=float(payload.get("confidence", 0.5)),
            reasoning=str(payload.get("reasoning", "")),
            style_guess=str(payload.get("style_guess", "")),
            producer_notes=[str(n) for n in payload.get("producer_notes", [])],
        )
