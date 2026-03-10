"""Compatibility wrapper for stem role classification service."""

from app.services.stem_classifier import (
    STEM_ROLES,
    StemClassification,
    classify_stem,
)

__all__ = ["STEM_ROLES", "StemClassification", "classify_stem"]
