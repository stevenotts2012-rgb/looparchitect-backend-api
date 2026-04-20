"""
AI Producer System — multi-agent producer workflow for LoopArchitect.

Public API:
- AIProducerOrchestrator  — runs the full planner → critic → repair → validate pipeline
- PlannerAgent            — builds strict arrangement plans
- CriticAgent             — scores plans like a producer / A&R reviewer
- RepairAgent             — fixes weak plans before they reach the renderer
- validate_plan           — hard-rule post-repair validator
- result_to_dict          — serialise AIProducerResult to a JSON-safe dict

Shadow mode only — does NOT drive live rendering.
"""

from app.services.ai_producer_system.schemas import (
    AICriticScore,
    AIMicroPlanEvent,
    AIProducerPlan,
    AIProducerResult,
    AIRepairAction,
    AISectionPlan,
    VALID_TRANSITIONS,
    VAGUE_PHRASES,
)
from app.services.ai_producer_system.planner_agent import PlannerAgent
from app.services.ai_producer_system.critic_agent import CriticAgent
from app.services.ai_producer_system.repair_agent import RepairAgent, MAX_REPAIR_PASSES
from app.services.ai_producer_system.validator import validate_plan
from app.services.ai_producer_system.orchestrator import AIProducerOrchestrator, result_to_dict

__all__ = [
    # Schemas
    "AICriticScore",
    "AIMicroPlanEvent",
    "AIProducerPlan",
    "AIProducerResult",
    "AIRepairAction",
    "AISectionPlan",
    "VALID_TRANSITIONS",
    "VAGUE_PHRASES",
    # Agents
    "PlannerAgent",
    "CriticAgent",
    "RepairAgent",
    "MAX_REPAIR_PASSES",
    # Validator
    "validate_plan",
    # Orchestrator
    "AIProducerOrchestrator",
    "result_to_dict",
]
