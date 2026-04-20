"""
Variation state module for the Pattern Variation Engine.

Re-exports :class:`PatternVariationState` from the internal ``state`` module
so external callers can import from the canonical name expected by the
LoopArchitect spec::

    from app.services.pattern_variation_engine.variation_state import (
        PatternVariationState,
    )
"""

from app.services.pattern_variation_engine.state import PatternVariationState

__all__ = ["PatternVariationState"]
