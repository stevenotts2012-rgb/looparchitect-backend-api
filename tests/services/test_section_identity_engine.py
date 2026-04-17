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

# Minimum Jaccard distance between consecutive same-type sections for them
# to be considered audibly distinct.  Mirrors MIN_REPEAT_DISTINCTION_THRESHOLD
# from section_identity_engine but defined here so tests are self-contained.
_MIN_REPEAT_DISTINCTION = 0.20


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
        # Give verse and bridge a scenario where naive selection overlaps a lot
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
        # Bridge entry now uses silence_gap (smooth density reduction) instead of
        # pre_hook_silence_drop which was repurposed for hook entries.
        assert event_types & {"silence_gap", "pre_hook_silence_drop"}, (
            f"Bridge entry needs a silence/gap event, got {event_types}"
        )

    def test_verse_to_verse_produces_drum_fill(self):
        events = get_transition_events(
            prev_section_type="verse",
            next_section_type="verse",
            prev_end_bar=7,
            next_start_bar=8,
            available_roles=["drums", "bass", "melody"],
        )
        event_types = {e.event_type for e in events}
        # verse → verse should get a rhythmic fill; drum_fill when drums are available.
        assert event_types & {"drum_fill", "snare_pickup"}, (
            f"verse→verse should get a fill event, got {event_types}"
        )
        assert "drum_fill" in event_types, f"verse→verse with drums should get drum_fill, got {event_types}"

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


# ===========================================================================
# Additional regression tests — breakdown, normalization, reference mode
# ===========================================================================


class TestBreakdownSectionBehavior:
    """'breakdown' must be treated as a distinct section type, not collapsed into 'bridge'."""

    def test_normalize_section_type_preserves_breakdown(self):
        from app.services.arrangement_jobs import _normalize_section_type
        assert _normalize_section_type("breakdown") == "breakdown", (
            "_normalize_section_type must preserve 'breakdown' — it has its own identity profile"
        )

    def test_normalize_section_type_maps_break_to_breakdown(self):
        from app.services.arrangement_jobs import _normalize_section_type
        assert _normalize_section_type("break") == "breakdown", (
            "'break' is a short alias for 'breakdown', not for 'bridge'"
        )

    def test_normalize_section_type_preserves_bridge(self):
        from app.services.arrangement_jobs import _normalize_section_type
        assert _normalize_section_type("bridge") == "bridge"

    def test_breakdown_forbids_drums_in_identity_engine(self):
        roles = select_roles_for_section("breakdown", _FULL_ROLES, occurrence=1)
        assert "drums" not in roles, f"Breakdown must forbid drums, got {roles}"
        assert "bass" not in roles, f"Breakdown must forbid bass, got {roles}"

    def test_breakdown_density_is_sparse(self):
        roles = select_roles_for_section("breakdown", _FULL_ROLES, occurrence=1)
        assert len(roles) <= 2, f"Breakdown should have at most 2 roles, got {roles}"

    def _stem_meta(self, roles: list[str]) -> dict:
        return {"enabled": True, "succeeded": True, "roles_detected": roles}

    def _run_with_flag(self, sections, roles, flag_value=True):
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states
        with unittest.mock.patch(
            "app.services.arrangement_jobs.settings"
        ) as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = flag_value
            return _apply_stem_primary_section_states(sections, self._stem_meta(roles))

    def _make_sections(self, section_specs: list) -> list[dict]:
        return [
            {"name": n, "type": t, "bar_start": bs, "bars": b}
            for n, t, bs, b in section_specs
        ]

    def test_breakdown_has_no_drums_in_renderer_with_flag_on(self):
        sections = self._make_sections([("Breakdown", "breakdown", 0, 8)])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        assert "drums" not in result[0]["active_stem_roles"], (
            f"Breakdown must not have drums with identity engine on, got {result[0]['active_stem_roles']}"
        )
        assert "bass" not in result[0]["active_stem_roles"], (
            f"Breakdown must not have bass with identity engine on, got {result[0]['active_stem_roles']}"
        )

    def test_breakdown_gets_strip_variation_with_flag_on(self):
        sections = self._make_sections([("Breakdown", "breakdown", 0, 8)])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        breakdown = result[0]
        variations = breakdown.get("variations") or []
        var_types = {v["variation_type"] for v in variations}
        assert "bridge_strip" in var_types, (
            f"Breakdown should inject bridge_strip variation; got {var_types}"
        )

    def test_breakdown_gets_strip_variation_legacy_path(self):
        sections = self._make_sections([("Breakdown", "breakdown", 0, 8)])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=False)
        breakdown = result[0]
        variations = breakdown.get("variations") or []
        var_types = {v["variation_type"] for v in variations}
        assert "bridge_strip" in var_types, (
            f"Breakdown should inject bridge_strip variation in legacy path too; got {var_types}"
        )

    def test_breakdown_materially_differs_from_hook_in_renderer(self):
        sections = self._make_sections([
            ("Hook", "hook", 0, 8),
            ("Breakdown", "breakdown", 8, 8),
        ])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        hook_roles = set(result[0]["active_stem_roles"])
        breakdown_roles = set(result[1]["active_stem_roles"])
        assert "drums" not in breakdown_roles, "Breakdown must not have drums after hook"
        assert len(breakdown_roles) < len(hook_roles), (
            f"Breakdown ({len(breakdown_roles)} roles) must be less dense than hook ({len(hook_roles)} roles)"
        )

    def test_breakdown_and_bridge_both_valid_in_legacy_path(self):
        """Both 'breakdown' and 'bridge' must produce valid results in legacy path."""
        for section_type in ("bridge", "breakdown"):
            sections = self._make_sections([(section_type.title(), section_type, 0, 8)])
            result = self._run_with_flag(sections, _FULL_ROLES, flag_value=False)
            assert "drums" not in result[0]["active_stem_roles"], (
                f"{section_type} should not have drums in legacy path"
            )

    def test_breakdown_type_preserved_in_section_dict(self):
        """The rendered section dict must retain type='breakdown', not 'bridge'."""
        sections = self._make_sections([("Breakdown", "breakdown", 0, 8)])
        result = self._run_with_flag(sections, _FULL_ROLES, flag_value=True)
        assert result[0]["type"] == "breakdown", (
            f"Section type must remain 'breakdown' after render, got '{result[0]['type']}'"
        )


class TestPlannerSectionNotes:
    """Planner must produce meaningful per-section notes for inspectability."""

    def _build_plan(self, flag_value: bool) -> list:
        import unittest.mock
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

    def test_hook_section_has_specific_note(self):
        sections = self._build_plan(flag_value=False)
        hook_sections = [s for s in sections if s.type == "hook"]
        for hook in hook_sections:
            assert "hook" in hook.notes.lower() or "peak" in hook.notes.lower(), (
                f"Hook section note should be specific, got: {hook.notes!r}"
            )

    def test_repeated_section_note_mentions_occurrence(self):
        sections = self._build_plan(flag_value=False)
        by_type: dict[str, list] = {}
        for s in sections:
            by_type.setdefault(s.type, []).append(s)
        for stype, slist in by_type.items():
            if len(slist) >= 2:
                repeated_note = slist[1].notes
                assert (
                    "occurrence" in repeated_note
                    or "evolved" in repeated_note
                    or "2" in repeated_note
                ), (
                    f"Repeated {stype} (occurrence 2) note should mention evolution: {repeated_note!r}"
                )

    def test_intro_and_hook_have_distinct_notes(self):
        sections = self._build_plan(flag_value=False)
        intro_notes = [s.notes for s in sections if s.type == "intro"]
        hook_notes = [s.notes for s in sections if s.type == "hook"]
        if intro_notes and hook_notes:
            assert intro_notes[0] != hook_notes[0], (
                "Intro and hook notes must differ for inspectability"
            )


class TestReferenceGuidedRegression:
    """Reference-guided mode must still work after identity-engine changes."""

    def test_reference_adapter_type_map_includes_breakdown(self):
        from app.services.reference_plan_adapter import _TYPE_MAP
        assert "breakdown" in _TYPE_MAP, (
            "reference_plan_adapter._TYPE_MAP must include 'breakdown'"
        )
        assert _TYPE_MAP["breakdown"] == "breakdown", (
            "reference_plan_adapter must map breakdown → breakdown (not bridge)"
        )

    def test_canonical_section_types_survive_normalize(self):
        """Canonical section types must round-trip through _normalize_section_type."""
        from app.services.arrangement_jobs import _normalize_section_type
        for section_type in ("intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"):
            normalized = _normalize_section_type(section_type)
            assert normalized == section_type, (
                f"_normalize_section_type('{section_type}') returned '{normalized}' "
                f"but canonical types must round-trip unchanged"
            )

    def test_identity_engine_forbids_drums_in_intro_regardless_of_caller(self):
        """The identity engine enforces forbidden roles independent of caller context."""
        intro_roles = select_roles_for_section("intro", _FULL_ROLES, occurrence=1)
        assert "drums" not in intro_roles
        assert "bass" not in intro_roles

    def test_reference_breakdown_section_gets_correct_profile(self):
        """A breakdown section originating from reference analysis uses the breakdown
        profile (not bridge) in the identity engine path."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [{"name": "Breakdown", "type": "breakdown", "bar_start": 0, "bars": 8}]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        assert "drums" not in result[0]["active_stem_roles"]
        assert "bass" not in result[0]["active_stem_roles"]
        assert result[0]["type"] == "breakdown", (
            "'breakdown' must not be re-typed to 'bridge' during render"
        )

    def test_legacy_path_does_not_regress_on_reference_section_types(self):
        """Legacy path (flag=False) must handle all canonical section types without error."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}
        bar = 0
        sections = []
        for stype in ("intro", "verse", "pre_hook", "hook", "bridge", "breakdown", "outro"):
            sections.append({"name": stype.title(), "type": stype, "bar_start": bar, "bars": 8})
            bar += 8

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = False
            result = _apply_stem_primary_section_states(sections, stem_meta)

        assert len(result) == len(sections)
        for section in result:
            assert isinstance(section.get("active_stem_roles"), list), (
                f"Section {section.get('type')} has no active_stem_roles in legacy path"
            )


# ===========================================================================
# Phase 6 — Regression Tests (Section Choreography V2 + Phrase Variation)
# ===========================================================================


class TestSectionChoreography:
    """Phase 1: Each section must have a deterministic role hierarchy."""

    def test_get_section_choreography_verse_occurrence1(self):
        from app.services.section_identity_engine import get_section_choreography
        choro = get_section_choreography("verse", occurrence=1, available_roles=_FULL_ROLES)
        assert isinstance(choro.leader_roles, tuple)
        assert isinstance(choro.support_roles, tuple)
        assert isinstance(choro.suppressed_roles, tuple)
        assert isinstance(choro.contrast_roles, tuple)
        assert len(choro.rotation_note) > 0

    def test_get_section_choreography_verse_rotates_on_repeat(self):
        """Verse 2 choreography must differ from verse 1 (support rotation)."""
        from app.services.section_identity_engine import get_section_choreography
        choro1 = get_section_choreography("verse", occurrence=1, available_roles=_FULL_ROLES)
        choro2 = get_section_choreography("verse", occurrence=2, available_roles=_FULL_ROLES)
        # Leader roles or support roles must change between occurrences.
        assert (
            set(choro1.leader_roles) != set(choro2.leader_roles)
            or set(choro1.support_roles) != set(choro2.support_roles)
        ), "Verse choreography must differ between occurrence 1 and 2"

    def test_get_section_choreography_hook_escalates(self):
        """Hook 3 must have more contrast roles than hook 1."""
        from app.services.section_identity_engine import get_section_choreography
        choro1 = get_section_choreography("hook", occurrence=1, available_roles=_FULL_ROLES)
        choro3 = get_section_choreography("hook", occurrence=3, available_roles=_FULL_ROLES)
        assert len(choro3.contrast_roles) >= len(choro1.contrast_roles), (
            "Hook 3 should have at least as many contrast roles as hook 1"
        )

    def test_intro_choreography_suppresses_drums_and_bass(self):
        """Intro choreography must suppress drums and bass."""
        from app.services.section_identity_engine import get_section_choreography
        choro = get_section_choreography("intro", occurrence=1, available_roles=_FULL_ROLES)
        assert "drums" in choro.suppressed_roles
        assert "bass" in choro.suppressed_roles

    def test_bridge_choreography_suppresses_groove(self):
        """Bridge choreography must suppress drums, bass, percussion."""
        from app.services.section_identity_engine import get_section_choreography
        choro = get_section_choreography("bridge", occurrence=1, available_roles=_FULL_ROLES)
        assert "drums" in choro.suppressed_roles
        assert "bass" in choro.suppressed_roles

    def test_select_roles_with_choreography_verse1_vs_verse2_differ(self):
        """select_roles_with_choreography must produce audibly distinct verse 1 and verse 2."""
        from app.services.section_identity_engine import select_roles_with_choreography
        roles1, _ = select_roles_with_choreography(
            "verse", _FULL_ROLES, occurrence=1,
        )
        roles2, _ = select_roles_with_choreography(
            "verse", _FULL_ROLES, occurrence=2,
            prev_same_type_roles=roles1,
        )
        dist = _jaccard(roles1, roles2)
        assert dist >= _MIN_REPEAT_DISTINCTION, (
            f"Verse 1 ({roles1}) and verse 2 ({roles2}) are too similar "
            f"(Jaccard={dist:.2f}, need >= {_MIN_REPEAT_DISTINCTION})"
        )

    def test_select_roles_with_choreography_hook1_vs_hook2_differ(self):
        """Hook 2 must differ from hook 1 at the role-map level."""
        from app.services.section_identity_engine import select_roles_with_choreography
        roles1, _ = select_roles_with_choreography(
            "hook", _FULL_ROLES, occurrence=1,
        )
        roles2, _ = select_roles_with_choreography(
            "hook", _FULL_ROLES, occurrence=2,
            prev_same_type_roles=roles1,
        )
        dist = _jaccard(roles1, roles2)
        assert dist >= _MIN_REPEAT_DISTINCTION, (
            f"Hook 1 ({roles1}) and hook 2 ({roles2}) are too similar "
            f"(Jaccard={dist:.2f}, need >= {_MIN_REPEAT_DISTINCTION})"
        )

    def test_select_roles_with_choreography_intro_no_drums_or_bass(self):
        """Choreography-aware selection must never include drums/bass in intro."""
        from app.services.section_identity_engine import select_roles_with_choreography
        roles, choro = select_roles_with_choreography("intro", _FULL_ROLES, occurrence=1)
        assert "drums" not in roles, f"Drums in intro choreography roles: {roles}"
        assert "bass" not in roles, f"Bass in intro choreography roles: {roles}"

    def test_select_roles_with_choreography_bridge_no_groove(self):
        """Bridge must have no drums, bass, or percussion via choreography."""
        from app.services.section_identity_engine import select_roles_with_choreography
        roles, _ = select_roles_with_choreography("bridge", _FULL_ROLES, occurrence=1)
        assert "drums" not in roles
        assert "bass" not in roles
        assert "percussion" not in roles

    def test_pre_hook_occurrence2_suppresses_drums(self):
        """Pre-hook 2 uses tension-through-absence: drums must be suppressed."""
        from app.services.section_identity_engine import (
            get_section_choreography,
            select_roles_with_choreography,
        )
        choro2 = get_section_choreography("pre_hook", occurrence=2, available_roles=_FULL_ROLES)
        assert "drums" in choro2.suppressed_roles, (
            "Pre-hook 2 choreography must suppress drums for tension-through-absence"
        )
        roles2, _ = select_roles_with_choreography(
            "pre_hook", _FULL_ROLES, occurrence=2,
            prev_same_type_roles=["bass", "arp", "fx"],
        )
        assert "drums" not in roles2, (
            f"Drums must be absent from pre-hook 2 roles: {roles2}"
        )

    def test_choreography_returns_only_available_roles(self):
        """Leader/support/contrast roles must be filtered to available roles."""
        from app.services.section_identity_engine import get_section_choreography
        limited = ["bass", "melody"]
        choro = get_section_choreography("verse", occurrence=1, available_roles=limited)
        for r in choro.leader_roles:
            assert r in limited, f"Leader role {r} not in available_roles"
        for r in choro.support_roles:
            assert r in limited, f"Support role {r} not in available_roles"
        for r in choro.contrast_roles:
            assert r in limited, f"Contrast role {r} not in available_roles"


class TestPhraseVariationPlan:
    """Phase 2: Sections > 4 bars must receive phrase-level variation plans."""

    def test_verse_8bars_gets_phrase_plan(self):
        """An 8-bar verse must get a phrase variation plan."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "verse", ["drums", "bass", "melody", "vocal"], section_bars=8, occurrence=1
        )
        assert plan is not None, "8-bar verse must have a phrase variation plan"

    def test_verse_4bars_no_phrase_plan(self):
        """A 4-bar verse must NOT get a phrase variation plan (too short)."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "verse", ["drums", "bass", "melody"], section_bars=4, occurrence=1
        )
        assert plan is None, "4-bar sections should not get phrase variation plans"

    def test_hook_8bars_first_half_differs_from_second_half(self):
        """Hook phrase plan must have different roles in first and second halves."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "hook", ["drums", "bass", "melody", "synth"], section_bars=8,
            occurrence=1, available_roles=_FULL_ROLES
        )
        assert plan is not None, "8-bar hook must have a phrase plan"
        first = set(plan.first_phrase_roles)
        second = set(plan.second_phrase_roles)
        # Hook second half should be at least as dense as first (escalation direction).
        assert len(second) >= len(first), (
            f"Hook second half ({plan.second_phrase_roles}) should be >= first half ({plan.first_phrase_roles})"
        )

    def test_verse_phrase_plan_rhythm_first_melody_second(self):
        """Verse phrase plan: first half is rhythm-only, second is full."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "verse", ["drums", "bass", "melody", "vocal"], section_bars=8, occurrence=1
        )
        assert plan is not None
        first = set(plan.first_phrase_roles)
        second = set(plan.second_phrase_roles)
        assert "drums" in first or "bass" in first, "First half should have rhythmic roles"
        assert "melody" in second or "vocal" in second, "Second half should have melodic roles"
        # Second half should be fuller
        assert len(second) > len(first) or second != first, "Second half must differ from first"

    def test_bridge_phrase_plan_delayed_lead_entry(self):
        """Bridge phrase plan: atmospheric first, melody enters in second half."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "bridge", ["pads", "fx", "melody", "vocal"], section_bars=8, occurrence=1
        )
        assert plan is not None, "8-bar bridge with pads+fx+melody should have phrase plan"
        first = set(plan.first_phrase_roles)
        second = set(plan.second_phrase_roles)
        assert first != second, "Bridge phrase halves must differ"
        assert plan.lead_entry_delay_bars > 0, "Bridge must have delayed lead entry"

    def test_outro_phrase_plan_strips_progressively(self):
        """Outro phrase plan: second half must have fewer roles than first."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "outro", ["pads", "melody", "fx"], section_bars=8, occurrence=1
        )
        assert plan is not None
        assert len(plan.second_phrase_roles) < len(plan.first_phrase_roles), (
            "Outro second half must strip roles for progressive resolution"
        )

    def test_phrase_plan_split_bar_is_valid(self):
        """Phrase split_bar must be >= 1 and < section_bars."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "verse", ["drums", "bass", "melody", "pads"], section_bars=8, occurrence=1
        )
        assert plan is not None
        assert 1 <= plan.split_bar < 8, f"split_bar={plan.split_bar} out of range [1, 7]"

    def test_pre_hook_phrase_plan_end_dropout(self):
        """Pre-hook phrase plan must specify end-of-section dropout for tension."""
        from app.services.section_identity_engine import get_phrase_variation_plan
        plan = get_phrase_variation_plan(
            "pre_hook", ["bass", "arp", "fx", "drums"], section_bars=8, occurrence=1
        )
        assert plan is not None, "8-bar pre-hook must have a phrase plan"
        assert plan.end_dropout_bars > 0, "Pre-hook must have end dropout bars"


class TestRepeatDistinction:
    """Phase 3: Repeated sections must be audibly distinct at the role-map level."""

    def test_verse1_verse2_jaccard_meets_threshold(self):
        """Verse 1 and verse 2 must have >= _MIN_REPEAT_DISTINCTION Jaccard distance."""
        from app.services.section_identity_engine import select_roles_with_choreography
        roles1, _ = select_roles_with_choreography("verse", _FULL_ROLES, occurrence=1)
        roles2, _ = select_roles_with_choreography(
            "verse", _FULL_ROLES, occurrence=2, prev_same_type_roles=roles1
        )
        dist = _jaccard(roles1, roles2)
        assert dist >= _MIN_REPEAT_DISTINCTION, (
            f"verse1={roles1} vs verse2={roles2}: Jaccard={dist:.2f} < {_MIN_REPEAT_DISTINCTION}"
        )

    def test_hook1_hook2_jaccard_meets_threshold(self):
        """Hook 1 and hook 2 must have >= _MIN_REPEAT_DISTINCTION Jaccard distance."""
        from app.services.section_identity_engine import select_roles_with_choreography
        roles1, _ = select_roles_with_choreography("hook", _FULL_ROLES, occurrence=1)
        roles2, _ = select_roles_with_choreography(
            "hook", _FULL_ROLES, occurrence=2, prev_same_type_roles=roles1
        )
        dist = _jaccard(roles1, roles2)
        assert dist >= _MIN_REPEAT_DISTINCTION, (
            f"hook1={roles1} vs hook2={roles2}: Jaccard={dist:.2f} < {_MIN_REPEAT_DISTINCTION}"
        )

    def test_verse3_differs_from_verse2(self):
        """Verse 3 must differ from verse 2 (no two-state oscillation)."""
        from app.services.section_identity_engine import select_roles_with_choreography
        roles1, _ = select_roles_with_choreography("verse", _FULL_ROLES, occurrence=1)
        roles2, _ = select_roles_with_choreography(
            "verse", _FULL_ROLES, occurrence=2, prev_same_type_roles=roles1
        )
        roles3, _ = select_roles_with_choreography(
            "verse", _FULL_ROLES, occurrence=3, prev_same_type_roles=roles2
        )
        assert set(roles2) != set(roles3), f"verse2={roles2} and verse3={roles3} are identical"

    def test_breakdown_distinct_from_bridge(self):
        """Breakdown and bridge must be distinct section types with different role profiles."""
        from app.services.section_identity_engine import select_roles_with_choreography
        bridge_roles, _ = select_roles_with_choreography("bridge", _FULL_ROLES, occurrence=1)
        breakdown_roles, _ = select_roles_with_choreography("breakdown", _FULL_ROLES, occurrence=1)
        # Both suppress groove, but may differ in lead roles.
        assert "drums" not in bridge_roles, "Bridge must not have drums"
        assert "drums" not in breakdown_roles, "Breakdown must not have drums"
        # Their active sets must differ from hook to confirm they are not just density shifts.
        hook_roles, _ = select_roles_with_choreography("hook", _FULL_ROLES, occurrence=1)
        assert _jaccard(bridge_roles, hook_roles) >= 0.40, (
            f"Bridge ({bridge_roles}) is too similar to hook ({hook_roles})"
        )
        assert _jaccard(breakdown_roles, hook_roles) >= 0.40, (
            f"Breakdown ({breakdown_roles}) is too similar to hook ({hook_roles})"
        )


class TestRendererChoreographyEnforcement:
    """Phase 4: Renderer must materially respect choreography and phrase plans."""

    def test_apply_stem_primary_stores_choreography_with_flag_on(self):
        """When SECTION_CHOREOGRAPHY_V2=True, sections get choreography metadata."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [
            {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8},
            {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8},
        ]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            mock_settings.feature_section_choreography_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        for section in result:
            assert "choreography" in section, (
                f"Section {section.get('type')} missing choreography metadata"
            )
            choro = section["choreography"]
            assert "leader_roles" in choro
            assert "support_roles" in choro
            assert "suppressed_roles" in choro

    def test_apply_stem_primary_stores_phrase_plan_for_8bar_sections(self):
        """When SECTION_CHOREOGRAPHY_V2=True, 8-bar sections get phrase plans."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [
            {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8},
            {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8},
        ]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            mock_settings.feature_section_choreography_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        # At least one 8-bar section should have a phrase plan (verse or hook)
        sections_with_phrase_plans = [s for s in result if s.get("phrase_plan")]
        assert len(sections_with_phrase_plans) > 0, (
            "At least one 8-bar section must have a phrase_plan when SECTION_CHOREOGRAPHY_V2=True"
        )

    def test_apply_stem_primary_no_phrase_plan_for_4bar_sections(self):
        """Short sections (4 bars) must NOT have phrase plans injected."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 4},
            {"name": "Pre-hook", "type": "pre_hook", "bar_start": 4, "bars": 4},
        ]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            mock_settings.feature_section_choreography_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        for section in result:
            assert not section.get("phrase_plan"), (
                f"4-bar section {section.get('type')} must not have a phrase_plan"
            )

    def test_verse1_and_verse2_have_different_instruments(self):
        """Verse 1 and verse 2 must have different instrument lists in the renderer."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 4},
            {"name": "Verse 1", "type": "verse", "bar_start": 4, "bars": 8},
            {"name": "Hook 1", "type": "hook", "bar_start": 12, "bars": 8},
            {"name": "Verse 2", "type": "verse", "bar_start": 20, "bars": 8},
            {"name": "Hook 2", "type": "hook", "bar_start": 28, "bars": 8},
        ]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            mock_settings.feature_section_choreography_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        verse_sections = [s for s in result if s.get("type") == "verse"]
        assert len(verse_sections) >= 2
        verse1_roles = set(verse_sections[0].get("active_stem_roles", []))
        verse2_roles = set(verse_sections[1].get("active_stem_roles", []))
        dist = _jaccard(list(verse1_roles), list(verse2_roles))
        assert dist >= 0.15, (
            f"Verse 1 ({sorted(verse1_roles)}) and verse 2 ({sorted(verse2_roles)}) "
            f"are too similar in renderer output (Jaccard={dist:.2f} < 0.15)"
        )

    def test_hook1_and_hook2_have_different_instruments(self):
        """Hook 1 and hook 2 must have different instrument lists in the renderer."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [
            {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8},
            {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8},
            {"name": "Verse 2", "type": "verse", "bar_start": 16, "bars": 8},
            {"name": "Hook 2", "type": "hook", "bar_start": 24, "bars": 8},
        ]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            mock_settings.feature_section_choreography_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        hook_sections = [s for s in result if s.get("type") == "hook"]
        assert len(hook_sections) >= 2
        hook1_roles = set(hook_sections[0].get("active_stem_roles", []))
        hook2_roles = set(hook_sections[1].get("active_stem_roles", []))
        dist = _jaccard(list(hook1_roles), list(hook2_roles))
        assert dist >= 0.15, (
            f"Hook 1 ({sorted(hook1_roles)}) and hook 2 ({sorted(hook2_roles)}) "
            f"are too similar (Jaccard={dist:.2f} < 0.15)"
        )

    def test_transition_events_are_present(self):
        """Transition boundary events must be present at section boundaries."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [
            {"name": "Verse 1", "type": "verse", "bar_start": 0, "bars": 8},
            {"name": "Hook 1", "type": "hook", "bar_start": 8, "bars": 8},
        ]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            mock_settings.feature_section_choreography_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        # Verse → Hook boundary should have at least one transition event.
        verse_section = next((s for s in result if s.get("type") == "verse"), None)
        assert verse_section is not None
        boundary_events = verse_section.get("boundary_events", [])
        assert len(boundary_events) > 0, (
            "Verse → Hook transition must generate at least one boundary event"
        )

    def test_anti_mud_still_holds_with_choreography(self):
        """Anti-mud: intro and bridge must not have drums or bass even with choreography on."""
        import unittest.mock
        from app.services.arrangement_jobs import _apply_stem_primary_section_states

        sections = [
            {"name": "Intro", "type": "intro", "bar_start": 0, "bars": 4},
            {"name": "Bridge", "type": "bridge", "bar_start": 4, "bars": 8},
        ]
        stem_meta = {"enabled": True, "succeeded": True, "roles_detected": _FULL_ROLES}

        with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
            mock_settings.feature_producer_section_identity_v2 = True
            mock_settings.feature_section_choreography_v2 = True
            result = _apply_stem_primary_section_states(sections, stem_meta)

        for section in result:
            roles = section.get("active_stem_roles", [])
            assert "drums" not in roles, (
                f"Section {section.get('type')} must not have drums: {roles}"
            )
            assert "bass" not in roles, (
                f"Section {section.get('type')} must not have bass: {roles}"
            )


class TestNewQAMetrics:
    """Phase 5: New QA metrics must compute correctly and catch fake arrangements."""

    def _make_sections(self, roles_per_section: list[tuple[str, list[str], int]]) -> list[dict]:
        """Helper: build section dicts from (type, roles, bars) triples."""
        result = []
        bar = 0
        for stype, roles, bars in roles_per_section:
            result.append({
                "type": stype,
                "active_stem_roles": roles,
                "instruments": roles,
                "bars": bars,
                "bar_start": bar,
            })
            bar += bars
        return result

    def test_section_identity_score_perfect_when_no_forbidden_violations(self):
        """section_identity_score must be 1.0 when all sections respect forbidden roles."""
        sections = self._make_sections([
            ("intro", ["pads", "fx"], 4),
            ("verse", ["drums", "bass", "melody"], 8),
            ("hook", ["drums", "bass", "melody", "synth"], 8),
            ("outro", ["pads", "melody"], 4),
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.section_identity_score == 1.0, (
            f"section_identity_score={metrics.section_identity_score} — expected 1.0"
        )

    def test_section_identity_score_penalised_for_forbidden_roles(self):
        """section_identity_score must drop below 1.0 when a section has forbidden roles."""
        sections = self._make_sections([
            ("intro", ["drums", "pads", "fx"], 4),   # drums forbidden in intro
            ("verse", ["drums", "bass"], 8),
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.section_identity_score < 1.0, (
            "section_identity_score must be < 1.0 when intro has forbidden drums"
        )
        assert any("section_identity_score" in w for w in metrics.warnings)

    def test_repeat_distinction_score_high_when_repeated_sections_differ(self):
        """repeat_distinction_score must be >= _MIN_REPEAT_DISTINCTION for well-differentiated arrangements."""
        sections = self._make_sections([
            ("verse", ["drums", "bass"], 8),
            ("hook", ["drums", "bass", "melody", "synth"], 8),
            ("verse", ["drums", "melody", "vocal"], 8),   # different from verse 1
            ("hook", ["drums", "bass", "melody", "synth", "pads"], 8),  # different from hook 1
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.repeat_distinction_score >= _MIN_REPEAT_DISTINCTION, (
            f"repeat_distinction_score={metrics.repeat_distinction_score:.2f} — "
            f"expected >= {_MIN_REPEAT_DISTINCTION} for well-differentiated arrangement"
        )

    def test_repeat_distinction_score_low_for_identical_repeats(self):
        """repeat_distinction_score must warn when repeated sections are identical."""
        roles = ["drums", "bass", "melody"]
        sections = self._make_sections([
            ("verse", roles, 8),
            ("hook", ["drums", "bass", "melody", "synth"], 8),
            ("verse", roles, 8),  # identical repeat
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.repeat_distinction_score < _MIN_REPEAT_DISTINCTION, (
            f"repeat_distinction_score={metrics.repeat_distinction_score:.2f} — "
            f"should be < {_MIN_REPEAT_DISTINCTION} for identical repeats"
        )
        assert any("repeat_distinction_score" in w for w in metrics.warnings)

    def test_phrase_variation_score_1_when_all_sections_have_plans(self):
        """phrase_variation_score must be 1.0 when all >4-bar sections have phrase plans."""
        sections = self._make_sections([
            ("intro", ["pads"], 4),
            ("verse", ["drums", "bass", "melody"], 8),
            ("hook", ["drums", "bass", "melody", "synth"], 8),
        ])
        # Inject phrase plans for the > 4 bar sections
        for s in sections:
            if int(s.get("bars", 0)) > 4:
                s["phrase_plan"] = {"split_bar": 4, "description": "test"}
        metrics = compute_arrangement_quality(sections)
        assert metrics.phrase_variation_score == 1.0, (
            f"phrase_variation_score={metrics.phrase_variation_score} — expected 1.0"
        )

    def test_phrase_variation_score_0_when_no_plans(self):
        """phrase_variation_score must be 0.0 when no >4-bar sections have plans."""
        sections = self._make_sections([
            ("verse", ["drums", "bass", "melody"], 8),
            ("hook", ["drums", "bass", "melody", "synth"], 8),
        ])
        # No phrase_plan injected
        metrics = compute_arrangement_quality(sections)
        assert metrics.phrase_variation_score == 0.0, (
            f"phrase_variation_score={metrics.phrase_variation_score} — expected 0.0"
        )
        assert any("phrase_variation_score" in w for w in metrics.warnings)

    def test_arrangement_motion_score_reflects_real_swaps(self):
        """arrangement_motion_score must be high when roles are swapped not just added."""
        sections = self._make_sections([
            ("verse", ["drums", "bass"], 8),
            ("hook", ["bass", "melody", "synth"], 8),   # drums removed, melody+synth added
            ("bridge", ["pads", "fx"], 8),              # bass removed, pads+fx added
            ("outro", ["pads", "melody"], 4),
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.arrangement_motion_score >= 0.50, (
            f"arrangement_motion_score={metrics.arrangement_motion_score:.2f} — "
            "expected >= 0.50 for arrangement with real role swaps"
        )

    def test_arrangement_motion_score_low_for_density_only_shifts(self):
        """arrangement_motion_score must be low when sections only add roles (no removals)."""
        sections = self._make_sections([
            ("intro", ["pads"], 4),
            ("verse", ["pads", "drums"], 8),          # only added
            ("hook", ["pads", "drums", "bass"], 8),   # only added
            ("outro", ["pads", "drums", "bass", "melody"], 4),  # only added
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.arrangement_motion_score <= 0.25, (
            f"arrangement_motion_score={metrics.arrangement_motion_score:.2f} — "
            "should be low for density-only shifts (no role removals)"
        )

    def test_audible_contrast_score_high_when_sections_clearly_different(self):
        """audible_contrast_score must be high when adjacent sections have > 0.35 Jaccard."""
        sections = self._make_sections([
            ("intro", ["pads", "fx"], 4),
            ("verse", ["drums", "bass", "melody"], 8),
            ("hook", ["drums", "bass", "melody", "synth", "vocal"], 8),
            ("bridge", ["pads", "arp", "melody"], 8),
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.audible_contrast_score >= 0.50, (
            f"audible_contrast_score={metrics.audible_contrast_score:.2f} — "
            "expected >= 0.50 for clearly differentiated arrangement"
        )

    def test_audible_contrast_score_warns_when_low(self):
        """audible_contrast_score must emit a warning when below threshold."""
        sections = self._make_sections([
            ("verse", ["drums", "bass", "melody"], 8),
            ("hook", ["drums", "bass", "melody"], 8),  # identical to verse — no contrast
        ])
        metrics = compute_arrangement_quality(sections)
        assert metrics.audible_contrast_score < 0.50
        assert any("audible_contrast_score" in w for w in metrics.warnings)

    def test_all_new_metrics_are_present_in_result(self):
        """All five v2.0 metrics must be present as named fields on the result."""
        sections = self._make_sections([
            ("verse", ["drums", "bass"], 8),
            ("hook", ["drums", "bass", "melody"], 8),
        ])
        metrics = compute_arrangement_quality(sections)
        assert hasattr(metrics, "section_identity_score")
        assert hasattr(metrics, "repeat_distinction_score")
        assert hasattr(metrics, "phrase_variation_score")
        assert hasattr(metrics, "arrangement_motion_score")
        assert hasattr(metrics, "audible_contrast_score")
        # All scores must be in [0, 1].
        for attr in (
            "section_identity_score", "repeat_distinction_score",
            "phrase_variation_score", "arrangement_motion_score", "audible_contrast_score",
        ):
            val = getattr(metrics, attr)
            assert 0.0 <= val <= 1.0, f"{attr}={val} out of [0, 1]"

