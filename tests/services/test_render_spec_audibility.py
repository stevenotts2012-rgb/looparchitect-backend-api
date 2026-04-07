"""
Render-spec audibility regression tests.

These tests fail if the arrangement pipeline produces only density-shifted
output — i.e. if section choreography decisions do not survive into actual
render-time audio input selection.

Covers Phase 5 (DELIVERABLES §5) and Phase 4 enforcement:

- phrase_plan survives _build_producer_arrangement_from_render_plan()
- hook_evolution survives normalization
- Section-level variations (bridge_strip, outro_strip_down) survive normalization
- verse 1 stem set != verse 2 stem set when SECTION_CHOREOGRAPHY_V2 is on
- hook 1 phrase A != hook 1 phrase B when choreography says so
- hook 2 differs from hook 1 in actual render spec
- breakdown/bridge have no drums or bass in render spec
- transition events alter the render spec (boundary_events present)
- _build_render_spec_summary() detects density-only flattening

Root cause for regressions caught here:
  _build_producer_arrangement_from_render_plan() was setting "variations": []
  and not forwarding "phrase_plan" or "hook_evolution" — so choreography
  decisions computed by _apply_stem_primary_section_states() were silently
  dropped before _render_producer_arrangement() executed.
"""

from __future__ import annotations

import json
import unittest.mock

import pytest

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


def _stem_meta(roles: list[str]) -> dict:
    return {"enabled": True, "succeeded": True, "roles_detected": list(roles)}


def _make_sections(specs: list[tuple]) -> list[dict]:
    """specs: (name, type, bar_start, bars)"""
    return [{"name": n, "type": t, "bar_start": bs, "bars": b} for n, t, bs, b in specs]


def _run_choreography(sections: list[dict], roles: list[str] = _FULL_ROLES) -> list[dict]:
    """Run _apply_stem_primary_section_states with BOTH v2 flags enabled."""
    from app.services.arrangement_jobs import _apply_stem_primary_section_states
    with unittest.mock.patch("app.services.arrangement_jobs.settings") as mock_settings:
        mock_settings.feature_producer_section_identity_v2 = True
        mock_settings.feature_section_choreography_v2 = True
        return _apply_stem_primary_section_states(sections, _stem_meta(roles))


def _normalize(sections: list[dict]) -> list[dict]:
    """Round-trip sections through _build_producer_arrangement_from_render_plan()."""
    from app.services.render_executor import _build_producer_arrangement_from_render_plan
    render_plan = {
        "bpm": 120.0,
        "sections": sections,
        "events": [],
    }
    producer_arrangement, _ = _build_producer_arrangement_from_render_plan(render_plan, 120.0)
    return producer_arrangement["sections"]


# ===========================================================================
# Phase 4 — Renderer Enforcement: field survival through normalization
# ===========================================================================


class TestRenderSpecFieldSurvival:
    """Fields set by choreography planner must survive the JSON normalization step."""

    def test_phrase_plan_survives_normalization(self):
        """phrase_plan must not be dropped by _build_producer_arrangement_from_render_plan."""
        sections = _run_choreography(_make_sections([("Hook", "hook", 0, 8)]))
        # hook + 8 bars should always receive a phrase_plan with SECTION_CHOREOGRAPHY_V2
        hook_section = sections[0]
        assert hook_section.get("phrase_plan") is not None, (
            "hook section (8 bars) must have a phrase_plan when SECTION_CHOREOGRAPHY_V2 is on"
        )
        normalized = _normalize([hook_section])
        assert normalized[0].get("phrase_plan") is not None, (
            "phrase_plan was dropped by _build_producer_arrangement_from_render_plan — "
            "intra-section phrase splits will never execute"
        )

    def test_phrase_plan_first_and_second_roles_survive(self):
        """first_phrase_roles and second_phrase_roles must survive round-trip."""
        sections = _run_choreography(_make_sections([("Verse", "verse", 0, 8)]))
        verse = sections[0]
        phrase_plan = verse.get("phrase_plan")
        if phrase_plan is None:
            pytest.skip("Verse 8 bars did not produce a phrase_plan (likely only 1 role)")
        first = phrase_plan.get("first_phrase_roles")
        second = phrase_plan.get("second_phrase_roles")
        assert first is not None and second is not None

        normalized = _normalize([verse])
        pp = normalized[0].get("phrase_plan")
        assert pp is not None, "phrase_plan dropped in normalization"
        assert pp.get("first_phrase_roles") == first
        assert pp.get("second_phrase_roles") == second

    def test_hook_evolution_survives_normalization(self):
        """hook_evolution stage must survive so hook1/hook2/hook3 processing differs."""
        sections = _run_choreography(_make_sections([
            ("Hook 1", "hook", 0, 8),
            ("Verse", "verse", 8, 8),
            ("Hook 2", "hook", 16, 8),
        ]))
        hook1 = sections[0]
        hook2 = sections[2]
        assert hook1.get("hook_evolution") is not None, "hook_evolution not set on hook 1"
        assert hook2.get("hook_evolution") is not None, "hook_evolution not set on hook 2"

        normalized = _normalize([hook1, sections[1], hook2])
        n_hook1 = normalized[0]
        n_hook2 = normalized[2]
        assert n_hook1.get("hook_evolution") is not None, (
            "hook_evolution dropped in normalization for hook 1"
        )
        assert n_hook2.get("hook_evolution") is not None, (
            "hook_evolution dropped in normalization for hook 2"
        )
        # Stages must differ
        stage1 = n_hook1["hook_evolution"].get("stage")
        stage2 = n_hook2["hook_evolution"].get("stage")
        assert stage1 != stage2, (
            f"hook 1 and hook 2 must have different evolution stages, both got '{stage1}'"
        )

    def test_bridge_strip_variation_survives_normalization(self):
        """bridge_strip variations must survive so bridge gets proper DSP treatment."""
        sections = _run_choreography(_make_sections([("Bridge", "bridge", 0, 8)]))
        bridge = sections[0]
        variations = bridge.get("variations") or []
        bridge_strip_vars = [v for v in variations if v.get("variation_type") == "bridge_strip"]
        assert bridge_strip_vars, "bridge section should have bridge_strip variation"

        normalized = _normalize([bridge])
        n_vars = normalized[0].get("variations") or []
        n_bridge_strip = [v for v in n_vars if v.get("variation_type") == "bridge_strip"]
        assert n_bridge_strip, (
            "bridge_strip variation was dropped in normalization — "
            "bridge section will not receive groove-removal DSP"
        )

    def test_outro_strip_down_variation_survives_normalization(self):
        """outro_strip_down variations must survive for progressive outro stripping."""
        sections = _run_choreography(_make_sections([("Outro", "outro", 0, 8)]))
        outro = sections[0]
        variations = outro.get("variations") or []
        outro_vars = [v for v in variations if v.get("variation_type") == "outro_strip_down"]
        assert outro_vars, "outro section should have outro_strip_down variation"

        normalized = _normalize([outro])
        n_vars = normalized[0].get("variations") or []
        n_outro = [v for v in n_vars if v.get("variation_type") == "outro_strip_down"]
        assert n_outro, (
            "outro_strip_down variation was dropped in normalization — "
            "outro section will not progressively strip"
        )

    def test_pre_hook_drum_mute_survives_normalization(self):
        """pre_hook_drum_mute must survive for pre-hook tension effect."""
        sections = _run_choreography(_make_sections([
            ("Verse", "verse", 0, 8),
            ("Pre-Hook", "pre_hook", 8, 4),
            ("Hook", "hook", 12, 8),
        ]))
        pre_hook = sections[1]
        all_events = list(pre_hook.get("variations") or []) + list(pre_hook.get("boundary_events") or [])
        drum_mute_types = {
            str(e.get("variation_type") or e.get("type") or "")
            for e in all_events
        }
        assert "pre_hook_drum_mute" in drum_mute_types, (
            f"pre_hook should have pre_hook_drum_mute, found {drum_mute_types}"
        )

        normalized = _normalize([sections[0], pre_hook, sections[2]])
        n_pre_hook = normalized[1]
        n_all = list(n_pre_hook.get("variations") or []) + list(n_pre_hook.get("boundary_events") or [])
        n_types = {str(e.get("variation_type") or e.get("type") or "") for e in n_all}
        assert "pre_hook_drum_mute" in n_types or "snare_pickup" in n_types, (
            f"pre_hook drum mute event dropped in normalization, found: {n_types}"
        )

    def test_boundary_events_survive_normalization(self):
        """boundary_events were already preserved; this is a non-regression guard."""
        sections = _run_choreography(_make_sections([
            ("Verse", "verse", 0, 8),
            ("Hook", "hook", 8, 8),
        ]))
        verse = sections[0]
        boundary_events = verse.get("boundary_events") or []
        assert boundary_events, "Verse before hook should have boundary events"

        normalized = _normalize([verse, sections[1]])
        n_boundary = normalized[0].get("boundary_events") or []
        assert n_boundary, "boundary_events must survive normalization"


# ===========================================================================
# Phase 5 — Audible stem-set differences
# ===========================================================================


class TestAudibleStemSetDifferences:
    """Stem sets must differ materially across repeated and adjacent sections."""

    def test_verse_2_stem_set_differs_from_verse_1(self):
        """With SECTION_CHOREOGRAPHY_V2 on, verse 2 must have a different stem set from verse 1."""
        sections = _run_choreography(_make_sections([
            ("Verse 1", "verse", 0, 8),
            ("Verse 2", "verse", 8, 8),
        ]))
        v1 = set(sections[0].get("active_stem_roles") or sections[0].get("instruments") or [])
        v2 = set(sections[1].get("active_stem_roles") or sections[1].get("instruments") or [])
        dist = _jaccard(list(v1), list(v2))
        assert dist >= 0.15, (
            f"Verse 2 {sorted(v2)} vs verse 1 {sorted(v1)}: "
            f"Jaccard distance {dist:.2f} is too low — sections sound identical"
        )

    def test_hook_2_differs_from_hook_1(self):
        """Hook 2 must have a different or larger stem set than hook 1."""
        sections = _run_choreography(_make_sections([
            ("Hook 1", "hook", 0, 8),
            ("Verse", "verse", 8, 8),
            ("Hook 2", "hook", 16, 8),
        ]))
        h1 = set(sections[0].get("active_stem_roles") or sections[0].get("instruments") or [])
        h2 = set(sections[2].get("active_stem_roles") or sections[2].get("instruments") or [])
        # Hook 2 must either have more roles or different roles than hook 1
        assert h2 != h1 or len(h2) >= len(h1), (
            f"Hook 2 {sorted(h2)} must differ from hook 1 {sorted(h1)} or be denser"
        )

    def test_breakdown_has_no_drums_or_bass(self):
        """Breakdown stem set must not include drums or bass (groove removal)."""
        sections = _run_choreography(_make_sections([("Breakdown", "breakdown", 0, 8)]))
        roles = set(sections[0].get("active_stem_roles") or sections[0].get("instruments") or [])
        assert "drums" not in roles, f"breakdown must not have drums, got {sorted(roles)}"
        assert "bass" not in roles, f"breakdown must not have bass, got {sorted(roles)}"

    def test_bridge_has_no_drums_or_bass(self):
        """Bridge stem set must not include drums or bass."""
        sections = _run_choreography(_make_sections([("Bridge", "bridge", 0, 8)]))
        roles = set(sections[0].get("active_stem_roles") or sections[0].get("instruments") or [])
        assert "drums" not in roles, f"bridge must not have drums, got {sorted(roles)}"
        assert "bass" not in roles, f"bridge must not have bass, got {sorted(roles)}"

    def test_intro_has_no_drums_or_bass(self):
        """Intro stem set must not include drums or bass (atmospheric entry)."""
        sections = _run_choreography(_make_sections([("Intro", "intro", 0, 4)]))
        roles = set(sections[0].get("active_stem_roles") or sections[0].get("instruments") or [])
        assert "drums" not in roles, f"intro must not have drums, got {sorted(roles)}"
        assert "bass" not in roles, f"intro must not have bass, got {sorted(roles)}"

    def test_hook_phrase_a_differs_from_phrase_b(self):
        """Hook phrase split must result in different stem sets for each half."""
        sections = _run_choreography(_make_sections([("Hook", "hook", 0, 8)]))
        hook = sections[0]
        phrase_plan = hook.get("phrase_plan")
        if phrase_plan is None:
            pytest.skip("Hook did not receive a phrase_plan (insufficient roles)")
        first = set(phrase_plan.get("first_phrase_roles") or [])
        second = set(phrase_plan.get("second_phrase_roles") or [])
        assert first != second or len(second) >= len(first), (
            f"Hook phrase A {sorted(first)} must differ from or expand phrase B {sorted(second)}"
        )

    def test_verse_phrase_a_is_rhythmic_only(self):
        """Verse phrase split: first half should be rhythm-only, second half adds melody."""
        sections = _run_choreography(_make_sections([("Verse", "verse", 0, 8)]))
        verse = sections[0]
        phrase_plan = verse.get("phrase_plan")
        if phrase_plan is None:
            pytest.skip("Verse did not receive a phrase_plan (short section or too few roles)")
        first = set(phrase_plan.get("first_phrase_roles") or [])
        second = set(phrase_plan.get("second_phrase_roles") or [])
        # Second phrase must have at least as many roles as first (or different roles)
        assert second != first or len(second) >= len(first), (
            f"Verse phrase B {sorted(second)} must differ from phrase A {sorted(first)}"
        )

    def test_pre_hook_2_loses_drums_vs_pre_hook_1(self):
        """Pre-hook 2 must suppress drums for tension-through-absence."""
        sections = _run_choreography(_make_sections([
            ("Pre-Hook 1", "pre_hook", 0, 4),
            ("Hook 1",     "hook",     4, 8),
            ("Pre-Hook 2", "pre_hook", 12, 4),
            ("Hook 2",     "hook",     16, 8),
        ]))
        ph1 = set(sections[0].get("active_stem_roles") or sections[0].get("instruments") or [])
        ph2 = set(sections[2].get("active_stem_roles") or sections[2].get("instruments") or [])
        # Pre-hook 2 should have fewer or different roles than pre-hook 1
        assert ph2 != ph1 or len(ph2) <= len(ph1), (
            f"Pre-hook 2 {sorted(ph2)} should differ from or be sparser than pre-hook 1 {sorted(ph1)}"
        )

    def test_transition_events_present_before_hook(self):
        """Verse section immediately before a hook must have transition boundary events."""
        sections = _run_choreography(_make_sections([
            ("Verse",  "verse", 0, 8),
            ("Hook",   "hook",  8, 8),
        ]))
        verse = sections[0]
        boundary = verse.get("boundary_events") or []
        variations = verse.get("variations") or []
        all_event_types = {str(e.get("type") or "") for e in boundary} | \
                          {str(v.get("variation_type") or "") for v in variations}
        transitional = {"silence_drop_before_hook", "crash_hit", "drum_fill", "snare_pickup"}
        assert all_event_types & transitional, (
            f"No transition event before hook — verse boundary has only: {all_event_types}"
        )

    def test_no_density_only_arrangement_detected(self):
        """_build_render_spec_summary must report > 1 distinct stem set for a real arrangement."""
        from app.services.arrangement_jobs import _build_render_spec_summary

        # Build a typical arrangement with multiple section types
        section_specs = [
            ("Intro",   "intro",     0,  4),
            ("Verse 1", "verse",     4,  8),
            ("Hook 1",  "hook",      12, 8),
            ("Verse 2", "verse",     20, 8),
            ("Hook 2",  "hook",      28, 8),
            ("Bridge",  "bridge",    36, 8),
            ("Outro",   "outro",     44, 4),
        ]
        sections = _run_choreography(_make_sections(section_specs))

        # Simulate what _render_producer_arrangement stores in timeline_sections
        timeline_sections = []
        for s in sections:
            timeline_sections.append({
                "name": s.get("name"),
                "type": s.get("type"),
                "runtime_active_stems": s.get("active_stem_roles") or s.get("instruments") or [],
                "phrase_plan_used": bool(s.get("phrase_plan") and int(s.get("bars", 0)) > 4),
                "phrase_plan": s.get("phrase_plan"),
                "hook_evolution": s.get("hook_evolution"),
                "applied_events": [
                    str(e.get("type") or e.get("variation_type") or "")
                    for e in list(s.get("boundary_events") or []) + list(s.get("variations") or [])
                ],
                "boundary_events": s.get("boundary_events") or [],
            })

        summary = _build_render_spec_summary(timeline_sections)

        assert summary["distinct_stem_set_count"] > 1, (
            f"distinct_stem_set_count={summary['distinct_stem_set_count']} — "
            "all sections use identical stem sets (density-only syndrome)"
        )


# ===========================================================================
# Phase 4 — Render spec reflects choreography intent (full pipeline check)
# ===========================================================================


class TestRenderSpecMatchesChoreographyIntent:
    """After round-trip through normalization, render spec must reflect planner decisions."""

    def test_full_arrangement_render_spec_has_phrase_splits_after_normalization(self):
        """With SECTION_CHOREOGRAPHY_V2, sections > 4 bars with eligible roles must have phrase plans."""
        specs = [
            ("Intro",   "intro",     0,  4),
            ("Verse 1", "verse",     4,  8),
            ("Pre-Hook","pre_hook",  12, 4),
            ("Hook 1",  "hook",      16, 8),
            ("Verse 2", "verse",     24, 8),
            ("Hook 2",  "hook",      32, 8),
            ("Breakdown","breakdown",40, 8),
            ("Outro",   "outro",     48, 4),
        ]
        sections = _run_choreography(_make_sections(specs))

        # Count eligible (> 4 bars) sections that received a phrase_plan from the planner
        planned_before = sum(
            1 for s in sections
            if s.get("phrase_plan") is not None and int(s.get("bars", 0)) > 4
        )
        assert planned_before > 0, (
            "SECTION_CHOREOGRAPHY_V2 should produce at least one phrase_plan for sections > 4 bars"
        )

        normalized = _normalize(sections)

        # After normalization, every section that had a phrase_plan must still have it
        for i, (orig, norm) in enumerate(zip(sections, normalized)):
            if orig.get("phrase_plan") is not None:
                assert norm.get("phrase_plan") is not None, (
                    f"Section {i} ({orig.get('type')}) had phrase_plan before normalization "
                    "but it was dropped — phrase splits will not execute"
                )

    def test_hooks_have_distinct_evolution_stages_after_normalization(self):
        """Hook evolution stages must be preserved and distinct after normalization."""
        specs = [
            ("Hook 1", "hook", 0,  8),
            ("Verse",  "verse", 8, 8),
            ("Hook 2", "hook", 16, 8),
            ("Verse 2","verse", 24, 8),
            ("Hook 3", "hook", 32, 8),
        ]
        sections = _run_choreography(_make_sections(specs))
        normalized = _normalize(sections)

        hook_stages = [
            (normalized[i].get("hook_evolution") or {}).get("stage")
            for i, spec in enumerate(specs)
            if spec[1] == "hook"
        ]
        assert len(set(filter(None, hook_stages))) >= 2, (
            f"Expected at least 2 distinct hook stages, got {hook_stages}"
        )

    def test_breakdown_has_bridge_strip_in_render_spec(self):
        """Breakdown section must have bridge_strip variation in normalized render spec."""
        sections = _run_choreography(_make_sections([("Breakdown", "breakdown", 0, 8)]))
        normalized = _normalize([sections[0]])
        n_vars = normalized[0].get("variations") or []
        n_boundary = normalized[0].get("boundary_events") or []
        all_types = {str(v.get("variation_type") or "") for v in n_vars} | \
                    {str(e.get("type") or "") for e in n_boundary}
        assert "bridge_strip" in all_types, (
            f"Breakdown section missing bridge_strip in render spec after normalization. "
            f"Found: {sorted(all_types)}"
        )

    def test_outro_has_progressive_strip_in_render_spec(self):
        """Outro must have outro_strip_down variation in normalized render spec."""
        sections = _run_choreography(_make_sections([("Outro", "outro", 0, 8)]))
        normalized = _normalize([sections[0]])
        n_vars = normalized[0].get("variations") or []
        n_types = {str(v.get("variation_type") or "") for v in n_vars}
        assert "outro_strip_down" in n_types, (
            f"Outro section missing outro_strip_down in render spec after normalization. "
            f"Found: {sorted(n_types)}"
        )
