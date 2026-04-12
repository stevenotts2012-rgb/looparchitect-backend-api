"""Music arrangement generation service.

Generates dynamic arrangements for loops with flexible duration support.
Converts duration_seconds to bar counts using BPM, then creates repeating
section patterns that fill the target bars exactly.
"""

import logging
import random
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
    Note: This is a static example. Dynamic arrangements use variable intro (2-16 bars).

    Returns:
        List of sections: [{"name": str, "bars": int}, ...]
    """
    sections = [
        {"name": "Intro", "bars": 4},
        {"name": "Verse", "bars": 8},
        {"name": "Hook", "bars": 8},
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
    1. Intro (2-16 bars) - sets up the groove
    2. Repeating Verse/Hook cycle:
       - Verse (8 bars)
       - Hook (8 bars)
    3. Bridge (8 bars) - appears after every 2 Verse/Hook cycles
    4. Outro (4 bars) - always ends the arrangement

    The function fills the middle with verse/hook/bridge cycles,
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
        7
        >>> sections[0]  # Intro bars vary between 2-16, randomly selected
        {'name': 'Intro', 'bars': 8, 'start_bar': 0, 'end_bar': 7}
    """
    if target_bars < 16:
        logger.warning(
            f"Target bars {target_bars} is less than minimum 16, using 16"
        )
        target_bars = 16

    logger.info(f"Generating arrangement for {target_bars} bars")

    sections = []
    current_bar = 0

    # --- Intro (always 4 bars for consistent arrangement structure) ---
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

    # --- Middle: Repeating Verse + Hook pattern with Bridge ---
    # Reserve 4 bars for outro
    remaining_bars = target_bars - current_bar - 4

    # Build sections dynamically: Verse → Hook → Verse → Hook → Bridge → repeat
    # Pattern: 2x(Verse+Hook) + Bridge = 2x(8+8) + 8 = 40 bars per super-cycle
    verse_hook_cycle = 0  # Track how many Verse-Hook pairs we've added
    
    logger.debug(f"Middle section: {remaining_bars} bars available")

    while remaining_bars > 0:
        # Add Verse (8 bars) if space available
        if remaining_bars >= 8:
            sections.append(
                {
                    "name": "Verse",
                    "bars": 8,
                    "start_bar": current_bar,
                    "end_bar": current_bar + 7,
                }
            )
            current_bar += 8
            remaining_bars -= 8
        elif remaining_bars > 0:
            # Partial verse to fill remaining
            sections.append(
                {
                    "name": "Verse",
                    "bars": remaining_bars,
                    "start_bar": current_bar,
                    "end_bar": current_bar + remaining_bars - 1,
                }
            )
            current_bar += remaining_bars
            remaining_bars = 0
            break

        # Add Hook (8 bars) if space available
        if remaining_bars >= 8:
            sections.append(
                {
                    "name": "Hook",
                    "bars": 8,
                    "start_bar": current_bar,
                    "end_bar": current_bar + 7,
                }
            )
            current_bar += 8
            remaining_bars -= 8
            verse_hook_cycle += 1
        elif remaining_bars > 0:
            # Partial hook to fill remaining
            sections.append(
                {
                    "name": "Hook",
                    "bars": remaining_bars,
                    "start_bar": current_bar,
                    "end_bar": current_bar + remaining_bars - 1,
                }
            )
            current_bar += remaining_bars
            remaining_bars = 0
            break

        # Add Bridge every 2 Verse-Hook cycles (if space available)
        if verse_hook_cycle % 2 == 0 and remaining_bars >= 8:
            sections.append(
                {
                    "name": "Bridge",
                    "bars": 8,
                    "start_bar": current_bar,
                    "end_bar": current_bar + 7,
                }
            )
            current_bar += 8
            remaining_bars -= 8

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

