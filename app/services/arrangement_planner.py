"""AI-assisted arrangement planning service with deterministic validation and fallback."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any, Optional

from app.config import settings
from app.schemas.arrangement import (
    ArrangementPlan,
    ArrangementPlannerInput,
    ArrangementPlannerConfig,
    ArrangementPlanSection,
    ArrangementPlannerNotes,
    ArrangementPlanValidation,
    ArrangementPlannerMeta,
)

logger = logging.getLogger(__name__)

ALLOWED_SECTION_TYPES = {"intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"}
ALLOWED_ROLES = {
    "drums",
    "bass",
    "melody",
    "pads",
    "fx",
    "percussion",
    "vocal",
    "arp",
    "synth",
    "full_mix",
}
ALLOWED_TRANSITIONS = {
    "none",
    "drum_fill",
    "fx_rise",
    "fx_hit",
    "mute_drop",
    "bass_drop",
    "vocal_chop",
    "arp_lift",
    "percussion_fill",
}


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def _normalize_roles(detected_roles: list[str], allow_full_mix: bool = True) -> list[str]:
    normalized = [str(role).strip().lower() for role in (detected_roles or [])]
    normalized = [role for role in normalized if role in ALLOWED_ROLES]
    normalized = _dedupe(normalized)

    non_full_mix_roles = [role for role in normalized if role != "full_mix"]
    if len(non_full_mix_roles) >= 2:
        normalized = [role for role in normalized if role != "full_mix"]

    if not allow_full_mix:
        normalized = [role for role in normalized if role != "full_mix"]

    return normalized


def _default_structure(source_type: str) -> list[str]:
    if source_type == "loop":
        return ["intro", "verse", "hook", "verse", "hook", "outro"]
    return ["intro", "verse", "pre_hook", "hook", "verse", "hook", "bridge", "hook", "outro"]


def _fit_bars_to_target(structure: list[str], target_total_bars: Optional[int]) -> list[int]:
    base_map = {
        "intro": 4,
        "verse": 8,
        "pre_hook": 4,
        "hook": 8,
        "bridge": 8,
        "breakdown": 8,
        "outro": 4,
    }
    bars = [base_map.get(section, 8) for section in structure]

    if not target_total_bars:
        return bars

    target = max(4, int(target_total_bars))
    current = sum(bars)
    if current == target:
        return bars

    adjust_priority = [i for i, section in enumerate(structure) if section in {"verse", "hook", "bridge", "breakdown"}]
    if not adjust_priority:
        adjust_priority = list(range(len(structure)))

    idx = 0
    while current != target and idx < 512:
        section_idx = adjust_priority[idx % len(adjust_priority)]
        if current < target:
            bars[section_idx] += 4
            current += 4
        elif bars[section_idx] > 4:
            bars[section_idx] -= 4
            current -= 4
        else:
            idx += 1
            continue
        idx += 1

    return bars


def _section_energy(section_type: str) -> int:
    return {
        "intro": 1,
        "verse": 3,
        "pre_hook": 4,
        "hook": 5,
        "bridge": 2,
        "breakdown": 2,
        "outro": 1,
    }.get(section_type, 3)


def _section_density(section_type: str, energy: int) -> str:
    if section_type in {"intro", "outro", "breakdown"}:
        return "sparse"
    if section_type == "hook":
        return "full"
    return "medium" if energy <= 3 else "full"


_TRANSITION_SCHEMA_ALLOWED = frozenset({
    "none",
    "drum_fill",
    "fx_rise",
    "fx_hit",
    "mute_drop",
    "bass_drop",
    "vocal_chop",
    "arp_lift",
    "percussion_fill",
})

_TRANSITION_REMAP = {
    "riser": "fx_rise",
    "pull_back": "none",
    "crossfade": "none",
    "silence_drop": "fx_hit",
    "filter_open": "none",
    "lift": "drum_fill",
    "impact": "fx_hit",
    "fade": "none",
}


def _normalize_transition(value: str) -> str:
    """Map any transition string to an ``ArrangementPlanSection``-allowed value."""
    v = str(value).strip().lower()
    if v in _TRANSITION_SCHEMA_ALLOWED:
        return v
    return _TRANSITION_REMAP.get(v, "none")


def _transition_for_section(section_type: str, arrangement_preset: str | None = None) -> str:
    if arrangement_preset:
        try:
            from app.services.arrangement_presets import get_preset_config
            preset = get_preset_config(arrangement_preset)
            if preset:
                override = preset.section_overrides.get(str(section_type).strip().lower())
                if override and override.default_transition_in is not None:
                    return _normalize_transition(override.default_transition_in)
        except ImportError:
            pass
    return {
        "intro": "none",
        "verse": "drum_fill",
        "pre_hook": "fx_rise",
        "hook": "fx_rise",
        "bridge": "mute_drop",
        "breakdown": "fx_hit",
        "outro": "none",
    }.get(section_type, "none")


def _roles_for_section(section_type: str, allowed_roles: list[str], density: str, occurrence: int = 1, prev_same_type_roles: list[str] | None = None, prev_adjacent_roles: list[str] | None = None, arrangement_preset: str | None = None) -> list[str]:
    if settings.feature_producer_section_identity_v2:
        from app.services.section_identity_engine import select_roles_for_section
        return select_roles_for_section(
            section_type=section_type,
            available_roles=allowed_roles,
            occurrence=occurrence,
            prev_same_type_roles=prev_same_type_roles,
            prev_adjacent_roles=prev_adjacent_roles,
            preset_name=arrangement_preset,
        )

    if not allowed_roles:
        return []

    # When an arrangement preset is given, apply its role priorities and density
    # overrides even outside the identity engine.
    if arrangement_preset:
        try:
            from app.services.section_identity_engine import get_effective_profile
            profile = get_effective_profile(section_type, arrangement_preset)
            forbidden = profile.forbidden_roles
            permitted = [r for r in allowed_roles if r not in forbidden]
            ordered_pref = [r for r in profile.role_priorities if r in set(permitted)]
            for r in permitted:
                if r not in set(ordered_pref):
                    ordered_pref.append(r)
            max_roles_p = profile.density_max
            selected = _dedupe(ordered_pref[:max_roles_p])
            if len(selected) < profile.density_min and ordered_pref:
                extra = [r for r in ordered_pref if r not in set(selected)]
                selected.extend(extra[: profile.density_min - len(selected)])
            return selected if selected else (ordered_pref[:1] if ordered_pref else ([allowed_roles[0]] if allowed_roles else []))
        except (ImportError, Exception):
            pass  # Fall through to hardcoded preference below

    preference = {
        "intro": ["pads", "fx", "melody", "arp", "vocal", "full_mix", "synth"],
        "verse": ["drums", "bass", "melody", "vocal", "synth", "percussion", "arp", "full_mix", "pads"],
        "pre_hook": ["drums", "bass", "arp", "fx", "melody", "vocal", "percussion", "synth", "full_mix"],
        "hook": ["drums", "bass", "melody", "synth", "vocal", "percussion", "arp", "pads", "fx", "full_mix"],
        "bridge": ["pads", "fx", "melody", "vocal", "arp", "bass", "synth", "full_mix"],
        "breakdown": ["pads", "fx", "vocal", "arp", "melody", "full_mix", "synth"],
        "outro": ["pads", "fx", "melody", "arp", "full_mix", "vocal"],
    }

    max_roles = 2 if density == "sparse" else 3 if density == "medium" else 4
    ordered = [role for role in preference.get(section_type, []) if role in allowed_roles]

    if section_type == "hook" and "drums" in allowed_roles and "drums" not in ordered:
        ordered.insert(0, "drums")
    if section_type in {"verse", "hook"} and "bass" in allowed_roles and "bass" not in ordered:
        ordered.insert(1 if ordered else 0, "bass")

    selected = _dedupe(ordered[:max_roles])
    if not selected:
        selected = [allowed_roles[0]]
    return selected


_SECTION_PLAN_NOTES: dict[str, str] = {
    "intro": "Sparse entry — atmosphere and texture only, no groove.",
    "verse": "Rhythmic backbone established; melody and bass carry the groove.",
    "pre_hook": "Tension build — add edge, strip softness, drive toward hook.",
    "hook": "Hook peak with strongest groove and lead emphasis.",
    "bridge": "Contrast and reset — stripped groove, melodic or textural focus.",
    "breakdown": "Attention reset — subtractive, atmospheric, maximum space.",
    "outro": "Resolution — strip layers, fade energy, close cleanly.",
}


def build_fallback_arrangement_plan(
    planner_input: ArrangementPlannerInput,
    user_request: Optional[str],
    planner_config: ArrangementPlannerConfig,
) -> ArrangementPlan:
    arrangement_preset = getattr(planner_input, "arrangement_preset", None)

    allowed_roles = _normalize_roles(
        planner_input.detected_roles,
        allow_full_mix=planner_config.allow_full_mix,
    )

    if not allowed_roles:
        return ArrangementPlan(
            structure=[],
            total_bars=0,
            sections=[],
            planner_notes=ArrangementPlannerNotes(
                strategy="No valid roles available.",
                fallback_used=False,
            ),
        )

    preferred_structure = planner_input.preferred_structure or []
    preferred_structure = [str(item).strip().lower() for item in preferred_structure if str(item).strip().lower() in ALLOWED_SECTION_TYPES]

    structure = preferred_structure or _default_structure(planner_input.source_type)
    structure = structure[: max(1, planner_config.max_sections)]

    bars_by_section = _fit_bars_to_target(structure, planner_input.target_total_bars)

    sections: list[ArrangementPlanSection] = []
    occurrence_counter: dict[str, int] = {}
    prev_same_type_roles: dict[str, list[str]] = {}
    prev_adjacent_roles: list[str] = []

    for idx, section_type in enumerate(structure):
        occurrence_counter[section_type] = occurrence_counter.get(section_type, 0) + 1
        occurrence = occurrence_counter[section_type]

        energy = _section_energy(section_type)
        density = _section_density(section_type, energy)
        roles = _roles_for_section(
            section_type,
            allowed_roles,
            density,
            occurrence=occurrence,
            prev_same_type_roles=prev_same_type_roles.get(section_type),
            prev_adjacent_roles=prev_adjacent_roles if idx > 0 else None,
            arrangement_preset=arrangement_preset,
        )
        transition = _transition_for_section(section_type, arrangement_preset)
        note = _SECTION_PLAN_NOTES.get(section_type, "Controlled section change to preserve progression.")
        if occurrence > 1:
            note = f"{note} (occurrence {occurrence}: evolved from prior {section_type})"

        sections.append(
            ArrangementPlanSection(
                index=idx,
                type=section_type,
                bars=int(bars_by_section[idx]),
                energy=int(energy),
                density=density,
                active_roles=roles,
                transition_into=transition,
                notes=note,
            )
        )
        prev_same_type_roles[section_type] = roles
        prev_adjacent_roles = roles

    verse_energies = [section.energy for section in sections if section.type == "verse"]
    max_verse = max(verse_energies) if verse_energies else 3
    for section in sections:
        if section.type == "hook" and section.energy < max_verse:
            section.energy = max_verse

    total_bars = int(sum(section.bars for section in sections))

    strategy = "Start sparse, build through verses, peak in hooks, then resolve cleanly."
    if user_request:
        strategy = "Blend user intent with role-safe deterministic section planning."

    return ArrangementPlan(
        structure=[section.type for section in sections],
        total_bars=total_bars,
        sections=sections,
        planner_notes=ArrangementPlannerNotes(
            strategy=strategy,
            fallback_used=True,
        ),
    )


def validate_arrangement_plan(plan: ArrangementPlan, detected_roles: list[str]) -> ArrangementPlanValidation:
    errors: list[str] = []
    warnings: list[str] = []

    allowed_roles = _normalize_roles(detected_roles, allow_full_mix=True)
    allowed_roles_set = set(allowed_roles)
    non_full_mix_count = len([role for role in allowed_roles if role != "full_mix"])

    if len(plan.structure) != len(plan.sections):
        errors.append("structure length must equal sections length")

    sum_bars = sum(int(section.bars) for section in plan.sections)
    if int(plan.total_bars) != int(sum_bars):
        errors.append("total_bars must equal sum of section bars")

    for idx, section in enumerate(plan.sections):
        if section.index != idx:
            errors.append("section indexes must be sequential and zero-based")

        if section.type not in ALLOWED_SECTION_TYPES:
            errors.append(f"invalid section type: {section.type}")

        if section.transition_into not in ALLOWED_TRANSITIONS:
            errors.append(f"invalid transition label: {section.transition_into}")

        role_set = set(section.active_roles)
        if len(role_set) != len(section.active_roles):
            errors.append(f"section {idx} active_roles contains duplicates")

        invalid_roles = [role for role in section.active_roles if role not in allowed_roles_set]
        if invalid_roles:
            errors.append(f"section {idx} has roles not in detected_roles: {', '.join(invalid_roles)}")

    if non_full_mix_count >= 2:
        for section in plan.sections:
            if "full_mix" in section.active_roles:
                errors.append("full_mix must be excluded when 2+ non-full_mix roles exist")
                break

    verse_energies = [section.energy for section in plan.sections if section.type == "verse"]
    hook_energies = [section.energy for section in plan.sections if section.type == "hook"]
    if verse_energies and hook_energies and min(hook_energies) < max(verse_energies):
        errors.append("hooks must have energy greater than or equal to every verse")

    if plan.sections:
        first = plan.sections[0]
        last = plan.sections[-1]
        if first.type == "intro" and first.energy not in {1, 2}:
            warnings.append("intro energy is usually 1 or 2")

        final_hook_energy = max((section.energy for section in plan.sections if section.type == "hook"), default=None)
        if last.type == "outro" and final_hook_energy is not None and last.energy > final_hook_energy:
            warnings.append("outro energy is usually <= final hook energy")

    return ArrangementPlanValidation(valid=len(errors) == 0, errors=errors, warnings=warnings)


def plan_to_producer_arrangement(plan: ArrangementPlan) -> dict[str, Any]:
    """Convert planner output into producer_arrangement-compatible payload."""
    sections: list[dict[str, Any]] = []
    bar_cursor = 0

    for section in plan.sections:
        bars = int(section.bars)
        section_payload = {
            "name": str(section.type).replace("_", " ").title(),
            "type": section.type,
            "bar_start": int(bar_cursor),
            "bars": bars,
            "energy": round(float(section.energy) / 5.0, 3),
            "instruments": list(section.active_roles),
            "transition_hint": section.transition_into,
            "notes": section.notes,
        }
        sections.append(section_payload)
        bar_cursor += bars

    return {
        "version": "2.1",
        "sections": sections,
        "tracks": [],
        "transitions": [],
        "energy_curve": [],
        "total_bars": int(plan.total_bars),
    }


class ArrangementPlannerService:
    """LLM-backed arrangement planner with deterministic fallback."""

    def __init__(self) -> None:
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url
        self.model = settings.openai_model
        self.timeout = settings.openai_timeout

        self.client = None
        if self.api_key:
            try:
                from openai import OpenAI

                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url if self.base_url != "https://api.openai.com/v1" else None,
                )
            except Exception:
                logger.exception("Failed to initialize OpenAI client for arrangement planner")

    async def generate_plan(
        self,
        planner_input: ArrangementPlannerInput,
        user_request: Optional[str],
        planner_config: ArrangementPlannerConfig,
    ) -> tuple[ArrangementPlan, ArrangementPlanValidation, ArrangementPlannerMeta]:
        started = time.perf_counter()
        fallback_used = False
        tokens = None

        if not self.client:
            fallback_plan = build_fallback_arrangement_plan(planner_input, user_request, planner_config)
            validation = validate_arrangement_plan(fallback_plan, planner_input.detected_roles)
            latency_ms = int((time.perf_counter() - started) * 1000)
            meta = ArrangementPlannerMeta(
                model=None,
                latency_ms=latency_ms,
                tokens=tokens,
                fallback_used=True,
            )
            return fallback_plan, validation, meta

        try:
            llm_plan, tokens = await self._call_llm(planner_input, user_request, planner_config)
            validation = validate_arrangement_plan(llm_plan, planner_input.detected_roles)

            if planner_config.strict and not validation.valid:
                repaired_plan, repair_tokens = await self._repair_plan(llm_plan, planner_input, validation.errors)
                tokens = (tokens or 0) + (repair_tokens or 0)
                validation = validate_arrangement_plan(repaired_plan, planner_input.detected_roles)
                llm_plan = repaired_plan

            if not validation.valid:
                fallback_used = True
                llm_plan = build_fallback_arrangement_plan(planner_input, user_request, planner_config)
                validation = validate_arrangement_plan(llm_plan, planner_input.detected_roles)

            latency_ms = int((time.perf_counter() - started) * 1000)
            meta = ArrangementPlannerMeta(
                model=self.model,
                latency_ms=latency_ms,
                tokens=tokens,
                fallback_used=fallback_used,
            )
            return llm_plan, validation, meta
        except Exception:
            logger.exception("Arrangement planner LLM call failed; falling back")
            fallback_plan = build_fallback_arrangement_plan(planner_input, user_request, planner_config)
            validation = validate_arrangement_plan(fallback_plan, planner_input.detected_roles)
            latency_ms = int((time.perf_counter() - started) * 1000)
            meta = ArrangementPlannerMeta(
                model=self.model,
                latency_ms=latency_ms,
                tokens=tokens,
                fallback_used=True,
            )
            return fallback_plan, validation, meta

    async def _call_llm(
        self,
        planner_input: ArrangementPlannerInput,
        user_request: Optional[str],
        planner_config: ArrangementPlannerConfig,
    ) -> tuple[ArrangementPlan, Optional[int]]:
        prompt = self._build_prompt(planner_input, user_request, planner_config)

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a music arrangement planner. Return strict JSON only.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            max_tokens=1400,
            response_format={"type": "json_object"},
            timeout=self.timeout,
        )

        raw_text = (response.choices[0].message.content or "").strip()
        payload = json.loads(raw_text)
        plan = ArrangementPlan.model_validate(payload)

        usage = getattr(response, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage else None
        return plan, tokens

    async def _repair_plan(
        self,
        invalid_plan: ArrangementPlan,
        planner_input: ArrangementPlannerInput,
        errors: list[str],
    ) -> tuple[ArrangementPlan, Optional[int]]:
        repair_prompt = (
            "Fix the plan to satisfy all rules and return strict JSON only.\n"
            f"Input metadata: {planner_input.model_dump_json()}\n"
            f"Validation errors: {json.dumps(errors)}\n"
            f"Invalid plan: {invalid_plan.model_dump_json()}"
        )

        response = await asyncio.to_thread(
            self.client.chat.completions.create,
            model=self.model,
            messages=[
                {"role": "system", "content": "Return strict JSON only and preserve schema."},
                {"role": "user", "content": repair_prompt},
            ],
            temperature=0.1,
            max_tokens=1400,
            response_format={"type": "json_object"},
            timeout=self.timeout,
        )

        raw_text = (response.choices[0].message.content or "").strip()
        payload = json.loads(raw_text)
        repaired_plan = ArrangementPlan.model_validate(payload)

        usage = getattr(response, "usage", None)
        tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage else None
        return repaired_plan, tokens

    def _build_prompt(
        self,
        planner_input: ArrangementPlannerInput,
        user_request: Optional[str],
        planner_config: ArrangementPlannerConfig,
    ) -> str:
        allowed_roles = _normalize_roles(planner_input.detected_roles, allow_full_mix=planner_config.allow_full_mix)
        data = planner_input.model_dump()
        data["detected_roles"] = allowed_roles

        return (
            "Create a professional section-by-section arrangement plan for a loop-to-song engine. "
            "Return strict JSON only, no markdown, no comments.\n"
            "Rules:\n"
            "- Use only roles present in detected_roles.\n"
            "- Hook energy must be >= every verse.\n"
            "- Intro sparse, hook usually full, outro simplified.\n"
            "- Allowed transitions: none, drum_fill, fx_rise, fx_hit, mute_drop, bass_drop, vocal_chop, arp_lift, percussion_fill.\n"
            "- Keep structure concise and deterministic.\n"
            "- Use section types only: intro, verse, pre_hook, hook, bridge, breakdown, outro.\n"
            "Output schema keys exactly: structure, total_bars, sections, planner_notes.\n"
            f"Planner config: {json.dumps(planner_config.model_dump())}\n"
            f"User request: {user_request or ''}\n"
            f"Input JSON: {json.dumps(data)}"
        )


arrangement_planner_service = ArrangementPlannerService()
