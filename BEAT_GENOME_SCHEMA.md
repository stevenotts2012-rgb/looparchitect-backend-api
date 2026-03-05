# Beat Genome Schema & Configuration

**Version:** 1.0  
**Date:** March 5, 2026  
**Purpose:** Define beat genome data format for genre-specific production rules

---

## What is a Beat Genome?

A **Beat Genome** is a JSON configuration file that encodes the "personality" of a music genre.

It controls:
- Song structure (section lengths)
- Energy progression (how a track builds/releases)
- Instrument behavior (what plays when)
- Change frequency (how often something happens)
- Variation patterns (specific fills/rolls)
- Drop rules (intro/drop transitions)
- Vocal space (where vocals fit)

Instead of hardcoding all behavior in Python, genomes allow **data-driven, scalable** genre support.

---

## File Structure

**Location:** `config/genomes/`

**Naming Convention:** `{genre}_{mood}.json`

**Examples:**
- `trap_dark.json` - Dark trap production
- `trap_bounce.json` - Bouncy trap (Memphis rap)
- `drill_uk.json` - UK drill
- `rnb_smooth.json` - Smooth R&B
- `rnb_modern.json` - Contemporary bedroom R&B
- `edm_pop.json` - Pop-oriented EDM
- `edm_hard.json` - Hard EDM/progressive house
- `afrobeats.json` - Afrobeats/Amapiano
- `cinematic.json` - Orchestral/film score

---

## Full Schema

```json
{
  // ─────────────────────────────────────────────────────────────
  // BASIC METADATA
  // ─────────────────────────────────────────────────────────────
  
  "name": "Trap Dark",
  "genre": "trap",
  "mood": "dark",
  "version": "1.0",
  "description": "Dark trap production inspired by FutureHendrix, Southside",
  
  // ─────────────────────────────────────────────────────────────
  // SONG STRUCTURE
  // ─────────────────────────────────────────────────────────────
  
  "section_lengths": {
    "intro": 8,
    "verse": 16,
    "pre_hook": 4,
    "hook": 8,
    "bridge": 8,
    "breakdown": 8,
    "outro": 4
  },
  
  "recommended_arrangement": [
    "intro",
    "hook",
    "verse",
    "hook",
    "verse",
    "bridge",
    "hook",
    "outro"
  ],
  
  "typical_duration_seconds": 180,
  
  // ─────────────────────────────────────────────────────────────
  // ENERGY CURVE
  // ─────────────────────────────────────────────────────────────
  
  "energy_curve": [
    {"section": "intro", "energy": 0.2, "description": "Atmospheric buildup"},
    {"section": "hook", "energy": 0.9, "description": "Main drop - peak energy"},
    {"section": "verse", "energy": 0.6, "description": "Groove pocket"},
    {"section": "pre_hook", "energy": 0.7, "description": "Building anticipation"},
    {"section": "bridge", "energy": 0.4, "description": "Release / breakdown"},
    {"section": "outro", "energy": 0.3, "description": "Fade"}
  ],
  
  "energy_interpolation": "smooth",  // "smooth" or "stepped"
  "energy_smoothing_bars": 4,  // Number of bars to interpolate over
  
  // ─────────────────────────────────────────────────────────────
  // CHANGE RATE (How often things change)
  // ─────────────────────────────────────────────────────────────
  
  "change_rate_bars": 8,  // Something new happens every 8 bars minimum
  
  "variation_frequency": {
    "intro": 2,      // Vary at bar 2
    "verse": 8,      // Vary at bar 8, 16, etc.
    "hook": 4,       // Vary more frequently (busier)
    "bridge": 8,
    "outro": 2
  },
  
  // ─────────────────────────────────────────────────────────────
  // INSTRUMENT LAYERS (What plays in each section)
  // ─────────────────────────────────────────────────────────────
  
  "instrument_layers": {
    "intro": {
      "required": ["kick", "pad"],
      "optional": ["fx"],
      "forbidden": ["snare", "vocal"],
      "description": "Minimal - just vibe setting"
    },
    
    "verse": {
      "required": ["kick", "snare", "hats", "bass"],
      "optional": ["melody", "percussion"],
      "forbidden": ["vocal"],
      "description": "Driving groove without melody"
    },
    
    "hook": {
      "required": ["kick", "snare", "hats", "bass", "lead"],
      "optional": ["pad", "fx", "strings"],
      "forbidden": [],
      "description": "MAXIMUM energy - all instruments"
    },
    
    "bridge": {
      "required": ["kick", "snare", "pad"],
      "optional": [],
      "forbidden": ["hats", "bass", "lead"],
      "description": "Stripped down - build anticipation"
    },
    
    "outro": {
      "required": ["kick", "pad"],
      "optional": [],
      "forbidden": ["snare", "hats", "lead"],
      "description": "Fade out - minimal"
    }
  },
  
  // ─────────────────────────────────────────────────────────────
  // VARIATION PATTERNS (What happens at specific points)
  // ─────────────────────────────────────────────────────────────
  
  "variation_moves": [
    {
      "type": "hihat_roll",
      "probability": 0.7,
      "intensity": 0.7,
      "bar_offset": 4,
      "description": "Hat rolls at bar 4 of verses"
    },
    {
      "type": "drum_fill",
      "probability": 0.6,
      "intensity": 0.8,
      "bar_offset": 8,
      "description": "Snare fill at section boundaries"
    },
    {
      "type": "bass_variation",
      "probability": 0.5,
      "intensity": 0.6,
      "bar_offset": 8,
      "description": "Bass glide/portamento"
    },
    {
      "type": "fx_automation",
      "probability": 0.8,
      "intensity": 0.6,
      "bar_offset": 6,
      "description": "Filter or reverb sweep"
    }
  ],
  
  // ─────────────────────────────────────────────────────────────
  // TRANSITIONS (How to move between sections)
  // ─────────────────────────────────────────────────────────────
  
  "transitions": [
    {
      "from": "intro",
      "to": "hook",
      "type": "drum_fill",
      "duration_bars": 0.5,
      "intensity": 0.8,
      "description": "Snare fill leading into hook drop"
    },
    {
      "from": "verse",
      "to": "hook",
      "type": "riser",
      "duration_bars": 1,
      "intensity": 0.7,
      "description": "Rising automatio leading to hook"
    },
    {
      "from": "hook",
      "to": "bridge",
      "type": "silence_drop",
      "duration_bars": 0.25,
      "intensity": 1.0,
      "description": "Abrupt silence for dramatic effect"
    }
  ],
  
  // ─────────────────────────────────────────────────────────────
  // DROP RULES (Special handling for intro/drop)
  // ─────────────────────────────────────────────────────────────
  
  "drop_rules": {
    "intro_type": "fade_in",  // "fade_in", "hit_hard", "building"
    "pre_drop_bars": 2,       // Bars to build before drop
    "drop_silence_bars": 0.5, // Silence before drop
    "drop_drum_fill": true,   // Snare roll on drop
    "description": "Fade in pad for 8 bars, sudden drum drop"
  },
  
  // ─────────────────────────────────────────────────────────────
  // VOCAL SPACE (Where vocals fit - if used)
  // ─────────────────────────────────────────────────────────────
  
  "vocal_space": {
    "primary_sections": ["hook", "verse"],
    "remove_instruments_for_vocals": ["melody", "lead"],
    "reduce_instruments_for_vocals": ["hats", "fx"],
    "pad_underneath": true,
    "description": "Drop melody/lead when vocals come in, keep pad"
  },
  
  // ─────────────────────────────────────────────────────────────
  // SONIC CHARACTERISTICS
  // ─────────────────────────────────────────────────────────────
  
  "tempo_range": [130, 150],
  "swing_factor": 0.0,  // 0.0 = straight, 0.05 = slight swing, 0.15 = bouncy
  "groove_pocket": "on_beat",  // "on_beat", "behind_beat", "ahead_of_beat"
  
  "compression": {
    "drums": "heavy",    // "none", "light", "moderate", "heavy"
    "bass": "moderate",
    "overall": "heavy"   // Sidechain compression on master
  },
  
  "effects_palette": [
    "reverb",           // Space
    "delay",            // Rhythm  
    "distortion",       // Aggression
    "filter_sweep",     // Drama
    "redundancy_shift"  // Pitch variation
  ],
  
  // ─────────────────────────────────────────────────────────────
  // MIXING GUIDELINES
  // ─────────────────────────────────────────────────────────────
  
  "mixing": {
    "bass_presence": 0.85,     // 0.0-1.0, emphasis on low end
    "drum_clarity": 0.9,        // Punchy drums, well-separated
    "melody_presence": 0.5,     // Melody is subordinate to drums
    "stereo_width": 0.6,        // Moderate - hip hop is narrower than EDM
    "master_loudness": "loud"   // "quiet" (jazz), "normal" (pop), "loud" (trap)
  },
  
  // ─────────────────────────────────────────────────────────────
  // PRODUCTION NOTES
  // ─────────────────────────────────────────────────────────────
  
  "production_notes": {
    "key_elements": [
      "Massive kick with sub-bass",
      "Snappy 808 drums",
      "Dark, sparse pad underneath",
      "Occasional aggressive FX"
    ],
    "avoid": [
      "Bright, cheerful sounds",
      "Complex melodies",
      "Orchestral elements",
      "Too much reverb"
    ],
    "inspiration": [
      "Future - Mask Off",
      "Southside - Beat tape collections",
      "Metro Boomin - Not All Heroes Wear Capes"
    ]
  }
}
```

---

## Minimal Genome Example

For quick start, here's a minimal genome (only required fields):

```json
{
  "name": "Trap Dark",
  "genre": "trap",
  
  "section_lengths": {
    "intro": 8,
    "verse": 16,
    "hook": 8,
    "bridge": 8,
    "outro": 4
  },
  
  "energy_curve": [
    {"section": "intro", "energy": 0.2},
    {"section": "hook", "energy": 0.9},
    {"section": "verse", "energy": 0.6},
    {"section": "bridge", "energy": 0.4},
    {"section": "outro", "energy": 0.2}
  ],
  
  "instrument_layers": {
    "intro": ["kick", "pad"],
    "verse": ["kick", "snare", "hats", "bass"],
    "hook": ["kick", "snare", "hats", "bass", "lead", "fx"],
    "bridge": ["kick", "pad"],
    "outro": ["kick", "pad"]
  },
  
  "variation_moves": [
    {"type": "hihat_roll", "probability": 0.7},
    {"type": "drum_fill", "probability": 0.6}
  ]
}
```

---

## Defined Genomes

### 1. Trap Dark (trap_dark.json)

**Characteristics:**
- Dark, atmospheric pads
- 808 kicks with heavy sub-bass
- Minimal drums (kick + snare + hats)
- Sparse melody if any
- Aggressive transition drops
- Good for: Hip-hop beats, trap instrumentals

### 2. Trap Bounce (trap_bounce. json)

**Characteristics:**
- Memphis-style drums (bouncy swing)
- Perky melodic elements
- Less dark than trap_dark
- Higher energy overall
- Good for: Uplifting trap, 90s Memphis vibes

### 3. Drill UK (drill_uk.json)

**Characteristics:**
- Fast hi-hat rolls (140-180 BPM)
- Punchy kick and snare
- Dark, gritty aesthetic
- Minimal bass
- Aggressive energy sustain
- Good for: UK drill, grime, aggressive beats

### 4. R&B Modern (rnb_modern.json)

**Characteristics:**
- Smooth drums with swing
- Rich harmonic pads
- Soulful basslines
- Melodic vocals-ready
- Soft compression
- Good for: Bedroom R&B, neo-soul, contemporary

### 5. Afrobeats (afrobeats.json)

**Characteristics:**
- Polyrhythmic percussion
- Groovy kick and snare interaction
- Lively hi-hat patterns
- Melodic, percussive bass
- High swing factor
- Good for: Afrobeats, Amapiano, Afro-house

### 6. EDM Pop (edm_pop.json)

**Characteristics:**
- Bright, punchy drums
- Euphoric melody/synth
- High-energy drops
- Sidechain compression on bass
- Wide stereo image
- Good for: Dance-pop, future bass, progressive house

### 7. Cinematic (cinematic.json)

**Characteristics:**
- Orchestral elements (strings, horns)
- Slow, epic structure
- Dramatic dynamics
- Movie-scale production
- Minimal drums (jazz-like)
- Good for: Film scores, trailers, orchestral

---

## Loading Genomes in Code

```python
from pathlib import Path
import json
from app.services.producer_models import BeatGenome

class GenomeLoader:
    """Load beat genomes from JSON files"""
    
    GENOMES_DIR = Path("config/genomes")
    
    @classmethod
    def load(cls, genre: str, mood: str = None) -> dict:
        """Load a beat genome by genre/mood"""
        
        # Build filename
        if mood:
            filename = f"{genre}_{mood}.json"
        else:
            filename = f"{genre}.json"
        
        filepath = cls.GENOMES_DIR / filename
        
        if not filepath.exists():
            raise FileNotFoundError(f"Genome not found: {filename}")
        
        with open(filepath) as f:
            return json.load(f)
    
    @classmethod
    def list_available(cls) -> list[str]:
        """List all available genomes"""
        return [f.stem for f in cls.GENOMES_DIR.glob("*.json")]

# Usage in ProducerEngine
genome = GenomeLoader.load("trap", "dark")
arrangement.genome_reference = genome["name"]
```

---

## Creating a New Genome

**Steps:**

1. Choose genre + mood
2. Create `config/genomes/{genre}_{mood}.json`
3. Fill in metadata (name, description)
4. Define section_lengths
5. Assign energy_curve
6. List instrument layers
7. Define variation patterns
8. Set transition rules
9. Test with ProducerEngine

**Validation Checklist:**

- ✅ All sections referenced in energy_curve
- ✅ All instruments defined in presets
- ✅ Duration formula: sum(section_lengths) * (bpm / 120)
- ✅ Energy values between 0.0 and 1.0
- ✅ Probabilities between 0.0 and 1.0
- ✅ No circular references
- ✅ Compatible with loader code

---

## Integration with ProducerEngine

In `app/services/producer_engine.py`:

```python
def generate(
    loop_metadata: LoopMetadata,
    style_profile: StyleProfile,
    target_duration: int
) -> ProducerArrangement:
    
    # Load beat genome
    genome = GenomeLoader.load(style_profile.genre)
    arrangement.genome_reference = genome["name"]
    
    # Use genome for structure
    template_sections = genome["section_lengths"]
    
    # Use genome for instruments
    for section in arrangement.sections:
        instruments = genome["instrument_layers"][section.name]
        arrangement = _assign_instruments(arrangement, instruments)
    
    # Use genome for energy
    energy_map = {e["section"]: e["energy"] for e in genome["energy_curve"]}
    arrangement.energy_curve = [
        EnergyPoint(bar=s.start_bar, energy=energy_map.get(s.name, 0.5))
        for s in arrangement.sections
    ]
    
    # Use genome for variations
    for variation_spec in genome["variation_moves"]:
        if random.random() < variation_spec["probability"]:
            # Apply variation
            pass
    
    return arrangement
```

---

## Directory Structure

```
config/
├── genomes/
│   ├── trap_dark.json
│   ├── trap_bounce.json
│   ├── drill_uk.json
│   ├── rnb_modern.json
│   ├── rnb_smooth.json
│   ├── afrobeats.json
│   ├── edm_pop.json
│   ├── edm_hard.json
│   ├── cinematic.json
│   └── README.md (genome guide)
└── README.md (config guide)
```

---

**Next Steps:**
1. Create 9 genome JSON files
2. Implement GenomeLoader class
3. Integrate into ProducerEngine
4. Test with different styles

See PRODUCER_ENGINE_ARCHITECTURE.md for integration details.
