"""
Groove state tracker for the Groove Engine.

Tracks groove decisions across sections so the engine can make deterministic,
context-aware choices about escalation, differentiation, and reset behaviour.

No randomness — state is updated in strict arrangement order.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass
class GrooveState:
    """Mutable state accumulated as sections are processed in order.

    Attributes:
        section_groove_intensities: Maps section_name → groove_intensity.
        section_profiles: Maps section_name → profile_name used.
        hook_intensities: Ordered list of groove_intensity values for each hook.
        verse_intensities: Ordered list of groove_intensity values for each verse.
        bridge_intensity: Groove intensity of the most recent bridge, if any.
        outro_intensity: Groove intensity of the most recent outro, if any.
        occurrence_counts: Maps section_type → number of occurrences seen so far.
    """

    section_groove_intensities: Dict[str, float] = field(default_factory=dict)
    section_profiles: Dict[str, str] = field(default_factory=dict)
    hook_intensities: List[float] = field(default_factory=list)
    verse_intensities: List[float] = field(default_factory=list)
    bridge_intensity: Optional[float] = None
    outro_intensity: Optional[float] = None
    occurrence_counts: Dict[str, int] = field(default_factory=dict)

    # ---------------------------------------------------------------------------
    # Update helpers
    # ---------------------------------------------------------------------------

    def record_section(
        self,
        section_name: str,
        section_type: str,
        profile_name: str,
        groove_intensity: float,
    ) -> None:
        """Record groove decisions for a completed section."""
        self.section_groove_intensities[section_name] = groove_intensity
        self.section_profiles[section_name] = profile_name
        self.occurrence_counts[section_type] = self.occurrence_counts.get(section_type, 0) + 1

        if section_type == "hook":
            self.hook_intensities.append(groove_intensity)
        elif section_type == "verse":
            self.verse_intensities.append(groove_intensity)
        elif section_type in ("bridge", "breakdown"):
            self.bridge_intensity = groove_intensity
        elif section_type == "outro":
            self.outro_intensity = groove_intensity

    def next_occurrence(self, section_type: str) -> int:
        """Return the 1-based occurrence index for the *next* section of *section_type*.

        Does NOT increment the counter — call :meth:`record_section` after building
        the plan to advance state.
        """
        return self.occurrence_counts.get(section_type, 0) + 1

    # ---------------------------------------------------------------------------
    # Query helpers
    # ---------------------------------------------------------------------------

    def max_verse_intensity(self) -> float:
        """Return the maximum groove intensity seen across all verses, or 0.0."""
        return max(self.verse_intensities, default=0.0)

    def max_hook_intensity(self) -> float:
        """Return the maximum groove intensity seen across all hooks, or 0.0."""
        return max(self.hook_intensities, default=0.0)

    def last_hook_intensity(self) -> float:
        """Return the groove intensity of the most recent hook, or 0.0."""
        return self.hook_intensities[-1] if self.hook_intensities else 0.0

    def last_verse_intensity(self) -> float:
        """Return the groove intensity of the most recent verse, or 0.0."""
        return self.verse_intensities[-1] if self.verse_intensities else 0.0

    def hook_escalation_satisfied(self) -> bool:
        """Return True if each hook is at least as intense as the previous one."""
        if len(self.hook_intensities) < 2:
            return True
        for i in range(1, len(self.hook_intensities)):
            if self.hook_intensities[i] < self.hook_intensities[i - 1] - 0.05:
                return False
        return True

    def to_snapshot(self) -> dict:
        """Return a JSON-serialisable snapshot of current state."""
        return {
            "hook_intensities": list(self.hook_intensities),
            "verse_intensities": list(self.verse_intensities),
            "bridge_intensity": self.bridge_intensity,
            "outro_intensity": self.outro_intensity,
            "occurrence_counts": dict(self.occurrence_counts),
            "section_profiles": dict(self.section_profiles),
        }
