"""
Arrangement Layering Engine: Rule-based section-by-section layering intelligence for LoopArchitect.

This module generates a structured layering plan for each arrangement section,
based on genre, mood, energy, arrangement template, section list, and detected elements.

Genres supported: trap, dark_trap, melodic_trap, drill, rage
Sections supported: intro, verse, hook, bridge, outro
Detected elements: melody, counter_melody, bass, 808, kick, snare, hats, perc, pad, fx, texture

No external AI APIs. Rule-based only.
"""

from typing import List, Dict, Optional, Any
from enum import Enum

class LayeringSectionType(str, Enum):
    INTRO = "intro"
    VERSE = "verse"
    HOOK = "hook"
    BRIDGE = "bridge"
    OUTRO = "outro"

class LayeringPlanSection:
    def __init__(
        self,
        section_name: str,
        active_elements: List[str],
        muted_elements: List[str],
        introduced_elements: List[str],
        removed_elements: List[str],
        transition_in: Optional[str],
        transition_out: Optional[str],
        variation_strategy: Optional[str],
        energy_level: Optional[float],
    ):
        self.section_name = section_name
        self.active_elements = active_elements
        self.muted_elements = muted_elements
        self.introduced_elements = introduced_elements
        self.removed_elements = removed_elements
        self.transition_in = transition_in
        self.transition_out = transition_out
        self.variation_strategy = variation_strategy
        self.energy_level = energy_level

class ArrangementLayeringEngine:
    # Genre priorities for elements
    GENRE_PRIORITIES = {
        "trap": ["808", "kick", "snare", "hats", "melody", "pad", "fx"],
        "dark_trap": ["808", "kick", "snare", "hats", "pad", "fx", "texture", "melody"],
        "melodic_trap": ["melody", "counter_melody", "808", "kick", "snare", "pad", "fx"],
        "drill": ["808", "kick", "snare", "hats", "perc", "fx", "melody"],
        "rage": ["synth", "808", "kick", "snare", "hats", "fx", "texture"],
    }

    SECTION_RULES = {
        "intro": {
            "energy": 0.2,
            "active": lambda elements, genre: elements[:2],
            "muted": lambda elements, genre: elements[2:],
            "transition_in": "fade_in",
            "variation": "minimal",
        },
        "verse": {
            "energy": 0.5,
            "active": lambda elements, genre: elements[:4],
            "muted": lambda elements, genre: elements[4:],
            "transition_in": "fill",
            "variation": "additive",
        },
        "hook": {
            "energy": 1.0,
            "active": lambda elements, genre: elements,
            "muted": lambda elements, genre: [],
            "transition_in": "impact",
            "variation": "full",
        },
        "bridge": {
            "energy": 0.6,
            "active": lambda elements, genre: elements[:3],
            "muted": lambda elements, genre: elements[3:],
            "transition_in": "contrast",
            "variation": "dropout",
        },
        "outro": {
            "energy": 0.3,
            "active": lambda elements, genre: elements[:2],
            "muted": lambda elements, genre: elements[2:],
            "transition_in": "fade_out",
            "variation": "reduction",
        },
    }

    @classmethod
    def generate_layering_plan(
        cls,
        genre: str,
        mood: str,
        energy_level: float,
        arrangement_template: str,
        section_list: List[str],
        detected_elements: Optional[List[str]] = None,
        loop_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[LayeringPlanSection]:
        # Fallback to genre priorities if detected_elements is missing
        elements = detected_elements or cls.GENRE_PRIORITIES.get(genre, ["melody", "bass", "kick", "snare"])
        plan = []
        prev_active = []
        for idx, section in enumerate(section_list):
            section_key = section.lower()
            rules = cls.SECTION_RULES.get(section_key, cls.SECTION_RULES["verse"])
            active = rules["active"](elements, genre)
            muted = rules["muted"](elements, genre)
            introduced = [e for e in active if e not in prev_active]
            removed = [e for e in prev_active if e not in active]
            transition_in = rules["transition_in"]
            transition_out = None
            variation_strategy = rules["variation"]
            energy = rules["energy"] * energy_level if energy_level is not None else rules["energy"]
            plan.append(
                LayeringPlanSection(
                    section_name=section,
                    active_elements=active,
                    muted_elements=muted,
                    introduced_elements=introduced,
                    removed_elements=removed,
                    transition_in=transition_in,
                    transition_out=transition_out,
                    variation_strategy=variation_strategy,
                    energy_level=energy,
                )
            )
            prev_active = active
        return plan
