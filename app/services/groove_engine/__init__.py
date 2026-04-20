"""
Groove Engine — public package API.

Usage example (section-level engine)::

    from app.services.groove_engine import GrooveEngine, GrooveContext

    engine = GrooveEngine()
    ctx = GrooveContext(
        section_name="Hook 2",
        section_index=6,
        section_occurrence_index=1,
        total_occurrences=3,
        bars=16,
        energy=0.9,
        density=0.8,
        active_roles=["drums", "bass", "melody"],
        source_quality="true_stems",
    )
    plan = engine.build_groove_plan(ctx)
    print(plan.to_dict())

Usage example (profile lookup)::

    from app.services.groove_engine import get_profile_for_section, list_profiles

    profile = get_profile_for_section("hook", occurrence=2, energy=0.9)
    all_profiles = list_profiles()

Usage example (validator)::

    from app.services.groove_engine import GrooveValidator

    validator = GrooveValidator()
    issues = validator.validate(plans, source_quality="true_stems")

NOTE: This module does NOT wire into the live renderer.  It is a standalone
foundation layer integrated into arrangement jobs in shadow mode.
"""

from app.services.groove_engine.accent_engine import build_accent_events
from app.services.groove_engine.groove_engine import GrooveEngine, score_bounce
from app.services.groove_engine.groove_profiles import (
    get_profile,
    get_profile_for_section,
    list_profiles,
)
from app.services.groove_engine.groove_state import GrooveState
from app.services.groove_engine.microtiming import (
    bass_timing_offset,
    hat_timing_offset,
    kick_timing_offset,
    percussion_timing_offset,
    safe_offset,
    snare_timing_offset,
)
from app.services.groove_engine.types import (
    GrooveContext,
    GrooveEvent,
    GroovePlan,
    GrooveProfile,
)
from app.services.groove_engine.validator import GrooveValidationIssue, GrooveValidator

__all__ = [
    # Engine
    "GrooveEngine",
    "score_bounce",
    # Types
    "GrooveContext",
    "GrooveEvent",
    "GroovePlan",
    "GrooveProfile",
    # Profiles
    "get_profile",
    "get_profile_for_section",
    "list_profiles",
    # State
    "GrooveState",
    # Microtiming
    "hat_timing_offset",
    "snare_timing_offset",
    "kick_timing_offset",
    "bass_timing_offset",
    "percussion_timing_offset",
    "safe_offset",
    # Accent engine
    "build_accent_events",
    # Validator
    "GrooveValidator",
    "GrooveValidationIssue",
]
