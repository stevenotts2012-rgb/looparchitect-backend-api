"""
Orchestrator — runs the full multi-agent producer workflow.

Pipeline:
1. PlannerAgent  → builds initial plan
2. CriticAgent   → scores the plan
3. RepairAgent   → repairs weak plans (up to MAX_REPAIR_PASSES)
4. CriticAgent   → re-scores after repair
5. Validator     → hard-rule validation
6. Fallback      → deterministic fallback plan if still weak
7. Return AIProducerResult

Design principles:
- Deterministic execution — no randomness.
- Observability — every step is logged.
- Graceful failure — arrangement jobs always complete even if AI fails.
- Never drives live rendering — shadow mode only.
"""

from __future__ import annotations

import dataclasses
import json
import logging
from typing import Any, Optional

from app.services.ai_producer_system.critic_agent import CriticAgent
from app.services.ai_producer_system.planner_agent import PlannerAgent
from app.services.ai_producer_system.repair_agent import MAX_REPAIR_PASSES, RepairAgent
from app.services.ai_producer_system.schemas import (
    AICriticScore,
    AIMicroPlanEvent,
    AIProducerPlan,
    AIProducerResult,
    AIRepairAction,
    AISectionPlan,
)
from app.services.ai_producer_system.validator import validate_plan

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Deterministic fallback plan
# ---------------------------------------------------------------------------

def _build_fallback_plan(
    section_template: list[dict[str, Any]],
    available_roles: list[str],
) -> AIProducerPlan:
    """Build a minimal deterministic fallback plan.

    This plan satisfies all hard rules by construction and is used when
    the AI planner + repair cycle cannot produce an acceptable result.
    """
    logger.warning(
        "ORCHESTRATOR: building deterministic fallback plan for %d sections",
        len(section_template),
    )

    section_plans: list[AISectionPlan] = []
    energy_levels = [0.35, 0.55, 0.70, 0.85, 0.40, 0.30]
    density_levels = [0.30, 0.50, 0.65, 0.80, 0.30, 0.25]

    occurrence_counter: dict[str, int] = {}
    for i, spec in enumerate(section_template):
        name = str(spec.get("name", "verse")).strip().lower()
        bars = max(1, int(spec.get("bars", 8)))
        occurrence_counter[name] = occurrence_counter.get(name, 0) + 1
        occ = occurrence_counter[name]

        energy = energy_levels[i % len(energy_levels)]
        density = density_levels[i % len(density_levels)]

        # Override for specific sections
        if name in ("hook", "chorus"):
            energy = min(1.0, 0.85 + (occ - 1) * 0.05)
            density = min(1.0, 0.80 + (occ - 1) * 0.05)
        elif name in ("bridge", "breakdown"):
            energy = 0.30
            density = 0.20
        elif name == "outro":
            energy = 0.25
            density = 0.20

        n_roles = max(1, round(len(available_roles) * density)) if available_roles else 1
        active_roles = available_roles[:n_roles]

        variation_strategy = ""
        if occ > 1:
            variation_strategy = (
                f"{name.title()} occurrence {occ}: increase upper-register activity, "
                f"shift drum pattern to off-beat 16th emphasis, "
                f"introduce additional '{active_roles[0] if active_roles else 'melody'}' layer."
            )

        sp = AISectionPlan(
            section_name=name,
            occurrence=occ,
            bars=bars,
            target_energy=round(energy, 3),
            target_density=round(density, 3),
            active_roles=list(active_roles),
            introduced_elements=list(active_roles[:1]),
            dropped_elements=[],
            transition_in="cut",
            transition_out="drum_fill",
            variation_strategy=variation_strategy,
            micro_timeline_notes=f"Fallback section: bars 1–{bars}.",
            rationale=f"Deterministic fallback: {name}, energy={energy:.2f}, density={density:.2f}.",
        )
        section_plans.append(sp)

    # Ensure energy curve is not flat
    energies = [sp.target_energy for sp in section_plans]
    if (max(energies) - min(energies)) < 0.10 and len(section_plans) >= 2:
        section_plans[0] = dataclasses.replace(
            section_plans[0],
            target_energy=max(0.0, section_plans[0].target_energy - 0.15),
        )
        section_plans[-1] = dataclasses.replace(
            section_plans[-1],
            target_energy=max(0.0, section_plans[-1].target_energy - 0.15),
        )

    energy_curve = [sp.target_energy for sp in section_plans]

    # Minimal micro events
    micro_events: list[AIMicroPlanEvent] = []
    if available_roles:
        for sp in section_plans:
            if sp.bars >= 8:
                micro_events.append(AIMicroPlanEvent(
                    bar_start=sp.bars // 2,
                    bar_end=sp.bars // 2,
                    role=available_roles[0],
                    action="pattern_change",
                    intensity=0.5,
                    notes=f"Fallback midpoint event in '{sp.section_name}'.",
                ))

    return AIProducerPlan(
        section_plans=section_plans,
        micro_plan_events=micro_events,
        global_energy_curve=energy_curve,
        novelty_targets={},
        risk_flags=["FALLBACK_PLAN: deterministic fallback used — AI plan was unacceptable."],
        planner_notes="Deterministic fallback plan.",
    )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class AIProducerOrchestrator:
    """Runs the full multi-agent producer workflow.

    Parameters
    ----------
    available_roles:
        Stem/instrument roles available in the source material.
    source_quality:
        One of ``"true_stems"``, ``"zip_stems"``, ``"ai_separated"``,
        ``"stereo_fallback"``.
    arrangement_id:
        Optional ID for log correlation.
    correlation_id:
        Optional correlation ID for log correlation.
    """

    def __init__(
        self,
        available_roles: Optional[list[str]] = None,
        source_quality: str = "stereo_fallback",
        arrangement_id: Optional[int] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        self.available_roles = list(available_roles or [])
        self.source_quality = source_quality
        self.arrangement_id = arrangement_id
        self.correlation_id = correlation_id or "n/a"

        self._planner = PlannerAgent(
            available_roles=self.available_roles,
            source_quality=source_quality,
        )
        self._critic = CriticAgent()
        self._repair = RepairAgent()

    def run(
        self,
        section_template: list[dict[str, Any]],
        reference_profile: Optional[dict[str, Any]] = None,
    ) -> AIProducerResult:
        """Execute the full producer pipeline and return an :class:`AIProducerResult`.

        This method never raises — all exceptions are caught and recorded in the
        result so that arrangement jobs always complete.

        Parameters
        ----------
        section_template:
            Ordered list of dicts describing the arrangement structure.
        reference_profile:
            Optional reference track profile.

        Returns
        -------
        AIProducerResult
        """
        logger.info(
            "ORCHESTRATOR [arr=%s corr=%s]: starting — %d sections, quality=%s, roles=%s",
            self.arrangement_id,
            self.correlation_id,
            len(section_template),
            self.source_quality,
            self.available_roles,
        )

        try:
            return self._run_pipeline(section_template, reference_profile)
        except Exception:
            logger.exception(
                "ORCHESTRATOR [arr=%s corr=%s]: unexpected error — returning fallback result",
                self.arrangement_id,
                self.correlation_id,
            )
            fallback_plan = _build_fallback_plan(section_template, self.available_roles)
            critic_score = self._critic.score(fallback_plan)
            validator_ok, validator_msgs = validate_plan(
                fallback_plan, self.available_roles, self.source_quality
            )
            return AIProducerResult(
                planner_output=fallback_plan,
                critic_scores=critic_score,
                repair_actions=[],
                validator_warnings=validator_msgs,
                accepted=validator_ok,
                rejected_reason="Unexpected error in AI producer pipeline — fallback used.",
                fallback_used=True,
            )

    def _run_pipeline(
        self,
        section_template: list[dict[str, Any]],
        reference_profile: Optional[dict[str, Any]],
    ) -> AIProducerResult:
        all_repair_actions: list[AIRepairAction] = []

        # ------------------------------------------------------------------
        # Step 1: Plan
        # ------------------------------------------------------------------
        logger.info("ORCHESTRATOR: step 1 — planner")
        plan = self._planner.build_plan(
            section_template=section_template,
            reference_profile=reference_profile,
        )

        # ------------------------------------------------------------------
        # Step 2: Critic (first pass)
        # ------------------------------------------------------------------
        logger.info("ORCHESTRATOR: step 2 — critic (initial)")
        score = self._critic.score(plan)

        # ------------------------------------------------------------------
        # Step 3: Repair loop
        # ------------------------------------------------------------------
        repair_pass = 0
        while not self._critic.is_acceptable(score) and repair_pass < MAX_REPAIR_PASSES:
            repair_pass += 1
            logger.info(
                "ORCHESTRATOR: step 3 — repair pass %d/%d (overall=%.3f)",
                repair_pass,
                MAX_REPAIR_PASSES,
                score.overall_score,
            )
            plan, actions = self._repair.repair(
                plan=plan,
                score=score,
                available_roles=self.available_roles,
            )
            all_repair_actions.extend(actions)

            # Re-score after repair
            score = self._critic.score(plan)
            logger.info(
                "ORCHESTRATOR: post-repair score — overall=%.3f (pass %d)",
                score.overall_score,
                repair_pass,
            )

        # ------------------------------------------------------------------
        # Step 4: Validate
        # ------------------------------------------------------------------
        logger.info("ORCHESTRATOR: step 4 — validator")
        validator_ok, validator_msgs = validate_plan(
            plan, self.available_roles, self.source_quality
        )

        # ------------------------------------------------------------------
        # Step 5: Accept / reject / fallback
        # ------------------------------------------------------------------
        accepted = self._critic.is_acceptable(score) and validator_ok
        rejected_reason = ""
        fallback_used = False

        if not accepted:
            logger.warning(
                "ORCHESTRATOR: plan rejected — overall=%.3f, validator_ok=%s, repair_passes=%d",
                score.overall_score,
                validator_ok,
                repair_pass,
            )
            rejected_reason = (
                f"Plan failed after {repair_pass} repair pass(es). "
                f"overall_score={score.overall_score:.3f}, "
                f"validator_ok={validator_ok}. "
                f"Switching to deterministic fallback."
            )

            # Build fallback
            fallback_plan = _build_fallback_plan(section_template, self.available_roles)
            fallback_score = self._critic.score(fallback_plan)
            fallback_ok, fallback_msgs = validate_plan(
                fallback_plan, self.available_roles, self.source_quality
            )

            plan = fallback_plan
            score = fallback_score
            validator_msgs = fallback_msgs
            accepted = fallback_ok
            fallback_used = True
        else:
            logger.info(
                "ORCHESTRATOR: plan accepted — overall=%.3f after %d repair pass(es)",
                score.overall_score,
                repair_pass,
            )

        result = AIProducerResult(
            planner_output=plan,
            critic_scores=score,
            repair_actions=all_repair_actions,
            validator_warnings=validator_msgs,
            accepted=accepted,
            rejected_reason=rejected_reason,
            fallback_used=fallback_used,
        )
        self._log_result(result, repair_pass)
        return result

    def _log_result(self, result: AIProducerResult, repair_passes: int) -> None:
        logger.info(
            "ORCHESTRATOR [arr=%s corr=%s]: complete — "
            "accepted=%s fallback=%s repairs=%d validator_warnings=%d "
            "overall=%.3f",
            self.arrangement_id,
            self.correlation_id,
            result.accepted,
            result.fallback_used,
            len(result.repair_actions),
            len(result.validator_warnings),
            result.critic_scores.overall_score if result.critic_scores else 0.0,
        )


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------

def result_to_dict(result: AIProducerResult) -> dict[str, Any]:
    """Serialise an :class:`AIProducerResult` to a JSON-safe dict."""
    import dataclasses as dc

    def _serialise(obj: Any) -> Any:
        if dc.is_dataclass(obj) and not isinstance(obj, type):
            return {k: _serialise(v) for k, v in dc.asdict(obj).items()}
        if isinstance(obj, list):
            return [_serialise(i) for i in obj]
        if isinstance(obj, dict):
            return {k: _serialise(v) for k, v in obj.items()}
        return obj

    return _serialise(result)
