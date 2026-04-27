"""
Generative Producer Layer — app/services/generative_producer_layer.py

Generates new musical behavior from uploaded loops/stems while preserving
the original material.  All generation is:

- Deterministic: same seed → same output; different seed → musically valid
  variation.
- Renderer-facing: every emitted event maps to a supported render action via
  ``SUPPORTED_RENDER_ACTIONS``.  Events that cannot be mapped are logged
  (with a ``skipped_reason``) rather than silently ignored.
- Degradation-safe: works with zero stems available; more stems unlock richer
  behavior.

Section rules implemented (Trap default):
    INTRO     — melody/sample partial; no 808; no full drums.
    VERSE     — basic drum/hat pattern; simple 808 root movement;
                melody reduced/chopped; ear-candy every 4 bars.
    PRE_HOOK  — remove kick or reduce anchor; riser/snare build; simplify 808.
    HOOK      — fullest section; active 808; hat rolls/stutters;
                counter-melody/pad when available; impact FX.
    VERSE_2   — strip back after hook; ≥2 generated behaviors changed vs Verse 1.
    HOOK_2    — same identity as Hook 1 but bigger (extra layer or stronger
                808/hat/FX behavior).
    OUTRO     — remove 808/drums; keep melody/sample tail;
                reverb/reverse/fade behavior.
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Sequence

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Supported render actions registry
# ---------------------------------------------------------------------------
# Every render_action value used in a GenerativeEvent MUST appear here.
# Events whose render_action is absent are rejected and logged.

SUPPORTED_RENDER_ACTIONS: frozenset[str] = frozenset(
    {
        # Drum / percussion
        "trigger_drum_pattern",
        "trigger_hat_roll",
        "trigger_snare_build",
        "mute_kick",
        "mute_drums",
        # Bass / 808
        "trigger_808_root",
        "trigger_808_active",
        "mute_808",
        "simplify_808",
        # Melody / sample
        "play_melody_full",
        "play_melody_reduced",
        "chop_melody",
        "play_counter_melody",
        "play_melody_tail",
        # FX / automation
        "trigger_riser",
        "trigger_impact",
        "trigger_reverb_tail",
        "trigger_reverse_fx",
        "trigger_fade_out",
        "trigger_ear_candy",
        "trigger_filter_automation",
        "trigger_volume_automation",
        # Section-level
        "section_strip",
        "section_full",
    }
)


# ---------------------------------------------------------------------------
# GenerativeEvent — renderer-facing event schema
# ---------------------------------------------------------------------------


@dataclass
class GenerativeEvent:
    """A single audio-actionable event emitted by the Generative Producer Layer.

    Attributes
    ----------
    event_type:
        Logical event category (e.g. ``"drum_pattern"``, ``"808_pattern"``).
    section_name:
        Human-readable section label (e.g. ``"Verse"``, ``"Hook 2"``).
    bar_start:
        Absolute bar where the event begins (0-indexed).
    bar_end:
        Inclusive absolute bar where the event ends.
    target_role:
        Which stem/role this event targets (``"drums"``, ``"bass"``,
        ``"melody"``, ``"percussion"``, ``"fx"``, ``"arp"``).
    intensity:
        Strength of the event [0.0, 1.0].
    parameters:
        Arbitrary key/value bag passed straight through to the renderer.
    render_action:
        The exact renderer action string.  Must exist in
        :data:`SUPPORTED_RENDER_ACTIONS`.
    skipped_reason:
        Non-empty when the event was rejected (unsupported render_action or
        missing stem).  Renderer MUST NOT act on events with a skipped_reason.
    """

    event_type: str
    section_name: str
    bar_start: int
    bar_end: int
    target_role: str
    intensity: float
    parameters: Dict[str, Any] = field(default_factory=dict)
    render_action: str = ""
    skipped_reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# SectionOutput — per-section collection of events
# ---------------------------------------------------------------------------


@dataclass
class SectionOutput:
    """All generated events for a single section.

    Attributes
    ----------
    section_name:
        Label of the section (matches ``GenerativeEvent.section_name``).
    section_type:
        Canonical type key (``"intro"``, ``"verse"``, ``"pre_hook"``,
        ``"hook"``, ``"verse_2"``, ``"hook_2"``, ``"outro"``).
    bar_start:
        Absolute bar index where the section begins.
    bars:
        Total bar count for this section.
    generated_drum_pattern_events:    Kick/snare pattern events.
    generated_808_pattern_events:     808/bass movement events.
    generated_hat_roll_events:        Hi-hat roll/stutter events.
    melody_chop_events:               Melodic chop/reduce events.
    counter_melody_events:            Counter-melody/pad events.
    fx_transition_events:             FX (risers, impacts, reverb …) events.
    automation_events:                Volume/filter automation events.
    """

    section_name: str
    section_type: str
    bar_start: int
    bars: int
    generated_drum_pattern_events: List[GenerativeEvent] = field(default_factory=list)
    generated_808_pattern_events: List[GenerativeEvent] = field(default_factory=list)
    generated_hat_roll_events: List[GenerativeEvent] = field(default_factory=list)
    melody_chop_events: List[GenerativeEvent] = field(default_factory=list)
    counter_melody_events: List[GenerativeEvent] = field(default_factory=list)
    fx_transition_events: List[GenerativeEvent] = field(default_factory=list)
    automation_events: List[GenerativeEvent] = field(default_factory=list)

    # ------------------------------------------------------------------ #
    # Convenience helpers                                                   #
    # ------------------------------------------------------------------ #

    @property
    def all_events(self) -> List[GenerativeEvent]:
        """Flat list of all events across all event-type buckets."""
        return (
            self.generated_drum_pattern_events
            + self.generated_808_pattern_events
            + self.generated_hat_roll_events
            + self.melody_chop_events
            + self.counter_melody_events
            + self.fx_transition_events
            + self.automation_events
        )

    @property
    def active_events(self) -> List[GenerativeEvent]:
        """Subset of :meth:`all_events` that were not skipped."""
        return [e for e in self.all_events if not e.skipped_reason]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "section_name": self.section_name,
            "section_type": self.section_type,
            "bar_start": self.bar_start,
            "bars": self.bars,
            "generated_drum_pattern_events": [e.to_dict() for e in self.generated_drum_pattern_events],
            "generated_808_pattern_events": [e.to_dict() for e in self.generated_808_pattern_events],
            "generated_hat_roll_events": [e.to_dict() for e in self.generated_hat_roll_events],
            "melody_chop_events": [e.to_dict() for e in self.melody_chop_events],
            "counter_melody_events": [e.to_dict() for e in self.counter_melody_events],
            "fx_transition_events": [e.to_dict() for e in self.fx_transition_events],
            "automation_events": [e.to_dict() for e in self.automation_events],
        }


# ---------------------------------------------------------------------------
# GenerativeProducerLayer — main class
# ---------------------------------------------------------------------------


class GenerativeProducerLayer:
    """Generates audio-actionable events for each section of an arrangement.

    Parameters
    ----------
    loop_analysis:
        Dict from the loop analyzer: ``bpm``, ``key``, ``duration_seconds``,
        ``sample_rate``, ``channels``, and any stem metadata.
    genre:
        Genre hint for rule selection (default ``"trap"``).
    vibe:
        Vibe/mood hint (e.g. ``"dark"``, ``"hype"``).
    instrument_rules:
        Optional pre-resolved instrument activation rules (from
        :class:`~app.services.instrument_activation_rules.InstrumentActivationRules`).
        When ``None`` the layer uses its own built-in defaults.
    vibe_modifier_rules:
        Optional pre-resolved vibe modifier rules.
    variation_seed:
        Integer seed driving all probabilistic decisions.  Same seed → same
        output for the same inputs.
    available_roles:
        Stem roles actually present in the uploaded material.  When a role
        is absent the corresponding event-type is skipped (not silently
        dropped — a ``skipped_reason`` is recorded).
    arrangement_plan:
        Optional resolved arrangement plan (list of section dicts).  When
        supplied the generator reads ``bar_start``, ``bars``, and
        ``section_type`` from it; otherwise these are inferred from the
        ``sections`` argument passed to :meth:`generate`.
    """

    def __init__(
        self,
        loop_analysis: Dict[str, Any],
        genre: str = "trap",
        vibe: str = "",
        instrument_rules: Optional[Dict[str, Any]] = None,
        vibe_modifier_rules: Optional[Dict[str, Any]] = None,
        variation_seed: int = 42,
        available_roles: Optional[Sequence[str]] = None,
        arrangement_plan: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        self.loop_analysis = dict(loop_analysis or {})
        self.genre = str(genre or "trap").lower().strip()
        self.vibe = str(vibe or "").lower().strip()
        self.instrument_rules = instrument_rules or {}
        self.vibe_modifier_rules = vibe_modifier_rules or {}
        self.variation_seed = int(variation_seed)
        self.available_roles: frozenset[str] = (
            frozenset(_DEFAULT_ROLES) if available_roles is None
            else frozenset(available_roles)
        )
        self.arrangement_plan = arrangement_plan or []

        # Master RNG — every section gets its own derived sub-seed so that
        # section order changes do not affect individual section outputs.
        self._master_rng = random.Random(self.variation_seed)

    # ---------------------------------------------------------------------- #
    # Main entry point                                                         #
    # ---------------------------------------------------------------------- #

    def generate(
        self,
        sections: Optional[List[Dict[str, Any]]] = None,
    ) -> List[SectionOutput]:
        """Generate events for all sections in the arrangement.

        Parameters
        ----------
        sections:
            Optional explicit list of section dicts, each with at minimum:
            ``section_type`` (or ``name``), ``bar_start``, and ``bars``.
            When omitted the :attr:`arrangement_plan` supplied at construction
            is used.  When both are empty a default Trap arrangement is used.

        Returns
        -------
        List[SectionOutput]
            One :class:`SectionOutput` per section, in arrangement order.
        """
        plan = sections or self.arrangement_plan or _DEFAULT_TRAP_PLAN
        outputs: List[SectionOutput] = []

        verse_output: Optional[SectionOutput] = None
        hook_output: Optional[SectionOutput] = None

        for idx, section_dict in enumerate(plan):
            section_type = _normalise_section_type(
                str(section_dict.get("section_type") or section_dict.get("name") or "verse")
            )
            label = str(section_dict.get("section_name") or section_dict.get("label") or _default_label(section_type, idx))
            bar_start = int(section_dict.get("bar_start") or 0)
            bars = int(section_dict.get("bars") or 8)

            # Sub-seed: deterministic per (seed, position)
            sub_seed = self.variation_seed ^ (idx * 0x9E3779B9 & 0xFFFFFFFF)

            output = self._generate_section(
                section_type=section_type,
                section_name=label,
                bar_start=bar_start,
                bars=bars,
                sub_seed=sub_seed,
                verse_1_output=verse_output,
                hook_1_output=hook_output,
            )
            outputs.append(output)

            # Track first verse/hook for verse_2/hook_2 differentiation.
            if section_type == "verse" and verse_output is None:
                verse_output = output
            if section_type == "hook" and hook_output is None:
                hook_output = output

        return outputs

    # ---------------------------------------------------------------------- #
    # Per-section generators                                                   #
    # ---------------------------------------------------------------------- #

    def _generate_section(
        self,
        section_type: str,
        section_name: str,
        bar_start: int,
        bars: int,
        sub_seed: int,
        verse_1_output: Optional[SectionOutput],
        hook_1_output: Optional[SectionOutput],
    ) -> SectionOutput:
        """Dispatch to the correct section generator."""
        generators = {
            "intro":    self._gen_intro,
            "verse":    self._gen_verse,
            "pre_hook": self._gen_pre_hook,
            "hook":     self._gen_hook,
            "verse_2":  lambda sn, bs, br, ss: self._gen_verse_2(sn, bs, br, ss, verse_1_output),
            "hook_2":   lambda sn, bs, br, ss: self._gen_hook_2(sn, bs, br, ss, hook_1_output),
            "outro":    self._gen_outro,
            "bridge":   self._gen_bridge,
        }
        gen_fn = generators.get(section_type, self._gen_verse)
        return gen_fn(section_name, bar_start, bars, sub_seed)

    # ------------------------------------------------------------------ #
    # INTRO                                                                 #
    # ------------------------------------------------------------------ #

    def _gen_intro(
        self, section_name: str, bar_start: int, bars: int, seed: int
    ) -> SectionOutput:
        """Rule: melody/sample partial; NO 808; NO full drums."""
        rng = random.Random(seed)
        out = SectionOutput(
            section_name=section_name,
            section_type="intro",
            bar_start=bar_start,
            bars=bars,
        )

        # Melody — partial / sparse
        if "melody" in self.available_roles:
            out.melody_chop_events.append(
                self._make_event(
                    event_type="melody_chop",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="melody",
                    intensity=_jitter(0.35, 0.10, rng),
                    render_action="play_melody_reduced",
                    parameters={"pattern": "sparse", "intro": True},
                )
            )

        # FX texture
        out.fx_transition_events.append(
            self._make_event(
                event_type="fx_texture",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="fx",
                intensity=_jitter(0.30, 0.08, rng),
                render_action="trigger_filter_automation",
                parameters={"filter": "low_pass", "sweep_up": True},
            )
        )

        # Automation: fade in
        out.automation_events.append(
            self._make_event(
                event_type="volume_automation",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="melody",
                intensity=0.5,
                render_action="trigger_volume_automation",
                parameters={"direction": "fade_in", "curve": "linear"},
            )
        )

        # 808 / drums MUST be absent — emit skipped events so caller can verify
        for role, reason in (("bass", "intro_no_808"), ("drums", "intro_no_drums")):
            out.generated_808_pattern_events.append(
                self._make_skipped_event(
                    event_type="808_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role=role,
                    render_action="trigger_808_root",
                    skipped_reason=reason,
                )
            ) if role == "bass" else out.generated_drum_pattern_events.append(
                self._make_skipped_event(
                    event_type="drum_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role=role,
                    render_action="trigger_drum_pattern",
                    skipped_reason=reason,
                )
            )

        return out

    # ------------------------------------------------------------------ #
    # VERSE                                                                 #
    # ------------------------------------------------------------------ #

    def _gen_verse(
        self,
        section_name: str,
        bar_start: int,
        bars: int,
        seed: int,
    ) -> SectionOutput:
        """Rule: basic drum/hat; simple 808 root; melody reduced; ear candy /4."""
        rng = random.Random(seed)
        out = SectionOutput(
            section_name=section_name,
            section_type="verse",
            bar_start=bar_start,
            bars=bars,
        )

        # Drums
        if "drums" in self.available_roles:
            out.generated_drum_pattern_events.append(
                self._make_event(
                    event_type="drum_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="drums",
                    intensity=_jitter(0.55, 0.08, rng),
                    render_action="trigger_drum_pattern",
                    parameters={"pattern": "straight", "complexity": "basic"},
                )
            )
        else:
            out.generated_drum_pattern_events.append(
                self._make_skipped_event(
                    event_type="drum_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="drums",
                    render_action="trigger_drum_pattern",
                    skipped_reason="role_unavailable:drums",
                )
            )

        # Hi-hat
        if "percussion" in self.available_roles:
            out.generated_hat_roll_events.append(
                self._make_event(
                    event_type="hat_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="percussion",
                    intensity=_jitter(0.50, 0.08, rng),
                    render_action="trigger_hat_roll",
                    parameters={"roll": False, "density": "medium"},
                )
            )

        # 808 — simple root movement
        if "bass" in self.available_roles:
            out.generated_808_pattern_events.append(
                self._make_event(
                    event_type="808_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="bass",
                    intensity=_jitter(0.60, 0.10, rng),
                    render_action="trigger_808_root",
                    parameters={"movement": "root_only", "slides": False},
                )
            )

        # Melody — reduced / chopped
        if "melody" in self.available_roles:
            out.melody_chop_events.append(
                self._make_event(
                    event_type="melody_chop",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="melody",
                    intensity=_jitter(0.55, 0.08, rng),
                    render_action="play_melody_reduced",
                    parameters={"chop": True, "density": "medium"},
                )
            )

        # Ear candy every 4 bars
        for ec_bar in range(bar_start + 4, bar_start + bars, 4):
            out.fx_transition_events.append(
                self._make_event(
                    event_type="ear_candy",
                    section_name=section_name,
                    bar_start=ec_bar,
                    bar_end=ec_bar,
                    target_role="fx",
                    intensity=_jitter(0.35, 0.08, rng),
                    render_action="trigger_ear_candy",
                    parameters={"type": rng.choice(["riser_short", "reverse_stab", "hit"])},
                )
            )

        return out

    # ------------------------------------------------------------------ #
    # PRE_HOOK                                                              #
    # ------------------------------------------------------------------ #

    def _gen_pre_hook(
        self,
        section_name: str,
        bar_start: int,
        bars: int,
        seed: int,
    ) -> SectionOutput:
        """Rule: mute/reduce kick; riser/snare build; simplified 808."""
        rng = random.Random(seed)
        out = SectionOutput(
            section_name=section_name,
            section_type="pre_hook",
            bar_start=bar_start,
            bars=bars,
        )

        # Drums — mute kick / reduce anchor
        out.generated_drum_pattern_events.append(
            self._make_event(
                event_type="drum_mute_kick",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="drums",
                intensity=_jitter(0.70, 0.08, rng),
                render_action="mute_kick",
                parameters={"reason": "pre_hook_build"},
            )
        )

        # Snare build
        out.generated_drum_pattern_events.append(
            self._make_event(
                event_type="snare_build",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="percussion",
                intensity=_jitter(0.75, 0.08, rng),
                render_action="trigger_snare_build",
                parameters={"escalate": True},
            )
        )

        # Riser FX
        out.fx_transition_events.append(
            self._make_event(
                event_type="riser",
                section_name=section_name,
                bar_start=bar_start + max(0, bars - 4),
                bar_end=bar_start + bars - 1,
                target_role="fx",
                intensity=_jitter(0.80, 0.08, rng),
                render_action="trigger_riser",
                parameters={"duration_bars": min(4, bars)},
            )
        )

        # 808 — simplified
        if "bass" in self.available_roles:
            out.generated_808_pattern_events.append(
                self._make_event(
                    event_type="808_simplified",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="bass",
                    intensity=_jitter(0.50, 0.10, rng),
                    render_action="simplify_808",
                    parameters={"movement": "root_hold", "slides": False},
                )
            )

        return out

    # ------------------------------------------------------------------ #
    # HOOK                                                                  #
    # ------------------------------------------------------------------ #

    def _gen_hook(
        self,
        section_name: str,
        bar_start: int,
        bars: int,
        seed: int,
    ) -> SectionOutput:
        """Rule: fullest section; active 808; hat rolls; counter melody; impact FX."""
        rng = random.Random(seed)
        out = SectionOutput(
            section_name=section_name,
            section_type="hook",
            bar_start=bar_start,
            bars=bars,
        )

        # Full drums
        if "drums" in self.available_roles:
            out.generated_drum_pattern_events.append(
                self._make_event(
                    event_type="drum_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="drums",
                    intensity=_jitter(0.95, 0.05, rng),
                    render_action="trigger_drum_pattern",
                    parameters={"pattern": "full_groove", "complexity": "high"},
                )
            )

        # Hat rolls / stutters
        if "percussion" in self.available_roles:
            roll_bars = max(1, bars // 4)
            for i in range(0, bars, roll_bars):
                out.generated_hat_roll_events.append(
                    self._make_event(
                        event_type="hat_roll",
                        section_name=section_name,
                        bar_start=bar_start + i,
                        bar_end=bar_start + i + roll_bars - 1,
                        target_role="percussion",
                        intensity=_jitter(0.80, 0.08, rng),
                        render_action="trigger_hat_roll",
                        parameters={"roll": True, "stutter": rng.random() > 0.5},
                    )
                )

        # Active 808
        if "bass" in self.available_roles:
            out.generated_808_pattern_events.append(
                self._make_event(
                    event_type="808_active",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="bass",
                    intensity=_jitter(0.90, 0.05, rng),
                    render_action="trigger_808_active",
                    parameters={"movement": "melodic", "slides": True},
                )
            )

        # Full melody
        if "melody" in self.available_roles:
            out.melody_chop_events.append(
                self._make_event(
                    event_type="melody_full",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="melody",
                    intensity=_jitter(0.90, 0.05, rng),
                    render_action="play_melody_full",
                    parameters={"density": "full"},
                )
            )

        # Counter melody / pad when arp available
        if "arp" in self.available_roles:
            out.counter_melody_events.append(
                self._make_event(
                    event_type="counter_melody",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="arp",
                    intensity=_jitter(0.70, 0.08, rng),
                    render_action="play_counter_melody",
                    parameters={"voice": "pad"},
                )
            )

        # Impact FX at section start
        out.fx_transition_events.append(
            self._make_event(
                event_type="impact",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start,
                target_role="fx",
                intensity=_jitter(0.90, 0.05, rng),
                render_action="trigger_impact",
                parameters={"placement": "section_start"},
            )
        )

        # Filter automation — opens up on hook
        out.automation_events.append(
            self._make_event(
                event_type="filter_automation",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="melody",
                intensity=_jitter(0.80, 0.08, rng),
                render_action="trigger_filter_automation",
                parameters={"filter": "high_pass", "direction": "open"},
            )
        )

        return out

    # ------------------------------------------------------------------ #
    # VERSE 2                                                               #
    # ------------------------------------------------------------------ #

    def _gen_verse_2(
        self,
        section_name: str,
        bar_start: int,
        bars: int,
        seed: int,
        verse_1_output: Optional[SectionOutput],
    ) -> SectionOutput:
        """Rule: strip back post-hook; ≥2 behaviours differ from Verse 1."""
        rng = random.Random(seed)

        # Start from a verse template
        base = self._gen_verse(section_name, bar_start, bars, seed)
        base.section_type = "verse_2"

        # Differentiation 1: chop melody more aggressively
        for ev in base.melody_chop_events:
            ev.render_action = "chop_melody"
            ev.parameters["chop_rate"] = "16th"
            ev.parameters["density"] = "sparse"
            ev.intensity = max(0.0, ev.intensity - 0.15)

        # Differentiation 2: 808 rhythm offset / sparse movement
        for ev in base.generated_808_pattern_events:
            ev.parameters["movement"] = "sparse_root"
            ev.parameters["offset_beats"] = rng.choice([1, 2])
            ev.intensity = max(0.0, ev.intensity - 0.10)

        # Differentiation 3 (optional, depends on seed): mute hat rolls
        if rng.random() > 0.40:
            for ev in base.generated_hat_roll_events:
                ev.parameters["density"] = "sparse"
                ev.intensity = max(0.0, ev.intensity - 0.15)

        # Differentiation 4: add a reverse FX at the end of the section
        base.fx_transition_events.append(
            self._make_event(
                event_type="reverse_fx",
                section_name=section_name,
                bar_start=bar_start + max(0, bars - 2),
                bar_end=bar_start + bars - 1,
                target_role="fx",
                intensity=_jitter(0.55, 0.08, rng),
                render_action="trigger_reverse_fx",
                parameters={"placement": "verse_2_exit"},
            )
        )

        return base

    # ------------------------------------------------------------------ #
    # HOOK 2                                                                #
    # ------------------------------------------------------------------ #

    def _gen_hook_2(
        self,
        section_name: str,
        bar_start: int,
        bars: int,
        seed: int,
        hook_1_output: Optional[SectionOutput],
    ) -> SectionOutput:
        """Rule: same identity as Hook 1 but bigger (extra layer / stronger behavior)."""
        rng = random.Random(seed)

        # Start from Hook template
        base = self._gen_hook(section_name, bar_start, bars, seed)
        base.section_type = "hook_2"

        # Make 808 more aggressive
        for ev in base.generated_808_pattern_events:
            ev.intensity = min(1.0, ev.intensity + 0.05)
            ev.parameters["movement"] = "aggressive_melodic"
            ev.parameters["slides"] = True

        # Add an extra layer: counter melody overlay using melody role as a secondary voice
        if not base.counter_melody_events:
            base.counter_melody_events.append(
                self._make_event(
                    event_type="counter_melody_hook2",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="melody",
                    intensity=_jitter(0.65, 0.08, rng),
                    render_action="play_counter_melody",
                    parameters={"voice": "lead_layer", "hook_2_extra": True},
                )
            )

        # Extra impact at the midpoint of hook 2
        mid_bar = bar_start + bars // 2
        base.fx_transition_events.append(
            self._make_event(
                event_type="impact_mid",
                section_name=section_name,
                bar_start=mid_bar,
                bar_end=mid_bar,
                target_role="fx",
                intensity=_jitter(0.85, 0.05, rng),
                render_action="trigger_impact",
                parameters={"placement": "hook_2_mid"},
            )
        )

        # Boost hat roll intensity
        for ev in base.generated_hat_roll_events:
            ev.intensity = min(1.0, ev.intensity + 0.10)

        return base

    # ------------------------------------------------------------------ #
    # OUTRO                                                                 #
    # ------------------------------------------------------------------ #

    def _gen_outro(
        self,
        section_name: str,
        bar_start: int,
        bars: int,
        seed: int,
    ) -> SectionOutput:
        """Rule: remove 808/drums; keep melody tail; reverb/reverse/fade."""
        rng = random.Random(seed)
        out = SectionOutput(
            section_name=section_name,
            section_type="outro",
            bar_start=bar_start,
            bars=bars,
        )

        # 808 and drums MUST be absent
        for role, event_list, action, skip_reason in (
            ("bass", out.generated_808_pattern_events, "mute_808", "outro_no_808"),
            ("drums", out.generated_drum_pattern_events, "mute_drums", "outro_no_drums"),
        ):
            event_list.append(
                self._make_skipped_event(
                    event_type=f"{role}_pattern",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role=role,
                    render_action=action,
                    skipped_reason=skip_reason,
                )
            )

        # Melody tail
        if "melody" in self.available_roles:
            out.melody_chop_events.append(
                self._make_event(
                    event_type="melody_tail",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="melody",
                    intensity=_jitter(0.40, 0.08, rng),
                    render_action="play_melody_tail",
                    parameters={"tail": True, "sparse": True},
                )
            )

        # Reverb tail
        out.fx_transition_events.append(
            self._make_event(
                event_type="reverb_tail",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="fx",
                intensity=_jitter(0.70, 0.08, rng),
                render_action="trigger_reverb_tail",
                parameters={"decay": "long"},
            )
        )

        # Reverse FX at start
        out.fx_transition_events.append(
            self._make_event(
                event_type="reverse_fx",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + 1,
                target_role="fx",
                intensity=_jitter(0.50, 0.08, rng),
                render_action="trigger_reverse_fx",
                parameters={"placement": "outro_open"},
            )
        )

        # Fade out automation
        out.automation_events.append(
            self._make_event(
                event_type="volume_automation",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="melody",
                intensity=0.8,
                render_action="trigger_fade_out",
                parameters={"duration_bars": bars, "curve": "exponential"},
            )
        )

        return out

    # ------------------------------------------------------------------ #
    # BRIDGE (bonus — graceful fallback for unexpected section types)       #
    # ------------------------------------------------------------------ #

    def _gen_bridge(
        self,
        section_name: str,
        bar_start: int,
        bars: int,
        seed: int,
    ) -> SectionOutput:
        """Bridge: reduced energy, minimal drums, melodic focus."""
        rng = random.Random(seed)
        out = SectionOutput(
            section_name=section_name,
            section_type="bridge",
            bar_start=bar_start,
            bars=bars,
        )

        if "melody" in self.available_roles:
            out.melody_chop_events.append(
                self._make_event(
                    event_type="melody_chop",
                    section_name=section_name,
                    bar_start=bar_start,
                    bar_end=bar_start + bars - 1,
                    target_role="melody",
                    intensity=_jitter(0.50, 0.10, rng),
                    render_action="play_melody_reduced",
                    parameters={"pattern": "contrast"},
                )
            )

        out.fx_transition_events.append(
            self._make_event(
                event_type="filter_automation",
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_start + bars - 1,
                target_role="fx",
                intensity=_jitter(0.45, 0.08, rng),
                render_action="trigger_filter_automation",
                parameters={"filter": "low_pass", "direction": "close"},
            )
        )

        return out

    # ---------------------------------------------------------------------- #
    # Event factory helpers                                                    #
    # ---------------------------------------------------------------------- #

    def _make_event(
        self,
        *,
        event_type: str,
        section_name: str,
        bar_start: int,
        bar_end: int,
        target_role: str,
        intensity: float,
        render_action: str,
        parameters: Optional[Dict[str, Any]] = None,
    ) -> GenerativeEvent:
        """Create a :class:`GenerativeEvent`, validating render_action."""
        if render_action not in SUPPORTED_RENDER_ACTIONS:
            logger.warning(
                "generative_producer_layer: unsupported render_action=%r "
                "for event_type=%r section=%r — event will be skipped",
                render_action,
                event_type,
                section_name,
            )
            return GenerativeEvent(
                event_type=event_type,
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_end,
                target_role=target_role,
                intensity=float(intensity),
                parameters=parameters or {},
                render_action=render_action,
                skipped_reason=f"unsupported_render_action:{render_action}",
            )

        # Role availability check
        if target_role not in self.available_roles and target_role not in _META_ROLES:
            logger.debug(
                "generative_producer_layer: target_role=%r not in available_roles "
                "for event_type=%r section=%r — event skipped",
                target_role,
                event_type,
                section_name,
            )
            return GenerativeEvent(
                event_type=event_type,
                section_name=section_name,
                bar_start=bar_start,
                bar_end=bar_end,
                target_role=target_role,
                intensity=float(intensity),
                parameters=parameters or {},
                render_action=render_action,
                skipped_reason=f"role_unavailable:{target_role}",
            )

        return GenerativeEvent(
            event_type=event_type,
            section_name=section_name,
            bar_start=bar_start,
            bar_end=bar_end,
            target_role=target_role,
            intensity=float(intensity),
            parameters=parameters or {},
            render_action=render_action,
            skipped_reason="",
        )

    @staticmethod
    def _make_skipped_event(
        *,
        event_type: str,
        section_name: str,
        bar_start: int,
        bar_end: int,
        target_role: str,
        render_action: str,
        skipped_reason: str,
    ) -> GenerativeEvent:
        """Create an explicitly-skipped (no-op) event."""
        return GenerativeEvent(
            event_type=event_type,
            section_name=section_name,
            bar_start=bar_start,
            bar_end=bar_end,
            target_role=target_role,
            intensity=0.0,
            parameters={},
            render_action=render_action,
            skipped_reason=skipped_reason,
        )


# ---------------------------------------------------------------------------
# Module-level singleton factory
# ---------------------------------------------------------------------------


def create_generative_producer_layer(
    loop_analysis: Dict[str, Any],
    genre: str = "trap",
    vibe: str = "",
    variation_seed: int = 42,
    available_roles: Optional[Sequence[str]] = None,
    arrangement_plan: Optional[List[Dict[str, Any]]] = None,
    instrument_rules: Optional[Dict[str, Any]] = None,
    vibe_modifier_rules: Optional[Dict[str, Any]] = None,
) -> GenerativeProducerLayer:
    """Convenience factory for :class:`GenerativeProducerLayer`."""
    return GenerativeProducerLayer(
        loop_analysis=loop_analysis,
        genre=genre,
        vibe=vibe,
        variation_seed=variation_seed,
        available_roles=available_roles,
        arrangement_plan=arrangement_plan,
        instrument_rules=instrument_rules,
        vibe_modifier_rules=vibe_modifier_rules,
    )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

# Roles that are always considered "available" (no physical stem needed)
_META_ROLES: frozenset[str] = frozenset({"fx"})

# Default roles assumed when no stem analysis is available
_DEFAULT_ROLES: frozenset[str] = frozenset(
    {"drums", "bass", "melody", "percussion", "fx"}
)

# Default Trap arrangement plan used when no plan is provided
_DEFAULT_TRAP_PLAN: List[Dict[str, Any]] = [
    {"section_type": "intro",    "section_name": "Intro",    "bar_start": 0,   "bars": 8},
    {"section_type": "verse",    "section_name": "Verse",    "bar_start": 8,   "bars": 16},
    {"section_type": "pre_hook", "section_name": "Pre-Hook", "bar_start": 24,  "bars": 8},
    {"section_type": "hook",     "section_name": "Hook",     "bar_start": 32,  "bars": 16},
    {"section_type": "verse_2",  "section_name": "Verse 2",  "bar_start": 48,  "bars": 16},
    {"section_type": "hook_2",   "section_name": "Hook 2",   "bar_start": 64,  "bars": 16},
    {"section_type": "outro",    "section_name": "Outro",    "bar_start": 80,  "bars": 8},
]


def _normalise_section_type(raw: str) -> str:
    """Map raw section type/name strings to canonical keys."""
    mapping: Dict[str, str] = {
        "intro":        "intro",
        "verse":        "verse",
        "verse 1":      "verse",
        "verse1":       "verse",
        "verse_1":      "verse",
        "verse 2":      "verse_2",
        "verse2":       "verse_2",
        "verse_2":      "verse_2",
        "pre_hook":     "pre_hook",
        "pre hook":     "pre_hook",
        "prehook":      "pre_hook",
        "pre_chorus":   "pre_hook",
        "pre chorus":   "pre_hook",
        "chorus":       "hook",
        "hook":         "hook",
        "hook 1":       "hook",
        "hook1":        "hook",
        "hook_1":       "hook",
        "hook 2":       "hook_2",
        "hook2":        "hook_2",
        "hook_2":       "hook_2",
        "bridge":       "bridge",
        "breakdown":    "bridge",
        "outro":        "outro",
    }
    clean = raw.lower().strip()
    return mapping.get(clean, clean)


def _default_label(section_type: str, idx: int) -> str:
    """Generate a human-readable label for a section."""
    names = {
        "intro":    "Intro",
        "verse":    "Verse",
        "verse_2":  "Verse 2",
        "pre_hook": "Pre-Hook",
        "hook":     "Hook",
        "hook_2":   "Hook 2",
        "bridge":   "Bridge",
        "outro":    "Outro",
    }
    return names.get(section_type, f"Section {idx + 1}")


def _jitter(base: float, delta: float, rng: random.Random) -> float:
    """Return base ± delta, clamped to [0, 1], deterministic via rng."""
    return round(max(0.0, min(1.0, base + rng.uniform(-delta, delta))), 4)
