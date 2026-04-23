"""Genre-aware Plan Resolver.

Builds a ResolvedArrangementPlan by:
1. Running genre/vibe classification
2. Selecting an arrangement template
3. Building an arrangement strategy
4. Delegating engine merging to FinalPlanResolver
5. Mapping results into genre-contexted ResolvedArrangementPlan sections
6. Resolving conflicts between engines deterministically

Conflict resolution rules:
- Decision Engine wins for role blocking/subtraction
- Timeline Engine wins for section structure (names, bars, energy)
- Pattern/Groove Engines win for internal motion
- Drop Engine wins for boundary payoff
- Motif Engine wins for identity continuity
- AI Producer treated as advisory only

Usage::
    resolver = GenreAwarePlanResolver(render_plan, available_roles=["drums", "bass"])
    plan = resolver.resolve()
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GenreAwarePlanResolver:
    """Merge all engine outputs into a genre-aware :class:`ResolvedArrangementPlan`.

    Parameters
    ----------
    render_plan:
        Raw render plan dict (same structure as consumed by ``FinalPlanResolver``).
    available_roles:
        Full list of roles available in the source material.
    source_quality:
        Source quality mode string.
    arrangement_id:
        Used for log messages.
    loop_id:
        Source loop identifier (stored in the resolved plan for traceability).
    variation_seed:
        Seed for deterministic template/candidate selection.
    """

    def __init__(
        self,
        render_plan: dict[str, Any],
        *,
        available_roles: list[str] | None = None,
        source_quality: str = "stereo_fallback",
        arrangement_id: int = 0,
        loop_id: int | None = None,
        variation_seed: int | None = None,
    ) -> None:
        self._plan = render_plan
        self._available_roles: list[str] = list(available_roles or [])
        self._source_quality = source_quality
        self._arrangement_id = arrangement_id
        self._loop_id = loop_id
        self._variation_seed = int(variation_seed or 0)
        self._conflicts: list[dict] = []
        self._skipped: list[dict] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def resolve(self) -> "ResolvedArrangementPlan":  # noqa: F821
        """Produce the canonical :class:`ResolvedArrangementPlan`.

        Never raises — falls back gracefully on any error.
        """
        from app.services.resolved_arrangement_plan import ResolvedArrangementPlan

        try:
            return self._build()
        except Exception as exc:
            logger.warning(
                "GenreAwarePlanResolver [arr=%d] resolve() failed: %s — falling back",
                self._arrangement_id,
                exc,
                exc_info=True,
            )
            try:
                return self._fallback_plan(reason=str(exc))
            except Exception as fb_exc:
                logger.warning(
                    "GenreAwarePlanResolver [arr=%d] fallback also failed: %s",
                    self._arrangement_id,
                    fb_exc,
                )
                return ResolvedArrangementPlan(
                    loop_id=self._loop_id,
                    selected_genre="generic",
                    selected_vibe="dark",
                    style_profile="generic_dark_balanced",
                    template_id="generic_A",
                    variation_seed=self._variation_seed,
                    sections=[],
                    warnings=["GenreAwarePlanResolver double-fallback", str(fb_exc)],
                    fallback_used=True,
                )

    # ------------------------------------------------------------------
    # Build
    # ------------------------------------------------------------------

    def _build(self) -> "ResolvedArrangementPlan":
        from app.services.final_plan_resolver import FinalPlanResolver
        from app.services.genre_vibe_classifier import GenreVibeClassifier
        from app.services.resolved_arrangement_plan import (
            ResolvedArrangementPlan,
            ResolvedArrangementSection,
        )
        from app.services.template_selector import TemplateSelector
        from app.services.arrangement_strategy import StrategySelector

        # --- Step 1: derive analysis context from render plan ---
        analysis = self._extract_analysis_context()
        sections_raw = list(self._plan.get("sections") or [])

        # Treat an empty sections list as a fallback condition
        if not sections_raw:
            return self._fallback_plan(reason="no sections in render plan")

        # --- Step 2: classify genre + vibe ---
        classifier = GenreVibeClassifier()
        classification = classifier.classify(analysis)

        # --- Step 3: select template ---
        selector = TemplateSelector()
        template = selector.select(
            genre=classification["selected_genre"],
            vibe=classification["selected_vibe"],
            energy=float(analysis.get("energy") or 0.5),
            melodic_richness=float(analysis.get("melodic_richness") or 0.5),
            loop_density=float(analysis.get("loop_density") or 0.5),
            variation_seed=self._variation_seed,
        )

        # --- Step 4: build strategy ---
        strategy_selector = StrategySelector()
        strategy = strategy_selector.select(
            analysis=analysis,
            classification=classification,
            template=template,
            variation_seed=self._variation_seed,
        )

        # --- Step 5: delegate engine merging to FinalPlanResolver ---
        fpr = FinalPlanResolver(
            self._plan,
            available_roles=self._available_roles,
            source_quality=self._source_quality,
            arrangement_id=self._arrangement_id,
        )
        resolved_render = fpr.resolve()

        # --- Step 6: collect skipped actions from no-op annotations ---
        for noop in resolved_render.noop_annotations:
            self._skipped.append({
                "engine_name": noop.get("engine_name", "unknown"),
                "section_name": noop.get("section", "unknown"),
                "proposed_action": noop.get("planned_action", ""),
                "reason_skipped": noop.get("reason_not_applied", ""),
            })

        # --- Step 7: detect conflicts and map sections ---
        motif_wanted_roles = self._extract_motif_wanted_roles(sections_raw)

        resolved_sections = []
        occurrence_tracker: dict[str, int] = {}
        for idx, resolved_sec in enumerate(resolved_render.resolved_sections):
            sec_type = resolved_sec.section_type
            occ = occurrence_tracker.get(sec_type, 0)
            occurrence_tracker[sec_type] = occ + 1

            # Detect Decision-vs-Motif conflict: Decision blocks a role Motif wanted
            for blocked in resolved_sec.final_blocked_roles:
                if blocked in motif_wanted_roles:
                    self._conflicts.append({
                        "conflict_type": "decision_blocks_motif_role",
                        "winner": "decision",
                        "loser": "motif",
                        "section_name": resolved_sec.section_name,
                        "role": blocked,
                        "resolution": "Decision Engine wins — role blocked",
                    })

            energy_curve = strategy.energy_curve_policy.get(sec_type, {})
            target_energy = float(energy_curve.get("target") or resolved_sec.energy)
            target_fullness = _energy_to_fullness(target_energy)

            payoff_level = "full" if sec_type == "hook" else "medium"
            if strategy.hook_policy.get("payoff_level") and sec_type == "hook":
                payoff_level = str(strategy.hook_policy["payoff_level"])

            transition_agg = float(strategy.transition_policy.get("aggression") or 0.5)
            transition_profile = (
                "aggressive" if transition_agg >= 0.6
                else "smooth" if transition_agg < 0.4
                else "standard"
            )

            ras = ResolvedArrangementSection(
                section_name=resolved_sec.section_name,
                section_type=sec_type,
                occurrence_index=occ,
                start_bar=resolved_sec.bar_start,
                length_bars=resolved_sec.bars,
                target_energy=target_energy,
                target_fullness=target_fullness,
                final_active_roles=list(resolved_sec.final_active_roles),
                final_blocked_roles=list(resolved_sec.final_blocked_roles),
                final_reentry_roles=list(resolved_sec.final_reentries),
                final_pattern_events=list(resolved_sec.final_pattern_events),
                final_groove_events=list(resolved_sec.final_groove_events),
                final_boundary_events=[
                    e.to_dict() if hasattr(e, "to_dict") else dict(e)
                    for e in resolved_sec.final_boundary_events
                ],
                final_motif_treatment=resolved_sec.final_motif_treatment,
                final_transition_profile=transition_profile,
                final_hook_payoff_level=payoff_level,
                final_notes=[],
            )
            resolved_sections.append(ras)

        # --- Step 8: compute global scores ---
        genre_conf = float(classification.get("genre_confidence") or 0.5)
        vibe_conf = float(classification.get("vibe_confidence") or 0.5)
        contrast_score = self._compute_contrast_score(resolved_sections)

        return ResolvedArrangementPlan(
            loop_id=self._loop_id,
            selected_genre=classification["selected_genre"],
            selected_vibe=classification["selected_vibe"],
            style_profile=classification["style_profile"],
            template_id=template.template_id,
            variation_seed=self._variation_seed,
            sections=resolved_sections,
            global_scores={
                "genre_confidence": genre_conf,
                "vibe_confidence": vibe_conf,
                "contrast_score": contrast_score,
            },
            warnings=[],
            fallback_used=False,
            arrangement_strategy_summary=strategy.to_dict(),
            resolver_conflicts=list(self._conflicts),
            resolver_skipped_actions=list(self._skipped),
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_analysis_context(self) -> dict[str, Any]:
        """Build an analysis dict from the raw render plan for classification."""
        plan = self._plan
        render_profile: dict = dict(plan.get("render_profile") or {})
        sections_raw: list[dict] = list(plan.get("sections") or [])

        # Attempt to gather energy and density from sections
        energies = [float(s.get("energy") or 0.5) for s in sections_raw]
        avg_energy = sum(energies) / len(energies) if energies else 0.5

        # Collect all instrument tags from all sections
        all_tags: list[str] = []
        for sec in sections_raw:
            tags = sec.get("instrument_tags") or sec.get("instruments") or []
            all_tags.extend(str(t).lower() for t in tags)

        return {
            "bpm": plan.get("bpm") or render_profile.get("bpm") or 120.0,
            "key": plan.get("key") or render_profile.get("key") or "C",
            "energy": avg_energy,
            "melodic_richness": float(render_profile.get("melodic_richness") or 0.5),
            "loop_density": float(render_profile.get("loop_density") or 0.5),
            "instrument_tags": all_tags,
            "genre_hint": str(render_profile.get("genre_profile") or plan.get("genre") or ""),
            "vibe_hint": str(render_profile.get("vibe") or ""),
            "inferred_genre_probs": dict(render_profile.get("inferred_genre_probs") or {}),
            "inferred_vibe_probs": dict(render_profile.get("inferred_vibe_probs") or {}),
        }

    def _extract_motif_wanted_roles(self, sections_raw: list[dict]) -> set[str]:
        """Collect roles that the Motif Engine wants to preserve."""
        roles: set[str] = set()
        for sec in sections_raw:
            motif = sec.get("_motif_treatment") or {}
            preserved = motif.get("preserved_roles") or []
            roles.update(str(r) for r in preserved)
        return roles

    def _compute_contrast_score(self, sections: list) -> float:
        """Estimate contrast as the standard deviation of target energies."""
        if len(sections) < 2:
            return 0.0
        energies = [s.target_energy for s in sections]
        mean = sum(energies) / len(energies)
        variance = sum((e - mean) ** 2 for e in energies) / len(energies)
        return round(variance ** 0.5, 4)

    # ------------------------------------------------------------------
    # Fallback
    # ------------------------------------------------------------------

    def _fallback_plan(self, reason: str = "") -> "ResolvedArrangementPlan":
        """Return a minimal fallback plan when the resolver fails."""
        from app.services.resolved_arrangement_plan import (
            ResolvedArrangementPlan,
            ResolvedArrangementSection,
        )

        sections_raw = list(self._plan.get("sections") or [])
        occurrence_tracker: dict[str, int] = {}
        fallback_sections = []
        for idx, raw_sec in enumerate(sections_raw):
            try:
                sec_type = str(raw_sec.get("type") or raw_sec.get("section_type") or "verse")
                occ = occurrence_tracker.get(sec_type, 0)
                occurrence_tracker[sec_type] = occ + 1
                try:
                    length_bars = int(raw_sec.get("bars") or 8)
                except (TypeError, ValueError):
                    length_bars = 8
                try:
                    start_bar = int(raw_sec.get("bar_start") or 0)
                except (TypeError, ValueError):
                    start_bar = 0
                try:
                    target_energy = float(raw_sec.get("energy") or 0.5)
                except (TypeError, ValueError):
                    target_energy = 0.5
                fallback_sections.append(
                    ResolvedArrangementSection(
                        section_name=str(raw_sec.get("name") or f"Section {idx + 1}"),
                        section_type=sec_type,
                        occurrence_index=occ,
                        start_bar=start_bar,
                        length_bars=length_bars,
                        target_energy=target_energy,
                        target_fullness=0.5,
                        final_active_roles=list(
                            raw_sec.get("active_stem_roles")
                            or raw_sec.get("instruments")
                            or []
                        ),
                    )
                )
            except Exception:
                pass

        warnings = ["GenreAwarePlanResolver fallback used"]
        if reason:
            warnings.append(f"Reason: {reason}")

        return ResolvedArrangementPlan(
            loop_id=self._loop_id,
            selected_genre="generic",
            selected_vibe="dark",
            style_profile="generic_dark_balanced",
            template_id="generic_A",
            variation_seed=self._variation_seed,
            sections=fallback_sections,
            global_scores={
                "genre_confidence": 0.0,
                "vibe_confidence": 0.0,
                "contrast_score": 0.0,
            },
            warnings=warnings,
            fallback_used=True,
            arrangement_strategy_summary={},
            resolver_conflicts=[],
            resolver_skipped_actions=[],
        )


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _energy_to_fullness(energy: float) -> float:
    """Map energy [0,1] to a fullness target [0,1] with slight compression."""
    return round(min(max(energy * 0.9, 0.0), 1.0), 4)
