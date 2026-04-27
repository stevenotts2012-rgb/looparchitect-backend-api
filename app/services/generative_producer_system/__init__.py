"""
Multi-Genre Generative Producer System.

Generates audio-actionable producer events from the user's uploaded
loop/stems using deterministic procedural generation.  Supports trap,
drill, rnb, rage, west_coast, and a generic fallback genre.

Shadow mode only — does NOT drive live rendering.
"""

from app.services.generative_producer_system.types import (
    ProducerEvent,
    GenreProducerProfile,
    ProducerPlan,
)
from app.services.generative_producer_system.orchestrator import (
    GenerativeProducerOrchestrator,
    plan_to_dict,
)

__all__ = [
    "ProducerEvent",
    "GenreProducerProfile",
    "ProducerPlan",
    "GenerativeProducerOrchestrator",
    "plan_to_dict",
]
