"""
Unit tests for AIProducerAssistService — Phase 4 AI Co-Producer Assist Layer.

Tests:
- AIProducerSuggestion schema validation
- Fallback behaviour when AI is disabled or unavailable
- Rules-validation tests showing AI suggestions cannot violate required constraints
- Schema round-trip (to_dict)
- Strict planning: repeated section contrast enforcement
- Vague plan rejection
- Hook novelty requirement
- Bridge/breakdown density reduction
- AI plan novelty scoring (score_ai_plan)
- Observability fields (ai_plan_raw, ai_section_deltas, ai_novelty_score, etc.)
"""

import pytest
from app.services.ai_producer_assist import (
    AIProducerAssistService,
    AIProducerSuggestion,
    SuggestedSectionEntry,
    _contains_vague_phrase,
    score_ai_plan,
    validate_ai_suggestion,
    _MIN_JACCARD_CONTRAST,
    _MIN_NOVELTY_SCORE,
)


# ---------------------------------------------------------------------------
# Schema Tests
# ---------------------------------------------------------------------------


class TestAIProducerSuggestionSchema:
    """Test AIProducerSuggestion data model."""

    def test_default_suggestion_is_empty(self):
        suggestion = AIProducerSuggestion()
        assert suggestion.suggested_sections == []
        assert suggestion.confidence == 0.0
        assert not suggestion.validation_passed
        assert suggestion.fallback_used is False

    def test_to_dict_has_required_keys(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums", "bass"],
                )
            ],
            confidence=0.8,
            reasoning="Strong hook needed",
            style_guess="trap",
            producer_notes=["Add drums to hook"],
        )
        d = suggestion.to_dict()
        assert "suggested_sections" in d
        assert "confidence" in d
        assert "reasoning" in d
        assert "style_guess" in d
        assert "producer_notes" in d
        assert "validation_passed" in d
        assert "validation_errors" in d

    def test_to_dict_is_json_safe(self):
        import json
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="verse", bars=8, energy=3, active_roles=["drums"]
                )
            ],
            confidence=0.7,
        )
        d = suggestion.to_dict()
        serialized = json.dumps(d)
        assert len(serialized) > 0


class TestValidateAISuggestion:
    """Tests for the validate_ai_suggestion function."""

    def _valid_suggestion(self, available_roles=None):
        """Build a valid suggestion."""
        return AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="intro", bars=8, energy=1, active_roles=["pads"]),
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=["drums", "bass"]),
                SuggestedSectionEntry(section_type="hook", bars=8, energy=5, active_roles=["drums", "bass"]),
                SuggestedSectionEntry(section_type="outro", bars=4, energy=1, active_roles=["pads"]),
            ],
            confidence=0.8,
        )

    def test_valid_suggestion_passes_validation(self):
        suggestion = self._valid_suggestion()
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums", "bass", "pads"])
        assert is_valid, f"Should be valid but got errors: {errors}"
        assert errors == []

    def test_empty_sections_fails(self):
        suggestion = AIProducerSuggestion(suggested_sections=[], confidence=0.5)
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("no sections" in e.lower() for e in errors)

    def test_hook_energy_not_above_verse_fails(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=4, active_roles=["drums"]),
                SuggestedSectionEntry(section_type="hook", bars=8, energy=3, active_roles=["drums"]),  # lower than verse
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("hook energy" in e for e in errors)

    def test_intro_energy_too_high_fails(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="intro", bars=8, energy=5, active_roles=["drums"]),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("intro energy" in e for e in errors)

    def test_unavailable_roles_flagged(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums", "violin"],  # violin not in available
                )
            ],
            confidence=0.7,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums", "bass"])
        assert not is_valid
        assert any("violin" in e for e in errors)

    def test_invalid_bar_count_fails(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=7, energy=3, active_roles=["drums"]),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("bar count" in e for e in errors)

    def test_invalid_section_type_fails(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="megahook", bars=8, energy=4, active_roles=["drums"]),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("megahook" in e for e in errors)

    def test_confidence_out_of_range_fails(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=["drums"]),
            ],
            confidence=1.5,   # > 1.0
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("confidence" in e for e in errors)

    def test_no_available_roles_skips_role_check(self):
        """When no available_roles provided, role constraint is skipped."""
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=["drums"]),
                SuggestedSectionEntry(section_type="hook", bars=8, energy=5, active_roles=["drums"]),
            ],
            confidence=0.6,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=[])
        assert is_valid, f"Should pass when available_roles is empty: {errors}"


class TestAIProducerAssistServiceFallback:
    """Service fallback tests (no LLM key required)."""

    def _service(self):
        return AIProducerAssistService(api_key="", model="gpt-4")

    @pytest.mark.asyncio
    async def test_feature_disabled_returns_fallback(self):
        service = self._service()
        result = await service.assist(
            available_roles=["drums", "bass"],
            feature_enabled=False,
        )
        assert result.fallback_used is True
        assert result.suggested_sections == []

    @pytest.mark.asyncio
    async def test_no_api_key_returns_fallback(self):
        service = self._service()
        result = await service.assist(
            available_roles=["drums", "bass"],
            feature_enabled=True,   # enabled but no client
        )
        assert result.fallback_used is True
        assert result.suggested_sections == []

    @pytest.mark.asyncio
    async def test_fallback_result_has_reasoning(self):
        service = self._service()
        result = await service.assist(
            available_roles=["drums", "bass"],
            feature_enabled=False,
        )
        assert len(result.reasoning) > 0


class TestParseResponse:
    """Test the static _parse_response helper directly."""

    def test_parse_valid_payload(self):
        payload = {
            "suggested_sections": [
                {"section_type": "intro", "bars": 8, "energy": 2, "active_roles": ["pads"], "notes": "sparse"},
                {"section_type": "hook", "bars": 8, "energy": 5, "active_roles": ["drums", "bass"], "notes": "big"},
            ],
            "confidence": 0.85,
            "reasoning": "Strong hook-focused arrangement",
            "style_guess": "trap",
            "producer_notes": ["Add drums to hook", "Keep intro sparse"],
        }
        suggestion = AIProducerAssistService._parse_response(payload)
        assert len(suggestion.suggested_sections) == 2
        assert suggestion.confidence == 0.85
        assert suggestion.style_guess == "trap"
        assert len(suggestion.producer_notes) == 2

    def test_parse_empty_sections(self):
        payload = {
            "suggested_sections": [],
            "confidence": 0.5,
            "reasoning": "",
            "style_guess": "",
            "producer_notes": [],
        }
        suggestion = AIProducerAssistService._parse_response(payload)
        assert suggestion.suggested_sections == []

    def test_parse_malformed_section_skipped(self):
        payload = {
            "suggested_sections": [
                "not a dict",
                {"section_type": "verse", "bars": 8, "energy": 3, "active_roles": ["drums"], "notes": ""},
            ],
            "confidence": 0.5,
            "reasoning": "",
            "style_guess": "",
            "producer_notes": [],
        }
        suggestion = AIProducerAssistService._parse_response(payload)
        assert len(suggestion.suggested_sections) == 1

    def test_parse_clamps_energy_to_valid_range(self):
        payload = {
            "suggested_sections": [
                {"section_type": "hook", "bars": 8, "energy": 99, "active_roles": [], "notes": ""},
            ],
            "confidence": 0.5,
            "reasoning": "",
            "style_guess": "",
            "producer_notes": [],
        }
        suggestion = AIProducerAssistService._parse_response(payload)
        assert suggestion.suggested_sections[0].energy == 5

    def test_parse_floors_bars_to_4(self):
        payload = {
            "suggested_sections": [
                {"section_type": "intro", "bars": 1, "energy": 2, "active_roles": [], "notes": ""},
            ],
            "confidence": 0.5,
            "reasoning": "",
            "style_guess": "",
            "producer_notes": [],
        }
        suggestion = AIProducerAssistService._parse_response(payload)
        assert suggestion.suggested_sections[0].bars == 4


# ---------------------------------------------------------------------------
# New strict planning tests
# ---------------------------------------------------------------------------


class TestSuggestedSectionEntryStrictFields:
    """SuggestedSectionEntry must carry all strict planning fields."""

    def test_default_values_are_safe(self):
        entry = SuggestedSectionEntry(section_type="verse", bars=8, energy=3)
        assert entry.target_density == "medium"
        assert entry.transition_in == "none"
        assert entry.transition_out == "none"
        assert entry.variation_strategy == "none"
        assert entry.introduced_elements == []
        assert entry.dropped_elements == []

    def test_to_dict_includes_all_strict_fields(self):
        import json
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums", "bass"],
                    target_density="full",
                    transition_in="fx_rise",
                    transition_out="none",
                    variation_strategy="role_rotation",
                    introduced_elements=["bass"],
                    dropped_elements=[],
                )
            ],
            confidence=0.8,
        )
        d = suggestion.to_dict()
        sec = d["suggested_sections"][0]
        assert sec["target_density"] == "full"
        assert sec["transition_in"] == "fx_rise"
        assert sec["transition_out"] == "none"
        assert sec["variation_strategy"] == "role_rotation"
        assert sec["introduced_elements"] == ["bass"]
        assert sec["dropped_elements"] == []
        # Must be JSON-serialisable
        json.dumps(d)

    def test_to_dict_includes_observability_fields(self):
        import json
        suggestion = AIProducerSuggestion(
            ai_plan_raw='{"raw": true}',
            ai_plan_rejected_reason="",
            ai_section_deltas=[{"section_type": "verse"}],
            ai_novelty_score=0.75,
            ai_plan_vs_actual_match=0.9,
        )
        d = suggestion.to_dict()
        assert "ai_plan_raw" in d
        assert "ai_plan_rejected_reason" in d
        assert "ai_section_deltas" in d
        assert "ai_novelty_score" in d
        assert "ai_plan_vs_actual_match" in d
        json.dumps(d)


class TestVaguePlanDetection:
    """Vague section notes must be detected and rejected."""

    def test_empty_notes_are_not_vague(self):
        assert not _contains_vague_phrase("")
        assert not _contains_vague_phrase("   ")

    def test_specific_notes_are_not_vague(self):
        assert not _contains_vague_phrase("Add synth pad layer on top of drums and bass")
        assert not _contains_vague_phrase("Drop drums, keep bass and pads for contrast")
        assert not _contains_vague_phrase("Introduce vocal chop on beat 3")

    def test_add_more_energy_is_vague(self):
        assert _contains_vague_phrase("add more energy")
        assert _contains_vague_phrase("ADD MORE ENERGY to this section")

    def test_make_it_bigger_is_vague(self):
        assert _contains_vague_phrase("make it bigger")

    def test_keep_it_same_but_stronger_is_vague(self):
        assert _contains_vague_phrase("keep it the same but stronger")

    def test_validation_rejects_vague_notes(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="verse",
                    bars=8,
                    energy=3,
                    active_roles=["drums"],
                    notes="add more energy",
                ),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("vague" in e.lower() for e in errors)

    def test_validation_rejects_vague_notes_case_insensitive(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums"],
                    notes="Make It Bigger on every beat",
                ),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums"])
        assert not is_valid
        assert any("vague" in e.lower() for e in errors)


class TestRepeatedSectionContrast:
    """Verse 1 vs Verse 2 and Hook 1 vs Hook 2 must differ sufficiently."""

    def test_identical_verses_fail_validation(self):
        roles = ["drums", "bass"]
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=roles),
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=roles),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums", "bass"])
        assert not is_valid
        assert any("too similar" in e for e in errors)

    def test_identical_hooks_fail_validation(self):
        roles = ["drums", "bass", "melody"]
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=["drums"]),
                SuggestedSectionEntry(section_type="hook", bars=8, energy=5, active_roles=roles),
                SuggestedSectionEntry(section_type="hook", bars=8, energy=5, active_roles=roles),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(
            suggestion, available_roles=["drums", "bass", "melody"]
        )
        assert not is_valid
        assert any("too similar" in e for e in errors)

    def test_different_roles_between_verses_passes(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="verse", bars=8, energy=3, active_roles=["drums", "bass"]
                ),
                SuggestedSectionEntry(
                    # Changed role set: added melody, removed bass → Jaccard > 0.20
                    section_type="verse",
                    bars=8,
                    energy=3,
                    active_roles=["drums", "melody"],
                ),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(
            suggestion, available_roles=["drums", "bass", "melody"]
        )
        assert is_valid, f"Different verse roles should pass: {errors}"

    def test_same_roles_different_energy_between_verses_passes(self):
        """Energy delta >= 1 is sufficient contrast even with identical role sets."""
        roles = ["drums", "bass"]
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=roles),
                SuggestedSectionEntry(section_type="verse", bars=8, energy=4, active_roles=roles),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["drums", "bass"])
        assert is_valid, f"Energy delta alone should satisfy contrast: {errors}"

    def test_intro_repeated_is_allowed_same(self):
        """intro/outro are exempt from the repeated-section contrast rule."""
        roles = ["pads"]
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="intro", bars=4, energy=1, active_roles=roles),
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=["drums"]),
                SuggestedSectionEntry(section_type="hook", bars=8, energy=5, active_roles=["drums"]),
                SuggestedSectionEntry(section_type="intro", bars=4, energy=1, active_roles=roles),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(
            suggestion, available_roles=["pads", "drums"]
        )
        assert is_valid, f"Repeated intro should not trigger contrast check: {errors}"


class TestBridgeBreakdownDensity:
    """Bridge and breakdown sections must reduce density (energy <= 2)."""

    def test_bridge_with_high_energy_fails(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="bridge", bars=8, energy=4, active_roles=["pads"]),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["pads"])
        assert not is_valid
        assert any("bridge" in e and "density" in e for e in errors)

    def test_breakdown_with_high_energy_fails(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="breakdown", bars=8, energy=3, active_roles=["pads"]
                ),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["pads"])
        assert not is_valid
        assert any("breakdown" in e and "density" in e for e in errors)

    def test_bridge_with_energy_2_passes(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="bridge", bars=8, energy=2, active_roles=["pads"]),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["pads"])
        assert is_valid, f"Bridge energy=2 should be valid: {errors}"

    def test_outro_must_simplify(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="outro", bars=4, energy=4, active_roles=["pads"]),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["pads"])
        assert not is_valid
        assert any("outro" in e and "simplif" in e for e in errors)

    def test_outro_with_energy_1_passes(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="outro", bars=4, energy=1, active_roles=["pads"]),
            ],
            confidence=0.5,
        )
        is_valid, errors = validate_ai_suggestion(suggestion, available_roles=["pads"])
        assert is_valid, f"Outro energy=1 should be valid: {errors}"


class TestAIPlanScoring:
    """score_ai_plan computes novelty score and section deltas correctly."""

    def _rich_contrast_suggestion(self) -> AIProducerSuggestion:
        """A suggestion with clear, audible contrast between repeated sections."""
        return AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="intro", bars=4, energy=1, active_roles=["pads"]
                ),
                SuggestedSectionEntry(
                    section_type="verse", bars=8, energy=3, active_roles=["drums", "bass"]
                ),
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums", "bass", "melody"],
                    introduced_elements=["melody"],
                ),
                SuggestedSectionEntry(
                    section_type="verse",
                    bars=8,
                    energy=4,
                    active_roles=["drums", "bass", "synth"],
                    introduced_elements=["synth"],
                ),
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums", "bass", "melody", "vocal"],
                    introduced_elements=["vocal"],
                ),
                SuggestedSectionEntry(
                    section_type="outro", bars=4, energy=1, active_roles=["pads"]
                ),
            ],
            confidence=0.9,
        )

    def test_rich_plan_scores_above_minimum(self):
        suggestion = self._rich_contrast_suggestion()
        score, deltas = score_ai_plan(suggestion)
        assert score >= _MIN_NOVELTY_SCORE, f"Rich plan should score >= {_MIN_NOVELTY_SCORE}, got {score}"

    def test_flat_identical_plan_scores_low(self):
        """A plan where every section has the same energy and repeated sections are identical."""
        roles = ["drums", "bass"]
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=roles),
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=roles),
            ],
            confidence=0.5,
        )
        score, deltas = score_ai_plan(suggestion)
        assert score < _MIN_NOVELTY_SCORE, f"Flat identical plan should score < {_MIN_NOVELTY_SCORE}, got {score}"

    def test_section_deltas_populated_for_repeated_sections(self):
        suggestion = self._rich_contrast_suggestion()
        _, deltas = score_ai_plan(suggestion)
        # Should have deltas for verse and hook (both repeated)
        delta_types = {d["section_type"] for d in deltas}
        assert "verse" in delta_types
        assert "hook" in delta_types

    def test_section_deltas_report_roles_added(self):
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="verse", bars=8, energy=3, active_roles=["drums", "bass"]
                ),
                SuggestedSectionEntry(
                    section_type="verse",
                    bars=8,
                    energy=3,
                    active_roles=["drums", "bass", "synth"],
                ),
            ],
            confidence=0.5,
        )
        _, deltas = score_ai_plan(suggestion)
        assert len(deltas) == 1
        delta = deltas[0]
        assert delta["section_type"] == "verse"
        assert "synth" in delta["roles_added"]
        assert delta["roles_removed"] == []
        assert delta["sufficient_contrast"] is True

    def test_section_deltas_flag_insufficient_contrast(self):
        roles = ["drums", "bass"]
        suggestion = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=roles),
                SuggestedSectionEntry(section_type="verse", bars=8, energy=3, active_roles=roles),
            ],
            confidence=0.5,
        )
        _, deltas = score_ai_plan(suggestion)
        assert len(deltas) == 1
        assert deltas[0]["sufficient_contrast"] is False

    def test_hook_novelty_included_in_score(self):
        """Hooks with introduced_elements push the novelty score higher."""
        # Hook with no novelty
        low_novelty = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="verse", bars=8, energy=2, active_roles=["drums"]
                ),
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums"],
                    introduced_elements=[],  # no novelty
                ),
                SuggestedSectionEntry(
                    section_type="outro", bars=4, energy=1, active_roles=["pads"]
                ),
            ],
            confidence=0.5,
        )
        # Hook with novelty
        high_novelty = AIProducerSuggestion(
            suggested_sections=[
                SuggestedSectionEntry(
                    section_type="verse", bars=8, energy=2, active_roles=["drums"]
                ),
                SuggestedSectionEntry(
                    section_type="hook",
                    bars=8,
                    energy=5,
                    active_roles=["drums", "melody"],
                    introduced_elements=["melody"],
                ),
                SuggestedSectionEntry(
                    section_type="outro", bars=4, energy=1, active_roles=["pads"]
                ),
            ],
            confidence=0.5,
        )
        low_score, _ = score_ai_plan(low_novelty)
        high_score, _ = score_ai_plan(high_novelty)
        assert high_score > low_score, (
            f"Hook novelty should increase score: low={low_score}, high={high_score}"
        )

    def test_empty_suggestion_scores_zero(self):
        suggestion = AIProducerSuggestion(suggested_sections=[], confidence=0.5)
        score, deltas = score_ai_plan(suggestion)
        assert score == 0.0
        assert deltas == []

    def test_score_is_bounded_0_to_1(self):
        suggestion = self._rich_contrast_suggestion()
        score, _ = score_ai_plan(suggestion)
        assert 0.0 <= score <= 1.0


class TestParseResponseStrictFields:
    """_parse_response must handle all strict planning fields from the LLM JSON."""

    def test_parse_includes_target_density(self):
        payload = {
            "suggested_sections": [
                {
                    "section_type": "hook",
                    "bars": 8,
                    "energy": 5,
                    "active_roles": ["drums"],
                    "notes": "",
                    "target_density": "full",
                    "transition_in": "fx_rise",
                    "transition_out": "none",
                    "variation_strategy": "role_rotation",
                    "introduced_elements": ["drums"],
                    "dropped_elements": [],
                }
            ],
            "confidence": 0.8,
            "reasoning": "",
            "style_guess": "",
            "producer_notes": [],
        }
        suggestion = AIProducerAssistService._parse_response(payload)
        sec = suggestion.suggested_sections[0]
        assert sec.target_density == "full"
        assert sec.transition_in == "fx_rise"
        assert sec.variation_strategy == "role_rotation"
        assert sec.introduced_elements == ["drums"]
        assert sec.dropped_elements == []

    def test_parse_defaults_new_fields_when_absent(self):
        """Legacy LLM responses without the new fields must still parse cleanly."""
        payload = {
            "suggested_sections": [
                {
                    "section_type": "verse",
                    "bars": 8,
                    "energy": 3,
                    "active_roles": ["drums"],
                    "notes": "",
                }
            ],
            "confidence": 0.5,
            "reasoning": "",
            "style_guess": "",
            "producer_notes": [],
        }
        suggestion = AIProducerAssistService._parse_response(payload)
        sec = suggestion.suggested_sections[0]
        assert sec.target_density == "medium"
        assert sec.transition_in == "none"
        assert sec.transition_out == "none"
        assert sec.variation_strategy == "none"
        assert sec.introduced_elements == []
        assert sec.dropped_elements == []


class TestRenderObservabilityAIFields:
    """assemble_render_metadata must surface AI planning observability fields."""

    def test_ai_fields_passed_through_from_observability(self):
        from app.services.render_observability import assemble_render_metadata

        observability = {
            "fallback_triggered_count": 0,
            "fallback_sections_count": 0,
            "fallback_reasons": [],
            "planned_stem_map_by_section": [],
            "actual_stem_map_by_section": [],
            "section_execution_report": [],
            "render_signatures": [],
            "unique_render_signature_count": 0,
            "phrase_split_count": 0,
            "distinct_stem_set_count": 0,
            "hook_stages_rendered": [],
            "transition_event_count": 0,
            "ai_plan_raw": '{"sections": []}',
            "ai_plan_rejected_reason": "",
            "ai_section_deltas": [{"section_type": "verse"}],
            "ai_novelty_score": 0.75,
            "ai_plan_vs_actual_match": 0.9,
        }
        metadata = assemble_render_metadata(
            worker_mode="external",
            job_terminal_state="success_truthful",
            failure_stage=None,
            render_path_used="stem_pack",
            source_quality_mode_used="true_stems",
            observability=observability,
        )
        assert metadata["ai_plan_raw"] == '{"sections": []}'
        assert metadata["ai_plan_rejected_reason"] == ""
        assert metadata["ai_section_deltas"] == [{"section_type": "verse"}]
        assert metadata["ai_novelty_score"] == 0.75
        assert metadata["ai_plan_vs_actual_match"] == 0.9

    def test_plan_vs_actual_match_computed_from_stem_maps(self):
        """When ai_plan_vs_actual_match is absent, it must be computed from stem maps."""
        from app.services.render_observability import assemble_render_metadata

        planned = [
            {"section_index": 0, "section_type": "verse", "roles": ["drums", "bass"]},
            {"section_index": 1, "section_type": "hook", "roles": ["drums", "bass", "melody"]},
        ]
        actual = [
            {"section_index": 0, "section_type": "verse", "roles": ["drums", "bass"]},
            # Hook has one role dropped — not a match
            {"section_index": 1, "section_type": "hook", "roles": ["drums", "bass"]},
        ]
        observability = {
            "fallback_triggered_count": 0,
            "fallback_sections_count": 0,
            "fallback_reasons": [],
            "planned_stem_map_by_section": planned,
            "actual_stem_map_by_section": actual,
            "section_execution_report": [],
            "render_signatures": [],
            "unique_render_signature_count": 0,
            "phrase_split_count": 0,
            "distinct_stem_set_count": 0,
            "hook_stages_rendered": [],
            "transition_event_count": 0,
        }
        metadata = assemble_render_metadata(
            worker_mode="external",
            job_terminal_state="success_with_fallbacks",
            failure_stage=None,
            render_path_used="stem_pack",
            source_quality_mode_used="true_stems",
            observability=observability,
        )
        # 1 of 2 sections matched → 0.5
        assert "ai_plan_vs_actual_match" in metadata
        assert metadata["ai_plan_vs_actual_match"] == 0.5

    def test_plan_vs_actual_match_perfect(self):
        from app.services.render_observability import assemble_render_metadata

        roles = ["drums", "bass"]
        planned = [{"section_index": 0, "roles": roles}]
        actual = [{"section_index": 0, "roles": roles}]
        observability = {
            "fallback_triggered_count": 0,
            "fallback_sections_count": 0,
            "fallback_reasons": [],
            "planned_stem_map_by_section": planned,
            "actual_stem_map_by_section": actual,
            "section_execution_report": [],
            "render_signatures": [],
            "unique_render_signature_count": 0,
            "phrase_split_count": 0,
            "distinct_stem_set_count": 0,
            "hook_stages_rendered": [],
            "transition_event_count": 0,
        }
        metadata = assemble_render_metadata(
            worker_mode="embedded",
            job_terminal_state="success_truthful",
            failure_stage=None,
            render_path_used="stem_pack",
            source_quality_mode_used="true_stems",
            observability=observability,
        )
        assert metadata["ai_plan_vs_actual_match"] == 1.0
