"""
Decision Engine public API.

The Decision Engine is the "producer brain" that sits ABOVE the Timeline,
Pattern Variation, Groove, Drop, and Motif engines.  It decides:

- what roles should be held back
- what roles should be removed temporarily
- what roles should re-enter for payoff
- whether a section should feel sparse, medium, or full
- whether repeated sections need stronger contrast

Import the public surface from this package::

    from app.services.decision_engine import (
        DecisionAction,
        DecisionPlan,
        DecisionPlanner,
        DecisionValidator,
        DecisionValidationIssue,
        DecisionEngineState,
        SectionDecision,
        SUPPORTED_ACTION_TYPES,
        SUBTRACTIVE_ACTION_TYPES,
        ADDITIVE_ACTION_TYPES,
        VALID_FULLNESS_LABELS,
    )
"""

from app.services.decision_engine.state import DecisionEngineState
from app.services.decision_engine.types import (
    ADDITIVE_ACTION_TYPES,
    SUBTRACTIVE_ACTION_TYPES,
    SUPPORTED_ACTION_TYPES,
    VALID_FULLNESS_LABELS,
    DecisionAction,
    DecisionPlan,
    DecisionValidationIssue,
    SectionDecision,
)
from app.services.decision_engine.planner import DecisionPlanner
from app.services.decision_engine.validator import DecisionValidator

__all__ = [
    "DecisionAction",
    "DecisionEngineState",
    "DecisionPlan",
    "DecisionPlanner",
    "DecisionValidationIssue",
    "DecisionValidator",
    "SectionDecision",
    "SUPPORTED_ACTION_TYPES",
    "SUBTRACTIVE_ACTION_TYPES",
    "ADDITIVE_ACTION_TYPES",
    "VALID_FULLNESS_LABELS",
]
