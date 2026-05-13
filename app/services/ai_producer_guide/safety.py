from __future__ import annotations

from typing import Any, Dict

UNSAFE_PATTERNS = (
    "copy exact song",
    "clone artist melody",
    "reproduce lyrics",
    "imitate a copyrighted recording exactly",
    "sound exactly like",
)


def normalize_style_text(text: str) -> str:
    lowered = text.lower()
    if "-like" in lowered or "like" in lowered:
        return "broad genre traits only: moody melodic, sparse drums, atmospheric pads, restrained transitions"
    return text


def reject_unsafe_guidance(payload: Dict[str, Any]) -> None:
    blob = str(payload).lower()
    for pattern in UNSAFE_PATTERNS:
        if pattern in blob:
            raise ValueError(f"Unsafe guide instruction detected: {pattern}")
