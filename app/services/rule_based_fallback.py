"""Rule-based fallback parser for style intent when LLM unavailable."""

import logging
import random
from typing import Optional

from app.schemas.style_profile import StyleIntent, StyleOverrides, StyleProfile
from app.style_engine.presets import PRESETS
from app.style_engine.types import StylePresetName

logger = logging.getLogger(__name__)


# Keyword-to-attribute mapping for rule-based parsing
KEYWORD_PATTERNS = {
    # Aggression/intensity keywords
    r"aggressive|hard|harsh|hard hitting|brutal": {"aggression": 0.85},
    r"smooth|mellow|laid back|chill|relaxed": {"aggression": 0.2},
    r"mid aggressive|medium aggressive": {"aggression": 0.55},

    # Darkness/mood keywords
    r"dark|gloomy|moody|sinister|ominous": {"darkness": 0.85},
    r"bright|light|uplifting|cheerful": {"darkness": 0.15},
    r"atmospheric|ambient|cinematic|movie like": {"darkness": 0.6},

    # Bounce/swing keywords
    r"bouncy|bounce|bouncing|bouncy beat": {"bounce": 0.85},
    r"groove|groovy|swinging|swing": {"bounce": 0.7},
    r"stiff|rigid|locked|tight": {"bounce": 0.1},

    # Melody/harmonic keywords
    r"melodic|melody|musical|harmonic|harmonic complexity": {"melody_complexity": 0.80},
    r"simple|minimal|sparse|minimal melody": {"melody_complexity": 0.2},
    r"complex|layered|intricate|layered melody": {"melody_complexity": 0.9},

    # Energy/variation keywords
    r"energetic|high energy|explosive": {"energy_variance": 0.8},
    r"consistent|steady|locked in|stable": {"energy_variance": 0.2},
    r"dynamic|varying|variable|changing": {"energy_variance": 0.75},

    # Transition/switch keywords
    r"beat switch|drop|build|climax|peak": {"transition_intensity": 0.85},
    r"smooth transition|smooth switch|gradual": {"transition_intensity": 0.3},

    # Effect/complexity keywords
    r"effect heavy|effects|fx heavy|lots of effects": {"fx_density": 0.85},
    r"minimal effects|clean|dry|no effects": {"fx_density": 0.1},
    r"spacious|wide|spatial": {"fx_density": 0.6},

    # Bass keywords
    r"bass heavy|heavy bass|booming|subby|sub bass": {"bass_presence": 0.9},
    r"no bass|minimal bass|light bass": {"bass_presence": 0.2},
    r"bass focused|bass forward": {"bass_presence": 0.8},
}

# Producer/archetype keywords
PRODUCER_KEYWORDS = {
    "southside|southside type": "atl_aggressive",
    "808 mafia|mafia beats": "atl_aggressive",
    "metro boomin|metro|metro type": "dark_drill",
    "lil baby|baby": "melodic_trap",
    "gunna|wunna": "melodic_trap",
    "pierre|pierre bourne|bourne beats": "melodic_trap",
    "wheezy": "atl_melodic",
    "tay keith": "dark_drill",
    "london|london on da track": "melodic_trap",
    "dark drake|uk|uk drill": "drill",
}

# Genre/vibe keywords
GENRE_KEYWORDS = {
    "drill|uk drill|ny drill": "drill",
    "trap|trap beat": "atl",
    "dark trap|dark": "dark",
    "rnb|r&b|contemporary|modern": "melodic",
    "cinematic|dramatic|orchestral": "cinematic",
    "club|house|electronic|edm": "club",
    "experimental|experimental beat|weird": "experimental",
    "ambient|atmospheric|downtempo": "cinematic",
}


def parse_with_rules(
    user_input: str,
    loop_metadata: dict,
    overrides: Optional[StyleOverrides] = None,
) -> StyleProfile:
    """
    Parse user input using keyword matching and heuristics.

    Args:
        user_input: User's style description
        loop_metadata: Loop metadata {bpm, key, duration, bars}
        overrides: Optional manual slider overrides

    Returns:
        StyleProfile based on rule-based parsing
    """
    user_input_lower = user_input.lower().strip()

    # Step 1: Identify archetype using producer/genre keywords
    archetype = _identify_archetype(user_input_lower)

    # Step 2: Extract attributes using keyword patterns
    attributes = _extract_attributes(user_input_lower)

    # Step 3: Detect beat switch transitions
    transitions = _detect_transitions(user_input_lower)

    # Step 4: Create StyleIntent
    intent = StyleIntent(
        archetype=archetype,
        attributes=attributes,
        transitions=transitions,
        confidence=0.6,  # Lower confidence for fallback
        raw_input=user_input,
    )

    # Step 5: Get base preset and apply modifiers
    try:
        base_preset_name = StylePresetName(archetype)
    except ValueError:
        logger.warning(f"Invalid archetype {archetype}, defaulting to ATL")
        base_preset_name = StylePresetName.ATL

    base_preset = PRESETS.get(base_preset_name)
    if not base_preset:
        logger.warning(f"Preset {base_preset_name} not found, using ATL")
        base_preset = PRESETS[StylePresetName.ATL]

    # Apply attribute modifiers
    resolved_params = _apply_attribute_modifiers(
        base_preset.defaults,
        attributes,
        overrides,
    )

    # Generate sections with transitions
    sections = _generate_sections(
        target_seconds=int(loop_metadata.get("duration", 180)),
        bpm=float(loop_metadata.get("bpm", 120.0)),
        loop_bars=int(loop_metadata.get("bars", 4)),
        transitions=transitions,
        base_template=base_preset.section_templates,
    )

    # Create deterministic seed
    seed = random.randint(1, 2**31 - 1)

    profile = StyleProfile(
        intent=intent,
        overrides=overrides,
        resolved_preset=base_preset_name.value,
        resolved_params={
            "tempo_multiplier": resolved_params.tempo_multiplier,
            "drum_density": resolved_params.drum_density,
            "hat_roll_probability": resolved_params.hat_roll_probability,
            "glide_probability": resolved_params.glide_probability,
            "swing": resolved_params.swing,
            "aggression": resolved_params.aggression,
            "melody_complexity": resolved_params.melody_complexity,
            "fx_intensity": resolved_params.fx_intensity,
        },
        sections=sections,
        seed=seed,
    )

    logger.info(f"Rule-based parsing: {archetype} from '{user_input}'")
    return profile


def _identify_archetype(user_input_lower: str) -> str:
    """Identify primary archetype from keywords."""
    import re

    # Check producer keywords first (most specific)
    for pattern, archetype in PRODUCER_KEYWORDS.items():
        if re.search(pattern, user_input_lower):
            logger.debug(f"Matched producer keyword {pattern} -> {archetype}")
            return archetype

    # Check genre keywords
    for pattern, preset in GENRE_KEYWORDS.items():
        if re.search(pattern, user_input_lower):
            logger.debug(f"Matched genre keyword {pattern} -> {preset}")
            return preset

    # Default fallback
    logger.debug("No keyword match, defaulting to ATL")
    return "atl"


def _extract_attributes(user_input_lower: str) -> dict[str, float]:
    """Extract attributes from keywords."""
    import re

    attributes = {}

    for pattern, attr_dict in KEYWORD_PATTERNS.items():
        if re.search(pattern, user_input_lower):
            logger.debug(f"Matched pattern '{pattern}' -> {attr_dict}")
            attributes.update(attr_dict)

    # Normalize to [0, 1] range and provide defaults
    normalized = {}
    for key in [
        "aggression",
        "darkness",
        "bounce",
        "melody_complexity",
        "energy_variance",
        "transition_intensity",
        "fx_density",
        "bass_presence",
    ]:
        if key in attributes:
            normalized[key] = max(0.0, min(1.0, attributes[key]))
        else:
            normalized[key] = 0.5  # Default: neutral

    return normalized


def _detect_transitions(user_input_lower: str) -> list[dict]:
    """Detect beat switch/transition requests."""
    import re

    transitions = []

    # Look for beat switch patterns
    if re.search(r"beat switch|drop|build|after hook|bar \d+", user_input_lower):
        # Extract bar number if specified
        bar_match = re.search(r"bar (\d+)|after (\d+) bars", user_input_lower)
        if bar_match:
            bar = int(bar_match.group(1) or bar_match.group(2))
        else:
            bar = 32  # Default beat switch at 32 bars (8 bars = 1 chorus typical)

        # Determine energy level from context
        if "aggressive" in user_input_lower or "hard" in user_input_lower:
            new_energy = 0.9
        elif "smooth" in user_input_lower or "mellow" in user_input_lower:
            new_energy = 0.6
        else:
            new_energy = 0.8  # Default

        transitions.append(
            {
                "type": "beat_switch",
                "bar": bar,
                "new_energy": new_energy,
            }
        )

    return transitions


def _apply_attribute_modifiers(base_params, llm_attributes, user_overrides=None):
    """Apply attribute modifiers to base parameters."""
    from app.style_engine.types import StyleParameters

    # Create params dict from base
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

    # Apply LLM attributes
    if "aggression" in llm_attributes:
        modifier = llm_attributes["aggression"] - 0.5
        params_dict["aggression"] = max(0.0, min(1.0, params_dict["aggression"] + modifier * 0.2))

    if "darkness" in llm_attributes:
        modifier = llm_attributes["darkness"] - 0.5
        params_dict["fx_intensity"] = max(0.0, min(1.0, params_dict["fx_intensity"] + modifier * 0.15))

    if "bounce" in llm_attributes:
        modifier = llm_attributes["bounce"] - 0.5
        params_dict["swing"] = max(0.0, min(1.0, params_dict["swing"] + modifier * 0.1))

    if "melody_complexity" in llm_attributes:
        modifier = llm_attributes["melody_complexity"] - 0.5
        params_dict["melody_complexity"] = max(0.0, min(1.0, params_dict["melody_complexity"] + modifier * 0.2))

    # Apply user overrides
    if user_overrides:
        if user_overrides.aggression is not None:
            params_dict["aggression"] = user_overrides.aggression
        if user_overrides.bounce is not None:
            params_dict["swing"] = user_overrides.bounce * 0.15

    from app.style_engine.types import StyleParameters

    return StyleParameters(**params_dict)


def _generate_sections(target_seconds, bpm, loop_bars, transitions, base_template):
    """Generate section plan with transitions."""
    bar_duration = (60.0 / bpm) * 4  # seconds per bar
    total_bars = int(target_seconds / bar_duration)

    sections = []
    current_bar = 0

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

    return sections
