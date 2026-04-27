"""Extended tests for app/services/arrangement_memory.py.

Covers previously-untested branches:
- all_role_combos_for (line 139)
- is_role_combo_used when memory is disabled (line 144)
- suggest_variation_strategy — add_percussion fallback (line 203)
- suggest_variation_strategy — role_rotation → support_swap (lines 206-208)
- suggest_variation_strategy — role_rotation → add_percussion fallback (line 209)
- suggest_variation_strategy — support_swap → add_percussion (lines 211-212)
- suggest_variation_strategy — support_swap → change_pattern (line 212)
- suggest_variation_strategy — add_percussion → change_pattern (lines 214-216)
- suggest_variation_strategy — add_percussion → none (line 217)
- suggest_variation_strategy — unknown last_used → none (line 219)
"""

from __future__ import annotations

import pytest
from app.services.arrangement_memory import ArrangementMemory


# ---------------------------------------------------------------------------
# all_role_combos_for
# ---------------------------------------------------------------------------


class TestAllRoleCombosFor:
    def test_returns_empty_list_for_unknown_section(self):
        mem = ArrangementMemory()
        result = mem.all_role_combos_for("unknown_section")
        assert result == []

    def test_returns_combos_after_recording_sections(self):
        mem = ArrangementMemory()
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=5)
        mem.record_section(section_type="verse", roles=["drums", "bass", "melody"], energy=6)
        combos = mem.all_role_combos_for("verse")
        assert len(combos) == 2
        assert frozenset({"drums", "bass"}) in combos
        assert frozenset({"drums", "bass", "melody"}) in combos

    def test_returns_list_copy_not_original(self):
        """Mutating the returned list must not affect internal state."""
        mem = ArrangementMemory()
        mem.record_section(section_type="hook", roles=["drums"], energy=8)
        combos = mem.all_role_combos_for("hook")
        combos.clear()
        assert len(mem.all_role_combos_for("hook")) == 1


# ---------------------------------------------------------------------------
# is_role_combo_used — disabled branch
# ---------------------------------------------------------------------------


class TestIsRoleComboUsedDisabled:
    def test_returns_false_when_disabled(self):
        """When memory is disabled, is_role_combo_used always returns False (line 144)."""
        mem = ArrangementMemory(enabled=False)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=5)
        # Even though we recorded it, disabled memory returns False
        result = mem.is_role_combo_used("verse", ["drums", "bass"])
        assert result is False

    def test_returns_true_when_enabled_and_combo_used(self):
        mem = ArrangementMemory(enabled=True)
        mem.record_section(section_type="verse", roles=["drums", "bass"], energy=5)
        assert mem.is_role_combo_used("verse", ["drums", "bass"]) is True

    def test_returns_false_when_enabled_and_combo_not_used(self):
        mem = ArrangementMemory(enabled=True)
        assert mem.is_role_combo_used("verse", ["synth"]) is False


# ---------------------------------------------------------------------------
# suggest_variation_strategy
# ---------------------------------------------------------------------------


class TestSuggestVariationStrategy:
    """Tests for all branches of suggest_variation_strategy."""

    def test_returns_none_when_occurrence_is_1(self):
        mem = ArrangementMemory()
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=1,
            available_roles=["drums", "bass", "melody"],
            prev_roles=["drums", "bass"],
        )
        assert result == "none"

    def test_returns_none_when_disabled(self):
        mem = ArrangementMemory(enabled=False)
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "melody"],
            prev_roles=["drums"],
        )
        assert result == "none"

    def test_last_none_with_new_roles_returns_role_rotation(self):
        """last_used=none, new roles available → role_rotation."""
        mem = ArrangementMemory()
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "melody"],
            prev_roles=["drums", "bass"],
        )
        assert result == "role_rotation"

    def test_last_none_no_new_roles_percussion_in_both_returns_none(self):
        """last_used=none, percussion already in prev_roles (no net-new roles) → none."""
        mem = ArrangementMemory()
        # available_set == prev_set → available_set - prev_set is empty → falls through to none
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "percussion"],
            prev_roles=["drums", "bass", "percussion"],
        )
        # prev_set == available_set → no new roles → fall through
        assert result == "none"

    def test_last_none_percussion_not_in_prev_returns_add_percussion(self):
        """last_used=none, no available_set - prev_set but percussion is new."""
        mem = ArrangementMemory()
        # available_set = {drums, bass, percussion}
        # prev_set = {drums, bass}
        # available_set - prev_set = {percussion} → len >= 1 → returns role_rotation
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "percussion"],
            prev_roles=["drums", "bass"],
        )
        assert result == "role_rotation"

    def test_last_none_no_new_roles_returns_none(self):
        """last_used=none, prev == available, no percussion → none."""
        mem = ArrangementMemory()
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass"],
            prev_roles=["drums", "bass"],
        )
        assert result == "none"

    def test_last_role_rotation_with_new_roles_returns_support_swap(self):
        """last_used=role_rotation and there are new roles → support_swap (line 208)."""
        mem = ArrangementMemory()
        # Inject a fake history showing role_rotation was last used
        mem.repeat_variation_history["verse"] = ["role_rotation"]
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "melody"],
            prev_roles=["drums", "bass"],
        )
        assert result == "support_swap"

    def test_last_role_rotation_no_new_roles_with_percussion_returns_add_percussion(self):
        """last_used=role_rotation, no new roles, percussion available → add_percussion."""
        mem = ArrangementMemory()
        mem.repeat_variation_history["verse"] = ["role_rotation"]
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "percussion"],
            prev_roles=["drums", "bass", "percussion"],
        )
        assert result == "add_percussion"

    def test_last_role_rotation_no_new_roles_no_percussion_returns_none(self):
        """last_used=role_rotation, no new roles, no percussion → none."""
        mem = ArrangementMemory()
        mem.repeat_variation_history["verse"] = ["role_rotation"]
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass"],
            prev_roles=["drums", "bass"],
        )
        assert result == "none"

    def test_last_support_swap_with_percussion_returns_add_percussion(self):
        """last_used=support_swap, percussion available → add_percussion (line 212)."""
        mem = ArrangementMemory()
        mem.repeat_variation_history["verse"] = ["support_swap"]
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "percussion"],
            prev_roles=["drums", "bass"],
        )
        assert result == "add_percussion"

    def test_last_support_swap_without_percussion_returns_change_pattern(self):
        """last_used=support_swap, no percussion → change_pattern (line 212 else branch)."""
        mem = ArrangementMemory()
        mem.repeat_variation_history["verse"] = ["support_swap"]
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass"],
            prev_roles=["drums"],
        )
        assert result == "change_pattern"

    def test_last_add_percussion_with_new_melody_returns_change_pattern(self):
        """last_used=add_percussion, melody available but not in prev → change_pattern (line 216)."""
        mem = ArrangementMemory()
        mem.repeat_variation_history["verse"] = ["add_percussion"]
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "melody"],
            prev_roles=["drums", "bass"],
        )
        assert result == "change_pattern"

    def test_last_add_percussion_melody_already_used_returns_none(self):
        """last_used=add_percussion, melody in prev → none (line 217)."""
        mem = ArrangementMemory()
        mem.repeat_variation_history["verse"] = ["add_percussion"]
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass", "melody"],
            prev_roles=["drums", "bass", "melody"],
        )
        assert result == "none"

    def test_unknown_last_used_returns_none(self):
        """Unknown last strategy returns none (line 219)."""
        mem = ArrangementMemory()
        mem.repeat_variation_history["verse"] = ["half_time"]  # valid but no branch for it
        result = mem.suggest_variation_strategy(
            section_type="verse",
            occurrence=2,
            available_roles=["drums", "bass"],
            prev_roles=["drums"],
        )
        assert result == "none"
