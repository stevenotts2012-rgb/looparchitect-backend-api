"""Music arrangement generation service.

Generates dynamic arrangements for loops with flexible duration support.
Converts duration_seconds to bar counts using BPM, then creates repeating
section patterns that fill the target bars exactly.
"""

import logging
from typing import List, Dict, Tuple

logger = logging.getLogger(__name__)


def duration_to_bars(duration_seconds: int, bpm: float) -> int:
    """Convert duration in seconds to number of 4/4 bars.

    Formula: bars = (duration_seconds / 60) * (bpm / 4)
    - Dividing by 60 converts seconds to minutes
    - Multiplying by (bpm/4) converts minutes to bars at given BPM
    - Rounds to nearest bar

    Args:
        duration_seconds: Duration in seconds
        bpm: Tempo in beats per minute

    Returns:
        Number of 4/4 bars

    Example:
        >>> duration_to_bars(180, 140)  # 3 min at 140 BPM
        105
    """
    if bpm <= 0:
        raise ValueError(f"BPM must be positive, got {bpm}")
    if duration_seconds <= 0:
        raise ValueError(f"Duration must be positive, got {duration_seconds}")

    bars = round((duration_seconds / 60) * (bpm / 4))
    # Ensure minimum of 4 bars
    return max(4, bars)


def bars_to_duration(bars: int, bpm: float) -> int:
    """Convert bars to duration in seconds.

    Formula: duration_seconds = (bars / (bpm / 4)) * 60
    Reverse of duration_to_bars.

    Args:
        bars: Number of 4/4 bars
        bpm: Tempo in beats per minute

    Returns:
        Duration in seconds

    Example:
        >>> bars_to_duration(84, 140)  # 84 bars at 140 BPM
        180
    """
    if bpm <= 0:
        raise ValueError(f"BPM must be positive, got {bpm}")
    if bars <= 0:
        raise ValueError(f"Bars must be positive, got {bars}")

    duration = round((bars / (bpm / 4)) * 60)
    return duration


def create_default_arrangement() -> List[Dict]:
    """Generate a default arrangement with static sections.

    Returns sections with names and bar counts (no bar positions).

    Returns:
        List of sections: [{"name": str, "bars": int}, ...]
    """
    sections = [
        {"name": "Intro", "bars": 4},
        {"name": "Verse", "bars": 8},
        {"name": "Chorus", "bars": 8},
        {"name": "Bridge", "bars": 8},
        {"name": "Chorus", "bars": 8},
        {"name": "Outro", "bars": 4},
    ]
    return sections


def generate_arrangement(
    target_bars: int, bpm: float
) -> Tuple[List[Dict], int]:
    """Generate a dynamic arrangement that fills exactly target_bars.

    Structure:
    1. Intro (4 bars) - sets up the groove
    2. Repeating Verse/Chorus cycle:
       - Verse (8 bars)
       - Chorus/Hook (8 bars)
    3. Optional Bridge (if space allows)
    4. Outro (4 bars) - always ends the arrangement

    The function fills the middle with verse/chorus cycles,
    then trims the last section to fit exactly.

    Args:
        target_bars: Total number of bars to generate
        bpm: Tempo used for response (not used in calculation)

    Returns:
        Tuple of (sections list, actual total bars)
        where sections have name, bars, start_bar, end_bar

    Example:
        >>> sections, total = generate_arrangement(56, 140)
        >>> total
        56
        >>> len(sections)
        5
        >>> sections[0]
        {'name': 'Intro', 'bars': 4, 'start_bar': 0, 'end_bar': 3}
    """
    if target_bars < 16:
        logger.warning(
            f"Target bars {target_bars} is less than minimum 16, using 16"
        )
        target_bars = 16

    logger.info(f"Generating arrangement for {target_bars} bars")

    sections = []
    current_bar = 0

    # --- Intro (4 bars) ---
    intro_bars = 4
    sections.append(
        {
            "name": "Intro",
            "bars": intro_bars,
            "start_bar": current_bar,
            "end_bar": current_bar + intro_bars - 1,
        }
    )
    current_bar += intro_bars

    # --- Middle: Repeating Verse + Chorus pattern ---
    # Reserve 4 bars for outro
    remaining_bars = target_bars - current_bar - 4

    # Pattern: Verse (8) + Chorus (8) = 16 bars per cycle
    pattern_bars = 16
    full_cycles = remaining_bars // pattern_bars
    remainder_bars = remaining_bars % pattern_bars

    logger.debug(
        f"Middle section: {remaining_bars} bars"
        f" = {full_cycles} full cycles + {remainder_bars} remainder"
    )

    # Add full cycles
    for cycle in range(full_cycles):
        # Verse
        verse_bars = 8
        sections.append(
            {
                "name": "Verse",
                "bars": verse_bars,
                "start_bar": current_bar,
                "end_bar": current_bar + verse_bars - 1,
            }
        )
        current_bar += verse_bars

        # Chorus
        chorus_bars = 8
        sections.append(
            {
                "name": "Chorus",
                "bars": chorus_bars,
                "start_bar": current_bar,
                "end_bar": current_bar + chorus_bars - 1,
            }
        )
        current_bar += chorus_bars

    # Handle remainder bars
    if remainder_bars > 0:
        if remainder_bars <= 8:
            # Add as extended verse
            sections.append(
                {
                    "name": "Verse",
                    "bars": remainder_bars,
                    "start_bar": current_bar,
                    "end_bar": current_bar + remainder_bars - 1,
                }
            )
            current_bar += remainder_bars
        else:
            # Add verse (8) + partial chorus
            sections.append(
                {
                    "name": "Verse",
                    "bars": 8,
                    "start_bar": current_bar,
                    "end_bar": current_bar + 7,
                }
            )
            current_bar += 8

            chorus_remainder = remainder_bars - 8
            sections.append(
                {
                    "name": "Chorus",
                    "bars": chorus_remainder,
                    "start_bar": current_bar,
                    "end_bar": current_bar + chorus_remainder - 1,
                }
            )
            current_bar += chorus_remainder

    # --- Outro (4 bars) ---
    outro_bars = 4
    sections.append(
        {
            "name": "Outro",
            "bars": outro_bars,
            "start_bar": current_bar,
            "end_bar": current_bar + outro_bars - 1,
        }
    )
    current_bar += outro_bars

    actual_total_bars = current_bar
    logger.info(
        f"Arrangement generated: {len(sections)} sections, {actual_total_bars} total bars"
    )

    return sections, actual_total_bars


# Legacy function names (backward compatibility)
def create_arrangement():
    """Legacy function for backward compatibility."""
    return create_default_arrangement()


def create_arrangement_for_duration(bars_needed: int) -> list:
    """Legacy function for backward compatibility."""
    sections, _ = generate_arrangement(bars_needed, 120.0)
    # Convert to old format
    return [{"section": s["name"], "bars": s["bars"]} for s in sections]

