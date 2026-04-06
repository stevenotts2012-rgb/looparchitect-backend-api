"""
Unit tests for StemArrangementEngine — arrangement generation from audio stems.

Covers:
- Section planning for short / medium / full-length arrangements
- Energy level calculation per section type
- Active stem selection per section type and energy level
- Producer move generation at boundaries
- Stem state creation (pan / gain defaults)
- Edge cases: no stems, single stem, full_mix fallback
- Regression: verse lead-inclusion threshold is inclusive (>= 0.5, not > 0.5)
- Regression: hook group thresholds respected
"""

import pytest
from app.services.stem_arrangement_engine import (
    StemArrangementEngine,
    StemRole,
    StemState,
    SectionConfig,
    ProducerMove,
    STEM_GROUPS,
    _roles_in_group,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_engine(roles=None, tempo=120, key="C") -> StemArrangementEngine:
    """Build a StemArrangementEngine with the given roles (defaults to a full stem set)."""
    _roles = roles if roles is not None else [
        StemRole.DRUMS,
        StemRole.BASS,
        StemRole.MELODY,
        StemRole.HARMONY,
        StemRole.PADS,
        StemRole.FX,
    ]
    available = {role: f"/fake/path/{role.value}.wav" for role in _roles}
    return StemArrangementEngine(available_stems=available, tempo=tempo, key=key)


def _sections_by_type(sections: list[SectionConfig], section_type: str) -> list[SectionConfig]:
    return [s for s in sections if s.section_type == section_type]


# ---------------------------------------------------------------------------
# Section planning
# ---------------------------------------------------------------------------

class TestSectionPlanning:
    """Tests for _plan_sections() — section structure output."""

    def test_short_arrangement_has_intro_verse_hook(self):
        engine = _make_engine()
        plan = engine._plan_sections(target_bars=16, genre="generic")
        types = [s["type"] for s in plan]
        assert "intro" in types
        assert "verse" in types
        assert "hook" in types

    def test_medium_arrangement_includes_outro(self):
        engine = _make_engine()
        plan = engine._plan_sections(target_bars=32, genre="generic")
        types = [s["type"] for s in plan]
        assert "outro" in types

    def test_full_arrangement_has_bridge(self):
        engine = _make_engine()
        plan = engine._plan_sections(target_bars=56, genre="generic")
        types = [s["type"] for s in plan]
        assert "bridge" in types

    def test_full_arrangement_has_multiple_hooks(self):
        engine = _make_engine()
        plan = engine._plan_sections(target_bars=56, genre="generic")
        hook_count = sum(1 for s in plan if s["type"] == "hook")
        assert hook_count >= 2

    def test_section_bars_are_positive(self):
        engine = _make_engine()
        for target in [16, 32, 56]:
            plan = engine._plan_sections(target_bars=target, genre="generic")
            for s in plan:
                assert s["bars"] > 0, f"Section {s['type']} has non-positive bars: {s['bars']}"

    def test_large_arrangement_does_not_crash(self):
        engine = _make_engine()
        plan = engine._plan_sections(target_bars=128, genre="trap")
        assert len(plan) >= 4


# ---------------------------------------------------------------------------
# Energy level calculation
# ---------------------------------------------------------------------------

class TestEnergyCalculation:
    """Tests for _calculate_energy_level()."""

    def test_intro_energy_is_low(self):
        engine = _make_engine()
        e = engine._calculate_energy_level("intro")
        assert e < 0.5

    def test_verse_energy_is_medium(self):
        engine = _make_engine()
        e = engine._calculate_energy_level("verse")
        assert 0.4 <= e <= 0.6

    def test_hook_energy_is_high(self):
        engine = _make_engine()
        e = engine._calculate_energy_level("hook", hook_number=1)
        assert e >= 0.7

    def test_outro_energy_is_low(self):
        engine = _make_engine()
        e = engine._calculate_energy_level("outro")
        assert e < 0.4

    def test_hooks_increase_with_number(self):
        engine = _make_engine()
        e1 = engine._calculate_energy_level("hook", hook_number=1)
        e2 = engine._calculate_energy_level("hook", hook_number=2)
        e3 = engine._calculate_energy_level("hook", hook_number=3)
        assert e2 >= e1
        assert e3 >= e2

    def test_hook_energy_capped_at_1(self):
        engine = _make_engine()
        for n in range(1, 20):
            e = engine._calculate_energy_level("hook", hook_number=n)
            assert e <= 1.0


# ---------------------------------------------------------------------------
# Active stem selection
# ---------------------------------------------------------------------------

class TestActiveStemSelection:
    """Tests for _determine_active_stems() — which stems are active per section."""

    def test_intro_excludes_rhythm_and_low_end(self):
        engine = _make_engine()
        active = engine._determine_active_stems("intro", 0.3, engine.available_roles)
        assert StemRole.DRUMS not in active
        assert StemRole.BASS not in active

    def test_intro_includes_lead_and_harmonic(self):
        engine = _make_engine()
        active = engine._determine_active_stems("intro", 0.3, engine.available_roles)
        # At least one of melody/vocals or harmony/pads should be present
        lead_or_harmonic = {StemRole.MELODY, StemRole.VOCALS, StemRole.HARMONY, StemRole.PADS}
        assert len(active & lead_or_harmonic) >= 1

    def test_verse_includes_rhythm(self):
        engine = _make_engine()
        active = engine._determine_active_stems("verse", 0.5, engine.available_roles)
        rhythm_roles = {StemRole.DRUMS, StemRole.PERCUSSION}
        assert len(active & rhythm_roles) >= 1

    def test_verse_includes_low_end(self):
        engine = _make_engine()
        active = engine._determine_active_stems("verse", 0.5, engine.available_roles)
        assert StemRole.BASS in active

    def test_verse_includes_lead_at_exactly_0_5_energy(self):
        """Regression: energy >= 0.5 should include lead (was > 0.5 which excluded it)."""
        engine = _make_engine()
        active = engine._determine_active_stems("verse", 0.5, engine.available_roles)
        lead_roles = {StemRole.MELODY, StemRole.VOCALS}
        assert len(active & lead_roles) >= 1, (
            "Verse at energy=0.5 should include lead roles (>= threshold, not > threshold)"
        )

    def test_hook_includes_all_main_groups(self):
        engine = _make_engine()
        active = engine._determine_active_stems("hook", 0.9, engine.available_roles)
        assert StemRole.DRUMS in active
        assert StemRole.BASS in active
        # Melody or vocals should be active
        lead_roles = {StemRole.MELODY, StemRole.VOCALS}
        assert len(active & lead_roles) >= 1

    def test_hook_harmonic_added_above_0_70_energy(self):
        engine = _make_engine()
        active = engine._determine_active_stems("hook", 0.75, engine.available_roles)
        harmonic_roles = {StemRole.HARMONY, StemRole.PADS}
        assert len(active & harmonic_roles) >= 1

    def test_hook_texture_not_added_below_0_85_energy(self):
        """Regression: texture threshold raised from 0.82 to 0.85."""
        engine = _make_engine()
        # At exactly 0.83 — should NOT include FX (threshold is now 0.85)
        active = engine._determine_active_stems("hook", 0.83, engine.available_roles)
        assert StemRole.FX not in active, (
            "FX (texture) should not be included below energy threshold 0.85"
        )

    def test_hook_texture_added_above_0_85_energy(self):
        engine = _make_engine()
        active = engine._determine_active_stems("hook", 0.90, engine.available_roles)
        assert StemRole.FX in active

    def test_bridge_excludes_low_end(self):
        engine = _make_engine()
        active = engine._determine_active_stems("bridge", 0.55, engine.available_roles)
        assert StemRole.BASS not in active

    def test_bridge_includes_harmonic_texture(self):
        engine = _make_engine()
        active = engine._determine_active_stems("bridge", 0.55, engine.available_roles)
        harmonic_or_texture = {StemRole.HARMONY, StemRole.PADS, StemRole.FX}
        assert len(active & harmonic_or_texture) >= 1

    def test_outro_excludes_rhythm(self):
        engine = _make_engine()
        active = engine._determine_active_stems("outro", 0.2, engine.available_roles)
        assert StemRole.DRUMS not in active

    def test_outro_includes_lead_or_harmonic(self):
        engine = _make_engine()
        active = engine._determine_active_stems("outro", 0.2, engine.available_roles)
        lead_or_harmonic = {StemRole.MELODY, StemRole.VOCALS, StemRole.HARMONY, StemRole.PADS}
        assert len(active & lead_or_harmonic) >= 1

    def test_fallback_to_full_mix_when_no_active(self):
        """When no section-specific stems are available, full_mix is used as fallback."""
        engine = _make_engine(roles=[StemRole.FULL_MIX])
        active = engine._determine_active_stems("intro", 0.3, engine.available_roles)
        assert StemRole.FULL_MIX in active

    def test_last_resort_uses_all_available(self):
        """When even full_mix isn't available, all available roles are used."""
        engine = _make_engine(roles=[StemRole.ACCENT])
        active = engine._determine_active_stems("intro", 0.3, engine.available_roles)
        assert StemRole.ACCENT in active


# ---------------------------------------------------------------------------
# Producer moves
# ---------------------------------------------------------------------------

class TestProducerMoves:
    """Tests for _generate_producer_moves()."""

    def test_intro_has_no_moves(self):
        engine = _make_engine()
        moves = engine._generate_producer_moves("intro")
        assert moves == []

    def test_first_hook_has_drum_fill_and_silence(self):
        engine = _make_engine()
        moves = engine._generate_producer_moves("hook", hook_number=1)
        assert ProducerMove.DRUM_FILL in moves
        assert ProducerMove.PRE_HOOK_SILENCE in moves

    def test_second_hook_has_snare_roll_and_riser(self):
        engine = _make_engine()
        moves = engine._generate_producer_moves("hook", hook_number=2)
        assert ProducerMove.SNARE_ROLL in moves
        assert ProducerMove.RISER_FX in moves

    def test_third_hook_has_crash_and_buildout(self):
        engine = _make_engine()
        moves = engine._generate_producer_moves("hook", hook_number=3)
        assert ProducerMove.CRASH_HIT in moves
        assert ProducerMove.PRE_DROP_BUILDOUT in moves

    def test_bridge_has_bass_pause(self):
        engine = _make_engine()
        moves = engine._generate_producer_moves("bridge")
        assert ProducerMove.BASS_PAUSE in moves

    def test_outro_has_no_moves(self):
        engine = _make_engine()
        moves = engine._generate_producer_moves("outro")
        assert moves == []


# ---------------------------------------------------------------------------
# Stem states
# ---------------------------------------------------------------------------

class TestStemStates:
    """Tests for _create_stem_states()."""

    def test_states_created_for_all_available_roles(self):
        engine = _make_engine()
        active = {StemRole.DRUMS, StemRole.BASS}
        states = engine._create_stem_states(active)
        for role in engine.available_roles:
            assert role in states, f"Missing stem state for {role.value}"

    def test_active_stems_have_active_true(self):
        engine = _make_engine()
        active = {StemRole.DRUMS, StemRole.BASS}
        states = engine._create_stem_states(active)
        assert states[StemRole.DRUMS].active is True
        assert states[StemRole.BASS].active is True

    def test_inactive_stems_have_active_false(self):
        engine = _make_engine()
        active = {StemRole.DRUMS}
        states = engine._create_stem_states(active)
        assert states[StemRole.MELODY].active is False

    def test_pads_have_negative_gain(self):
        engine = _make_engine()
        states = engine._create_stem_states(engine.available_roles)
        assert states[StemRole.PADS].gain_db < 0.0

    def test_drums_have_center_pan(self):
        engine = _make_engine()
        states = engine._create_stem_states(engine.available_roles)
        assert states[StemRole.DRUMS].pan == 0.0

    def test_melody_has_slight_right_pan(self):
        engine = _make_engine()
        states = engine._create_stem_states(engine.available_roles)
        assert states[StemRole.MELODY].pan > 0.0

    def test_harmony_has_slight_left_pan(self):
        engine = _make_engine()
        states = engine._create_stem_states(engine.available_roles)
        assert states[StemRole.HARMONY].pan < 0.0


# ---------------------------------------------------------------------------
# Full arrangement generation
# ---------------------------------------------------------------------------

class TestGenerateArrangement:
    """Integration-style tests for generate_arrangement()."""

    def test_generate_returns_section_list(self):
        engine = _make_engine()
        sections = engine.generate_arrangement(target_bars=32)
        assert isinstance(sections, list)
        assert len(sections) > 0
        assert all(isinstance(s, SectionConfig) for s in sections)

    def test_bars_sum_covers_target(self):
        engine = _make_engine()
        sections = engine.generate_arrangement(target_bars=32)
        total = sum(s.bars for s in sections)
        assert total > 0

    def test_sections_have_non_empty_active_stems(self):
        engine = _make_engine()
        sections = engine.generate_arrangement(target_bars=32)
        for s in sections:
            assert len(s.active_stems) > 0, (
                f"Section {s.name} ({s.section_type}) has no active stems"
            )

    def test_hooks_have_higher_energy_than_intros(self):
        engine = _make_engine()
        sections = engine.generate_arrangement(target_bars=56)
        intros = [s for s in sections if s.section_type == "intro"]
        hooks = [s for s in sections if s.section_type == "hook"]
        if intros and hooks:
            max_intro_energy = max(s.energy_level for s in intros)
            min_hook_energy = min(s.energy_level for s in hooks)
            assert min_hook_energy > max_intro_energy, (
                f"Hooks should be higher energy than intros. "
                f"Intro max={max_intro_energy}, Hook min={min_hook_energy}"
            )

    def test_section_bar_positions_are_sequential(self):
        engine = _make_engine()
        sections = engine.generate_arrangement(target_bars=32)
        expected_bar = 0
        for s in sections:
            assert s.bar_start == expected_bar, (
                f"Section {s.name} starts at bar {s.bar_start}, expected {expected_bar}"
            )
            expected_bar += s.bars

    def test_generate_with_single_role(self):
        engine = _make_engine(roles=[StemRole.FULL_MIX])
        sections = engine.generate_arrangement(target_bars=16)
        assert len(sections) > 0
        for s in sections:
            assert StemRole.FULL_MIX in s.active_stems

    def test_generate_with_no_stems_raises(self):
        empty_engine = StemArrangementEngine(
            available_stems={},
            tempo=120,
            key="C",
        )
        with pytest.raises(ValueError):
            empty_engine.generate_arrangement(target_bars=32)

    def test_to_dict_is_serializable(self):
        import json
        engine = _make_engine()
        sections = engine.generate_arrangement(target_bars=16)
        for s in sections:
            data = s.to_dict()
            json.dumps(data)  # must not raise

    def test_stems_groups_helper_returns_intersection(self):
        available = {StemRole.DRUMS, StemRole.BASS, StemRole.MELODY}
        result = _roles_in_group("rhythm", available)
        assert StemRole.DRUMS in result
        assert StemRole.BASS not in result  # bass is in low_end, not rhythm

    def test_stems_groups_returns_empty_for_unknown_group(self):
        available = {StemRole.DRUMS}
        result = _roles_in_group("nonexistent_group", available)
        assert result == set()
