# app/services/arranger.py

import random

SECTIONS = [
    "Intro",
    "Hook",
    "Verse",
    "Hook",
    "Bridge",
    "Hook",
    "Outro"
]

def create_arrangement():
    """Generate a default arrangement with sections and bar counts."""
    arrangement = []
    
    for section in SECTIONS:
        bars = random.choice([4, 8, 16])
        arrangement.append({
            "section": section,
            "bars": bars
        })
    
    return arrangement


def create_arrangement_for_duration(bars_needed: int) -> list:
    """
    Generate a dynamic arrangement that spans exactly the requested bars.
    
    Creates a repeating pattern: Intro, Verse, Chorus, Verse, Chorus, ..., Outro
    Fills the arrangement to exactly match bars_needed.
    
    Args:
        bars_needed: Total bars the arrangement should span
        
    Returns:
        List of arrangement sections with bar counts
    """
    if bars_needed < 16:
        # Minimum: intro (4) + verse (8) + outro (4)
        bars_needed = 16
    
    arrangement = []
    
    # Reserve intro (4 bars) and outro (4 bars)
    intro_bars = 4
    outro_bars = 4
    remaining_bars = bars_needed - intro_bars - outro_bars
    
    # Add intro
    arrangement.append({"section": "Intro", "bars": intro_bars})
    
    # Generate repeating verse/chorus pattern
    # Pattern: [Verse (8), Chorus (8)] = 16 bars per cycle
    pattern_bars = 16
    full_cycles = remaining_bars // pattern_bars
    remainder_bars = remaining_bars % pattern_bars
    
    # Add full cycles of verse/chorus
    for i in range(full_cycles):
        arrangement.append({"section": "Verse", "bars": 8})
        arrangement.append({"section": "Chorus", "bars": 8})
    
    # Add remainder bars as extended verse if needed
    if remainder_bars > 0:
        if remainder_bars <= 8:
            # Add as extended verse
            arrangement.append({"section": "Verse", "bars": remainder_bars})
        else:
            # Add verse + partial chorus
            arrangement.append({"section": "Verse", "bars": 8})
            arrangement.append({"section": "Chorus", "bars": remainder_bars - 8})
    
    # Add outro
    arrangement.append({"section": "Outro", "bars": outro_bars})
    
    return arrangement

