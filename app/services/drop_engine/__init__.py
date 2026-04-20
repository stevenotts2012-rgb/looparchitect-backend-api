"""
Drop Engine — public API.

Import the main classes and helpers from this package::

    from app.services.drop_engine import (
        DropEnginePlanner,
        DropValidator,
        DropValidationIssue,
        DropEngineState,
        DropEvent,
        DropBoundaryPlan,
        DropPlan,
        SUPPORTED_DROP_EVENT_TYPES,
        STRONG_EVENT_TYPES,
        VALID_PLACEMENTS,
    )
"""

from app.services.drop_engine.types import (
    DropBoundaryPlan,
    DropEvent,
    DropPlan,
    STRONG_EVENT_TYPES,
    SUPPORTED_DROP_EVENT_TYPES,
    VALID_PLACEMENTS,
)
from app.services.drop_engine.state import DropEngineState
from app.services.drop_engine.planner import DropEnginePlanner
from app.services.drop_engine.validator import DropValidator, DropValidationIssue

__all__ = [
    "DropEnginePlanner",
    "DropValidator",
    "DropValidationIssue",
    "DropEngineState",
    "DropEvent",
    "DropBoundaryPlan",
    "DropPlan",
    "SUPPORTED_DROP_EVENT_TYPES",
    "STRONG_EVENT_TYPES",
    "VALID_PLACEMENTS",
]
