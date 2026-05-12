from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple


@dataclass
class ProducerState:
    used_stem_combinations: Set[Tuple[str, ...]] = field(default_factory=set)
    section_energy_history: List[Tuple[str, float]] = field(default_factory=list)
    transition_history: List[Dict[str, str]] = field(default_factory=list)
    phrase_history: List[Dict[str, str]] = field(default_factory=list)
    hook_intensity_history: List[float] = field(default_factory=list)
    fill_usage_history: List[Dict[str, str]] = field(default_factory=list)
    section_density_history: List[Tuple[str, float]] = field(default_factory=list)
