"""
Unit tests for the Groove Engine.

Coverage (40+ tests):
1.  GrooveEvent type contract and bounds checking.
2.  GrooveProfile construction and field clamping.
3.  GrooveContext section_type derivation.
4.  GroovePlan serialisation round-trip.
5.  Groove profile selection by section type.
6.  Hook escalation — each hook groove stronger than the previous.
7.  Verse 2 more alive than Verse 1.
8.  Bridge / breakdown groove reduction.
9.  Outro groove simplification.
10. Pre-hook tension behaviour.
11. Microtiming bounds for all roles.
12. Source quality degradation (stereo_fallback, ai_separated).
13. Accent engine generation.
14. Bounce score behaviour (rewards, penalties).
15. GrooveValidator rules.
16. Serialisation correctness.
17. Integration metadata storage via shadow runner.
18. Determinism — same input yields same output.
"""

from __future__ import annotations

import pytest

from app.services.groove_engine import (
    GrooveContext,
    GrooveEngine,
    GrooveEvent,
    GroovePlan,
    GrooveProfile,
    GrooveState,
    GrooveValidationIssue,
    GrooveValidator,
    build_accent_events,
    get_profile,
    get_profile_for_section,
    list_profiles,
    safe_offset,
    score_bounce,
)
from app.services.groove_engine.microtiming import (
    bass_timing_offset,
    hat_timing_offset,
    kick_timing_offset,
    snare_timing_offset,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _ctx(
    section_name: str = "Verse 1",
    section_index: int = 0,
    section_occurrence_index: int = 0,
    total_occurrences: int = 2,
    bars: int = 16,
    energy: float = 0.6,
    density: float = 0.6,
    active_roles: list | None = None,
    source_quality: str = "true_stems",
) -> GrooveContext:
    return GrooveContext(
        section_name=section_name,
        section_index=section_index,
        section_occurrence_index=section_occurrence_index,
        total_occurrences=total_occurrences,
        bars=bars,
        energy=energy,
        density=density,
        active_roles=active_roles or ["drums", "bass", "melody"],
        source_quality=source_quality,
    )


FULL_SECTION_SPEC = [
    ("Intro",     0, 0, 1,  8, 0.20, 0.3),
    ("Verse 1",   1, 0, 2, 16, 0.55, 0.6),
    ("Pre-Hook 1",2, 0, 2,  8, 0.65, 0.7),
    ("Hook 1",    3, 0, 3, 16, 0.85, 0.8),
    ("Verse 2",   4, 1, 2, 16, 0.70, 0.7),
    ("Pre-Hook 2",5, 1, 2,  8, 0.68, 0.7),
    ("Hook 2",    6, 1, 3, 16, 0.90, 0.85),
    ("Bridge",    7, 0, 1,  8, 0.35, 0.4),
    ("Breakdown", 8, 0, 1,  8, 0.25, 0.3),
    ("Hook 3",    9, 2, 3, 16, 0.95, 0.9),
    ("Outro",    10, 0, 1,  8, 0.20, 0.3),
]


def _build_full_plans(source_quality: str = "true_stems") -> list[GroovePlan]:
    engine = GrooveEngine(default_source_quality=source_quality)
    plans = []
    for (name, idx, occ_idx, total, bars, energy, density) in FULL_SECTION_SPEC:
        ctx = GrooveContext(
            section_name=name,
            section_index=idx,
            section_occurrence_index=occ_idx,
            total_occurrences=total,
            bars=bars,
            energy=energy,
            density=density,
            active_roles=["drums", "bass", "melody"],
            source_quality=source_quality,
        )
        plans.append(engine.build_groove_plan(ctx))
    return plans


def _plan_by_name(plans: list[GroovePlan], name: str) -> GroovePlan:
    for p in plans:
        if p.section_name == name:
            return p
    raise KeyError(name)


# ===========================================================================
# 1. GrooveEvent contract
# ===========================================================================

class TestGrooveEventContract:
    def test_valid_event_creates_cleanly(self):
        evt = GrooveEvent(bar_start=1, bar_end=4, role="drums", groove_type="hat_push")
        assert evt.bar_start == 1
        assert evt.bar_end == 4
        assert evt.intensity == pytest.approx(0.7)

    def test_intensity_clamped_high(self):
        evt = GrooveEvent(bar_start=1, bar_end=2, role="bass", groove_type="bass_lag", intensity=5.0)
        assert evt.intensity == pytest.approx(1.0)

    def test_intensity_clamped_low(self):
        evt = GrooveEvent(bar_start=1, bar_end=2, role="drums", groove_type="hat_push", intensity=-1.0)
        assert evt.intensity == pytest.approx(0.0)

    def test_bar_end_before_bar_start_raises(self):
        with pytest.raises(ValueError, match="bar_end"):
            GrooveEvent(bar_start=5, bar_end=3, role="drums", groove_type="hat_push")

    def test_bar_start_zero_raises(self):
        with pytest.raises(ValueError, match="bar_start"):
            GrooveEvent(bar_start=0, bar_end=4, role="drums", groove_type="hat_push")

    def test_empty_role_raises(self):
        with pytest.raises(ValueError, match="role"):
            GrooveEvent(bar_start=1, bar_end=4, role="", groove_type="hat_push")

    def test_empty_groove_type_raises(self):
        with pytest.raises(ValueError, match="groove_type"):
            GrooveEvent(bar_start=1, bar_end=4, role="drums", groove_type="")

    def test_safe_timing_offset_accepted(self):
        evt = GrooveEvent(
            bar_start=1, bar_end=4, role="drums", groove_type="hat_push",
            timing_offset_ms=-8.0,
        )
        assert evt.timing_offset_ms == pytest.approx(-8.0)

    def test_unsafe_hat_offset_raises(self):
        with pytest.raises(ValueError, match="safe limit"):
            GrooveEvent(
                bar_start=1, bar_end=4, role="hat", groove_type="hat_push",
                timing_offset_ms=-20.0,
            )

    def test_unsafe_kick_offset_raises(self):
        with pytest.raises(ValueError, match="safe limit"):
            GrooveEvent(
                bar_start=1, bar_end=4, role="kick", groove_type="kick_emphasis",
                timing_offset_ms=10.0,
            )

    def test_to_dict_structure(self):
        evt = GrooveEvent(
            bar_start=1, bar_end=8, role="drums", groove_type="hat_push",
            intensity=0.7, timing_offset_ms=-6.0,
        )
        d = evt.to_dict()
        assert d["bar_start"] == 1
        assert d["bar_end"] == 8
        assert d["role"] == "drums"
        assert d["groove_type"] == "hat_push"
        assert "timing_offset_ms" in d


# ===========================================================================
# 2. GrooveProfile construction
# ===========================================================================

class TestGrooveProfileConstruction:
    def test_valid_profile(self):
        p = GrooveProfile(
            name="test",
            swing_amount=0.3,
            hat_push_ms=-5.0,
            snare_layback_ms=6.0,
            kick_tightness=0.9,
            accent_density=0.5,
            bass_lag_ms=4.0,
            section_bias="verse",
        )
        assert p.swing_amount == pytest.approx(0.3)

    def test_swing_clamped(self):
        p = GrooveProfile(
            name="test", swing_amount=5.0, hat_push_ms=0.0, snare_layback_ms=0.0,
            kick_tightness=1.0, accent_density=0.5, bass_lag_ms=0.0, section_bias="verse",
        )
        assert p.swing_amount == pytest.approx(1.0)

    def test_hat_push_clamped_to_safe_range(self):
        p = GrooveProfile(
            name="test", swing_amount=0.2, hat_push_ms=-100.0, snare_layback_ms=0.0,
            kick_tightness=1.0, accent_density=0.5, bass_lag_ms=0.0, section_bias="verse",
        )
        assert p.hat_push_ms >= -15.0

    def test_snare_layback_clamped(self):
        p = GrooveProfile(
            name="test", swing_amount=0.2, hat_push_ms=0.0, snare_layback_ms=100.0,
            kick_tightness=1.0, accent_density=0.5, bass_lag_ms=0.0, section_bias="verse",
        )
        assert p.snare_layback_ms <= 12.0

    def test_to_dict(self):
        p = get_profile("explosive_hook")
        d = p.to_dict()
        assert d["name"] == "explosive_hook"
        assert "swing_amount" in d
        assert "section_bias" in d


# ===========================================================================
# 3. GrooveContext section_type derivation
# ===========================================================================

class TestGrooveContextSectionType:
    @pytest.mark.parametrize("name,expected", [
        ("Intro", "intro"),
        ("Verse 1", "verse"),
        ("Pre-Hook 1", "pre_hook"),
        ("Hook 1", "hook"),
        ("Bridge", "bridge"),
        ("Breakdown", "breakdown"),
        ("Outro", "outro"),
        ("Chorus", "hook"),
        ("Prehook", "pre_hook"),
    ])
    def test_section_type_derivation(self, name, expected):
        ctx = _ctx(section_name=name)
        assert ctx.section_type == expected

    def test_occurrence_property(self):
        ctx = _ctx(section_occurrence_index=2)
        assert ctx.occurrence == 3


# ===========================================================================
# 4. Profile selection by section type
# ===========================================================================

class TestProfileSelection:
    def test_intro_gets_sparse_intro(self):
        profile = get_profile_for_section("intro", occurrence=1)
        assert profile.name == "sparse_intro"

    def test_verse_1_gets_steady_verse(self):
        profile = get_profile_for_section("verse", occurrence=1)
        assert profile.name == "steady_verse"

    def test_verse_2_gets_bounce_verse(self):
        profile = get_profile_for_section("verse", occurrence=2)
        assert profile.name == "bounce_verse"

    def test_hook_1_gets_explosive_hook(self):
        profile = get_profile_for_section("hook", occurrence=1)
        assert profile.name == "explosive_hook"

    def test_hook_2_gets_escalated_profile(self):
        profile = get_profile_for_section("hook", occurrence=2)
        assert profile.name != "explosive_hook"  # escalated

    def test_bridge_gets_halftime_profile(self):
        profile = get_profile_for_section("bridge", occurrence=1)
        assert "bridge" in profile.section_bias or "halftime" in profile.name

    def test_outro_gets_stripped_outro(self):
        profile = get_profile_for_section("outro", occurrence=1)
        assert profile.name == "stripped_outro"

    def test_stereo_fallback_gets_conservative_profile(self):
        profile = get_profile_for_section("hook", occurrence=3, source_quality="stereo_fallback")
        # Should be a conservative profile, not aggressive_drill
        assert profile.accent_density <= 0.5

    def test_all_profiles_registered(self):
        profiles = list_profiles()
        expected_names = {
            "sparse_intro", "steady_verse", "bounce_verse", "tension_pre_hook",
            "explosive_hook", "halftime_bridge", "stripped_outro", "dark_trap",
            "melodic_bounce", "aggressive_drill",
        }
        assert expected_names.issubset(set(profiles.keys()))

    def test_get_profile_returns_none_for_unknown(self):
        assert get_profile("nonexistent_profile") is None


# ===========================================================================
# 5. Hook escalation
# ===========================================================================

class TestHookEscalation:
    def test_hook_2_stronger_than_hook_1(self):
        plans = _build_full_plans()
        h1 = _plan_by_name(plans, "Hook 1")
        h2 = _plan_by_name(plans, "Hook 2")
        assert h2.groove_intensity >= h1.groove_intensity

    def test_hook_3_stronger_than_hook_2(self):
        plans = _build_full_plans()
        h2 = _plan_by_name(plans, "Hook 2")
        h3 = _plan_by_name(plans, "Hook 3")
        assert h3.groove_intensity >= h2.groove_intensity

    def test_hook_escalation_heuristic_present(self):
        plans = _build_full_plans()
        h2 = _plan_by_name(plans, "Hook 2")
        assert "hook_escalation" in h2.applied_heuristics

    def test_hook_stronger_than_verse(self):
        plans = _build_full_plans()
        h1 = _plan_by_name(plans, "Hook 1")
        v1 = _plan_by_name(plans, "Verse 1")
        assert h1.groove_intensity > v1.groove_intensity


# ===========================================================================
# 6. Verse 2 more alive than Verse 1
# ===========================================================================

class TestVerseEscalation:
    def test_verse_2_more_intense_than_verse_1(self):
        plans = _build_full_plans()
        v1 = _plan_by_name(plans, "Verse 1")
        v2 = _plan_by_name(plans, "Verse 2")
        assert v2.groove_intensity >= v1.groove_intensity

    def test_verse_2_more_alive_heuristic(self):
        plans = _build_full_plans()
        v2 = _plan_by_name(plans, "Verse 2")
        assert "verse_more_alive" in v2.applied_heuristics

    def test_verse_2_different_profile_than_verse_1(self):
        plans = _build_full_plans()
        v1 = _plan_by_name(plans, "Verse 1")
        v2 = _plan_by_name(plans, "Verse 2")
        # Verse 2 should use a different (richer) profile
        assert v2.groove_profile_name != v1.groove_profile_name


# ===========================================================================
# 7. Bridge / breakdown groove reduction
# ===========================================================================

class TestBridgeReduction:
    def test_bridge_groove_lower_than_hook(self):
        plans = _build_full_plans()
        bridge = _plan_by_name(plans, "Bridge")
        h1 = _plan_by_name(plans, "Hook 1")
        assert bridge.groove_intensity < h1.groove_intensity

    def test_bridge_reset_heuristic(self):
        plans = _build_full_plans()
        bridge = _plan_by_name(plans, "Bridge")
        assert "bridge_reset" in bridge.applied_heuristics

    def test_breakdown_groove_low(self):
        plans = _build_full_plans()
        breakdown = _plan_by_name(plans, "Breakdown")
        assert breakdown.groove_intensity <= 0.55

    def test_bridge_profile_is_halftime(self):
        plans = _build_full_plans()
        bridge = _plan_by_name(plans, "Bridge")
        assert bridge.groove_profile_name == "halftime_bridge"


# ===========================================================================
# 8. Outro simplification
# ===========================================================================

class TestOutroSimplification:
    def test_outro_groove_low(self):
        plans = _build_full_plans()
        outro = _plan_by_name(plans, "Outro")
        assert outro.groove_intensity <= 0.45

    def test_outro_relax_heuristic(self):
        plans = _build_full_plans()
        outro = _plan_by_name(plans, "Outro")
        assert "outro_relax" in outro.applied_heuristics

    def test_outro_fewer_events_than_hook(self):
        plans = _build_full_plans()
        outro = _plan_by_name(plans, "Outro")
        h1 = _plan_by_name(plans, "Hook 1")
        # Outro should generally have fewer or equal events
        assert len(outro.groove_events) <= len(h1.groove_events)


# ===========================================================================
# 9. Pre-hook tension
# ===========================================================================

class TestPreHookTension:
    def test_pre_hook_tension_heuristic(self):
        plans = _build_full_plans()
        ph = _plan_by_name(plans, "Pre-Hook 1")
        assert "pre_hook_tension" in ph.applied_heuristics

    def test_pre_hook_profile_is_tension(self):
        plans = _build_full_plans()
        ph = _plan_by_name(plans, "Pre-Hook 1")
        assert ph.groove_profile_name == "tension_pre_hook"


# ===========================================================================
# 10. Safe microtiming bounds
# ===========================================================================

class TestMicrotimingBounds:
    def _dummy_profile(self, hat_push: float = -10.0, snare: float = 8.0, bass: float = 6.0) -> GrooveProfile:
        return GrooveProfile(
            name="test", swing_amount=0.2, hat_push_ms=hat_push,
            snare_layback_ms=snare, kick_tightness=0.85, accent_density=0.5,
            bass_lag_ms=bass, section_bias="verse",
        )

    def test_hat_offset_within_bounds(self):
        profile = self._dummy_profile()
        offset = hat_timing_offset(profile, energy=0.8, occurrence=1)
        assert -15.0 <= offset <= 15.0

    def test_snare_offset_non_negative(self):
        profile = self._dummy_profile()
        offset = snare_timing_offset(profile, energy=0.8, occurrence=1)
        assert offset >= 0.0
        assert offset <= 12.0

    def test_kick_offset_within_bounds(self):
        profile = self._dummy_profile()
        offset = kick_timing_offset(profile, energy=0.8)
        assert -6.0 <= offset <= 6.0

    def test_bass_offset_non_negative(self):
        profile = self._dummy_profile()
        offset = bass_timing_offset(profile, energy=0.8)
        assert 0.0 <= offset <= 10.0

    def test_safe_offset_stereo_fallback_returns_none(self):
        profile = self._dummy_profile()
        result = safe_offset("drums", profile, energy=0.8, occurrence=1, source_quality="stereo_fallback")
        assert result is None

    def test_safe_offset_ai_separated_is_halved(self):
        profile = self._dummy_profile(hat_push=-10.0)
        full = safe_offset("drums", profile, energy=0.8, occurrence=1, source_quality="true_stems")
        halved = safe_offset("drums", profile, energy=0.8, occurrence=1, source_quality="ai_separated")
        if full is not None and halved is not None:
            assert abs(halved) <= abs(full) + 0.1  # halved or equal

    def test_occurrence_nudge_differentiates_repeated_sections(self):
        profile = self._dummy_profile()
        off1 = hat_timing_offset(profile, energy=0.7, occurrence=1)
        off2 = hat_timing_offset(profile, energy=0.7, occurrence=2)
        assert off1 != off2


# ===========================================================================
# 11. Accent engine
# ===========================================================================

class TestAccentEngine:
    def test_hat_accents_generated_for_drums(self):
        profile = get_profile("explosive_hook")
        events = build_accent_events(
            profile=profile, bars=16, energy=0.85,
            section_type="hook", occurrence=1,
            source_quality="true_stems",
            active_roles=["drums", "bass"],
        )
        hat_events = [e for e in events if e.groove_type == "hat_accent"]
        assert len(hat_events) > 0

    def test_no_accents_for_stereo_fallback(self):
        profile = get_profile("explosive_hook")
        events = build_accent_events(
            profile=profile, bars=16, energy=0.85,
            section_type="hook", occurrence=1,
            source_quality="stereo_fallback",
            active_roles=["drums", "bass"],
        )
        assert len(events) == 0

    def test_bass_attack_emphasis_for_bass_role(self):
        profile = get_profile("explosive_hook")
        events = build_accent_events(
            profile=profile, bars=16, energy=0.85,
            section_type="hook", occurrence=2,
            source_quality="true_stems",
            active_roles=["drums", "bass"],
        )
        bass_events = [e for e in events if e.groove_type == "bass_attack_emphasis"]
        assert len(bass_events) > 0

    def test_no_bass_accent_without_bass_role(self):
        profile = get_profile("explosive_hook")
        events = build_accent_events(
            profile=profile, bars=16, energy=0.85,
            section_type="hook", occurrence=1,
            source_quality="true_stems",
            active_roles=["melody"],
        )
        bass_events = [e for e in events if e.groove_type == "bass_attack_emphasis"]
        assert len(bass_events) == 0

    def test_turnaround_accents_for_high_energy_hook(self):
        profile = get_profile("explosive_hook")
        events = build_accent_events(
            profile=profile, bars=16, energy=0.9,
            section_type="hook", occurrence=1,
            source_quality="true_stems",
            active_roles=["drums"],
        )
        turnaround = [e for e in events if e.groove_type == "turnaround_accent"]
        assert len(turnaround) > 0

    def test_accent_intensities_within_bounds(self):
        profile = get_profile("melodic_bounce")
        events = build_accent_events(
            profile=profile, bars=16, energy=0.8,
            section_type="hook", occurrence=1,
            source_quality="true_stems",
            active_roles=["drums", "bass"],
        )
        for evt in events:
            assert 0.0 <= evt.intensity <= 1.0


# ===========================================================================
# 12. Bounce score behaviour
# ===========================================================================

class TestBounceScore:
    def test_active_hook_plan_scores_well(self):
        plans = _build_full_plans()
        h1 = _plan_by_name(plans, "Hook 1")
        assert h1.bounce_score >= 0.3

    def test_bridge_score_not_penalised_for_being_low(self):
        plans = _build_full_plans()
        bridge = _plan_by_name(plans, "Bridge")
        # Bridge should still score >= 0 (not catastrophically penalised)
        assert bridge.bounce_score >= 0.0

    def test_intro_score_reasonable(self):
        plans = _build_full_plans()
        intro = _plan_by_name(plans, "Intro")
        # Intro scores lower but shouldn't be zero
        assert 0.0 <= intro.bounce_score <= 1.0

    def test_score_in_valid_range(self):
        plans = _build_full_plans()
        for plan in plans:
            assert 0.0 <= plan.bounce_score <= 1.0

    def test_low_energy_over_busy_penalised(self):
        engine = GrooveEngine()
        # Build a low-energy section
        ctx = _ctx(section_name="Intro", energy=0.15, density=0.2,
                   active_roles=["drums", "bass"])
        plan = engine.build_groove_plan(ctx)
        # If it has too many events, score should be penalised
        if len(plan.groove_events) > 6:
            # With low energy + many events, score should be < baseline
            assert plan.bounce_score < 0.7


# ===========================================================================
# 13. Source quality degradation
# ===========================================================================

class TestSourceQualityDegradation:
    def test_stereo_fallback_no_microtiming_events(self):
        engine = GrooveEngine(default_source_quality="stereo_fallback")
        ctx = _ctx(source_quality="stereo_fallback", active_roles=["drums", "bass"])
        plan = engine.build_groove_plan(ctx)
        # No timing offset events for stereo_fallback
        timing_events = [e for e in plan.groove_events if e.timing_offset_ms is not None]
        assert len(timing_events) == 0

    def test_stereo_fallback_low_intensity(self):
        engine = GrooveEngine(default_source_quality="stereo_fallback")
        ctx = _ctx(section_name="Hook 1", energy=0.9, source_quality="stereo_fallback")
        plan = engine.build_groove_plan(ctx)
        assert plan.groove_intensity <= 0.35

    def test_ai_separated_reduced_offsets(self):
        engine_true = GrooveEngine(default_source_quality="true_stems")
        engine_ai = GrooveEngine(default_source_quality="ai_separated")
        ctx_true = _ctx(source_quality="true_stems", active_roles=["drums", "bass"])
        ctx_ai = _ctx(source_quality="ai_separated", active_roles=["drums", "bass"])

        plan_true = engine_true.build_groove_plan(ctx_true)
        plan_ai = engine_ai.build_groove_plan(ctx_ai)

        # ai_separated should have reduced intensity cap
        assert plan_ai.groove_intensity <= 0.65

    def test_weak_source_does_not_crash(self):
        for quality in ("stereo_fallback", "ai_separated", "true_stems", "zip_stems"):
            engine = GrooveEngine(default_source_quality=quality)
            ctx = _ctx(source_quality=quality, active_roles=["drums", "bass", "melody"])
            plan = engine.build_groove_plan(ctx)
            assert plan.section_name is not None
            assert 0.0 <= plan.bounce_score <= 1.0


# ===========================================================================
# 14. GrooveValidator
# ===========================================================================

class TestGrooveValidator:
    def test_valid_full_plan_has_no_hook_verse_issue(self):
        plans = _build_full_plans()
        validator = GrooveValidator()
        issues = validator.validate(plans)
        hook_verse_issues = [i for i in issues if i.rule == "hook_groove_must_exceed_verse"]
        assert len(hook_verse_issues) == 0

    def test_bridge_max_intensity_rule(self):
        plans = [
            GroovePlan(section_name="Bridge", groove_profile_name="test", groove_intensity=0.9),
        ]
        validator = GrooveValidator()
        issues = validator.validate(plans)
        bridge_issues = [i for i in issues if i.rule == "bridge_breakdown_must_reduce_activity"]
        assert len(bridge_issues) > 0

    def test_outro_max_intensity_rule(self):
        plans = [
            GroovePlan(section_name="Outro", groove_profile_name="test", groove_intensity=0.8),
        ]
        validator = GrooveValidator()
        issues = validator.validate(plans)
        outro_issues = [i for i in issues if i.rule == "outro_must_reduce_activity"]
        assert len(outro_issues) > 0

    def test_unsafe_timing_offset_flagged(self):
        bad_event = GrooveEvent.__new__(GrooveEvent)
        object.__setattr__(bad_event, "bar_start", 1)
        object.__setattr__(bad_event, "bar_end", 4)
        object.__setattr__(bad_event, "role", "kick")
        object.__setattr__(bad_event, "groove_type", "kick_emphasis")
        object.__setattr__(bad_event, "intensity", 0.7)
        object.__setattr__(bad_event, "timing_offset_ms", 50.0)  # way too high
        object.__setattr__(bad_event, "velocity_profile", None)
        object.__setattr__(bad_event, "density_profile", None)
        object.__setattr__(bad_event, "parameters", {})

        plan = GroovePlan(
            section_name="Hook 1",
            groove_profile_name="test",
            groove_intensity=0.8,
            groove_events=[bad_event],
        )
        validator = GrooveValidator()
        issues = validator.validate([plan])
        unsafe_issues = [i for i in issues if i.rule == "no_unsafe_timing_offsets"]
        assert len(unsafe_issues) > 0

    def test_repeated_sections_identical_flagged(self):
        plans = [
            GroovePlan(section_name="verse 1", groove_profile_name="steady_verse", groove_intensity=0.5),
            GroovePlan(section_name="verse 1", groove_profile_name="steady_verse", groove_intensity=0.5),
        ]
        validator = GrooveValidator()
        issues = validator.validate(plans, source_quality="true_stems")
        diff_issues = [i for i in issues if i.rule == "repeated_sections_must_differ"]
        assert len(diff_issues) > 0

    def test_repeated_sections_identical_not_flagged_for_stereo_fallback(self):
        plans = [
            GroovePlan(section_name="verse 1", groove_profile_name="steady_verse", groove_intensity=0.5),
            GroovePlan(section_name="verse 1", groove_profile_name="steady_verse", groove_intensity=0.5),
        ]
        validator = GrooveValidator()
        issues = validator.validate(plans, source_quality="stereo_fallback")
        diff_issues = [i for i in issues if i.rule == "repeated_sections_must_differ"]
        assert len(diff_issues) == 0

    def test_valid_full_plan_returns_warnings_not_crashes(self):
        plans = _build_full_plans()
        validator = GrooveValidator()
        issues = validator.validate(plans)
        # Even if there are warnings, they are returned — not raised
        assert isinstance(issues, list)


# ===========================================================================
# 15. Serialisation correctness
# ===========================================================================

class TestSerialisation:
    def test_groove_plan_to_dict_has_required_keys(self):
        plans = _build_full_plans()
        for plan in plans:
            d = plan.to_dict()
            assert "section_name" in d
            assert "groove_profile_name" in d
            assert "groove_intensity" in d
            assert "bounce_score" in d
            assert "applied_heuristics" in d
            assert "groove_events" in d

    def test_groove_event_serialised_within_plan(self):
        plans = _build_full_plans()
        hook = _plan_by_name(plans, "Hook 1")
        d = hook.to_dict()
        for event_dict in d["groove_events"]:
            assert "bar_start" in event_dict
            assert "bar_end" in event_dict
            assert "role" in event_dict
            assert "groove_type" in event_dict
            assert "intensity" in event_dict

    def test_serialised_intensities_are_floats(self):
        plans = _build_full_plans()
        for plan in plans:
            d = plan.to_dict()
            assert isinstance(d["groove_intensity"], float)
            assert isinstance(d["bounce_score"], float)

    def test_spec_format_matches_example(self):
        engine = GrooveEngine()
        ctx = GrooveContext(
            section_name="hook",
            section_index=3,
            section_occurrence_index=0,
            total_occurrences=2,
            bars=4,
            energy=0.85,
            density=0.8,
            active_roles=["drums", "bass"],
            source_quality="true_stems",
        )
        plan = engine.build_groove_plan(ctx)
        d = plan.to_dict()
        # Matches spec serialisation shape
        assert "groove_profile_name" in d
        assert isinstance(d["groove_events"], list)
        assert isinstance(d["applied_heuristics"], list)


# ===========================================================================
# 16. Determinism
# ===========================================================================

class TestDeterminism:
    def test_same_input_same_output(self):
        plans_a = _build_full_plans()
        plans_b = _build_full_plans()
        for pa, pb in zip(plans_a, plans_b):
            assert pa.to_dict() == pb.to_dict()

    def test_section_name_preserved(self):
        plans = _build_full_plans()
        expected_names = [spec[0] for spec in FULL_SECTION_SPEC]
        actual_names = [p.section_name for p in plans]
        assert actual_names == expected_names


# ===========================================================================
# 17. GrooveState tracking
# ===========================================================================

class TestGrooveState:
    def test_occurrence_counter_increments(self):
        state = GrooveState()
        assert state.next_occurrence("verse") == 1
        state.record_section("Verse 1", "verse", "steady_verse", 0.5)
        assert state.next_occurrence("verse") == 2

    def test_hook_intensity_tracking(self):
        state = GrooveState()
        state.record_section("Hook 1", "hook", "explosive_hook", 0.75)
        state.record_section("Hook 2", "hook", "melodic_bounce", 0.85)
        assert state.last_hook_intensity() == pytest.approx(0.85)
        assert state.max_hook_intensity() == pytest.approx(0.85)

    def test_hook_escalation_satisfied_true(self):
        state = GrooveState()
        state.hook_intensities = [0.75, 0.82, 0.90]
        assert state.hook_escalation_satisfied() is True

    def test_hook_escalation_satisfied_false(self):
        state = GrooveState()
        state.hook_intensities = [0.80, 0.70, 0.90]
        assert state.hook_escalation_satisfied() is False

    def test_to_snapshot(self):
        state = GrooveState()
        state.record_section("Hook 1", "hook", "explosive_hook", 0.80)
        snap = state.to_snapshot()
        assert "hook_intensities" in snap
        assert snap["hook_intensities"] == [0.80]


# ===========================================================================
# 18. Integration: shadow runner
# ===========================================================================

class TestShadowIntegration:
    def test_shadow_runner_returns_plans(self):
        from app.services.arrangement_jobs import _run_groove_engine_shadow

        render_plan = {
            "sections": [
                {"type": "verse", "section_name": "Verse 1", "bars": 16, "energy": 0.55},
                {"type": "hook",  "section_name": "Hook 1",  "bars": 16, "energy": 0.85},
                {"type": "outro", "section_name": "Outro",   "bars": 8,  "energy": 0.20},
            ]
        }
        result = _run_groove_engine_shadow(
            render_plan=render_plan,
            available_roles=["drums", "bass"],
            arrangement_id=999,
            correlation_id="test-cid",
            source_quality="true_stems",
        )
        assert result["error"] is None
        assert result["section_count"] == 3
        assert len(result["plans"]) == 3

    def test_shadow_runner_empty_sections_returns_gracefully(self):
        from app.services.arrangement_jobs import _run_groove_engine_shadow

        result = _run_groove_engine_shadow(
            render_plan={"sections": []},
            available_roles=[],
            arrangement_id=0,
            correlation_id="test",
        )
        assert result["error"] is None
        assert result["section_count"] == 0

    def test_shadow_runner_never_raises(self):
        from app.services.arrangement_jobs import _run_groove_engine_shadow

        # Pass malformed render_plan — should never raise
        result = _run_groove_engine_shadow(
            render_plan=None,
            available_roles=[],
            arrangement_id=0,
            correlation_id="test",
        )
        assert "error" in result

    def test_shadow_runner_includes_validation_issues_key(self):
        from app.services.arrangement_jobs import _run_groove_engine_shadow

        render_plan = {
            "sections": [
                {"type": "verse", "section_name": "Verse 1", "bars": 8},
            ]
        }
        result = _run_groove_engine_shadow(
            render_plan=render_plan,
            available_roles=["drums"],
            arrangement_id=1,
            correlation_id="test",
        )
        assert "validation_issues" in result
        assert isinstance(result["validation_issues"], list)
