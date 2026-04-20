"""
Repair Agent — automatically fixes weak AI producer plans.

Responsibilities:
- Detect specific weaknesses from critic scores.
- Apply targeted, concrete repairs.
- Emit structured AIRepairAction records.
- Limit to MAX_REPAIR_PASSES passes before declaring the plan unrepairable.
"""

from __future__ import annotations

import dataclasses
import logging
from typing import Any, Optional

from app.services.ai_producer_system.schemas import (
    AICriticScore,
    AIMicroPlanEvent,
    AIProducerPlan,
    AIRepairAction,
    AISectionPlan,
    VALID_TRANSITIONS,
)
from app.services.ai_producer_system.scoring import (
    CRITICAL_SUBSCORE_THRESHOLD,
    OVERALL_ACCEPTANCE_THRESHOLD,
)

logger = logging.getLogger(__name__)

MAX_REPAIR_PASSES = 2

# Fallback transition pool — used when transitions are too homogeneous
_VARIED_TRANSITIONS = [
    "drum_fill",
    "riser",
    "reverse_cymbal",
    "filter_sweep",
    "stutter",
    "fade_out",
    "crossfade",
    "cut",
]


class RepairAgent:
    """Repairs weak :class:`AIProducerPlan` instances.

    Each call to :meth:`repair` performs one repair pass and returns
    (repaired_plan, repair_actions).  The orchestrator is responsible for
    limiting the number of passes.
    """

    def repair(
        self,
        plan: AIProducerPlan,
        score: AICriticScore,
        available_roles: Optional[list[str]] = None,
    ) -> tuple[AIProducerPlan, list[AIRepairAction]]:
        """Apply all necessary repairs to *plan* based on *score*.

        Parameters
        ----------
        plan:
            The plan to repair (modified in-place; sections are replaced
            with updated copies where necessary).
        score:
            The critic scores that triggered repair.
        available_roles:
            All available stem roles, used when injecting new elements.

        Returns
        -------
        tuple[AIProducerPlan, list[AIRepairAction]]
            The repaired plan and a list of :class:`AIRepairAction` records.
        """
        logger.info(
            "REPAIR: starting pass — overall=%.3f  rsc=%.3f  hp=%.3f  tq=%.3f",
            score.overall_score,
            score.repeated_section_contrast_score,
            score.hook_payoff_score,
            score.transition_quality_score,
        )

        roles = list(available_roles or [])
        actions: list[AIRepairAction] = []

        # Work on a shallow copy of section_plans to avoid mutating during iteration
        section_plans = list(plan.section_plans)

        # 1. Repeated sections too similar
        if score.repeated_section_contrast_score < CRITICAL_SUBSCORE_THRESHOLD + 0.10:
            actions.extend(self._repair_repeated_sections(section_plans))

        # 2. Hook too weak
        if score.hook_payoff_score < CRITICAL_SUBSCORE_THRESHOLD + 0.10:
            actions.extend(self._repair_hook_payoff(section_plans, roles))

        # 3. Transitions too uniform
        if score.transition_quality_score < CRITICAL_SUBSCORE_THRESHOLD + 0.10:
            actions.extend(self._repair_transitions(section_plans))

        # 4. Bridge/breakdown too dense
        actions.extend(self._repair_bridge_breakdown_density(section_plans))

        # 5. Outro too full
        actions.extend(self._repair_outro(section_plans))

        # 6. Micro plan too sparse
        if score.timeline_movement_score < 0.40:
            micro_actions, new_events = self._repair_micro_plan(section_plans, plan.micro_plan_events)
            actions.extend(micro_actions)
            plan = dataclasses.replace(plan, micro_plan_events=new_events)

        # 7. Vague variation strategies
        if score.vagueness_score < CRITICAL_SUBSCORE_THRESHOLD + 0.10:
            actions.extend(self._repair_vague_strategies(section_plans))

        # Commit updated section plans
        plan = dataclasses.replace(
            plan,
            section_plans=section_plans,
            global_energy_curve=[sp.target_energy for sp in section_plans],
        )

        logger.info("REPAIR: completed — %d repair actions applied", len(actions))
        return plan, actions

    # ------------------------------------------------------------------
    # Repair routines
    # ------------------------------------------------------------------

    def _repair_repeated_sections(
        self, section_plans: list[AISectionPlan]
    ) -> list[AIRepairAction]:
        actions: list[AIRepairAction] = []
        seen: dict[str, int] = {}  # name → index of first occurrence in list

        for idx, sp in enumerate(section_plans):
            key = sp.section_name
            if key in seen:
                prior_idx = seen[key]
                prior = section_plans[prior_idx]

                before = {"target_energy": sp.target_energy, "variation_strategy": sp.variation_strategy}

                # Inject concrete energy delta
                new_energy = min(1.0, prior.target_energy + 0.08)
                new_strat = (
                    f"{sp.section_name.title()} occurrence {sp.occurrence}: "
                    f"shift primary rhythmic grid to dotted-8th feel, "
                    f"introduce counter-melody on '{sp.active_roles[0] if sp.active_roles else 'melody'}' "
                    f"starting bar 3, push energy from {prior.target_energy:.2f} to {new_energy:.2f}."
                )

                section_plans[idx] = dataclasses.replace(
                    sp,
                    target_energy=round(new_energy, 3),
                    variation_strategy=new_strat,
                )

                after = {
                    "target_energy": section_plans[idx].target_energy,
                    "variation_strategy": new_strat,
                }

                actions.append(AIRepairAction(
                    section_name=sp.section_name,
                    reason=(
                        f"Repeated section '{sp.section_name}' occurrence {sp.occurrence} "
                        "was too similar to prior occurrence."
                    ),
                    action_taken=(
                        "Raised energy by 0.08 and injected concrete variation strategy "
                        "specifying rhythmic shift + counter-melody introduction."
                    ),
                    before=before,
                    after=after,
                ))
            else:
                seen[key] = idx

        return actions

    def _repair_hook_payoff(
        self,
        section_plans: list[AISectionPlan],
        roles: list[str],
    ) -> list[AIRepairAction]:
        actions: list[AIRepairAction] = []
        verses = [sp for sp in section_plans if sp.section_name == "verse"]
        avg_verse_energy = (
            sum(v.target_energy for v in verses) / len(verses) if verses else 0.55
        )

        for idx, sp in enumerate(section_plans):
            if sp.section_name not in ("hook", "chorus"):
                continue

            before = {
                "target_energy": sp.target_energy,
                "introduced_elements": list(sp.introduced_elements),
            }

            # Ensure hook energy > verse energy by at least 0.15
            new_energy = max(sp.target_energy, min(1.0, avg_verse_energy + 0.20))
            new_density = min(1.0, sp.target_density + 0.10)

            # Add payoff element if introduced_elements is empty
            new_intro = list(sp.introduced_elements)
            if not new_intro:
                payoff_role = next(
                    (r for r in roles if "melody" in r or "vocal" in r),
                    roles[0] if roles else "melody",
                )
                new_intro.append(payoff_role)

            section_plans[idx] = dataclasses.replace(
                sp,
                target_energy=round(new_energy, 3),
                target_density=round(new_density, 3),
                introduced_elements=new_intro,
            )

            after = {
                "target_energy": section_plans[idx].target_energy,
                "introduced_elements": list(section_plans[idx].introduced_elements),
            }

            actions.append(AIRepairAction(
                section_name=sp.section_name,
                reason=(
                    f"Hook payoff insufficient: energy {sp.target_energy:.2f} "
                    f"not enough above verse average {avg_verse_energy:.2f}."
                ),
                action_taken=(
                    f"Raised hook energy to {new_energy:.2f}, "
                    f"density to {new_density:.2f}, "
                    f"added payoff element '{new_intro[-1]}'."
                ),
                before=before,
                after=after,
            ))

        return actions

    def _repair_transitions(
        self, section_plans: list[AISectionPlan]
    ) -> list[AIRepairAction]:
        """Diversify transitions that are too homogeneous."""
        actions: list[AIRepairAction] = []
        if not section_plans:
            return actions

        # Collect current transitions
        transition_pool = list(_VARIED_TRANSITIONS)
        used: list[str] = [sp.transition_out for sp in section_plans]
        unique_count = len(set(used))

        if unique_count >= max(2, len(section_plans) // 3):
            return actions  # Already diverse enough

        for idx, sp in enumerate(section_plans):
            if idx == 0:
                continue  # Skip first section

            before = {"transition_out": sp.transition_out}

            # Pick a transition different from the previous section's
            prev_trans = section_plans[idx - 1].transition_out
            candidates = [t for t in transition_pool if t != prev_trans]
            new_trans = candidates[idx % len(candidates)]

            section_plans[idx] = dataclasses.replace(sp, transition_out=new_trans)

            after = {"transition_out": new_trans}

            actions.append(AIRepairAction(
                section_name=sp.section_name,
                reason=(
                    f"Transition at end of '{sp.section_name}' occurrence {sp.occurrence} "
                    "was duplicating adjacent transition types."
                ),
                action_taken=(
                    f"Substituted transition_out from '{prev_trans}' to '{new_trans}'."
                ),
                before=before,
                after=after,
            ))

        return actions

    def _repair_bridge_breakdown_density(
        self, section_plans: list[AISectionPlan]
    ) -> list[AIRepairAction]:
        """Ensure bridge/breakdown density is below average."""
        actions: list[AIRepairAction] = []
        if not section_plans:
            return actions

        avg_density = sum(sp.target_density for sp in section_plans) / len(section_plans)

        for idx, sp in enumerate(section_plans):
            if sp.section_name not in ("bridge", "breakdown"):
                continue
            if sp.target_density < avg_density:
                continue

            before = {"target_density": sp.target_density, "active_roles": list(sp.active_roles)}

            new_density = max(0.10, avg_density - 0.20)
            stripped_roles = sp.active_roles[: max(1, len(sp.active_roles) // 2)]

            section_plans[idx] = dataclasses.replace(
                sp,
                target_density=round(new_density, 3),
                active_roles=stripped_roles,
            )

            after = {
                "target_density": section_plans[idx].target_density,
                "active_roles": list(section_plans[idx].active_roles),
            }

            actions.append(AIRepairAction(
                section_name=sp.section_name,
                reason=(
                    f"'{sp.section_name}' density {sp.target_density:.2f} >= "
                    f"arrangement average {avg_density:.2f} — must be reduced."
                ),
                action_taken=(
                    f"Stripped to {len(stripped_roles)} roles, "
                    f"reduced density to {new_density:.2f}."
                ),
                before=before,
                after=after,
            ))

        return actions

    def _repair_outro(self, section_plans: list[AISectionPlan]) -> list[AIRepairAction]:
        """Simplify outro — must reduce energy and density."""
        actions: list[AIRepairAction] = []
        if not section_plans:
            return actions

        avg_energy = sum(sp.target_energy for sp in section_plans) / len(section_plans)
        avg_density = sum(sp.target_density for sp in section_plans) / len(section_plans)

        for idx, sp in enumerate(section_plans):
            if sp.section_name != "outro":
                continue
            if sp.target_energy < avg_energy and sp.target_density < avg_density:
                continue

            before = {"target_energy": sp.target_energy, "target_density": sp.target_density}

            new_energy = max(0.10, avg_energy - 0.25)
            new_density = max(0.10, avg_density - 0.25)

            section_plans[idx] = dataclasses.replace(
                sp,
                target_energy=round(new_energy, 3),
                target_density=round(new_density, 3),
            )

            after = {
                "target_energy": section_plans[idx].target_energy,
                "target_density": section_plans[idx].target_density,
            }

            actions.append(AIRepairAction(
                section_name="outro",
                reason=(
                    f"Outro energy {sp.target_energy:.2f} or density {sp.target_density:.2f} "
                    "too high — outro must simplify."
                ),
                action_taken=(
                    f"Reduced outro energy to {new_energy:.2f}, density to {new_density:.2f}."
                ),
                before=before,
                after=after,
            ))

        return actions

    def _repair_micro_plan(
        self,
        section_plans: list[AISectionPlan],
        existing_events: list[AIMicroPlanEvent],
    ) -> tuple[list[AIRepairAction], list[AIMicroPlanEvent]]:
        """Inject missing internal motion events into long sections."""
        actions: list[AIRepairAction] = []
        new_events = list(existing_events)

        for sp in section_plans:
            if sp.bars < 8 or not sp.active_roles:
                continue

            # Check how many events already exist for this section (by bar range)
            existing_count = sum(
                1 for e in existing_events if 1 <= e.bar_start <= sp.bars
            )
            if existing_count >= sp.bars // 4:
                continue

            primary = sp.active_roles[0]
            injected = 0
            bar = 4
            while bar <= sp.bars:
                new_events.append(AIMicroPlanEvent(
                    bar_start=bar,
                    bar_end=bar,
                    role=primary,
                    action="pattern_change",
                    intensity=0.5,
                    notes=(
                        f"Auto-injected motion event at bar {bar} "
                        f"in '{sp.section_name}' occurrence {sp.occurrence}."
                    ),
                ))
                injected += 1
                bar += 4

            if injected:
                actions.append(AIRepairAction(
                    section_name=sp.section_name,
                    reason=(
                        f"'{sp.section_name}' ({sp.bars} bars) had too few micro-plan events "
                        f"(found {existing_count})."
                    ),
                    action_taken=(
                        f"Injected {injected} 'pattern_change' events every 4 bars "
                        f"on role '{primary}'."
                    ),
                    before={"micro_event_count": existing_count},
                    after={"micro_event_count": existing_count + injected},
                ))

        return actions, new_events

    def _repair_vague_strategies(
        self, section_plans: list[AISectionPlan]
    ) -> list[AIRepairAction]:
        """Replace vague variation strategies with concrete instructions."""
        from app.services.ai_producer_system.scoring import contains_vague_phrase

        actions: list[AIRepairAction] = []

        for idx, sp in enumerate(section_plans):
            if sp.occurrence <= 1:
                continue
            if not contains_vague_phrase(sp.variation_strategy):
                continue

            before = {"variation_strategy": sp.variation_strategy}

            concrete = (
                f"{sp.section_name.title()} occurrence {sp.occurrence}: "
                f"shift hi-hat pattern to 32nd-note triplet subdivision on bars 3–4, "
                f"detune '{sp.active_roles[0] if sp.active_roles else 'primary'}' layer by +7 cents, "
                f"replace transition_out with 'reverse_cymbal' for ear-pull effect."
            )
            section_plans[idx] = dataclasses.replace(sp, variation_strategy=concrete)

            after = {"variation_strategy": concrete}

            actions.append(AIRepairAction(
                section_name=sp.section_name,
                reason=(
                    f"'{sp.section_name}' occurrence {sp.occurrence} variation_strategy "
                    "contained vague language."
                ),
                action_taken="Replaced with concrete rhythmic/timbral instructions.",
                before=before,
                after=after,
            ))

        return actions
