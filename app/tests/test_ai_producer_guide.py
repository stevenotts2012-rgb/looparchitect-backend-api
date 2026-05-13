import os

import pytest

from app.services.ai_producer_guide.arrangement_advisor import AIProducerGuideAdvisor
from app.services.ai_producer_guide.decision_schema import GuideSchemaError, validate_guide_schema
from app.services.ai_producer_guide.safety import reject_unsafe_guidance
from app.services.producer_intelligence.planner import ProducerIntelligencePlanner


def test_ai_guide_disabled_uses_internal_rules(monkeypatch):
    monkeypatch.setenv("AI_PRODUCER_GUIDE_ENABLED", "false")
    guide = AIProducerGuideAdvisor().get_guide({"genre": "trap", "detected_roles": ["drums"]})
    assert guide is not None


def test_ai_guide_failure_falls_back_safely(monkeypatch):
    monkeypatch.setenv("AI_PRODUCER_GUIDE_ENABLED", "true")
    monkeypatch.setenv("AI_PRODUCER_GUIDE_PROVIDER", "openai")
    guide = AIProducerGuideAdvisor().get_guide({"genre": "trap", "detected_roles": ["drums"]})
    assert guide is not None


def test_ai_guide_response_adjusts_melody_priority(monkeypatch):
    monkeypatch.setenv("AI_PRODUCER_GUIDE_ENABLED", "true")
    monkeypatch.setenv("AI_PRODUCER_GUIDE_PROVIDER", "rules")
    plan = ProducerIntelligencePlanner().generate(["intro", "hook_1", "outro"], ["drums", "bass", "melody"])
    assert plan["melody_priority"] > 0.6


def test_ai_guide_response_adjusts_transition_density(monkeypatch):
    monkeypatch.setenv("AI_PRODUCER_GUIDE_ENABLED", "true")
    monkeypatch.setenv("AI_PRODUCER_GUIDE_PROVIDER", "rules")
    plan = ProducerIntelligencePlanner().generate(["intro", "verse_1", "hook_1", "outro"], ["drums", "bass", "melody"])
    assert plan["ai_guide"]["style_traits"]["transition_density"] == "moderate"


def test_ai_guide_response_has_two_variation_strategies(monkeypatch):
    monkeypatch.setenv("AI_PRODUCER_GUIDE_ENABLED", "true")
    monkeypatch.setenv("AI_PRODUCER_GUIDE_PROVIDER", "rules")
    guide = AIProducerGuideAdvisor().get_guide({"genre": "trap", "mood": "dark", "energy": "high", "bpm": 140, "detected_roles": ["drums", "bass"]})
    assert guide is not None
    assert len(guide["variation_strategy"]) >= 2
    assert guide["variation_strategy"][0]["focus"] != guide["variation_strategy"][1]["focus"]


def test_unsafe_copying_advice_rejected():
    with pytest.raises(ValueError):
        reject_unsafe_guidance({"do_not_do": [], "text": "copy exact song"})


def test_strict_json_schema_validation_works():
    with pytest.raises(GuideSchemaError):
        validate_guide_schema({"style_traits": {}})
