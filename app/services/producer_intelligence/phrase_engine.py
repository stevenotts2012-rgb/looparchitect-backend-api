from __future__ import annotations

from typing import Dict, List


def evolve_phrases(sections: List[str]) -> Dict[str, str]:
    phrase_map: Dict[str, str] = {}
    verse_idx = 0
    hook_idx = 0
    for section in sections:
        name = section.lower()
        if "verse" in name:
            verse_idx += 1
            phrase_map[section] = "verse_base" if verse_idx == 1 else "verse_evolved_rhythm+bass_response"
        elif "hook" in name:
            hook_idx += 1
            phrase_map[section] = "hook_reinforced" if hook_idx == 1 else "hook_reinforced+octave_response+drum_evolution"
        elif "bridge" in name:
            phrase_map[section] = "bridge_reset_phrase+melodic_space"
        elif "outro" in name:
            phrase_map[section] = "outro_simplified_phrase"
        else:
            phrase_map[section] = "support_phrase"
    return phrase_map
