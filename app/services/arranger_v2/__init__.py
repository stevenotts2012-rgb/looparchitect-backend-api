"""
Arranger V2 — public package exports.

Import from this package to access the new deterministic arrangement engine:

    from app.services.arranger_v2 import (
        build_arrangement_plan,
        validate_or_raise,
        ArrangementPlan,
        SectionPlan,
        ArrangerState,
        ValidationResult,
    )
"""

from app.services.arranger_v2.types import (
    ArrangementPlan,
    SectionPlan,
    StemRoleModel,
    CANONICAL_ROLES,
    ROLE_ENERGY_WEIGHTS,
    TRANSITION_TYPES,
    VARIATION_STRATEGIES,
    SECTION_TYPES,
)
from app.services.arranger_v2.state import ArrangerState
from app.services.arranger_v2.role_engine import (
    validate_stem_roles,
    get_valid_role_strings,
    normalise_role,
    compute_section_energy_weight,
    RoleValidationError,
)
from app.services.arranger_v2.density_engine import (
    select_stems_for_section,
    density_label_to_float,
    density_float_to_label,
)
from app.services.arranger_v2.variation_engine import apply_variation
from app.services.arranger_v2.transition_engine import (
    select_transition_in,
    select_transition_out,
    build_transition_plan,
)
from app.services.arranger_v2.planner import build_arrangement_plan
from app.services.arranger_v2.validator import (
    validate_plan,
    validate_or_raise,
    ValidationResult,
    ArrangementValidationError,
)

__all__ = [
    # Types
    "ArrangementPlan",
    "SectionPlan",
    "StemRoleModel",
    "CANONICAL_ROLES",
    "ROLE_ENERGY_WEIGHTS",
    "TRANSITION_TYPES",
    "VARIATION_STRATEGIES",
    "SECTION_TYPES",
    # State
    "ArrangerState",
    # Role engine
    "validate_stem_roles",
    "get_valid_role_strings",
    "normalise_role",
    "compute_section_energy_weight",
    "RoleValidationError",
    # Density engine
    "select_stems_for_section",
    "density_label_to_float",
    "density_float_to_label",
    # Variation engine
    "apply_variation",
    # Transition engine
    "select_transition_in",
    "select_transition_out",
    "build_transition_plan",
    # Planner
    "build_arrangement_plan",
    # Validator
    "validate_plan",
    "validate_or_raise",
    "ValidationResult",
    "ArrangementValidationError",
]
