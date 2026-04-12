"""LLM-powered style parser for natural language input (Style Engine V2)."""

import asyncio
import json
import logging
import random
from typing import Optional, List

from app.config import settings
from app.schemas.style_profile import StyleIntent, StyleOverrides, StyleProfile
from app.style_engine.presets import PRESETS
from app.style_engine.types import StylePresetName, StyleParameters

logger = logging.getLogger(__name__)


# Archetype mapping: Maps LLM-identified archetypes to base presets with attribute overrides
ARCHETYPE_MAP = {
    # ATL Variants
    "atl": ("atl", {}),
    "atl_aggressive": ("atl", {"aggression": 0.20, "drum_density": 0.10}),
    "atl_melodic": ("melodic", {"melody_complexity": 0.15, "aggression": -0.10}),
    "atl_bouncy": ("atl", {"bounce": 0.15, "swing": 0.05}),

    # Dark Variants
    "dark": ("dark", {}),
    "dark_drill": ("drill", {"aggression": 0.15, "darkness": 0.10}),
    "dark_cinematic": ("cinematic", {"darkness": 0.20, "fx_intensity": 0.15}),
    "dark_trap": ("dark", {"bass_presence": 0.15}),

    # Melodic Variants
    "melodic": ("melodic", {}),
    "melodic_trap": ("melodic", {"glide_probability": 0.10}),
    "melodic_drill": ("drill", {"melody_complexity": 0.20, "aggression": -0.10}),
    "melodic_ambient": ("cinematic", {"melody_complexity": 0.25, "fx_intensity": 0.20}),

    # Drill Variants
    "drill": ("drill", {}),
    "drill_aggressive": ("drill", {"aggression": 0.15, "hat_roll_probability": 0.10}),
    "drill_uk": ("drill", {"bounce": 0.20, "tempo_multiplier": 0.05}),
    "drill_melodic": ("drill", {"melody_complexity": 0.15}),

    # Cinematic Variants
    "cinematic": ("cinematic", {}),
    "cinematic_dark": ("cinematic", {"darkness": 0.20, "bass_presence": 0.15}),
    "cinematic_epic": ("cinematic", {"energy_variance": 0.25, "transition_intensity": 0.20}),

    # Club Variants
    "club": ("club", {}),
    "club_bounce": ("club", {"bounce": 0.20, "swing": 0.10}),
    "club_aggressive": ("club", {"aggression": 0.15, "drum_density": 0.10}),

    # Experimental
    "experimental": ("experimental", {}),
    "experimental_chaotic": ("experimental", {"transition_intensity": 0.25, "fx_density": 0.20}),
}

# Producer/artist to archetype mapping (for LLM to recognize)
PRODUCER_ARCHETYPES = {
    "southside": "atl_aggressive",
    "808 mafia": "atl_aggressive",
    "metro boomin": "dark_drill",
    "metro": "dark_drill",
    "lil baby": "melodic_trap",
    "gunna": "melodic_trap",
    "pierre bourne": "melodic_trap",
    "pierre": "melodic_trap",
    "wheezy": "atl_melodic",
    "tay keith": "dark_drill",
    "london on da track": "melodic_trap",
    "southside type": "atl_aggressive",
    "metro type": "dark_drill",
    "bouncy": "club_bounce",
    "bounce": "club_bounce",
    "smooth": "melodic",
    "aggressive": "atl_aggressive",
    "dark": "dark",
    "cinematic": "cinematic",
    "experimental": "experimental",
}


class LLMStyleParser:
    """Parse natural language style descriptions using OpenAI API."""

    def __init__(self):
        """Initialize LLM parser with OpenAI configuration."""
        self.api_key = settings.openai_api_key
        self.base_url = settings.openai_base_url
        self.model = settings.openai_model
        self.timeout = settings.openai_timeout
        self.max_retries = settings.openai_max_retries

        if self.api_key:
            try:
                from openai import OpenAI

                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url if self.base_url != "https://api.openai.com/v1" else None,
                )
            except ImportError:
                logger.error("OpenAI library not installed. Install with: pip install openai")
                self.client = None
        else:
            self.client = None

    async def parse_style_intent(
        self,
        user_input: str,
        loop_metadata: dict,
        overrides: Optional[StyleOverrides] = None,
    ) -> StyleProfile:
        """
        Parse user's natural language style input into structured StyleProfile.

        Args:
            user_input: User's style description (e.g., "Southside type, aggressive")
            loop_metadata: Loop info {bpm, key, duration, bars}
            overrides: Optional manual slider overrides

        Returns:
            StyleProfile with resolved preset, params, and sections
        """
        if not self.client:
            logger.warning("LLM client not configured. Falling back to rule-based parser.")
            return self._fallback_parse(user_input, loop_metadata, overrides)

        try:
            # Call LLM to parse intent
            intent = await self._call_llm_for_intent(user_input, loop_metadata)

            # Map archetype to preset
            base_preset_name = self._map_archetype_to_preset(intent.archetype)
            base_preset = PRESETS.get(base_preset_name)
            if not base_preset:
                logger.warning(f"Preset {base_preset_name} not found, using ATL")
                base_preset = PRESETS[StylePresetName.ATL]

            # Apply attribute modifiers and overrides
            resolved_params = self._apply_attribute_modifiers(
                base_preset.defaults,
                intent.attributes,
                overrides,
            )

            # Generate sections with transitions
            sections = self._generate_sections_with_transitions(
                target_seconds=int(loop_metadata.get("duration", 180)),
                bpm=float(loop_metadata.get("bpm", 120.0)),
                loop_bars=int(loop_metadata.get("bars", 4)),
                transitions=intent.transitions,
                base_template=base_preset.section_templates,
            )

            # Create seed for determinism
            seed = random.randint(1, 2**31 - 1)

            # Build StyleProfile
            profile = StyleProfile(
                intent=intent,
                overrides=overrides,
                resolved_preset=base_preset_name.value,
                resolved_params=self._params_to_dict(resolved_params),
                sections=sections,
                seed=seed,
            )

            logger.info(
                f"Successfully parsed style intent: {intent.archetype} "
                f"(confidence: {intent.confidence:.2f})"
            )
            return profile

        except Exception as e:
            logger.exception(f"LLM parsing failed: {e}")
            logger.info("Falling back to rule-based parser")
            return self._fallback_parse(user_input, loop_metadata, overrides)

    async def _call_llm_for_intent(
        self,
        user_input: str,
        loop_metadata: dict,
    ) -> StyleIntent:
        """Call OpenAI API to parse style intent."""
        prompt = self._build_prompt(user_input, loop_metadata)

        try:
            # Run synchronous OpenAI call in thread pool
            response_text = await asyncio.to_thread(
                self._make_llm_request,
                prompt,
            )

            # Parse JSON response
            try:
                data = json.loads(response_text)
            except json.JSONDecodeError:
                # Try to extract JSON from response
                start = response_text.find("{")
                end = response_text.rfind("}") + 1
                if start >= 0 and end > start:
                    data = json.loads(response_text[start:end])
                else:
                    raise ValueError("Could not extract JSON from LLM response")

            # Validate and construct StyleIntent
            intent = StyleIntent(
                archetype=str(data.get("archetype", "atl")).lower(),
                attributes=self._normalize_attributes(data.get("attributes", {})),
                transitions=data.get("transitions", []),
                confidence=float(data.get("confidence", 0.8)),
                raw_input=user_input,
            )

            return intent

        except Exception as e:
            logger.warning(f"LLM API call failed: {e}")
            raise

    def _make_llm_request(self, prompt: str) -> str:
        """Make synchronous LLM request (runs in thread pool)."""
        response = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.3,  # Low temperature for consistency
            max_tokens=500,
            timeout=self.timeout,
        )
        return response.choices[0].message.content.strip()

    def _build_prompt(self, user_input: str, loop_metadata: dict) -> str:
        """Build prompt for LLM."""
        archetype_list = ", ".join(sorted(ARCHETYPE_MAP.keys())[:15])  # Show first 15

        return f"""You are a music production assistant that parses style descriptions into structured data.

User Input: "{user_input}"

Loop Metadata:
- BPM: {loop_metadata.get('bpm', '?')}
- Key: {loop_metadata.get('key', '?')}
- Duration: {loop_metadata.get('duration', '?')}s
- Bars: {loop_metadata.get('bars', '?')}

Available Archetypes (select the most appropriate):
atl, atl_aggressive, atl_melodic, dark, dark_drill, dark_cinematic, melodic, melodic_trap, melodic_ambient, drill, drill_aggressive, club, club_bounce, cinematic, cinematic_dark, experimental

Parse the style description and return ONLY valid JSON (no markdown, no code blocks):

{{
  "archetype": "string (one of the available archetypes)",
  "attributes": {{
    "aggression": 0.0-1.0,
    "darkness": 0.0-1.0,
    "bounce": 0.0-1.0,
    "melody_complexity": 0.0-1.0,
    "energy_variance": 0.0-1.0,
    "transition_intensity": 0.0-1.0,
    "fx_density": 0.0-1.0,
    "bass_presence": 0.0-1.0
  }},
  "transitions": [
    {{"type": "beat_switch", "bar": 32, "new_energy": 0.9}}
  ],
  "confidence": 0.0-1.0
}}

Guidelines:
- All attribute values must be in range [0.0, 1.0]
- "confidence" reflects how well you understand the request (0-1)
- If user mentions "beat switch", "drop", or "change", include in transitions
- Look for producer names: Southside, Metro Boomin, Lil Baby, Pierre Bourne, Tay Keith, Wheezy, etc.
- Keywords: "aggressive" → high aggression, "dark" → high darkness, "bouncy" → high bounce, "smooth" → low aggression
- Default attributes to 0.5 if user doesn't specify

Return ONLY the JSON object, nothing else."""

    def _map_archetype_to_preset(self, archetype: str) -> StylePresetName:
        """Map archetype to base preset name."""
        archetype_lower = str(archetype).lower().strip()

        # Direct lookup
        if archetype_lower in ARCHETYPE_MAP:
            preset_name = ARCHETYPE_MAP[archetype_lower][0]
            return StylePresetName(preset_name)

        # Fallback: try producer matching
        for producer, arch in PRODUCER_ARCHETYPES.items():
            if producer in archetype_lower:
                if arch in ARCHETYPE_MAP:
                    preset_name = ARCHETYPE_MAP[arch][0]
                    return StylePresetName(preset_name)

        # Final fallback: return ATL
        logger.warning(f"Archetype {archetype} not recognized, defaulting to ATL")
        return StylePresetName.ATL

    def _normalize_attributes(self, attributes: dict) -> dict[str, float]:
        """Normalize attributes to [0, 1] range."""
        normalized = {}
        for key, value in attributes.items():
            try:
                val = float(value)
                normalized[key] = max(0.0, min(1.0, val))
            except (ValueError, TypeError):
                normalized[key] = 0.5

        return normalized

    def _generate_seed(self, user_input: str, loop_metadata: dict) -> int:
        """Generate a deterministic integer seed from *user_input* and *loop_metadata*.

        The same inputs always produce the same seed, and different inputs produce
        different seeds with very high probability.
        """
        import hashlib
        key = f"{user_input}|{str(sorted((k, str(v)) for k, v in loop_metadata.items()))}"
        digest = hashlib.sha256(key.encode()).hexdigest()
        return int(digest[:15], 16)

    def _apply_attribute_modifiers(
        self,
        base_params,
        llm_attributes_or_overrides=None,
        user_overrides: Optional[StyleOverrides] = None,
    ):
        """Apply attribute modifiers and overrides to base parameters.

        Supports two calling conventions:
        1. ``_apply_attribute_modifiers(StyleParameters, dict, StyleOverrides)`` —
           full form used internally; returns ``StyleParameters``.
        2. ``_apply_attribute_modifiers(dict, StyleOverrides)`` — simplified form
           used by tests and external callers; returns ``dict``.
        """
        # Detect simplified 2-arg calling convention: (dict, StyleOverrides)
        if isinstance(base_params, dict):
            attrs: dict = base_params
            overrides = llm_attributes_or_overrides
            result: dict = dict(attrs)
            if isinstance(overrides, StyleOverrides):
                if overrides.aggression is not None:
                    result["aggression"] = float(overrides.aggression)
                if overrides.bounce is not None:
                    result["bounce"] = float(overrides.bounce)
                if overrides.melody_complexity is not None:
                    result["melody_complexity"] = float(overrides.melody_complexity)
                if overrides.drum_density is not None:
                    result["drum_density"] = float(overrides.drum_density)
                if overrides.tempo_multiplier is not None:
                    result["tempo_multiplier"] = float(overrides.tempo_multiplier)
            # Clamp all float values to [0, 1]
            return {k: max(0.0, min(1.0, float(v))) if isinstance(v, (int, float)) else v
                    for k, v in result.items()}

        # Full 3-arg form: (StyleParameters, dict, StyleOverrides)
        llm_attributes: dict = llm_attributes_or_overrides if isinstance(llm_attributes_or_overrides, dict) else {}
        params_dict = {
            "tempo_multiplier": base_params.tempo_multiplier,
            "drum_density": base_params.drum_density,
            "hat_roll_probability": base_params.hat_roll_probability,
            "glide_probability": base_params.glide_probability,
            "swing": base_params.swing,
            "aggression": base_params.aggression,
            "melody_complexity": base_params.melody_complexity,
            "fx_intensity": base_params.fx_intensity,
        }

        # Apply LLM attributes (0-1 modifiers)
        if "aggression" in llm_attributes:
            modifier = llm_attributes["aggression"] - 0.5  # -0.5 to +0.5
            params_dict["aggression"] = max(0.0, min(1.0, params_dict["aggression"] + modifier * 0.2))

        if "darkness" in llm_attributes:
            modifier = llm_attributes["darkness"] - 0.5
            params_dict["fx_intensity"] = max(0.0, min(1.0, params_dict["fx_intensity"] + modifier * 0.15))

        if "bounce" in llm_attributes:
            modifier = llm_attributes["bounce"] - 0.5
            params_dict["swing"] = max(0.0, min(1.0, params_dict["swing"] + modifier * 0.1))
            params_dict["hat_roll_probability"] = max(0.0, min(1.0, params_dict["hat_roll_probability"] + modifier * 0.15))

        if "melody_complexity" in llm_attributes:
            modifier = llm_attributes["melody_complexity"] - 0.5
            params_dict["melody_complexity"] = max(0.0, min(1.0, params_dict["melody_complexity"] + modifier * 0.2))

        # Apply user overrides (take precedence)
        if user_overrides:
            if user_overrides.aggression is not None:
                params_dict["aggression"] = user_overrides.aggression
            if user_overrides.bounce is not None:
                params_dict["swing"] = user_overrides.bounce * 0.15
                params_dict["hat_roll_probability"] = user_overrides.bounce * 0.8
            if user_overrides.melody_complexity is not None:
                params_dict["melody_complexity"] = user_overrides.melody_complexity
            if user_overrides.drum_density is not None:
                params_dict["drum_density"] = user_overrides.drum_density
            if user_overrides.tempo_multiplier is not None:
                params_dict["tempo_multiplier"] = user_overrides.tempo_multiplier

        # Reconstruct StyleParameters
        return StyleParameters(**params_dict)

    def _generate_sections_with_transitions(
        self,
        transitions: List[dict],
        *args,
        total_bars: int = 64,
        metadata: Optional[dict] = None,
        # Legacy positional parameters (kept for backward compatibility)
        target_seconds: int = 0,
        bpm: float = 0.0,
        loop_bars: int = 0,
        base_template: tuple = (),
    ) -> List[dict]:
        """Generate section plan with beat switches and transitions.

        Supports two calling conventions:
        1. New: ``_generate_sections_with_transitions(transitions, total_bars=..., metadata=...)``
        2. Legacy: ``_generate_sections_with_transitions(target_seconds, bpm, loop_bars, transitions, base_template)``
        """
        # Resolve effective total_bars
        if not total_bars and target_seconds and bpm:
            bar_duration = (60.0 / bpm) * 4  # seconds per 4/4 bar
            total_bars = max(1, int(target_seconds / bar_duration))
        if not total_bars:
            total_bars = 64

        # Resolve effective bpm from metadata or positional arg
        eff_bpm = bpm or (metadata or {}).get("bpm") or 120.0

        # Start with base template sections if provided, else build a default structure
        sections: List[dict] = []
        current_bar = 0

        if base_template:
            for template in base_template:
                section = {
                    "name": template.name,
                    "bars": min(template.bars, max(1, total_bars - current_bar)),
                    "energy": template.energy,
                    "start_bar": current_bar,
                    "end_bar": current_bar + template.bars - 1,
                }
                sections.append(section)
                current_bar += template.bars
                if current_bar >= total_bars:
                    break
        else:
            # Default section structure: intro / verse / hook / bridge / outro
            default_structure = [
                ("intro", 4, 0.4), ("verse", 8, 0.6), ("hook", 8, 0.9),
                ("verse", 8, 0.6), ("hook", 8, 0.9), ("bridge", 8, 0.5),
                ("outro", 4, 0.3),
            ]
            for name, bars, energy in default_structure:
                if current_bar >= total_bars:
                    break
                actual_bars = min(bars, total_bars - current_bar)
                sections.append({
                    "name": name,
                    "bars": actual_bars,
                    "energy": energy,
                    "start_bar": current_bar,
                    "end_bar": current_bar + actual_bars - 1,
                })
                current_bar += actual_bars

        # Insert beat switches if specified
        for transition in transitions:
            if transition.get("type") == "beat_switch":
                beat_switch_bar = transition.get("bar", total_bars // 2)
                new_energy = transition.get("new_energy", 0.9)

                for i, section in enumerate(sections):
                    if section["start_bar"] <= beat_switch_bar < section["end_bar"]:
                        before_bars = beat_switch_bar - section["start_bar"]
                        after_bars = section["bars"] - before_bars

                        if before_bars > 0:
                            section["bars"] = before_bars
                            section["end_bar"] = beat_switch_bar - 1

                        beat_switch = {
                            "name": "beat_switch",
                            "bars": min(8, after_bars),
                            "energy": new_energy,
                            "start_bar": beat_switch_bar,
                            "end_bar": beat_switch_bar + min(8, after_bars) - 1,
                        }
                        sections.insert(i + 1, beat_switch)
                        break

        return sections

    def _params_to_dict(self, params: StyleParameters) -> dict:
        """Convert StyleParameters to dictionary."""
        return {
            "tempo_multiplier": params.tempo_multiplier,
            "drum_density": params.drum_density,
            "hat_roll_probability": params.hat_roll_probability,
            "glide_probability": params.glide_probability,
            "swing": params.swing,
            "aggression": params.aggression,
            "melody_complexity": params.melody_complexity,
            "fx_intensity": params.fx_intensity,
        }

    def _fallback_parse(
        self,
        user_input: str,
        loop_metadata: dict,
        overrides: Optional[StyleOverrides] = None,
    ) -> StyleProfile:
        """Fallback rule-based parsing when LLM unavailable."""
        from app.services.rule_based_fallback import parse_with_rules

        return parse_with_rules(user_input, loop_metadata, overrides)


# Singleton instance
llm_style_parser = LLMStyleParser()
