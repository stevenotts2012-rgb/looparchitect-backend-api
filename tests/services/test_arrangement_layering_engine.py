import pytest
from app.services.arrangement_layering_engine import ArrangementLayeringEngine

@pytest.mark.parametrize("genre,section_list,detected_elements,expected_hook_count", [
    ("dark_trap", ["intro", "verse", "hook", "bridge", "outro"], ["808", "kick", "snare", "hats", "pad", "fx", "texture", "melody"], 8),
    ("melodic_trap", ["intro", "verse", "hook", "bridge", "outro"], ["melody", "counter_melody", "808", "kick", "snare", "pad", "fx"], 7),
    ("drill", ["intro", "verse", "hook", "bridge", "outro"], ["808", "kick", "snare", "hats", "perc", "fx", "melody"], 7),
    ("rage", ["intro", "verse", "hook", "bridge", "outro"], ["synth", "808", "kick", "snare", "hats", "fx", "texture"], 7),
])
def test_hook_layering_is_fullest(genre, section_list, detected_elements, expected_hook_count):
    plan = ArrangementLayeringEngine.generate_layering_plan(
        genre=genre,
        mood="neutral",
        energy_level=1.0,
        arrangement_template="standard",
        section_list=section_list,
        detected_elements=detected_elements,
    )
    hook = next((s for s in plan if s.section_name == "hook"), None)
    verse = next((s for s in plan if s.section_name == "verse"), None)
    intro = next((s for s in plan if s.section_name == "intro"), None)
    outro = next((s for s in plan if s.section_name == "outro"), None)
    assert hook is not None
    assert verse is not None
    assert intro is not None
    assert outro is not None
    assert len(hook.active_elements) == expected_hook_count
    assert len(verse.active_elements) < len(hook.active_elements)
    assert len(intro.active_elements) < len(verse.active_elements)
    assert len(outro.active_elements) <= len(intro.active_elements)
    assert hook.energy_level > verse.energy_level
    assert intro.energy_level < hook.energy_level
    assert outro.energy_level < hook.energy_level
    assert hook.transition_in == "impact"
    assert intro.transition_in == "fade_in"
    assert outro.transition_in == "fade_out"
    assert hook.variation_strategy == "full"
    assert verse.variation_strategy == "additive"
    assert intro.variation_strategy == "minimal"
    assert outro.variation_strategy == "reduction"


def test_fallback_behavior_with_partial_elements():
    plan = ArrangementLayeringEngine.generate_layering_plan(
        genre="trap",
        mood="neutral",
        energy_level=1.0,
        arrangement_template="standard",
        section_list=["intro", "verse", "hook", "bridge", "outro"],
        detected_elements=None,
    )
    assert all(isinstance(s, object) for s in plan)
    assert len(plan) == 5
    assert plan[0].active_elements
    assert plan[2].active_elements


def test_transition_recommendations_present():
    plan = ArrangementLayeringEngine.generate_layering_plan(
        genre="drill",
        mood="neutral",
        energy_level=1.0,
        arrangement_template="standard",
        section_list=["intro", "verse", "hook", "bridge", "outro"],
        detected_elements=["808", "kick", "snare", "hats", "perc", "fx", "melody"],
    )
    transitions = [s.transition_in for s in plan]
    assert "impact" in transitions
    assert "fade_in" in transitions
    assert "fade_out" in transitions
    assert "contrast" in transitions


def test_variation_notes_and_energy_delta():
    plan = ArrangementLayeringEngine.generate_layering_plan(
        genre="melodic_trap",
        mood="neutral",
        energy_level=0.8,
        arrangement_template="standard",
        section_list=["intro", "verse", "hook", "bridge", "outro"],
        detected_elements=["melody", "counter_melody", "808", "kick", "snare", "pad", "fx"],
    )
    for section in plan:
        assert section.energy_level is not None
        assert section.variation_strategy is not None


def test_layering_output_structure():
    plan = ArrangementLayeringEngine.generate_layering_plan(
        genre="rage",
        mood="neutral",
        energy_level=1.0,
        arrangement_template="standard",
        section_list=["intro", "verse", "hook", "bridge", "outro"],
        detected_elements=["synth", "808", "kick", "snare", "hats", "fx", "texture"],
    )
    for section in plan:
        assert hasattr(section, "section_name")
        assert hasattr(section, "active_elements")
        assert hasattr(section, "muted_elements")
        assert hasattr(section, "introduced_elements")
        assert hasattr(section, "removed_elements")
        assert hasattr(section, "transition_in")
        assert hasattr(section, "transition_out")
        assert hasattr(section, "variation_strategy")
        assert hasattr(section, "energy_level")
