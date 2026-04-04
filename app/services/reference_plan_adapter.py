"""
Reference Plan Adapter — Phase 3.

Maps a :class:`ReferenceStructure` (structural guidance from a reference audio
track) into :class:`ReferenceProducerGuidance` that can be injected into the
ProducerPlanBuilderV2 workflow.

Design contracts:
- Reference is used ONLY as a structural blueprint.
- Musical content (melody, harmony, drum patterns) is never reproduced.
- Adapter degrades gracefully when reference quality is low.
- Every adaptation decision is written to an explicit decision log.
- The adapter never hard-forces section layouts; it provides weighted guidance.
"""

from __future__ import annotations

import logging
from typing import List, Optional

from app.schemas.reference_arrangement import (
    ReferenceAdaptationStrength,
    ReferenceGuidanceMode,
    ReferenceProducerGuidance,
    ReferenceSectionGuidance,
    ReferenceSection,
    ReferenceStructure,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Section type → producer section type mapping
# ---------------------------------------------------------------------------

# Maps reference section_type_guess → closest ProducerPlanBuilderV2 SectionKind value
_TYPE_MAP: dict[str, str] = {
    "intro": "intro",
    "verse": "verse",
    "hook": "hook",
    "bridge": "bridge",
    "breakdown": "breakdown",
    "outro": "outro",
    "pre_hook": "pre_hook",
    "unknown": "verse",  # Default unknown → verse
}

# Energy level thresholds (0–1) → ProducerPlanBuilderV2 EnergyLevel (1–5)
def _energy_to_level(energy: float) -> int:
    if energy >= 0.85:
        return 5
    if energy >= 0.65:
        return 4
    if energy >= 0.45:
        return 3
    if energy >= 0.25:
        return 2
    return 1


def _density_to_level(density: float) -> str:
    if density >= 0.6:
        return "full"
    if density >= 0.3:
        return "medium"
    return "sparse"


# Transition strength → intent hints
def _transition_in_intent(strength: float, section_type: str) -> str:
    if strength < 0.2:
        return "none"
    if section_type == "hook":
        return "fx_rise" if strength >= 0.5 else "drum_fill"
    if section_type == "breakdown":
        return "pull_back"
    if strength >= 0.6:
        return "fx_hit"
    return "drum_fill"


def _transition_out_intent(strength: float, section_type: str) -> str:
    if strength < 0.2:
        return "none"
    if section_type == "breakdown":
        return "fx_rise"
    if strength >= 0.5:
        return "bass_drop"
    return "drum_fill"


# ---------------------------------------------------------------------------
# Adaptation strength scaling
# ---------------------------------------------------------------------------

# How much to scale confidence requirements + how strictly to follow lengths.
_STRENGTH_CONFIG = {
    ReferenceAdaptationStrength.LOOSE: {
        "min_confidence": 0.55,   # Only follow high-confidence sections
        "energy_weight": 0.3,     # Reduce energy adherence
        "bars_weight": 0.4,       # Reduce length adherence
        "max_sections": 5,        # Simplify to fewer sections
    },
    ReferenceAdaptationStrength.MEDIUM: {
        "min_confidence": 0.4,
        "energy_weight": 0.7,
        "bars_weight": 0.7,
        "max_sections": 8,
    },
    ReferenceAdaptationStrength.CLOSE: {
        "min_confidence": 0.3,    # Use even uncertain sections
        "energy_weight": 1.0,
        "bars_weight": 1.0,
        "max_sections": 12,
    },
}


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------


class ReferencePlanAdapter:
    """Adapts a ReferenceStructure into producer plan guidance.

    Usage
    -----
    ::

        adapter = ReferencePlanAdapter()
        guidance = adapter.adapt(
            structure=ref_structure,
            guidance_mode=ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
            adaptation_strength=ReferenceAdaptationStrength.MEDIUM,
            available_roles=["drums", "bass", "melody"],
            user_tempo_bpm=140.0,
            user_target_bars=64,
        )
    """

    def adapt(
        self,
        structure: ReferenceStructure,
        guidance_mode: ReferenceGuidanceMode,
        adaptation_strength: ReferenceAdaptationStrength,
        available_roles: Optional[List[str]] = None,
        user_tempo_bpm: float = 120.0,
        user_target_bars: Optional[int] = None,
    ) -> ReferenceProducerGuidance:
        """Run adaptation and return :class:`ReferenceProducerGuidance`.

        Always returns a valid guidance object, even if the reference is low
        quality.  In that case, the guidance will be minimal and the decision
        log will explain why.
        """
        available_roles = available_roles or []
        decision_log: List[str] = []

        cfg = _STRENGTH_CONFIG[adaptation_strength]
        min_conf = cfg["min_confidence"]

        # ----------------------------------------------------------------
        # Guard: insufficient analysis
        # ----------------------------------------------------------------
        if structure.analysis_quality == "insufficient" or not structure.sections:
            decision_log.append(
                "Reference analysis quality insufficient — "
                "falling back to standard generation (no reference guidance applied)"
            )
            logger.warning(
                "ReferencePlanAdapter: insufficient reference quality — skipping guidance"
            )
            return ReferenceProducerGuidance(
                section_guidance=[],
                suggested_total_bars=user_target_bars,
                energy_arc_summary="Reference analysis insufficient; using standard generation.",
                adaptation_mode=guidance_mode.value,
                adaptation_strength=adaptation_strength.value,
                reference_confidence=structure.analysis_confidence,
                decision_log=decision_log,
            )

        # ----------------------------------------------------------------
        # Filter sections by confidence
        # ----------------------------------------------------------------
        eligible = [s for s in structure.sections if s.confidence >= min_conf]
        if not eligible:
            decision_log.append(
                f"No sections met confidence threshold ({min_conf:.2f}) for "
                f"adaptation_strength={adaptation_strength.value}; "
                "all sections used with lower trust"
            )
            eligible = list(structure.sections)

        # Cap section count
        max_sections = cfg["max_sections"]
        if len(eligible) > max_sections:
            decision_log.append(
                f"Reference suggested {len(eligible)}-section arc; "
                f"adapted to {max_sections} sections due to adaptation_strength={adaptation_strength.value}"
            )
            eligible = self._subsample_sections(eligible, max_sections)

        # ----------------------------------------------------------------
        # Stem availability check
        # ----------------------------------------------------------------
        stem_count = len([r for r in available_roles if r])
        if stem_count < 3 and len(eligible) > 5:
            old_count = len(eligible)
            eligible = self._subsample_sections(eligible, min(5, len(eligible)))
            decision_log.append(
                f"Reference suggested {old_count}-section arc; "
                f"adapted to {len(eligible)} sections due to limited stem roles ({stem_count} available)"
            )

        # ----------------------------------------------------------------
        # Build per-section guidance
        # ----------------------------------------------------------------
        section_guidance: List[ReferenceSectionGuidance] = []
        bars_weight = cfg["bars_weight"]
        energy_weight = cfg["energy_weight"]

        # Compute target bars per section
        total_ref_duration = structure.total_duration_sec
        ref_tempo = structure.tempo_estimate or user_tempo_bpm

        for sec in eligible:
            # Raw bars from reference (scaled to user tempo if different)
            ref_bars = sec.estimated_bars
            tempo_scale = user_tempo_bpm / max(ref_tempo, 1.0)
            scaled_bars = max(1, int(round(ref_bars * tempo_scale)))

            # Apply bars weight (loose → round to nearest multiple of 4)
            if bars_weight < 0.6:
                scaled_bars = max(4, round(scaled_bars / 4) * 4)
            else:
                scaled_bars = max(2, scaled_bars)

            # Section type
            section_type = _TYPE_MAP.get(sec.section_type_guess, "verse")

            # Energy & density
            if guidance_mode in (
                ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
                ReferenceGuidanceMode.ENERGY_ONLY,
            ):
                raw_energy = sec.energy_level
                # Blend with neutral (3) according to energy_weight
                blended_energy = raw_energy * energy_weight + 0.5 * (1.0 - energy_weight)
                target_energy = _energy_to_level(blended_energy)
                target_density = _density_to_level(
                    sec.density_level * energy_weight + 0.5 * (1.0 - energy_weight)
                )
            else:
                # Structure-only: neutral energy
                target_energy = 3
                target_density = "medium"

            # Transitions
            if guidance_mode in (
                ReferenceGuidanceMode.STRUCTURE_AND_ENERGY,
                ReferenceGuidanceMode.ENERGY_ONLY,
            ):
                trans_in = _transition_in_intent(sec.transition_in_strength, section_type)
                trans_out = _transition_out_intent(sec.transition_out_strength, section_type)
            else:
                trans_in = "none"
                trans_out = "none"

            note = (
                f"Reference {sec.section_type_guess} ({sec.start_time_sec:.0f}s–"
                f"{sec.end_time_sec:.0f}s, conf={sec.confidence:.2f})"
            )

            section_guidance.append(
                ReferenceSectionGuidance(
                    index=sec.index,
                    section_type=section_type,
                    target_bars=scaled_bars,
                    target_energy=target_energy,
                    target_density=target_density,
                    transition_in_intent=trans_in,
                    transition_out_intent=trans_out,
                    confidence=sec.confidence,
                    adaptation_note=note,
                )
            )

        # ----------------------------------------------------------------
        # Suggested total bars
        # ----------------------------------------------------------------
        if guidance_mode != ReferenceGuidanceMode.ENERGY_ONLY:
            suggested_bars = sum(g.target_bars for g in section_guidance)
            if user_target_bars:
                # Snap to user target if within 30%
                delta = abs(suggested_bars - user_target_bars) / max(user_target_bars, 1)
                if delta > 0.3:
                    decision_log.append(
                        f"Reference implied {suggested_bars} bars but user requested "
                        f"{user_target_bars} bars; using user target"
                    )
                    suggested_bars = user_target_bars
            else:
                suggested_bars = max(16, suggested_bars)
        else:
            suggested_bars = user_target_bars or 64

        # ----------------------------------------------------------------
        # Energy arc summary
        # ----------------------------------------------------------------
        energy_arc = self._describe_energy_arc(structure, eligible, decision_log)

        # ----------------------------------------------------------------
        # Final log entries
        # ----------------------------------------------------------------
        decision_log.append(
            f"Adapter: mode={guidance_mode.value}, strength={adaptation_strength.value}, "
            f"reference_confidence={structure.analysis_confidence:.2f}, "
            f"sections={len(section_guidance)}, suggested_bars={suggested_bars}"
        )

        logger.info(
            "ReferencePlanAdapter: %d sections adapted, total_bars=%d, confidence=%.2f",
            len(section_guidance),
            suggested_bars,
            structure.analysis_confidence,
        )

        return ReferenceProducerGuidance(
            section_guidance=section_guidance,
            suggested_total_bars=suggested_bars,
            energy_arc_summary=energy_arc,
            adaptation_mode=guidance_mode.value,
            adaptation_strength=adaptation_strength.value,
            reference_confidence=structure.analysis_confidence,
            decision_log=decision_log,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _subsample_sections(
        sections: List[ReferenceSection], target: int
    ) -> List[ReferenceSection]:
        """Downsample sections list to roughly `target` sections.

        Always keeps the first (intro) and last (outro) sections.
        """
        if len(sections) <= target:
            return sections
        if target <= 2:
            return [sections[0], sections[-1]]

        # Keep first and last; evenly sample the rest
        middle = sections[1:-1]
        step = max(1, len(middle) // (target - 2))
        kept_middle = middle[::step][: target - 2]
        return [sections[0]] + kept_middle + [sections[-1]]

    @staticmethod
    def _describe_energy_arc(
        structure: ReferenceStructure,
        sections: List[ReferenceSection],
        decision_log: List[str],
    ) -> str:
        """Generate a human-readable energy arc description and log key events."""
        if not sections:
            return "No energy arc available."

        energies = [s.energy_level for s in sections]
        peak_idx = energies.index(max(energies))
        valley_idx = energies.index(min(energies))
        peak_sec = sections[peak_idx]
        valley_sec = sections[valley_idx]

        decision_log.append(
            f"Energy peak preserved near section {peak_sec.section_type_guess} "
            f"({peak_sec.start_time_sec:.0f}s)"
        )

        if valley_sec.section_type_guess == "breakdown":
            decision_log.append(
                f"Breakdown energy valley at {valley_sec.start_time_sec:.0f}s preserved"
            )

        n = len(sections)
        first_half_avg = sum(e for e in energies[: n // 2]) / max(n // 2, 1)
        second_half_avg = sum(e for e in energies[n // 2 :]) / max(n - n // 2, 1)
        arc_shape = "builds toward end" if second_half_avg > first_half_avg + 0.1 else \
                    "peaks in middle" if peak_idx == n // 2 else "standard"

        return (
            f"{n} sections, peak at {peak_sec.section_type_guess} "
            f"({peak_sec.start_time_sec:.0f}s), arc={arc_shape}"
        )


# Module-level singleton
reference_plan_adapter = ReferencePlanAdapter()
