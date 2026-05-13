from __future__ import annotations

import json
import os
from typing import Any, Dict


class GuideClient:
    def __init__(self) -> None:
        self.provider = os.getenv("AI_PRODUCER_GUIDE_PROVIDER", "rules")

    def request(self, prompt: str, timeout_seconds: int = 20) -> Dict[str, Any]:
        if self.provider in {"openai", "azure_openai"}:
            # Provider abstraction placeholder: wire SDK/API here later.
            raise RuntimeError(f"{self.provider} provider not configured")
        if self.provider == "rules":
            return self._rules_response(prompt)
        raise RuntimeError(f"Unsupported AI_PRODUCER_GUIDE_PROVIDER={self.provider}")

    def _rules_response(self, prompt: str) -> Dict[str, Any]:
        return {
            "style_traits": {
                "tempo_feel": "steady groove",
                "drum_feel": "tight pocket",
                "bass_behavior": "supportive and rhythmic",
                "melody_behavior": "motif-led with space",
                "transition_density": "moderate",
                "section_pacing": "contrast every section",
                "energy_curve": "lift into hooks, reset at bridge",
            },
            "arrangement_advice": {
                "intro": ["tease motif"],
                "verse": ["keep harmonic motion simple"],
                "pre_hook": ["add tension riser"],
                "hook": ["widen melody and drums"],
                "bridge": ["strip drums briefly"],
                "outro": ["resolve motif softly"],
            },
            "mix_priorities": {
                "melody_priority": 0.68,
                "drum_bass_ducking_needed": True,
                "hook_melody_lift_db": 1.8,
                "bass_aggression": 0.62,
            },
            "variation_strategy": [
                {"variation_index": 0, "personality": "clean", "focus": "melodic clarity", "avoid": ["over-fills"]},
                {"variation_index": 1, "personality": "hype", "focus": "rhythmic momentum", "avoid": ["static loops"]},
            ],
            "do_not_do": ["avoid repetitive 4-bar copy-paste"],
        }
