"""
Pattern Variation Engine — public package API.

This module exposes the key symbols needed by callers.

Usage example::

    from app.services.pattern_variation_engine import (
        PatternVariationPlanner,
        PatternVariationValidator,
        PatternAction,
        PatternEvent,
        PatternSectionPlan,
        PatternVariationPlan,
    )

    planner = PatternVariationPlanner(source_quality="true_stems")
    plan = planner.build_plan([
        {"section_type": "intro",    "section_name": "Intro",    "bars": 8},
        {"section_type": "verse",    "section_name": "Verse 1",  "bars": 16},
        {"section_type": "pre_hook", "section_name": "Pre-Hook", "bars": 8},
        {"section_type": "hook",     "section_name": "Hook 1",   "bars": 16},
        {"section_type": "outro",    "section_name": "Outro",    "bars": 8},
    ])

    validator = PatternVariationValidator()
    issues = validator.validate_and_repair(plan)

NOTE: This module does NOT wire into the live renderer.  It is a standalone
foundation layer intended for future integration.
"""

from app.services.pattern_variation_engine.bass_patterns import build_bass_plan
from app.services.pattern_variation_engine.drum_patterns import build_drum_plan
from app.services.pattern_variation_engine.melodic_patterns import build_melodic_plan
from app.services.pattern_variation_engine.planner import PatternVariationPlanner
from app.services.pattern_variation_engine.state import PatternVariationState
from app.services.pattern_variation_engine.types import (
    PatternAction,
    PatternEvent,
    PatternSectionPlan,
    PatternVariationPlan,
)
from app.services.pattern_variation_engine.validator import (
    PatternValidationIssue,
    PatternVariationValidator,
)

__all__ = [
    # Planner
    "PatternVariationPlanner",
    # State
    "PatternVariationState",
    # Types
    "PatternAction",
    "PatternEvent",
    "PatternSectionPlan",
    "PatternVariationPlan",
    # Validator
    "PatternValidationIssue",
    "PatternVariationValidator",
    # Sub-planners (for direct use in tests / advanced callers)
    "build_drum_plan",
    "build_melodic_plan",
    "build_bass_plan",
]
