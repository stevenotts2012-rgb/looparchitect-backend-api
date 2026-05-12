from __future__ import annotations

from typing import Dict, List


def evolve_phrases(sections: List[str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    seen_verse = 0
    for s in sections:
        l = s.lower()
        if "verse" in l:
            seen_verse += 1
            out[s] = "base_verse" if seen_verse == 1 else "verse_evolved_rhythm"
        elif "hook" in l:
            out[s] = "hook_reinforced"
        elif "bridge" in l:
            out[s] = "bridge_reset_phrase"
        elif "outro" in l:
            out[s] = "outro_simplified_phrase"
        else:
            out[s] = "support_phrase"
    return out
