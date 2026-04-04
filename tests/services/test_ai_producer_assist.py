"""
Unit tests for AIProducerAssistService — Phase 4 AI Co-Producer Assist Layer.

Tests:
- AIProducerSuggestion schema validation
- Fallback behaviour when AI is disabled or unavailable
- Rules-validation tests showing AI suggestions cannot violate required constraints
- Schema round-trip (to_dict)
"""

import pytest
from app.services.ai_producer_assist import (
    AIProducerAssistService,
    AIProducerSuggestion,
    SuggestedSectionEntry,
    validate_ai_suggestion,
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
