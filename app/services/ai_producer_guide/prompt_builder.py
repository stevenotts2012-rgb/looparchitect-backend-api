from __future__ import annotations

import json
from typing import Any, Dict

from .safety import normalize_style_text


def build_prompt(guide_input: Dict[str, Any]) -> str:
    safe_genre = normalize_style_text(guide_input.get("genre", "generic"))
    payload = dict(guide_input)
    payload["genre"] = safe_genre
    return (
        "You are an AI music production advisor. Return strict JSON only. "
        "No song copying, no melody cloning, no lyric reproduction, no artist recording imitation.\n"
        f"INPUT={json.dumps(payload, ensure_ascii=False)}"
    )
