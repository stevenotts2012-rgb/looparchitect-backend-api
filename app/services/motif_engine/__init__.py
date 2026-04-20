"""
Motif Engine — public API.

Import the main classes and helpers from this package::

    from app.services.motif_engine import (
        MotifPlanner,
        MotifExtractor,
        MotifValidator,
        MotifValidationIssue,
        MotifEngineState,
        Motif,
        MotifTransformation,
        MotifOccurrence,
        MotifPlan,
        SUPPORTED_MOTIF_TYPES,
        SUPPORTED_TRANSFORMATION_TYPES,
        STRONG_TRANSFORMATION_TYPES,
        WEAK_TRANSFORMATION_TYPES,
    )
"""

from app.services.motif_engine.types import (
    Motif,
    MotifOccurrence,
    MotifPlan,
    MotifTransformation,
    STRONG_TRANSFORMATION_TYPES,
    SUPPORTED_MOTIF_TYPES,
    SUPPORTED_TRANSFORMATION_TYPES,
    WEAK_TRANSFORMATION_TYPES,
)
from app.services.motif_engine.state import MotifEngineState
from app.services.motif_engine.extractor import MotifExtractor
from app.services.motif_engine.planner import MotifPlanner
from app.services.motif_engine.validator import MotifValidator, MotifValidationIssue

__all__ = [
    "MotifPlanner",
    "MotifExtractor",
    "MotifValidator",
    "MotifValidationIssue",
    "MotifEngineState",
    "Motif",
    "MotifTransformation",
    "MotifOccurrence",
    "MotifPlan",
    "SUPPORTED_MOTIF_TYPES",
    "SUPPORTED_TRANSFORMATION_TYPES",
    "STRONG_TRANSFORMATION_TYPES",
    "WEAK_TRANSFORMATION_TYPES",
]
