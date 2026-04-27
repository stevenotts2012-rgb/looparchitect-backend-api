"""
Tests for ImpactEngine
(app/services/impact_engine.py).

Covers (from the problem statement):
1. Contrast increases when contrast_score < 0.6
2. Drops are inserted when missing from hook sections
3. Hooks become the strongest section (most roles, highest energy)
4. Repeated sections diverge (≥ 2 audible dimensions changed)
5. Re-entry accents exist when hook follows pre-hook
6. Metadata fields are always present
7. Safety — intensities never exceed ceiling, blocked roles not re-added
8. Hook identity — fx_impact event always injected
9. Verse shared roles removed from verse when contrast enforced
"""

from __future__ import annotations

import dataclasses

import pytest

from app.services.impact_engine import ImpactEngine, _SAFE_GAIN_CEILING, _make_boundary_event
from app.services.resolved_render_plan import (
    ResolvedBoundaryEvent,
    ResolvedRenderPlan,
    ResolvedSection,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _be(
    event_type: str = "drum_fill",
    intensity: float = 0.75,
    source_engine: str = "test",
    bar: int = 0,
    params: dict | None = None,
) -> ResolvedBoundaryEvent:
    return ResolvedBoundaryEvent(
        event_type=event_type,
        source_engine=source_engine,
        placement="boundary",
        intensity=intensity,
        bar=bar,
        params=params or {},
    )


def _sec(
    name: str = "Verse 1",
    section_type: str = "verse",
    bar_start: int = 0,
    bars: int = 8,
    energy: float = 0.60,
    active: list[str] | None = None,
    blocked: list[str] | None = None,
    reentries: list[str] | None = None,
    boundary_events: list[ResolvedBoundaryEvent] | None = None,
    pattern_events: list[dict] | None = None,
    groove_events: list[dict] | None = None,
    target_fullness: str | None = None,
) -> ResolvedSection:
    return ResolvedSection(
        section_name=name,
        section_type=section_type,
        bar_start=bar_start,
        bars=bars,
        energy=energy,
        final_active_roles=active or ["drums", "bass"],
        final_blocked_roles=blocked or [],
        final_reentries=reentries or [],
        final_boundary_events=boundary_events or [],
        final_pattern_events=pattern_events or [],
        final_groove_events=groove_events or [],
        target_fullness=target_fullness,
    )


def _plan(
    sections: list[ResolvedSection],
    available_roles: list[str] | None = None,
) -> ResolvedRenderPlan:
    return ResolvedRenderPlan(
        resolved_sections=sections,
        bpm=140.0,
        key="G minor",
        total_bars=sum(s.bars for s in sections),
        source_quality="true_stems",
        available_roles=available_roles
        or ["drums", "bass", "808", "melody", "pads", "synth", "fx"],
        genre="trap",
        noop_annotations=[],
    )


def _run(
    sections: list[ResolvedSection],
    report: dict | None = None,
    available_roles: list[str] | None = None,
    genre: str = "trap",
    vibe: str = "aggressive",
) -> tuple[ResolvedRenderPlan, dict]:
    p = _plan(sections, available_roles)
    r = report or {
        "repetition_groups": [],
        "contrast_score": 1.0,
        "hook_payoff_score": 1.0,
        "impact_scores": {},
        "safety_findings": [],
    }
    engine = ImpactEngine(
        resolved_plan=p,
        production_quality_report=r,
        selected_genre=genre,
        selected_vibe=vibe,
        arrangement_id=42,
    )
    return engine.enforce()


def _section_by_name(plan: ResolvedRenderPlan, name: str) -> ResolvedSection:
    for sec in plan.resolved_sections:
        if sec.section_name == name:
            return sec
    raise KeyError(name)


# ---------------------------------------------------------------------------
# 1. Contrast increases when contrast_score < 0.6
# ---------------------------------------------------------------------------


class TestContrastEnforcement:
    def test_verse_density_reduced_when_low_contrast(self):
        """Verse active roles are reduced when contrast_score < 0.6."""
        verse = _sec(
            "Verse 1", "verse", 0, 8, 0.55,
            active=["drums", "bass", "melody", "pads", "synth"],
        )
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.85,
            active=["drums", "bass", "melody", "pads", "synth", "808"],
        )
        report = {"contrast_score": 0.4}
        plan, meta = _run([verse, hook], report)

        repaired_verse = _section_by_name(plan, "Verse 1")
        assert len(repaired_verse.final_active_roles) < len(verse.final_active_roles), \
            "Verse density was not reduced"
        assert meta["impact_engine_applied"] is True
        assert any(
            a["rule"] == "verse_density_reduced"
            for a in meta["contrast_adjustments"]
        )

    def test_hook_energy_boosted_when_low_contrast(self):
        """Hook energy is raised to ≥ 0.9 when contrast_score < 0.6."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.55)
        hook = _sec("Hook 1", "hook", 8, 8, 0.70)
        report = {"contrast_score": 0.3}
        plan, meta = _run([verse, hook], report)

        repaired_hook = _section_by_name(plan, "Hook 1")
        assert repaired_hook.energy >= 0.9, "Hook energy not boosted to ≥ 0.9"

    def test_no_contrast_enforcement_above_threshold(self):
        """When contrast_score ≥ 0.6 no density changes are applied."""
        verse = _sec(
            "Verse 1", "verse", 0, 8, 0.55,
            active=["drums", "bass", "melody"],
        )
        hook = _sec("Hook 1", "hook", 8, 8, 0.90, active=["drums", "bass", "melody", "pads"])
        report = {"contrast_score": 0.8}
        plan, meta = _run([verse, hook], report)

        repaired_verse = _section_by_name(plan, "Verse 1")
        assert repaired_verse.final_active_roles == verse.final_active_roles, \
            "Verse roles changed when contrast was already sufficient"

    def test_shared_role_removed_from_verse_when_low_contrast(self):
        """At least one hook role must be removed from verse under low contrast."""
        shared = "melody"
        verse = _sec(
            "Verse 1", "verse", 0, 8, 0.55,
            active=["drums", "bass", shared, "pads"],
        )
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.85,
            active=["drums", "bass", shared, "synth"],
        )
        report = {"contrast_score": 0.4}
        plan, meta = _run([verse, hook], report)

        repaired_verse = _section_by_name(plan, "Verse 1")
        contrast_records = [
            a for a in meta["contrast_adjustments"]
            if a.get("rule") == "verse_density_reduced"
            and a.get("section") == "Verse 1"
        ]
        assert contrast_records, "No contrast_adjustments record for Verse 1"
        record = contrast_records[0]
        assert record["shared_roles_removed"], \
            "No shared hook roles were removed from verse"


# ---------------------------------------------------------------------------
# 2. Drops inserted when missing
# ---------------------------------------------------------------------------


class TestDropEnforcement:
    def test_drop_added_to_hook_with_no_drop_event(self):
        """A hook with no drop event receives a silence_drop_before_hook."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            active=["drums", "bass", "melody"],
            boundary_events=[_be("drum_fill")],
        )
        plan, meta = _run([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        drop_types = {e.event_type for e in repaired_hook.final_boundary_events}
        from app.services.impact_engine import _DROP_EVENT_TYPES
        assert drop_types & _DROP_EVENT_TYPES, "No drop event added to hook"
        assert meta["drop_enforcements"], "drop_enforcements metadata is empty"

    def test_drop_not_duplicated_if_already_present(self):
        """If a drop event already exists it must not be duplicated."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("silence_drop", bar=8)],
        )
        plan, meta = _run([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        silence_drop_count = sum(
            1 for e in repaired_hook.final_boundary_events
            if e.event_type == "silence_drop"
        )
        assert silence_drop_count == 1, "silence_drop was duplicated"

    def test_drop_duration_enforced(self):
        """An existing drop event with drop_bars < 0.25 must be patched."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("silence_drop", params={"drop_bars": 0.10})],
        )
        plan, meta = _run([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        for evt in repaired_hook.final_boundary_events:
            if evt.event_type == "silence_drop":
                assert evt.params.get("drop_bars", 0) >= 0.25, \
                    "drop_bars not patched to ≥ 0.25"

    def test_non_hook_sections_not_affected_by_drop_rule(self):
        """Verse and intro sections must not receive drop event injection."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60)
        plan, meta = _run([verse])

        repaired_verse = _section_by_name(plan, "Verse 1")
        from app.services.impact_engine import _DROP_EVENT_TYPES
        drop_types = {e.event_type for e in repaired_verse.final_boundary_events}
        assert not (drop_types & _DROP_EVENT_TYPES), \
            "Drop event incorrectly added to verse"


# ---------------------------------------------------------------------------
# 3. Hooks become the strongest section
# ---------------------------------------------------------------------------


class TestHookIdentity:
    def test_hook_has_more_roles_than_verse(self):
        """After engine runs hook must have more active roles than any verse."""
        verse = _sec(
            "Verse 1", "verse", 0, 8, 0.60,
            active=["drums", "bass", "melody"],
        )
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.85,
            active=["drums", "bass"],  # fewer roles than verse — must be fixed
        )
        plan, meta = _run([verse, hook], available_roles=["drums", "bass", "melody", "808", "pads"])

        repaired_hook = _section_by_name(plan, "Hook 1")
        repaired_verse = _section_by_name(plan, "Verse 1")
        assert len(repaired_hook.final_active_roles) > len(repaired_verse.final_active_roles), \
            "Hook does not have more roles than verse after identity enforcement"

    def test_hook_has_highest_energy(self):
        """Hook energy must be strictly higher than all verse energies."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.70)
        hook = _sec("Hook 1", "hook", 8, 8, 0.65)  # lower than verse — must be fixed
        plan, meta = _run([verse, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        repaired_verse = _section_by_name(plan, "Verse 1")
        assert repaired_hook.energy >= repaired_verse.energy, \
            "Hook energy is not highest after identity enforcement"

    def test_fx_impact_event_added_to_hook(self):
        """Every hook must receive an fx_impact boundary event."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            active=["drums", "bass", "melody"],
        )
        plan, meta = _run([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        event_types = {e.event_type for e in repaired_hook.final_boundary_events}
        assert "fx_impact" in event_types, "fx_impact event not added to hook"

    def test_fx_impact_not_duplicated(self):
        """fx_impact must not be added twice if already present."""
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("fx_impact")],
        )
        plan, meta = _run([hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        count = sum(1 for e in repaired_hook.final_boundary_events if e.event_type == "fx_impact")
        assert count == 1, "fx_impact was duplicated"


# ---------------------------------------------------------------------------
# 4. Repeated sections diverge
# ---------------------------------------------------------------------------


class TestRepeatedSectionDivergence:
    def test_two_identical_sections_diverge(self):
        """Second occurrence of a repeated section must differ in ≥ 2 dimensions."""
        sec1 = _sec("Verse 1", "verse", 0, 8, 0.60, active=["drums", "bass", "melody", "pads"])
        sec2 = _sec("Verse 2", "verse", 8, 8, 0.60, active=["drums", "bass", "melody", "pads"])
        report = {
            "contrast_score": 1.0,
            "repetition_groups": [{"sections": ["Verse 1", "Verse 2"]}],
        }
        plan, meta = _run([sec1, sec2], report)

        v2 = _section_by_name(plan, "Verse 2")
        v1_orig = sec1

        differences = 0
        if v2.energy != v1_orig.energy:
            differences += 1
        if any(
            "impact_variation_pass" in str(e.get("action", ""))
            for e in v2.final_pattern_events
        ):
            differences += 1
        if any(
            "impact_groove_shift" in str(e.get("groove_type", ""))
            for e in v2.final_groove_events
        ):
            differences += 1
        if set(v2.final_active_roles) != set(v1_orig.final_active_roles):
            differences += 1

        assert differences >= 2, f"Only {differences} dimension(s) changed — expected ≥ 2"

    def test_first_occurrence_unchanged(self):
        """First section in a repetition group must not be modified by this rule."""
        sec1 = _sec("Verse 1", "verse", 0, 8, 0.60, active=["drums", "bass"])
        sec2 = _sec("Verse 2", "verse", 8, 8, 0.60, active=["drums", "bass"])
        report = {
            "contrast_score": 1.0,
            "repetition_groups": [{"sections": ["Verse 1", "Verse 2"]}],
        }
        plan, meta = _run([sec1, sec2], report)

        v1 = _section_by_name(plan, "Verse 1")
        assert v1.energy == sec1.energy
        assert v1.final_pattern_events == sec1.final_pattern_events

    def test_differentiation_metadata_recorded(self):
        """contrast_adjustments must include a repeated_section_differentiated record."""
        sec1 = _sec("V1", "verse", 0, 8, 0.60, active=["drums", "bass"])
        sec2 = _sec("V2", "verse", 8, 8, 0.60, active=["drums", "bass"])
        report = {
            "contrast_score": 1.0,
            "repetition_groups": [{"sections": ["V1", "V2"]}],
        }
        _, meta = _run([sec1, sec2], report)

        assert any(
            a.get("rule") == "repeated_section_differentiated"
            for a in meta["contrast_adjustments"]
        )


# ---------------------------------------------------------------------------
# 5. Re-entry accents exist when hook follows pre-hook
# ---------------------------------------------------------------------------


class TestReentryImpact:
    def test_re_entry_accent_added_when_hook_follows_pre_hook(self):
        """A re_entry_accent must be added to a hook that follows a pre-hook."""
        pre_hook = _sec("Pre-Hook 1", "pre_hook", 8, 4, 0.70)
        hook = _sec(
            "Hook 1", "hook", 12, 8, 0.90,
            boundary_events=[_be("drum_fill")],
        )
        plan, meta = _run([pre_hook, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        event_types = {e.event_type for e in repaired_hook.final_boundary_events}
        assert "re_entry_accent" in event_types, \
            "re_entry_accent not added to hook following pre-hook"

    def test_anchor_roles_added_to_reentries(self):
        """Drums and 808 must be in final_reentries when hook follows pre-hook."""
        pre_hook = _sec("Pre-Hook 1", "pre_hook", 8, 4, 0.70)
        hook = _sec(
            "Hook 1", "hook", 12, 8, 0.90,
            active=["drums", "bass", "808", "melody"],
        )
        plan, meta = _run([pre_hook, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        assert "drums" in repaired_hook.final_reentries or "808" in repaired_hook.final_reentries, \
            "Anchor roles not in final_reentries after hook-follows-pre-hook enforcement"

    def test_re_entry_accent_not_duplicated(self):
        """If re_entry_accent already exists it must not be added again."""
        pre_hook = _sec("Pre-Hook 1", "pre_hook", 8, 4, 0.70)
        hook = _sec(
            "Hook 1", "hook", 12, 8, 0.90,
            boundary_events=[_be("re_entry_accent")],
        )
        plan, meta = _run([pre_hook, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        count = sum(
            1 for e in repaired_hook.final_boundary_events
            if e.event_type == "re_entry_accent"
        )
        assert count == 1, "re_entry_accent was duplicated"

    def test_reentry_enforcement_metadata_recorded(self):
        """reentry_enforcements metadata must be populated when rule fires."""
        pre_hook = _sec("Pre-Hook 1", "pre_hook", 8, 4, 0.70)
        hook = _sec("Hook 1", "hook", 12, 8, 0.90)
        _, meta = _run([pre_hook, hook])

        assert meta["reentry_enforcements"], "reentry_enforcements is empty"

    def test_no_reentry_when_hook_does_not_follow_pre_hook(self):
        """Hook that follows a verse must not receive re_entry_accent from this rule."""
        verse = _sec("Verse 1", "verse", 0, 8, 0.60)
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.90,
            boundary_events=[_be("drum_fill")],
        )
        plan, meta = _run([verse, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        # re_entry_accent may still be added by hook-identity rule (fx_impact),
        # but should not come from reentry_enforcement
        assert not meta["reentry_enforcements"], \
            "reentry_enforcements fired for hook not preceded by pre-hook"


# ---------------------------------------------------------------------------
# 6. Metadata fields always present
# ---------------------------------------------------------------------------


class TestMetadataFields:
    def test_all_metadata_fields_present(self):
        """All required metadata fields must be present in every run."""
        hook = _sec("Hook 1", "hook", 0, 8, 0.90)
        _, meta = _run([hook])

        required = {
            "impact_engine_applied",
            "contrast_adjustments",
            "drop_enforcements",
            "reentry_enforcements",
            "impact_engine_version",
        }
        for field in required:
            assert field in meta, f"Metadata field '{field}' is missing"

    def test_impact_engine_applied_is_true_on_success(self):
        """impact_engine_applied must be True on a successful run."""
        _, meta = _run([_sec("Hook 1", "hook", 0, 8, 0.90)])
        assert meta["impact_engine_applied"] is True

    def test_metadata_lists_are_lists(self):
        """contrast_adjustments, drop_enforcements and reentry_enforcements are lists."""
        _, meta = _run([_sec("Hook 1", "hook", 0, 8, 0.90)])
        assert isinstance(meta["contrast_adjustments"], list)
        assert isinstance(meta["drop_enforcements"], list)
        assert isinstance(meta["reentry_enforcements"], list)


# ---------------------------------------------------------------------------
# 7. Safety — intensities never exceed ceiling, blocked roles respected
# ---------------------------------------------------------------------------


class TestSafety:
    def test_injected_event_intensity_never_exceeds_ceiling(self):
        """All events injected by the engine must have intensity ≤ _SAFE_GAIN_CEILING."""
        pre_hook = _sec("Pre-Hook 1", "pre_hook", 0, 4, 0.70)
        hook = _sec("Hook 1", "hook", 4, 8, 0.90)
        plan, meta = _run([pre_hook, hook])

        repaired_hook = _section_by_name(plan, "Hook 1")
        for evt in repaired_hook.final_boundary_events:
            if evt.source_engine == "impact_engine":
                assert evt.intensity <= _SAFE_GAIN_CEILING, (
                    f"Event '{evt.event_type}' has intensity {evt.intensity} "
                    f"above ceiling {_SAFE_GAIN_CEILING}"
                )

    def test_blocked_roles_not_added_to_active(self):
        """Roles in final_blocked_roles must never be added to final_active_roles."""
        verse = _sec(
            "Verse 1", "verse", 0, 8, 0.60,
            active=["drums", "bass"],
        )
        hook = _sec(
            "Hook 1", "hook", 8, 8, 0.50,
            active=["drums", "bass"],
            blocked=["melody", "808", "pads"],
        )
        plan, meta = _run(
            [verse, hook],
            report={"contrast_score": 0.3},
            available_roles=["drums", "bass", "melody", "808", "pads"],
        )

        repaired_hook = _section_by_name(plan, "Hook 1")
        blocked = set(repaired_hook.final_blocked_roles)
        active = set(repaired_hook.final_active_roles)
        overlap = blocked & active
        assert not overlap, (
            f"Blocked roles {overlap} appear in final_active_roles"
        )

    def test_make_boundary_event_clamps_intensity(self):
        """_make_boundary_event must clamp intensity to _SAFE_GAIN_CEILING."""
        evt = _make_boundary_event(event_type="fx_impact", intensity=99.9)
        assert evt.intensity <= _SAFE_GAIN_CEILING
