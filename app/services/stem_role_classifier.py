"""Compatibility wrapper for stem role classification service."""

from app.services.stem_classifier import (
    STEM_ROLES,
    ARRANGEMENT_GROUPS,
    StemClassification,
    classify_stem,
)

__all__ = ["STEM_ROLES", "ARRANGEMENT_GROUPS", "StemClassification", "classify_stem"]
