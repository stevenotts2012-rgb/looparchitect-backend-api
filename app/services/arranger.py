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
