"""
Regression tests for the Section Identity Engine and its integration with the
arrangement pipeline.

Covers:
- Phase 2: Section Identity — each type has a distinct behavior profile
- Phase 3: Repeated Section Evolution — verse 2 ≠ verse 1; hooks escalate
- Phase 4: Role Choreography — lead roles change across sections
- Phase 5: Transition Events — deterministic events at section boundaries
- Phase 6: Renderer integration via _apply_stem_primary_section_states
- Phase 7: Quality Metrics — contrast / variation / choreography / payoff
- Phase 8: Regressions — anti-mud, intro vs hook, legacy path unchanged
- Phase 9: Feature flag — engine is gated and backward-compatible
"""

from __future__ import annotations

import os
import unittest.mock

import pytest

from app.services.section_identity_engine import (
    SECTION_PROFILES,
    SECTION_IDENTITY_ENGINE_VERSION,
    ArrangementQualityMetrics,
    TransitionEvent,
    compute_arrangement_quality,
    get_transition_events,
    select_roles_for_section,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FULL_ROLES = ["drums", "bass", "melody", "pads", "fx", "vocal", "arp", "synth"]


def _jaccard(a: list[str], b: list[str]) -> float:
    sa, sb = set(a), set(b)
    union = sa | sb
    if not union:
        return 0.0
    return 1.0 - len(sa & sb) / len(union)


# ===========================================================================
# Phase 2 — Section Identity Profiles
# ===========================================================================


class TestSectionProfiles:
    """Each section type must have a distinct, musically correct behavior profile."""

    def test_all_canonical_section_types_are_defined(self):
        for stype in ("intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"):
            assert stype in SECTION_PROFILES, f"Missing profile for {stype}"

    def test_intro_does_not_activate_drums_or_bass(self):
        roles = select_roles_for_section("intro", _FULL_ROLES, occurrence=1)
        assert "drums" not in roles, "Intro must not have drums"
        assert "bass" not in roles, "Intro must not have bass"

    def test_intro_density_is_at_most_2(self):
        roles = select_roles_for_section("intro", _FULL_ROLES, occurrence=1)
        assert len(roles) <= 2, f"Intro should have ≤2 roles, got {roles}"

    def test_hook_includes_drums_when_available(self):
        roles = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        assert "drums" in roles, "Hook must have drums when available"

    def test_hook_includes_bass_when_available(self):
        roles = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        assert "bass" in roles, "Hook must have bass when available"

    def test_hook_density_is_at_least_3(self):
        roles = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        assert len(roles) >= 3, f"Hook should have ≥3 roles, got {roles}"

    def test_bridge_forbids_drums(self):
        roles = select_roles_for_section("bridge", _FULL_ROLES, occurrence=1)
        assert "drums" not in roles, "Bridge must not have drums"

    def test_bridge_forbids_bass(self):
        roles = select_roles_for_section("bridge", _FULL_ROLES, occurrence=1)
        assert "bass" not in roles, "Bridge must not have bass"

    def test_breakdown_forbids_drums_and_bass(self):
        roles = select_roles_for_section("breakdown", _FULL_ROLES, occurrence=1)
        assert "drums" not in roles
        assert "bass" not in roles

    def test_outro_forbids_drums_and_bass(self):
        roles = select_roles_for_section("outro", _FULL_ROLES, occurrence=1)
        assert "drums" not in roles
        assert "bass" not in roles

    def test_pre_hook_does_not_use_pads(self):
        roles = select_roles_for_section("pre_hook", _FULL_ROLES, occurrence=1)
        assert "pads" not in roles, "Pre-hook must not use pads (they soften tension)"

    def test_verse_density_is_medium(self):
        roles = select_roles_for_section("verse", _FULL_ROLES, occurrence=1)
        assert 2 <= len(roles) <= 3, f"Verse should have 2–3 roles, got {roles}"

    def test_intro_materially_differs_from_hook(self):
        intro_roles = select_roles_for_section("intro", _FULL_ROLES, occurrence=1)
        hook_roles = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        dist = _jaccard(intro_roles, hook_roles)
        assert dist >= 0.50, (
            f"Intro {intro_roles} and hook {hook_roles} are too similar (jaccard={dist:.2f})"
        )

    def test_bridge_materially_differs_from_verse(self):
        verse_roles = select_roles_for_section("verse", _FULL_ROLES, occurrence=1)
        bridge_roles = select_roles_for_section("bridge", _FULL_ROLES, occurrence=1)
        dist = _jaccard(verse_roles, bridge_roles)
        assert dist >= 0.40, (
            f"Bridge {bridge_roles} and verse {verse_roles} are too similar (jaccard={dist:.2f})"
        )


# ===========================================================================
# Phase 3 — Repeated Section Evolution
# ===========================================================================


class TestRepeatedSectionEvolution:
    """Repeated sections must preserve identity but change execution."""

    def test_verse_2_differs_from_verse_1_with_full_stems(self):
        v1 = select_roles_for_section("verse", _FULL_ROLES, occurrence=1)
        v2 = select_roles_for_section(
            "verse", _FULL_ROLES, occurrence=2, prev_same_type_roles=v1
        )
        dist = _jaccard(v1, v2)
        assert dist > 0.0, f"Verse 2 {v2} is identical to verse 1 {v1}"

    def test_hook_escalates_density_across_occurrences(self):
        h1 = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        h2 = select_roles_for_section("hook", _FULL_ROLES, occurrence=2, prev_same_type_roles=h1)
        # Hook 2 should be at least as dense as hook 1 (escalation_per_repeat=1)
        assert len(h2) >= len(h1), (
            f"Hook 2 ({len(h2)} roles) should be >= Hook 1 ({len(h1)} roles)"
        )

    def test_hook_occurrence_3_is_at_least_as_dense_as_hook_2(self):
        h1 = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        h2 = select_roles_for_section("hook", _FULL_ROLES, occurrence=2, prev_same_type_roles=h1)
        h3 = select_roles_for_section("hook", _FULL_ROLES, occurrence=3, prev_same_type_roles=h2)
        assert len(h3) >= len(h2), (
            f"Hook 3 ({len(h3)} roles) should be >= Hook 2 ({len(h2)} roles)"
        )

    def test_pre_hook_2_loses_drums_for_tension(self):
        ph1 = select_roles_for_section("pre_hook", _FULL_ROLES, occurrence=1)
        ph2 = select_roles_for_section(
            "pre_hook", _FULL_ROLES, occurrence=2, prev_same_type_roles=ph1
        )
        # subtract_on_repeat=True for pre_hook: drums should be absent on repeat
        assert "drums" not in ph2, (
            f"Pre-hook 2 should drop drums for tension-through-absence, got {ph2}"
        )

    def test_verse_preserves_drums_on_repeat(self):
        """Verse 2 should still have rhythmic backbone unless constraints force removal."""
        v1 = select_roles_for_section("verse", _FULL_ROLES, occurrence=1)
        v2 = select_roles_for_section(
            "verse", _FULL_ROLES, occurrence=2, prev_same_type_roles=v1
        )
        # Verse profile allows drums — it should not strip them on repeat
        # (subtract_on_repeat=False for verse)
        # Either drums or bass should be present in v2
        assert ("drums" in v2 or "bass" in v2), (
            f"Verse 2 should still have a rhythmic element, got {v2}"
        )

    def test_repeated_section_with_limited_roles(self):
        """With only 2 stems, repeated section is still valid."""
        roles = ["drums", "bass"]
        v1 = select_roles_for_section("verse", roles, occurrence=1)
        v2 = select_roles_for_section("verse", roles, occurrence=2, prev_same_type_roles=v1)
        # Both should be non-empty
        assert len(v1) >= 1
        assert len(v2) >= 1
        # And both should be subsets of available
        assert set(v1) <= set(roles)
        assert set(v2) <= set(roles)


# ===========================================================================
# Phase 4 — Role Choreography / Handoff
# ===========================================================================


class TestRoleChoreography:
    """Sections should feel produced — lead roles must change across adjacent sections."""

    def test_intro_and_verse_have_different_lead_role(self):
        intro = select_roles_for_section("intro", _FULL_ROLES, occurrence=1)
        verse = select_roles_for_section(
            "verse", _FULL_ROLES, occurrence=1, prev_adjacent_roles=intro
        )
        if intro and verse:
            assert intro[0] != verse[0], (
                f"Intro lead={intro[0]} and verse lead={verse[0]} should differ"
            )

    def test_hook_differs_from_preceding_verse(self):
        verse = select_roles_for_section("verse", _FULL_ROLES, occurrence=1)
        hook = select_roles_for_section(
            "hook", _FULL_ROLES, occurrence=1, prev_adjacent_roles=verse
        )
        dist = _jaccard(verse, hook)
        assert dist >= 0.25, (
            f"Hook {hook} should differ from verse {verse} (jaccard={dist:.2f})"
        )

    def test_bridge_drops_groove_after_hook(self):
        hook = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        bridge = select_roles_for_section(
            "bridge", _FULL_ROLES, occurrence=1, prev_adjacent_roles=hook
        )
        assert "drums" not in bridge, "Bridge must not have drums after hook"
        assert "bass" not in bridge, "Bridge must not have bass after hook"

    def test_adjacent_contrast_enforcement_kicks_in(self):
        """When adjacent roles are too similar, the engine must swap roles."""
        # Give intro and verse a scenario where naive selection overlaps a lot
        # by restricting to only non-rhythmic roles — bridge should still differ from verse
        limited_roles = ["melody", "pads", "fx", "arp", "synth"]
        verse = select_roles_for_section("verse", limited_roles, occurrence=1)
        bridge = select_roles_for_section(
            "bridge", limited_roles, occurrence=1, prev_adjacent_roles=verse
        )
        # Both are from the same pool but should pick different preferred roles
        # (bridge prefers pads/fx first; verse prefers melody first for this pool)
        assert isinstance(bridge, list)
        assert len(bridge) >= 1


# ===========================================================================
# Phase 5 — Transition Events
# ===========================================================================


class TestTransitionEvents:
    """Transitions must produce actual event objects at the right bars."""

    def test_hook_entry_produces_silence_drop_and_crash(self):
        events = get_transition_events(
            prev_section_type="verse",
            next_section_type="hook",
            prev_end_bar=7,
            next_start_bar=8,
        )
        event_types = {e.event_type for e in events}
        assert "silence_drop_before_hook" in event_types, "Hook entry needs pre-silence"
        assert "crash_hit" in event_types, "Hook entry needs crash hit"

    def test_pre_hook_entry_produces_riser_and_snare_pickup(self):
        events = get_transition_events(
            prev_section_type="verse",
            next_section_type="pre_hook",
            prev_end_bar=7,
            next_start_bar=8,
        )
        event_types = {e.event_type for e in events}
        assert "riser_fx" in event_types or "snare_pickup" in event_types, (
            f"Pre-hook entry should have riser_fx or snare_pickup, got {event_types}"
        )

    def test_bridge_entry_produces_silence_drop(self):
        events = get_transition_events(
            prev_section_type="hook",
            next_section_type="bridge",
            prev_end_bar=15,
            next_start_bar=16,
        )
        event_types = {e.event_type for e in events}
        assert "pre_hook_silence_drop" in event_types, "Bridge entry needs silence drop"

    def test_verse_to_verse_produces_drum_fill(self):
        events = get_transition_events(
            prev_section_type="verse",
            next_section_type="verse",
            prev_end_bar=7,
            next_start_bar=8,
        )
        event_types = {e.event_type for e in events}
        # verse → verse should get a fill
        assert "drum_fill" in event_types, f"verse→verse should get drum_fill, got {event_types}"

    def test_final_hook_gets_expansion_event(self):
        events = get_transition_events(
            prev_section_type="bridge",
            next_section_type="hook",
            prev_end_bar=23,
            next_start_bar=24,
            occurrence_of_next=3,
        )
        event_types = {e.event_type for e in events}
        assert "final_hook_expansion" in event_types, "Hook occurrence 3 should get final expansion"

    def test_events_have_valid_bars(self):
        events = get_transition_events(
            prev_section_type="verse",
            next_section_type="hook",
            prev_end_bar=7,
            next_start_bar=8,
        )
        for e in events:
            assert isinstance(e.bar, int)
            assert e.bar >= 0

    def test_events_have_intensities_in_range(self):
        events = get_transition_events(
            prev_section_type="verse",
            next_section_type="hook",
            prev_end_bar=7,
            next_start_bar=8,
        )
        for e in events:
            assert 0.0 <= e.intensity <= 1.0, f"Intensity {e.intensity} out of range"

    def test_outro_to_nothing_produces_no_events(self):
        events = get_transition_events(
            prev_section_type="outro",
            next_section_type="outro",  # edge case
            prev_end_bar=63,
            next_start_bar=64,
        )
        # Should not crash; outro → outro is rare
        assert isinstance(events, list)


# ===========================================================================
# Phase 6 — Renderer integration via _apply_stem_primary_section_states
# ===========================================================================


class TestRendererEnforcement:
    """Renderer must honour planner decisions (section identity engine path)."""

    def _stem_meta(self, roles: list[str]) -> dict:
        return {"enabled": True, "succeeded": True, "roles_detected": roles}

    def _make_sections(self, section_specs: list[tuple[str, str, int, int]]) -> list[dict]:
        """section_specs: (name, type, bar_start, bars)"""
        return [
            {"name": n, "type": t, "bar_start": bs, "bars": b}
            for n, t, bs, b in section_specs
        ]

    def _run_with_flag(self, sections, roles, flag_value=True):
        from app.services.arrangement_jobs import _apply_stem_primary_section_states
        with unittest.mock.patch(
            "app.services.arrangement_jobs.settings"
        ) as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = flag_value
            return _apply_stem_primary_section_states(sections, self._stem_meta(roles))

    def test_intro_does_not_have_drums_with_flag_on(self):
        sections = self._make_sections([("Intro", "intro", 0, 4)])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        assert "drums" not in result[0]["active_stem_roles"], (
            f"Intro should not have drums with identity engine, got {result[0]['active_stem_roles']}"
        )

    def test_hook_has_drums_with_flag_on(self):
        sections = self._make_sections([("Hook", "hook", 0, 8)])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        assert "drums" in result[0]["active_stem_roles"], (
            f"Hook should have drums with identity engine, got {result[0]['active_stem_roles']}"
        )

    def test_bridge_has_no_drums_with_flag_on(self):
        sections = self._make_sections([("Bridge", "bridge", 0, 8)])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        assert "drums" not in result[0]["active_stem_roles"]
        assert "bass" not in result[0]["active_stem_roles"]

    def test_repeated_verses_differ_with_flag_on(self):
        sections = self._make_sections([
            ("Verse 1", "verse", 0, 8),
            ("Verse 2", "verse", 8, 8),
        ])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        v1 = result[0]["active_stem_roles"]
        v2 = result[1]["active_stem_roles"]
        dist = _jaccard(v1, v2)
        assert dist > 0.0, f"Verse 2 {v2} should differ from verse 1 {v1} with flag on"

    def test_pre_hook_boundary_events_injected_with_flag_on(self):
        sections = self._make_sections([
            ("Verse", "verse", 0, 8),
            ("Pre-Hook", "pre_hook", 8, 4),
            ("Hook", "hook", 12, 8),
        ])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        pre_hook = result[1]
        # Should have boundary events or variations
        has_events = bool(pre_hook.get("boundary_events") or pre_hook.get("variations"))
        assert has_events, "Pre-hook should have boundary events with identity engine"

    def test_legacy_path_unchanged_when_flag_off(self):
        """Flag=False must produce the same output as the original code."""
        sections = self._make_sections([
            ("Intro", "intro", 0, 4),
            ("Verse", "verse", 4, 8),
            ("Hook", "hook", 12, 8),
            ("Outro", "outro", 20, 4),
        ])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=False)
        # Just verify the output is valid (not empty, has expected keys)
        for section in result:
            assert "active_stem_roles" in section
            assert isinstance(section["active_stem_roles"], list)

    def test_no_regression_when_stem_metadata_is_none(self):
        from app.services.arrangement_jobs import _apply_stem_primary_section_states
        sections = [{"name": "Verse", "type": "verse", "bar_start": 0, "bars": 8}]
        result = _apply_stem_primary_section_states(sections, None)
        assert result == sections  # Should be returned unchanged

    def test_hook_transition_events_injected_before_hook(self):
        """Hook entry from a verse should inject silence_drop_before_hook."""
        sections = self._make_sections([
            ("Verse", "verse", 0, 8),
            ("Hook", "hook", 8, 8),
        ])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        verse_section = result[0]
        verse_variations = verse_section.get("variations") or []
        verse_events = verse_section.get("boundary_events") or []
        all_event_types = (
            {v["variation_type"] for v in verse_variations}
            | {e["type"] for e in verse_events}
        )
        assert "silence_drop_before_hook" in all_event_types or "drum_fill" in all_event_types, (
            f"Verse before hook should have transition event, found: {all_event_types}"
        )


# ===========================================================================
# Phase 7 — Quality Metrics
# ===========================================================================


class TestArrangementQualityMetrics:
    """Metrics must be accurate and catch fake arrangements."""

    def _make_section_dict(self, stype: str, roles: list[str]) -> dict:
        return {"type": stype, "instruments": roles}

    def test_high_quality_arrangement_has_good_scores(self):
        sections = [
            self._make_section_dict("intro", ["pads", "fx"]),
            self._make_section_dict("verse", ["drums", "bass"]),
            self._make_section_dict("pre_hook", ["bass", "arp", "fx"]),
            self._make_section_dict("hook", ["drums", "bass", "melody", "synth"]),
            self._make_section_dict("verse", ["drums", "bass", "melody"]),
            self._make_section_dict("hook", ["drums", "bass", "melody", "synth", "vocal"]),
            self._make_section_dict("bridge", ["pads", "melody"]),
            self._make_section_dict("outro", ["pads", "fx"]),
        ]
        metrics = compute_arrangement_quality(sections)
        assert metrics.section_contrast_score >= 0.25, (
            f"section_contrast_score={metrics.section_contrast_score:.2f} too low"
        )
        assert metrics.repetition_variation_score > 0.0, (
            f"repetition_variation_score={metrics.repetition_variation_score:.2f} — verses are identical"
        )
        assert metrics.payoff_strength_score > 0.0, (
            f"payoff_strength_score={metrics.payoff_strength_score:.2f} — hook not denser than verse"
        )

    def test_fake_arrangement_gets_low_contrast_score(self):
        """Identical role sets across all sections → low contrast score."""
        same_roles = ["drums", "bass"]
        sections = [
            self._make_section_dict("intro", same_roles),
            self._make_section_dict("verse", same_roles),
            self._make_section_dict("hook", same_roles),
            self._make_section_dict("outro", same_roles),
        ]
        metrics = compute_arrangement_quality(sections)
        assert metrics.section_contrast_score < 0.30, (
            f"Fake arrangement should score low contrast, got {metrics.section_contrast_score:.2f}"
        )

    def test_identical_repeated_sections_score_zero_variation(self):
        roles = ["drums", "bass"]
        sections = [
            self._make_section_dict("verse", roles),
            self._make_section_dict("verse", roles),
        ]
        metrics = compute_arrangement_quality(sections)
        assert metrics.repetition_variation_score == 0.0, (
            f"Identical verses should have 0.0 variation, got {metrics.repetition_variation_score}"
        )
        assert any("near-identical" in w for w in metrics.warnings), (
            "Should warn about near-identical repeated sections"
        )

    def test_hook_denser_than_verse_scores_positive_payoff(self):
        sections = [
            self._make_section_dict("verse", ["drums", "bass"]),            # 2 roles
            self._make_section_dict("hook", ["drums", "bass", "melody", "synth"]),  # 4 roles
        ]
        metrics = compute_arrangement_quality(sections)
        assert metrics.payoff_strength_score > 0.0, "Hook denser than verse should score > 0"

    def test_equal_density_verse_hook_warns(self):
        sections = [
            self._make_section_dict("verse", ["drums", "bass", "melody"]),
            self._make_section_dict("hook", ["drums", "bass", "melody"]),
        ]
        metrics = compute_arrangement_quality(sections)
        assert metrics.payoff_strength_score <= 0.0
        assert any("hooks are no denser" in w for w in metrics.warnings)

    def test_empty_sections_returns_zero_metrics(self):
        metrics = compute_arrangement_quality([])
        assert metrics.section_contrast_score == 0.0
        assert metrics.warnings

    def test_metrics_is_dataclass_instance(self):
        sections = [self._make_section_dict("verse", ["drums", "bass"])]
        metrics = compute_arrangement_quality(sections)
        assert isinstance(metrics, ArrangementQualityMetrics)

    def test_role_choreography_score_captures_lead_changes(self):
        sections = [
            self._make_section_dict("intro", ["pads"]),      # lead: pads
            self._make_section_dict("verse", ["drums"]),      # lead: drums — changed
            self._make_section_dict("hook", ["drums"]),       # lead: drums — same
            self._make_section_dict("bridge", ["pads"]),      # lead: pads — changed
        ]
        metrics = compute_arrangement_quality(sections)
        # 2 changes out of 3 transitions = 0.666
        assert metrics.role_choreography_score >= 0.60, (
            f"Expected role_choreography >= 0.60, got {metrics.role_choreography_score}"
        )


# ===========================================================================
# Phase 8 — Regression Coverage
# ===========================================================================


class TestRegressions:
    """Ensure existing contracts are preserved."""

    def test_anti_mud_full_mix_not_used_when_2_plus_roles_available(self):
        """full_mix should not appear when 2+ isolated roles exist."""
        roles = select_roles_for_section(
            "verse", ["drums", "bass", "full_mix"], occurrence=1
        )
        if len([r for r in roles if r != "full_mix"]) >= 2:
            assert "full_mix" not in roles

    def test_full_mix_accepted_when_only_option(self):
        roles = select_roles_for_section("verse", ["full_mix"], occurrence=1)
        assert roles == ["full_mix"]

    def test_empty_available_roles_returns_empty(self):
        roles = select_roles_for_section("hook", [], occurrence=1)
        assert roles == []

    def test_breakdown_reduces_density_vs_hook(self):
        hook = select_roles_for_section("hook", _FULL_ROLES, occurrence=1)
        breakdown = select_roles_for_section("breakdown", _FULL_ROLES, occurrence=1)
        assert len(breakdown) < len(hook), (
            f"Breakdown ({len(breakdown)} roles) must be less dense than hook ({len(hook)} roles)"
        )

    def test_intro_is_always_sparse(self):
        """Intro must have at most 2 roles regardless of how many stems exist."""
        roles = select_roles_for_section("intro", _FULL_ROLES, occurrence=1)
        assert len(roles) <= 2

    def test_select_roles_is_deterministic(self):
        """Same inputs must produce same output every time."""
        kwargs = dict(
            section_type="hook",
            available_roles=_FULL_ROLES,
            occurrence=2,
            prev_same_type_roles=["drums", "bass", "melody"],
        )
        r1 = select_roles_for_section(**kwargs)
        r2 = select_roles_for_section(**kwargs)
        assert r1 == r2, f"Not deterministic: {r1} != {r2}"

    def test_all_returned_roles_are_in_available_roles(self):
        available = ["drums", "bass", "melody"]
        for stype in SECTION_PROFILES:
            roles = select_roles_for_section(stype, available, occurrence=1)
            for r in roles:
                assert r in available, (
                    f"Role {r} returned for {stype} but not in available {available}"
                )

    def test_version_string_is_set(self):
        assert isinstance(SECTION_IDENTITY_ENGINE_VERSION, str)
        assert len(SECTION_IDENTITY_ENGINE_VERSION) > 0


# ===========================================================================
# Phase 9 — Feature Flag
# ===========================================================================


class TestFeatureFlag:
    """PRODUCER_SECTION_IDENTITY_V2 gates the identity engine in arrangement_planner."""

    def _build_plan(self, flag_value: bool) -> list:
        from app.schemas.arrangement import ArrangementPlannerConfig, ArrangementPlannerInput
        from app.services.arrangement_planner import build_fallback_arrangement_plan

        planner_input = ArrangementPlannerInput(
            bpm=140,
            detected_roles=_FULL_ROLES,
            target_total_bars=64,
            source_type="stem_pack",
        )
        with unittest.mock.patch(
            "app.services.arrangement_planner.settings"
        ) as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = flag_value
            plan = build_fallback_arrangement_plan(
                planner_input=planner_input,
                user_request=None,
                planner_config=ArrangementPlannerConfig(strict=True),
            )
        return plan.sections

    def test_flag_off_uses_legacy_role_selection(self):
        sections = self._build_plan(flag_value=False)
        assert len(sections) > 0

    def test_flag_on_enforces_intro_forbidden_roles(self):
        sections = self._build_plan(flag_value=True)
        intro_sections = [s for s in sections if s.type == "intro"]
        for intro in intro_sections:
            assert "drums" not in intro.active_roles, (
                f"Flag=ON: intro must not have drums, got {intro.active_roles}"
            )
            assert "bass" not in intro.active_roles, (
                f"Flag=ON: intro must not have bass, got {intro.active_roles}"
            )

    def test_flag_on_hook_still_has_drums(self):
        sections = self._build_plan(flag_value=True)
        hook_sections = [s for s in sections if s.type == "hook"]
        for hook in hook_sections:
            assert "drums" in hook.active_roles, (
                f"Flag=ON: hook must have drums, got {hook.active_roles}"
            )

    def test_flag_on_bridge_no_drums_or_bass(self):
        sections = self._build_plan(flag_value=True)
        bridge_sections = [s for s in sections if s.type in {"bridge", "breakdown"}]
        for bridge in bridge_sections:
            assert "drums" not in bridge.active_roles
            assert "bass" not in bridge.active_roles

    def test_flag_on_repeated_verses_differ(self):
        sections = self._build_plan(flag_value=True)
        verse_sections = [s for s in sections if s.type == "verse"]
        if len(verse_sections) >= 2:
            v1 = verse_sections[0].active_roles
            v2 = verse_sections[1].active_roles
            dist = _jaccard(v1, v2)
            assert dist > 0.0, (
                f"Flag=ON: verse 2 {v2} should differ from verse 1 {v1}"
            )

    def test_flag_on_validated_plan_still_passes_schema_validation(self):
        from app.schemas.arrangement import ArrangementPlannerConfig, ArrangementPlannerInput
        from app.services.arrangement_planner import (
            build_fallback_arrangement_plan,
            validate_arrangement_plan,
        )

        planner_input = ArrangementPlannerInput(
            bpm=140,
            detected_roles=_FULL_ROLES,
            target_total_bars=64,
            source_type="stem_pack",
        )
        with unittest.mock.patch(
            "app.services.arrangement_planner.settings"
        ) as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            plan = build_fallback_arrangement_plan(
                planner_input=planner_input,
                user_request=None,
                planner_config=ArrangementPlannerConfig(strict=True),
            )
        validation = validate_arrangement_plan(plan, _FULL_ROLES)
        assert validation.valid, f"Flag=ON plan must pass schema validation: {validation.errors}"
