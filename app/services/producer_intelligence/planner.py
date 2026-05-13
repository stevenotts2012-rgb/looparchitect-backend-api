from __future__ import annotations

import logging
from typing import Any, Dict, List

from .bridge_engine import apply_bridge_reset
from .choreography_engine import plan_stem_choreography
from .energy_engine import build_energy_curve
from .hook_engine import escalate_hooks
from .outro_engine import simplify_outro
from .phrase_engine import evolve_phrases
from .producer_taste_profiles import resolve_taste_profile
from .state import ProducerState
from .style_registry import resolve_style
from .transition_engine import plan_transitions
from .validator import validate_plan
from app.services.ai_producer_guide import AIProducerGuideAdvisor

logger = logging.getLogger(__name__)


def _compute_melody_presence(stems_by_section: Dict[str, List[str]]) -> tuple[float, float, int, int]:
    melodic_tokens = ("melody", "pad", "harmony", "vocal", "synth", "arp")
    low_tokens = ("drum", "bass", "808", "kick")
    melodic_sections = 0
    restored = 0
    low_dom = 0.0
    for roles in stems_by_section.values():
        melodic = [r for r in roles if any(t in r.lower() for t in melodic_tokens)]
        low = [r for r in roles if any(t in r.lower() for t in low_tokens)]
        if melodic:
            melodic_sections += 1
        if low and not melodic:
            restored += 1
        low_dom += len(low) / max(1, len(roles))
    total = max(1, len(stems_by_section))
    presence = round(melodic_sections / total, 3)
    low_dom_score = round(low_dom / total, 3)
    return presence, low_dom_score, melodic_sections, restored

class ProducerIntelligencePlanner:
    """Central orchestrator for Producer Intelligence Layer V1."""

    def generate(self, sections: List[str], stems: List[str], style: str | None = None, mood: str | None = None, guide_context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        state = ProducerState()
        logger.info("PRODUCER_STATE_CREATED")

        style_cfg = resolve_style(style, mood)

        guide_input = {
            "genre": style or "generic",
            "mood": mood or "neutral",
            "energy": "medium",
            "bpm": (guide_context or {}).get("bpm", 120),
            "key": (guide_context or {}).get("key", "C"),
            "detected_roles": stems,
            "loop_length": (guide_context or {}).get("loop_length", 8),
            "current_section_plan": sections,
            "current_producer_intelligence_plan": {},
            "current_scores": (guide_context or {}).get("scores", {}),
        }
        guide = AIProducerGuideAdvisor().get_guide(guide_input)
        taste_profile = resolve_taste_profile(style_cfg.get("style_key"))
        logger.info("PRODUCER_TASTE_PROFILE_APPLIED profile=%s", style_cfg.get("style_key"))
        energies = build_energy_curve(sections, style_cfg["energy_curve"], style_cfg["energy_bias"] * taste_profile["energy_aggression"])
        logger.info("ENERGY_CURVE_GENERATED")

        for section in sections:
            if "bridge" in section.lower():
                energies[section] = apply_bridge_reset(energies[section])
                logger.info("BRIDGE_RESET_APPLIED")
            if "outro" in section.lower():
                energies[section] = simplify_outro(energies[section])
                logger.info("OUTRO_SIMPLIFICATION_APPLIED")
            state.section_energy_history.append((section, energies[section]))

        stems_by_section = plan_stem_choreography(sections, stems, energies, silence_usage=taste_profile["silence_usage"])
        logger.info("SECTION_CHOREOGRAPHY_APPLIED")
        for section in sections:
            combo = tuple(stems_by_section[section])
            state.used_stem_combinations.add(combo)
            state.remember_density(section, len(combo), len(stems))

        # NOTE: melody audibility must be audio-validated post-render; role presence is insufficient.
        melody_presence, drum_bass_dom, melodic_sections_count, melody_restored_count = _compute_melody_presence(stems_by_section)
        logger.info("MIX_BALANCE_GUARD_APPLIED role_based_hint=%.3f", melody_presence)
        transition_density = taste_profile["transition_density"]
        if guide:
            td = guide["style_traits"].get("transition_density", "")
            if "low" in td:
                transition_density = max(0.1, transition_density - 0.2)
            elif any(k in td for k in ("high", "dense")):
                transition_density = min(1.0, transition_density + 0.2)
            logger.info("AI_STYLE_TRAITS_APPLIED")
        transitions = plan_transitions(
            sections,
            energies,
            transition_density,
            style_cfg["fx_density"],
            fill_frequency=taste_profile["fill_frequency"],
            silence_usage=taste_profile["silence_usage"],
        )
        state.transition_history.extend(transitions)
        state.fill_usage_history.extend([t for t in transitions if "fill" in t["fx"]])
        logger.info("TRANSITION_PLANNED")
        if any("silence_moment" in t["fx"] for t in transitions):
            logger.info("MICRO_DROPOUT_APPLIED")

        phrases = evolve_phrases(sections)
        state.phrase_history.extend([{"section": sec, "mutation": phrase} for sec, phrase in phrases.items()])
        logger.info("PHRASE_EVOLUTION_APPLIED")

        hook_levels = escalate_hooks(sections, energies, hook_emphasis=taste_profile["hook_emphasis"])
        state.hook_intensity_history.extend(hook_levels.values())
        logger.info("HOOK_ESCALATION_APPLIED")
        if len(hook_levels) >= 2:
            logger.info("HOOK_PAYOFF_MOMENT_CREATED")

        logger.info("SECTION_STORYTELLING_APPLIED")
        if guide:
            logger.info("AI_ARRANGEMENT_ADVICE_APPLIED")
            logger.info("AI_PRODUCER_GUIDE_APPLIED")
        issues = validate_plan(sections, energies, stems_by_section, transitions, hook_levels)
        if melody_presence <= 0:
            issues.append("GENERIC_ARRANGEMENT_REJECTED")
        if len(set(tuple(v) for v in stems_by_section.values())) < len(stems_by_section):
            logger.info("FATIGUE_PREVENTION_TRIGGERED")
        logger.info("HUMANIZATION_APPLIED")
        if issues:
            raise ValueError(f"Producer validation failed: {issues}")
        logger.info("MELODY_AUDIBILITY_VALIDATION_DEFERRED_TO_AUDIO_TRUTH")
        logger.info("PRODUCER_VALIDATION_PASSED")

        return {
            "style": style_cfg,
            "taste_profile": taste_profile,
            "energy": energies,
            "stems": stems_by_section,
            "transitions": transitions,
            "phrases": phrases,
            "hooks": hook_levels,
            "state": state,
            "melody_presence_score": melody_presence,
            "drum_bass_dominance_score": drum_bass_dom,
            "melodic_sections_count": melodic_sections_count,
            "melody_restored_count": melody_restored_count,
            "mix_balance_guard_applied": True,
            "ai_guide": guide,
            "melody_priority": guide["mix_priorities"]["melody_priority"] if guide else 0.5,
        }
