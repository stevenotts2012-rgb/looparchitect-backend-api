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
# Suggestion schema
# ---------------------------------------------------------------------------


@dataclass
class SuggestedSectionEntry:
    """A single section suggestion from the AI co-producer."""

    section_type: str           # "intro" | "verse" | "pre_hook" | "hook" | "bridge" | "breakdown" | "outro"
    bars: int
    energy: int                 # 1–5
    active_roles: List[str] = field(default_factory=list)
    notes: str = ""


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

    def to_dict(self) -> dict:
        return {
            "suggested_sections": [
                {
                    "section_type": s.section_type,
                    "bars": s.bars,
                    "energy": s.energy,
                    "active_roles": s.active_roles,
                    "notes": s.notes,
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
        }


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
            return AIProducerSuggestion(
                fallback_used=True,
                reasoning=f"AI suggestion failed validation: {'; '.join(errors)}",
                validation_errors=errors,
                model_used=self.model,
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
        return self._parse_response(payload)

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
            "Propose a section-by-section arrangement plan.\n"
            "Rules (MUST follow):\n"
            "- Use only roles from available_roles list.\n"
            "- Hook energy must be strictly greater than verse energy.\n"
            "- Intro energy must be <= 3.\n"
            "- Bar counts must be positive multiples of 4.\n"
            "- Confidence must be 0.0 to 1.0.\n"
            f"- Target approximately {target_bars} total bars.\n"
            f"{style_instruction}\n"
            "Output JSON with keys: suggested_sections (list), confidence, reasoning, "
            "style_guess, producer_notes (list of strings).\n"
            "Each section: section_type, bars, energy (1-5), active_roles (list), notes.\n"
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
                )
            )

        return AIProducerSuggestion(
            suggested_sections=sections,
            confidence=float(payload.get("confidence", 0.5)),
            reasoning=str(payload.get("reasoning", "")),
            style_guess=str(payload.get("style_guess", "")),
            producer_notes=[str(n) for n in payload.get("producer_notes", [])],
        )
