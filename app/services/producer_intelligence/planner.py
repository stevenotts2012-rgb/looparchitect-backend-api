from __future__ import annotations

import logging
from typing import Any, Dict, List

from .bridge_engine import apply_bridge_reset
from .choreography_engine import plan_stem_choreography
from .energy_engine import build_energy_curve
from .hook_engine import escalate_hooks
from .outro_engine import simplify_outro
from .phrase_engine import evolve_phrases
from .state import ProducerState
from .style_registry import resolve_style
from .transition_engine import plan_transitions
from .validator import validate_plan

logger = logging.getLogger(__name__)


class ProducerIntelligencePlanner:
    def generate(self, sections: List[str], stems: List[str], style: str | None = None, mood: str | None = None) -> Dict[str, Any]:
        state = ProducerState()
        logger.info("PRODUCER_STATE_CREATED")

        style_cfg = resolve_style(style, mood)
        energies = build_energy_curve(sections, style_cfg["energy_curve"])
        logger.info("ENERGY_CURVE_GENERATED")

        for s in sections:
            if "bridge" in s.lower():
                energies[s] = apply_bridge_reset(energies[s])
                logger.info("BRIDGE_RESET_APPLIED")
            if "outro" in s.lower():
                energies[s] = simplify_outro(energies[s])
                logger.info("OUTRO_SIMPLIFICATION_APPLIED")
            state.section_energy_history.append((s, energies[s]))

        stem_map = plan_stem_choreography(sections, stems, energies)
        logger.info("SECTION_CHOREOGRAPHY_APPLIED")
        for s in sections:
            combo = tuple(stem_map[s])
            state.used_stem_combinations.add(combo)
            state.section_density_history.append((s, round(len(combo) / max(1, len(stems)), 3)))

        transitions = plan_transitions(sections, energies, style_cfg["transition_density"])
        state.transition_history.extend(transitions)
        state.fill_usage_history.extend([t for t in transitions if "fill" in t["fx"]])
        logger.info("TRANSITION_PLANNED")

        phrases = evolve_phrases(sections)
        state.phrase_history.extend([{"section": k, "mutation": v} for k, v in phrases.items()])
        logger.info("PHRASE_EVOLUTION_APPLIED")

        hook_levels = escalate_hooks(sections, energies)
        state.hook_intensity_history.extend(hook_levels.values())
        logger.info("HOOK_ESCALATION_APPLIED")

        issues = validate_plan(sections, energies, stem_map, transitions, hook_levels)
        if issues:
            raise ValueError(f"Producer validation failed: {issues}")
        logger.info("PRODUCER_VALIDATION_PASSED")

        return {
            "style": style_cfg,
            "energy": energies,
            "stems": stem_map,
            "transitions": transitions,
            "phrases": phrases,
            "hooks": hook_levels,
            "state": state,
        }
