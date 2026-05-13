from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass
class GuideCache:
    _store: Dict[Tuple[Any, ...], Dict[str, Any]]

    def __init__(self) -> None:
        self._store = {}

    @staticmethod
    def key_for(inp: Dict[str, Any]) -> Tuple[Any, ...]:
        bpm = float(inp.get("bpm", 120.0))
        bpm_bucket = int(bpm // 5)
        roles = tuple(sorted(inp.get("detected_roles", [])))
        return (inp.get("genre"), inp.get("mood"), inp.get("energy"), bpm_bucket, roles)

    def get(self, inp: Dict[str, Any]) -> Dict[str, Any] | None:
        return self._store.get(self.key_for(inp))

    def set(self, inp: Dict[str, Any], out: Dict[str, Any]) -> None:
        self._store[self.key_for(inp)] = out
