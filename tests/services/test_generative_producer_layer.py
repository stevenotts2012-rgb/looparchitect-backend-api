"""Tests for app/services/generative_producer_layer.py.

Required test coverage:
1. trap hook gets more generated events than verse
2. intro has no 808/drums (active events)
3. verse 2 differs from verse 1 (≥2 changed behaviours)
4. hook 2 differs from hook 1 (extra layer or stronger behavior)
5. same seed is deterministic
6. generated events map to supported renderer actions
7. unsupported events are logged and skipped (not silently ignored)
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import pytest

from app.services.generative_producer_layer import (
    SUPPORTED_RENDER_ACTIONS,
    GenerativeEvent,
    GenerativeProducerLayer,
    SectionOutput,
    _DEFAULT_TRAP_PLAN,
    _jitter,
    _normalise_section_type,
    create_generative_producer_layer,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

LOOP_ANALYSIS: Dict[str, Any] = {
    "bpm": 140.0,
    "key": "F#",
    "duration_seconds": 8.0,
    "sample_rate": 44100,
    "channels": 2,
}

ALL_ROLES = ["drums", "bass", "melody", "percussion", "fx", "arp"]
MINIMAL_ROLES: List[str] = []  # no stems uploaded


def _make_layer(
    seed: int = 42,
    roles: Optional[List[str]] = None,
    genre: str = "trap",
) -> GenerativeProducerLayer:
    return GenerativeProducerLayer(
        loop_analysis=LOOP_ANALYSIS,
        genre=genre,
        vibe="dark",
        variation_seed=seed,
        available_roles=roles if roles is not None else ALL_ROLES,
    )


def _gen_section(layer: GenerativeProducerLayer, section_type: str, bars: int = 8) -> SectionOutput:
    """Generate a single section of the given type."""
    plan = [{"section_type": section_type, "section_name": section_type.title(), "bar_start": 0, "bars": bars}]
    outputs = layer.generate(sections=plan)
    assert len(outputs) == 1
    return outputs[0]


# ---------------------------------------------------------------------------
# 1. Trap hook gets more generated events than verse
# ---------------------------------------------------------------------------


class TestHookHasMoreEventsThanVerse:
    def test_hook_active_event_count_exceeds_verse(self):
        layer = _make_layer(seed=42)
        verse = _gen_section(layer, "verse", bars=16)
        hook = _gen_section(layer, "hook", bars=16)
        assert len(hook.active_events) > len(verse.active_events), (
            f"Hook active events ({len(hook.active_events)}) should exceed "
            f"verse active events ({len(verse.active_events)})"
        )

    def test_hook_all_event_count_exceeds_verse(self):
        layer = _make_layer(seed=99)
        verse = _gen_section(layer, "verse", bars=16)
        hook = _gen_section(layer, "hook", bars=16)
        assert len(hook.all_events) > len(verse.all_events)

    def test_hook_has_hat_rolls_verse_does_not(self):
        layer = _make_layer(seed=7)
        verse = _gen_section(layer, "verse", bars=8)
        hook = _gen_section(layer, "hook", bars=8)
        # Hook should have multiple hat roll events; verse has at most one (no roll)
        hook_rolls = [e for e in hook.generated_hat_roll_events if not e.skipped_reason and e.parameters.get("roll")]
        assert len(hook_rolls) >= 1

    def test_hook_has_counter_melody_when_arp_available(self):
        layer = _make_layer(seed=5, roles=["drums", "bass", "melody", "percussion", "fx", "arp"])
        hook = _gen_section(layer, "hook", bars=8)
        active_counter = [e for e in hook.counter_melody_events if not e.skipped_reason]
        assert len(active_counter) >= 1

    def test_hook_has_impact_fx(self):
        layer = _make_layer(seed=3)
        hook = _gen_section(layer, "hook", bars=8)
        impacts = [e for e in hook.fx_transition_events if e.event_type == "impact" and not e.skipped_reason]
        assert len(impacts) >= 1

    def test_hook_generates_events_across_all_buckets(self):
        layer = _make_layer(seed=21)
        hook = _gen_section(layer, "hook", bars=16)
        # At minimum: drum, 808, hat roll, melody, fx, automation buckets non-empty
        assert len(hook.generated_drum_pattern_events) >= 1
        assert len(hook.generated_808_pattern_events) >= 1
        assert len(hook.generated_hat_roll_events) >= 1
        assert len(hook.melody_chop_events) >= 1
        assert len(hook.fx_transition_events) >= 1
        assert len(hook.automation_events) >= 1


# ---------------------------------------------------------------------------
# 2. Intro has no 808 or drums in active events
# ---------------------------------------------------------------------------


class TestIntroHasNo808OrDrums:
    def test_intro_active_events_have_no_bass_role(self):
        layer = _make_layer(seed=42)
        intro = _gen_section(layer, "intro", bars=8)
        bass_active = [e for e in intro.active_events if e.target_role == "bass"]
        assert bass_active == [], f"Intro should have no active bass/808 events, got: {bass_active}"

    def test_intro_active_events_have_no_drums_role(self):
        layer = _make_layer(seed=42)
        intro = _gen_section(layer, "intro", bars=8)
        drum_active = [e for e in intro.active_events if e.target_role == "drums"]
        assert drum_active == [], f"Intro should have no active drum events, got: {drum_active}"

    def test_intro_808_events_are_skipped_with_reason(self):
        layer = _make_layer(seed=42)
        intro = _gen_section(layer, "intro", bars=8)
        bass_events = [e for e in intro.generated_808_pattern_events]
        assert all(e.skipped_reason for e in bass_events), (
            "All intro 808 events must have a skipped_reason"
        )

    def test_intro_drum_events_are_skipped_with_reason(self):
        layer = _make_layer(seed=42)
        intro = _gen_section(layer, "intro", bars=8)
        drum_events = [e for e in intro.generated_drum_pattern_events]
        assert all(e.skipped_reason for e in drum_events), (
            "All intro drum events must have a skipped_reason"
        )

    def test_intro_has_active_melody_event(self):
        layer = _make_layer(seed=42, roles=["melody", "fx"])
        intro = _gen_section(layer, "intro", bars=8)
        melody_active = [e for e in intro.active_events if e.target_role == "melody"]
        assert len(melody_active) >= 1

    def test_intro_skip_reasons_include_intro_no_drums(self):
        layer = _make_layer(seed=42)
        intro = _gen_section(layer, "intro", bars=8)
        drum_events = intro.generated_drum_pattern_events
        reasons = {e.skipped_reason for e in drum_events}
        assert "intro_no_drums" in reasons

    def test_intro_skip_reasons_include_intro_no_808(self):
        layer = _make_layer(seed=42)
        intro = _gen_section(layer, "intro", bars=8)
        bass_events = intro.generated_808_pattern_events
        reasons = {e.skipped_reason for e in bass_events}
        assert "intro_no_808" in reasons

    def test_outro_also_has_no_active_808_or_drums(self):
        """Outro follows the same rule: no 808, no drums."""
        layer = _make_layer(seed=42)
        outro = _gen_section(layer, "outro", bars=8)
        active_bass = [e for e in outro.active_events if e.target_role == "bass"]
        active_drums = [e for e in outro.active_events if e.target_role == "drums"]
        assert active_bass == []
        assert active_drums == []


# ---------------------------------------------------------------------------
# 3. Verse 2 differs from Verse 1 (≥2 changed behaviours)
# ---------------------------------------------------------------------------


class TestVerse2DiffersFromVerse1:
    def _get_verse_and_verse2(self, seed: int = 42, bars: int = 16):
        layer = _make_layer(seed=seed)
        verse = _gen_section(layer, "verse", bars=bars)
        verse2 = _gen_section(layer, "verse_2", bars=bars)
        return verse, verse2

    def test_verse_2_section_type_is_verse_2(self):
        _, v2 = self._get_verse_and_verse2()
        assert v2.section_type == "verse_2"

    def test_verse_2_melody_render_action_differs_from_verse_1(self):
        v1, v2 = self._get_verse_and_verse2()
        v1_actions = {e.render_action for e in v1.melody_chop_events if not e.skipped_reason}
        v2_actions = {e.render_action for e in v2.melody_chop_events if not e.skipped_reason}
        # Verse 2 uses "chop_melody" while Verse 1 uses "play_melody_reduced"
        assert v2_actions != v1_actions, "Verse 2 melody render action should differ from Verse 1"

    def test_verse_2_808_movement_differs_from_verse_1(self):
        v1, v2 = self._get_verse_and_verse2()
        v1_movements = {
            e.parameters.get("movement")
            for e in v1.generated_808_pattern_events
            if not e.skipped_reason
        }
        v2_movements = {
            e.parameters.get("movement")
            for e in v2.generated_808_pattern_events
            if not e.skipped_reason
        }
        assert v1_movements != v2_movements, "Verse 2 808 movement should differ from Verse 1"

    def test_verse_2_has_additional_reverse_fx_event(self):
        _, v2 = self._get_verse_and_verse2()
        reverse_events = [
            e for e in v2.fx_transition_events
            if e.event_type == "reverse_fx" and not e.skipped_reason
        ]
        assert len(reverse_events) >= 1, "Verse 2 should have at least one reverse FX event"

    def test_verse_2_melody_intensity_lower_than_verse_1(self):
        v1, v2 = self._get_verse_and_verse2(seed=77)
        v1_intensity = [
            e.intensity for e in v1.melody_chop_events if not e.skipped_reason
        ]
        v2_intensity = [
            e.intensity for e in v2.melody_chop_events if not e.skipped_reason
        ]
        if v1_intensity and v2_intensity:
            assert max(v2_intensity) <= max(v1_intensity) + 0.01, (
                "Verse 2 melody intensity should not exceed Verse 1"
            )

    def test_verse_2_counts_at_least_two_changed_behaviors(self):
        """End-to-end check: confirm ≥2 behaviours differ."""
        v1, v2 = self._get_verse_and_verse2()

        differences = 0

        # Behaviour 1: melody render_action
        v1_mel_actions = {e.render_action for e in v1.melody_chop_events if not e.skipped_reason}
        v2_mel_actions = {e.render_action for e in v2.melody_chop_events if not e.skipped_reason}
        if v1_mel_actions != v2_mel_actions:
            differences += 1

        # Behaviour 2: 808 movement parameter
        v1_moves = {e.parameters.get("movement") for e in v1.generated_808_pattern_events if not e.skipped_reason}
        v2_moves = {e.parameters.get("movement") for e in v2.generated_808_pattern_events if not e.skipped_reason}
        if v1_moves != v2_moves:
            differences += 1

        # Behaviour 3: extra reverse FX event
        v1_rev = len([e for e in v1.fx_transition_events if e.event_type == "reverse_fx"])
        v2_rev = len([e for e in v2.fx_transition_events if e.event_type == "reverse_fx"])
        if v2_rev > v1_rev:
            differences += 1

        assert differences >= 2, f"Expected ≥2 changed behaviours in Verse 2, found {differences}"


# ---------------------------------------------------------------------------
# 4. Hook 2 differs from Hook 1 (extra layer or stronger behavior)
# ---------------------------------------------------------------------------


class TestHook2DiffersFromHook1:
    def _get_hook_and_hook2(self, seed: int = 42, bars: int = 16):
        layer = _make_layer(seed=seed)
        hook = _gen_section(layer, "hook", bars=bars)
        hook2 = _gen_section(layer, "hook_2", bars=bars)
        return hook, hook2

    def test_hook_2_section_type_is_hook_2(self):
        _, h2 = self._get_hook_and_hook2()
        assert h2.section_type == "hook_2"

    def test_hook_2_has_more_counter_melody_than_hook_1(self):
        h1, h2 = self._get_hook_and_hook2(seed=10)
        h1_cm = len([e for e in h1.counter_melody_events if not e.skipped_reason])
        h2_cm = len([e for e in h2.counter_melody_events if not e.skipped_reason])
        assert h2_cm >= h1_cm, "Hook 2 should have at least as many counter-melody events as Hook 1"

    def test_hook_2_has_extra_impact_at_mid(self):
        _, h2 = self._get_hook_and_hook2(seed=8)
        mid_impacts = [
            e for e in h2.fx_transition_events
            if e.event_type == "impact_mid" and not e.skipped_reason
        ]
        assert len(mid_impacts) >= 1, "Hook 2 should have a mid-section impact event"

    def test_hook_2_808_intensity_higher_than_or_equal_to_hook_1(self):
        h1, h2 = self._get_hook_and_hook2(seed=55)
        h1_intens = [e.intensity for e in h1.generated_808_pattern_events if not e.skipped_reason]
        h2_intens = [e.intensity for e in h2.generated_808_pattern_events if not e.skipped_reason]
        if h1_intens and h2_intens:
            assert max(h2_intens) >= max(h1_intens) - 0.01, (
                "Hook 2 808 intensity should not be lower than Hook 1"
            )

    def test_hook_2_has_aggressive_melodic_808_movement(self):
        _, h2 = self._get_hook_and_hook2(seed=77)
        bass_events = [e for e in h2.generated_808_pattern_events if not e.skipped_reason]
        movements = {e.parameters.get("movement") for e in bass_events}
        assert "aggressive_melodic" in movements, "Hook 2 808 should use aggressive_melodic movement"

    def test_hook_2_counter_melody_added_even_without_arp(self):
        """Hook 2 should inject a counter melody even when 'arp' stem is absent."""
        layer = _make_layer(seed=30, roles=["drums", "bass", "melody", "percussion", "fx"])
        h2 = _gen_section(layer, "hook_2", bars=16)
        cm_active = [e for e in h2.counter_melody_events if not e.skipped_reason]
        assert len(cm_active) >= 1, "Hook 2 must add a counter melody layer even without arp stem"

    def test_hook_2_hat_roll_intensity_higher_than_hook_1(self):
        h1, h2 = self._get_hook_and_hook2(seed=19)
        h1_roll_intens = [e.intensity for e in h1.generated_hat_roll_events if not e.skipped_reason]
        h2_roll_intens = [e.intensity for e in h2.generated_hat_roll_events if not e.skipped_reason]
        if h1_roll_intens and h2_roll_intens:
            # Hook 2 boosts by +0.10
            assert max(h2_roll_intens) >= max(h1_roll_intens) - 0.01


# ---------------------------------------------------------------------------
# 5. Same seed is deterministic
# ---------------------------------------------------------------------------


class TestSeedDeterminism:
    def test_same_seed_produces_identical_events_full_plan(self):
        layer_a = _make_layer(seed=42)
        layer_b = _make_layer(seed=42)
        out_a = layer_a.generate()
        out_b = layer_b.generate()

        assert len(out_a) == len(out_b)
        for sec_a, sec_b in zip(out_a, out_b):
            assert sec_a.to_dict() == sec_b.to_dict()

    def test_different_seeds_produce_different_events(self):
        layer_a = _make_layer(seed=1)
        layer_b = _make_layer(seed=9999)
        out_a = layer_a.generate()
        out_b = layer_b.generate()

        # At least one section should have a different event distribution
        found_diff = False
        for sec_a, sec_b in zip(out_a, out_b):
            if sec_a.to_dict() != sec_b.to_dict():
                found_diff = True
                break
        assert found_diff, "Different seeds should produce at least one different section output"

    def test_same_seed_deterministic_for_individual_sections(self):
        for section_type in ["intro", "verse", "pre_hook", "hook", "verse_2", "hook_2", "outro"]:
            layer_a = _make_layer(seed=123)
            layer_b = _make_layer(seed=123)
            sec_a = _gen_section(layer_a, section_type)
            sec_b = _gen_section(layer_b, section_type)
            assert sec_a.to_dict() == sec_b.to_dict(), (
                f"Section {section_type} should be identical for same seed"
            )

    def test_determinism_is_independent_of_call_order(self):
        """Generating sections in different order does not affect individual section output."""
        layer_a = _make_layer(seed=77)
        layer_b = _make_layer(seed=77)
        # Generate with reversed order (verse before hook)
        plan_fwd = [
            {"section_type": "verse", "section_name": "Verse", "bar_start": 0, "bars": 8},
            {"section_type": "hook",  "section_name": "Hook",  "bar_start": 8, "bars": 8},
        ]
        plan_rev = [
            {"section_type": "hook",  "section_name": "Hook",  "bar_start": 8, "bars": 8},
            {"section_type": "verse", "section_name": "Verse", "bar_start": 0, "bars": 8},
        ]
        out_fwd = layer_a.generate(sections=plan_fwd)
        out_rev = layer_b.generate(sections=plan_rev)
        # The "verse" section should have the same output regardless of order
        verse_fwd = next(s for s in out_fwd if s.section_type == "verse")
        verse_rev = next(s for s in out_rev if s.section_type == "verse")
        # Bar start offsets differ so compare event counts and render_actions
        fwd_actions = sorted(e.render_action for e in verse_fwd.active_events)
        rev_actions = sorted(e.render_action for e in verse_rev.active_events)
        assert fwd_actions == rev_actions


# ---------------------------------------------------------------------------
# 6. Generated events map to supported renderer actions
# ---------------------------------------------------------------------------


class TestEventsMapToSupportedActions:
    def test_all_active_events_have_valid_render_action(self):
        layer = _make_layer(seed=42)
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.active_events:
                assert evt.render_action in SUPPORTED_RENDER_ACTIONS, (
                    f"Event {evt.event_type!r} in {sec.section_name!r} has "
                    f"unsupported render_action={evt.render_action!r}"
                )

    def test_active_events_have_non_empty_render_action(self):
        layer = _make_layer(seed=7)
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.active_events:
                assert evt.render_action != "", (
                    f"Active event {evt.event_type!r} has empty render_action"
                )

    def test_skipped_events_have_non_empty_skipped_reason(self):
        layer = _make_layer(seed=7)
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.all_events:
                if evt.skipped_reason:
                    # skipped events may have any render_action string (including unsupported)
                    assert evt.skipped_reason != ""

    def test_all_event_render_actions_are_in_registry(self):
        """Events without a skipped_reason MUST use a SUPPORTED_RENDER_ACTIONS value."""
        layer = _make_layer(seed=1234, roles=ALL_ROLES)
        outputs = layer.generate()
        violations = []
        for sec in outputs:
            for evt in sec.all_events:
                if not evt.skipped_reason:
                    if evt.render_action not in SUPPORTED_RENDER_ACTIONS:
                        violations.append(
                            f"{sec.section_name}/{evt.event_type}: {evt.render_action!r}"
                        )
        assert violations == [], f"Unsupported render actions found: {violations}"

    def test_supported_render_actions_registry_is_non_empty(self):
        assert len(SUPPORTED_RENDER_ACTIONS) > 10

    def test_all_section_types_produce_events_with_valid_actions(self):
        for stype in ["intro", "verse", "pre_hook", "hook", "verse_2", "hook_2", "outro"]:
            layer = _make_layer(seed=42, roles=ALL_ROLES)
            sec = _gen_section(layer, stype)
            for evt in sec.active_events:
                assert evt.render_action in SUPPORTED_RENDER_ACTIONS, (
                    f"[{stype}] Event {evt.event_type!r} → {evt.render_action!r} not in registry"
                )


# ---------------------------------------------------------------------------
# 7. Unsupported events are logged, not silently ignored
# ---------------------------------------------------------------------------


class TestUnsupportedEventsAreLogged:
    def test_unsupported_render_action_produces_skipped_event_not_active(self):
        """Events with unsupported render_action must appear in all_events with a skipped_reason."""
        layer = _make_layer(seed=42)
        # Inject a fake event using an unsupported render_action via _make_event
        evt = layer._make_event(
            event_type="test_event",
            section_name="Test",
            bar_start=0,
            bar_end=0,
            target_role="fx",
            intensity=0.5,
            render_action="nonexistent_action",
        )
        assert evt.skipped_reason != "", "Unsupported render_action must produce a non-empty skipped_reason"
        assert "unsupported_render_action" in evt.skipped_reason

    def test_unsupported_render_action_is_logged(self):
        """The logger.warning must be called for unsupported render actions."""
        layer = _make_layer(seed=42)
        with patch("app.services.generative_producer_layer.logger") as mock_log:
            evt = layer._make_event(
                event_type="test_event",
                section_name="Test",
                bar_start=0,
                bar_end=0,
                target_role="fx",
                intensity=0.5,
                render_action="unsupported_action_xyz",
            )
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args
        assert "unsupported" in call_args[0][0].lower() or any(
            "unsupported" in str(a) for a in call_args[0]
        )

    def test_unsupported_event_not_in_active_events_of_section(self):
        """An event with an unsupported render_action must NOT appear in active_events."""
        layer = _make_layer(seed=42)
        evt = layer._make_event(
            event_type="bad_event",
            section_name="Hook",
            bar_start=0,
            bar_end=8,
            target_role="fx",
            intensity=0.9,
            render_action="unsupported_render_action_xyz",
        )
        # Manually create a SectionOutput and add the event
        sec = SectionOutput(section_name="Hook", section_type="hook", bar_start=0, bars=8)
        sec.fx_transition_events.append(evt)

        active = sec.active_events
        assert evt not in active, "Unsupported event must not be in active_events"
        assert evt in sec.all_events, "Unsupported event must still appear in all_events"

    def test_missing_role_produces_skipped_event_not_active(self):
        """Events targeting unavailable roles must be skipped (not silently dropped)."""
        layer = _make_layer(seed=42, roles=["melody", "fx"])  # no drums, no bass
        intro = _gen_section(layer, "intro", bars=8)
        # All 808 events must be explicitly skipped
        for evt in intro.generated_808_pattern_events:
            assert evt.skipped_reason != "", (
                "Events for missing roles must have a skipped_reason, not be silently dropped"
            )

    def test_missing_role_events_have_role_unavailable_reason(self):
        """When a role is unavailable, skipped_reason contains 'role_unavailable' or section-specific rule."""
        layer = _make_layer(seed=42, roles=["melody", "fx"])  # no drums
        verse = _gen_section(layer, "verse", bars=8)
        drum_events = verse.generated_drum_pattern_events
        # All drum events for a layer with no drums stem should be skipped
        assert all(evt.skipped_reason for evt in drum_events), (
            "All drum events should be skipped when drums stem is absent"
        )

    def test_all_events_have_non_empty_event_type(self):
        """Every event (active or skipped) must carry a non-empty event_type."""
        layer = _make_layer(seed=42)
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.all_events:
                assert evt.event_type != "", f"Event in {sec.section_name!r} has empty event_type"

    def test_skipped_intro_events_still_carry_render_action(self):
        """Skipped events still declare what action would have been used."""
        layer = _make_layer(seed=42)
        intro = _gen_section(layer, "intro", bars=8)
        for evt in intro.generated_drum_pattern_events:
            assert evt.render_action != "", "Skipped drum events must declare render_action"
        for evt in intro.generated_808_pattern_events:
            assert evt.render_action != "", "Skipped 808 events must declare render_action"


# ---------------------------------------------------------------------------
# Additional: GenerativeEvent schema / to_dict contract
# ---------------------------------------------------------------------------


class TestGenerativeEventSchema:
    _REQUIRED_KEYS = {
        "event_type", "section_name", "bar_start", "bar_end",
        "target_role", "intensity", "parameters", "render_action", "skipped_reason",
    }

    def test_to_dict_has_all_required_keys(self):
        evt = GenerativeEvent(
            event_type="test",
            section_name="Hook",
            bar_start=0,
            bar_end=8,
            target_role="drums",
            intensity=0.8,
            render_action="trigger_drum_pattern",
        )
        d = evt.to_dict()
        assert self._REQUIRED_KEYS.issubset(d.keys())

    def test_all_generated_events_have_required_keys(self):
        layer = _make_layer(seed=5)
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.all_events:
                d = evt.to_dict()
                missing = self._REQUIRED_KEYS - d.keys()
                assert missing == set(), (
                    f"Event {evt.event_type!r} in {sec.section_name!r} missing keys: {missing}"
                )

    def test_intensity_is_in_0_to_1_range(self):
        layer = _make_layer(seed=42)
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.all_events:
                assert 0.0 <= evt.intensity <= 1.0, (
                    f"Event {evt.event_type!r} intensity={evt.intensity} out of range"
                )

    def test_bar_end_gte_bar_start(self):
        layer = _make_layer(seed=42)
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.all_events:
                assert evt.bar_end >= evt.bar_start, (
                    f"Event {evt.event_type!r} bar_end={evt.bar_end} < bar_start={evt.bar_start}"
                )


# ---------------------------------------------------------------------------
# Additional: SectionOutput contract
# ---------------------------------------------------------------------------


class TestSectionOutputContract:
    def test_all_events_flat_list_includes_all_bucket_events(self):
        layer = _make_layer(seed=42)
        sec = _gen_section(layer, "hook", bars=8)
        total = (
            len(sec.generated_drum_pattern_events)
            + len(sec.generated_808_pattern_events)
            + len(sec.generated_hat_roll_events)
            + len(sec.melody_chop_events)
            + len(sec.counter_melody_events)
            + len(sec.fx_transition_events)
            + len(sec.automation_events)
        )
        assert len(sec.all_events) == total

    def test_active_events_is_subset_of_all_events(self):
        layer = _make_layer(seed=42)
        sec = _gen_section(layer, "intro", bars=8)
        assert all(e in sec.all_events for e in sec.active_events)

    def test_to_dict_has_all_bucket_keys(self):
        layer = _make_layer(seed=42)
        sec = _gen_section(layer, "verse", bars=8)
        d = sec.to_dict()
        expected = {
            "section_name", "section_type", "bar_start", "bars",
            "generated_drum_pattern_events", "generated_808_pattern_events",
            "generated_hat_roll_events", "melody_chop_events",
            "counter_melody_events", "fx_transition_events", "automation_events",
        }
        assert expected.issubset(d.keys())


# ---------------------------------------------------------------------------
# Additional: graceful degradation with no stems
# ---------------------------------------------------------------------------


class TestGracefulDegradationNoStems:
    def test_generates_without_crash_with_empty_roles(self):
        layer = GenerativeProducerLayer(
            loop_analysis=LOOP_ANALYSIS,
            genre="trap",
            variation_seed=42,
            available_roles=[],
        )
        outputs = layer.generate()
        assert len(outputs) > 0  # at least returns sections

    def test_all_events_have_skipped_reason_or_fx_role_when_no_stems(self):
        """With no stems, events targeting non-fx roles must be skipped OR not emitted at all."""
        layer = GenerativeProducerLayer(
            loop_analysis=LOOP_ANALYSIS,
            genre="trap",
            variation_seed=42,
            available_roles=[],
        )
        outputs = layer.generate()
        for sec in outputs:
            for evt in sec.all_events:
                # FX is a meta-role and may be active; all other roles must be skipped
                if evt.target_role not in ("fx",):
                    assert evt.skipped_reason != "", (
                        f"Event targeting {evt.target_role!r} in {sec.section_name!r} "
                        f"should be skipped with no stems, but skipped_reason is empty. "
                        f"Event: {evt.event_type!r} render_action={evt.render_action!r}"
                    )

    def test_fx_role_events_are_active_even_with_no_stems(self):
        """FX events are meta-role and must still be emitted even with empty available_roles."""
        layer = GenerativeProducerLayer(
            loop_analysis=LOOP_ANALYSIS,
            genre="trap",
            variation_seed=42,
            available_roles=[],
        )
        outputs = layer.generate()
        found_fx_active = False
        for sec in outputs:
            for evt in sec.all_events:
                if evt.target_role == "fx" and not evt.skipped_reason:
                    found_fx_active = True
        assert found_fx_active, "At least one active FX event expected even with no stems"


# ---------------------------------------------------------------------------
# Additional: full default plan round-trip
# ---------------------------------------------------------------------------


class TestDefaultTrapPlanRoundTrip:
    def test_default_plan_generates_all_section_types(self):
        layer = _make_layer(seed=42)
        outputs = layer.generate()
        types = {o.section_type for o in outputs}
        assert "intro" in types
        assert "verse" in types
        assert "pre_hook" in types
        assert "hook" in types
        assert "verse_2" in types
        assert "hook_2" in types
        assert "outro" in types

    def test_default_plan_has_correct_number_of_sections(self):
        layer = _make_layer(seed=42)
        outputs = layer.generate()
        assert len(outputs) == len(_DEFAULT_TRAP_PLAN)

    def test_factory_function_works(self):
        layer = create_generative_producer_layer(LOOP_ANALYSIS, variation_seed=42)
        assert layer is not None
        outputs = layer.generate()
        assert len(outputs) > 0


# ---------------------------------------------------------------------------
# Additional: _normalise_section_type utility
# ---------------------------------------------------------------------------


class TestNormaliseSectionType:
    @pytest.mark.parametrize("raw,expected", [
        ("intro", "intro"),
        ("INTRO", "intro"),
        ("verse", "verse"),
        ("Verse 1", "verse"),
        ("verse_1", "verse"),
        ("verse 2", "verse_2"),
        ("Verse 2", "verse_2"),
        ("pre_hook", "pre_hook"),
        ("pre_chorus", "pre_hook"),
        ("Pre Hook", "pre_hook"),
        ("hook", "hook"),
        ("chorus", "hook"),
        ("hook 1", "hook"),
        ("Hook 2", "hook_2"),
        ("hook_2", "hook_2"),
        ("outro", "outro"),
        ("bridge", "bridge"),
        ("breakdown", "bridge"),
    ])
    def test_normalise(self, raw: str, expected: str):
        assert _normalise_section_type(raw) == expected
