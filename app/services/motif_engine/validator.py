"""
Motif Engine Validator.

Validates a :class:`~app.services.motif_engine.types.MotifPlan` for musical
coherence and returns a list of :class:`MotifValidationIssue` objects.

The validator NEVER raises — it only accumulates warnings so that callers
can inspect issues without crashing the pipeline.

Rules enforced:
1. If a viable motif exists it should be reused in at least two sections.
2. Hook motif statement must be stronger than verse motif statement.
3. Bridge should not copy hook motif unchanged.
4. Outro should reduce or resolve motif usage.
5. Repeated hooks should vary motif treatment when possible.
6. Weak source material may bypass motif reuse (warning, not crash).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from app.services.motif_engine.types import MotifOccurrence, MotifPlan


# ---------------------------------------------------------------------------
# MotifValidationIssue
# ---------------------------------------------------------------------------


@dataclass
class MotifValidationIssue:
    """A single validation finding from :class:`MotifValidator`.

    Attributes:
        severity: ``"warning"`` for issues that are audible but not fatal;
            ``"error"`` for structurally broken plans.
        rule: Short machine-readable rule name.
        message: Human-readable description.
        section_name: The affected section label, or ``None`` for plan-level issues.
    """

    severity: str  # "warning" | "error"
    rule: str
    message: str
    section_name: Optional[str] = None

    def to_dict(self) -> dict:
        d = {
            "severity": self.severity,
            "rule": self.rule,
            "message": self.message,
        }
        if self.section_name is not None:
            d["section_name"] = self.section_name
        return d


# ---------------------------------------------------------------------------
# MotifValidator
# ---------------------------------------------------------------------------


def _derive_section_type(name: str) -> str:
    """Derive a canonical section type from a raw section name string."""
    n = name.lower().strip()
    for token in ("pre_hook", "pre-hook", "prehook", "buildup", "build"):
        if token in n:
            return "pre_hook"
    for token in ("hook", "chorus", "drop"):
        if token in n:
            return "hook"
    for token in ("verse",):
        if token in n:
            return "verse"
    for token in ("bridge",):
        if token in n:
            return "bridge"
    for token in ("breakdown", "break"):
        if token in n:
            return "breakdown"
    for token in ("intro",):
        if token in n:
            return "intro"
    for token in ("outro",):
        if token in n:
            return "outro"
    return "verse"


class MotifValidator:
    """Validate a :class:`MotifPlan` and return a list of issues.

    Usage::

        validator = MotifValidator()
        issues = validator.validate(plan)
        warnings = [i for i in issues if i.severity == "warning"]
    """

    # Minimum occurrences when a viable motif exists.
    _MIN_REUSE_COUNT: int = 2

    # Minimum reuse score before raising a warning.
    _MIN_REUSE_SCORE: float = 0.30

    # Minimum variation score before raising a warning.
    _MIN_VARIATION_SCORE: float = 0.25

    # Confidence threshold below which source quality warnings apply.
    _WEAK_CONFIDENCE_THRESHOLD: float = 0.40

    def validate(self, plan: MotifPlan) -> List[MotifValidationIssue]:
        """Run all validation rules against *plan* and return all issues."""
        issues: List[MotifValidationIssue] = []

        self._check_no_motif(plan, issues)
        if plan.motif is None:
            # No further checks needed.
            return issues

        self._check_minimum_reuse(plan, issues)
        self._check_hook_stronger_than_verse(plan, issues)
        self._check_bridge_differs_from_hook(plan, issues)
        self._check_outro_resolves(plan, issues)
        self._check_repeated_hook_variation(plan, issues)
        self._check_reuse_score(plan, issues)
        self._check_variation_score(plan, issues)
        self._check_weak_source_quality(plan, issues)

        return issues

    # ------------------------------------------------------------------
    # Individual rule checks
    # ------------------------------------------------------------------

    def _check_no_motif(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        if plan.motif is None:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="no_motif_extracted",
                    message=(
                        "No viable motif was extracted — arrangement lacks "
                        "a reusable identity layer."
                    ),
                )
            )

    def _check_minimum_reuse(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        if len(plan.occurrences) < self._MIN_REUSE_COUNT:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="insufficient_motif_reuse",
                    message=(
                        f"Motif appears in only {len(plan.occurrences)} section(s) — "
                        f"should appear in at least {self._MIN_REUSE_COUNT} "
                        f"for structural cohesion."
                    ),
                )
            )

    def _check_hook_stronger_than_verse(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        hook_occurrences = [
            o for o in plan.occurrences
            if _derive_section_type(o.section_name) == "hook"
        ]
        verse_occurrences = [
            o for o in plan.occurrences
            if _derive_section_type(o.section_name) == "verse"
        ]
        if not hook_occurrences or not verse_occurrences:
            return

        hook_strong = any(o.is_strong for o in hook_occurrences)
        verse_strong_all = all(o.is_strong for o in verse_occurrences)
        hook_intensity = max(o.target_intensity for o in hook_occurrences)
        verse_intensity = max(o.target_intensity for o in verse_occurrences)

        if not hook_strong and verse_strong_all:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="hook_not_stronger_than_verse",
                    message=(
                        "Hook motif treatment is not stronger than verse motif — "
                        "hook should deliver the fullest motif statement."
                    ),
                )
            )
        elif hook_intensity < verse_intensity:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="hook_intensity_below_verse",
                    message=(
                        f"Hook motif target_intensity ({hook_intensity:.2f}) is lower "
                        f"than verse ({verse_intensity:.2f}) — hook should feel bigger."
                    ),
                )
            )

    def _check_bridge_differs_from_hook(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        bridge_occurrences = [
            o for o in plan.occurrences
            if _derive_section_type(o.section_name) in ("bridge", "breakdown")
        ]
        hook_occurrences = [
            o for o in plan.occurrences
            if _derive_section_type(o.section_name) == "hook"
        ]
        if not bridge_occurrences or not hook_occurrences:
            return

        bridge_sets = {frozenset(o.transformation_types) for o in bridge_occurrences}
        hook_sets = {frozenset(o.transformation_types) for o in hook_occurrences}

        overlap = bridge_sets & hook_sets
        if overlap:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="bridge_copies_hook_motif",
                    message=(
                        "Bridge/breakdown motif treatment matches hook motif treatment — "
                        "bridge should use a variation or counter-version."
                    ),
                )
            )

    def _check_outro_resolves(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        outro_occurrences = [
            o for o in plan.occurrences
            if _derive_section_type(o.section_name) == "outro"
        ]
        hook_occurrences = [
            o for o in plan.occurrences
            if _derive_section_type(o.section_name) == "hook"
        ]
        if not outro_occurrences:
            return

        hook_sets = {frozenset(o.transformation_types) for o in hook_occurrences}
        for outro_occ in outro_occurrences:
            outro_set = frozenset(outro_occ.transformation_types)
            # Outro copying hook unchanged is a problem.
            if outro_set in hook_sets and outro_occ.is_strong:
                issues.append(
                    MotifValidationIssue(
                        severity="warning",
                        rule="outro_unresolved_motif",
                        message=(
                            f"Section '{outro_occ.section_name}' uses the same strong "
                            f"motif treatment as a hook — outro should reduce or resolve."
                        ),
                        section_name=outro_occ.section_name,
                    )
                )
            # Outro using full_phrase is unexpected.
            if "full_phrase" in outro_occ.transformation_types:
                issues.append(
                    MotifValidationIssue(
                        severity="warning",
                        rule="outro_full_phrase",
                        message=(
                            f"Section '{outro_occ.section_name}' uses full_phrase in outro — "
                            f"consider simplify, rhythm_trim, or sustain_expand for resolution."
                        ),
                        section_name=outro_occ.section_name,
                    )
                )

    def _check_repeated_hook_variation(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        hook_occurrences = [
            o for o in plan.occurrences
            if _derive_section_type(o.section_name) == "hook"
        ]
        if len(hook_occurrences) < 2:
            return

        transform_sets = [frozenset(o.transformation_types) for o in hook_occurrences]
        if len(set(transform_sets)) == 1:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="repeated_hook_identical_motif",
                    message=(
                        f"All {len(hook_occurrences)} hook occurrences use identical "
                        f"motif treatment — listeners will notice the repetition."
                    ),
                )
            )

    def _check_reuse_score(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        if plan.motif_reuse_score < self._MIN_REUSE_SCORE:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="low_motif_reuse_score",
                    message=(
                        f"motif_reuse_score ({plan.motif_reuse_score:.2f}) is below "
                        f"threshold ({self._MIN_REUSE_SCORE:.2f}) — motif appears "
                        f"too infrequently to create cohesion."
                    ),
                )
            )

    def _check_variation_score(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        if plan.motif_variation_score < self._MIN_VARIATION_SCORE:
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="low_motif_variation_score",
                    message=(
                        f"motif_variation_score ({plan.motif_variation_score:.2f}) is "
                        f"below threshold ({self._MIN_VARIATION_SCORE:.2f}) — motif "
                        f"transformations lack variety across sections."
                    ),
                )
            )

    def _check_weak_source_quality(
        self, plan: MotifPlan, issues: List[MotifValidationIssue]
    ) -> None:
        if (
            plan.motif is not None
            and plan.motif.confidence < self._WEAK_CONFIDENCE_THRESHOLD
        ):
            issues.append(
                MotifValidationIssue(
                    severity="warning",
                    rule="weak_motif_confidence",
                    message=(
                        f"Motif confidence ({plan.motif.confidence:.2f}) is low — "
                        f"source quality may limit motif precision. "
                        f"Motif reuse is conservative."
                    ),
                )
            )
