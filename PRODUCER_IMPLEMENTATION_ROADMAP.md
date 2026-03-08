# LoopArchitect Producer Implementation Roadmap

**Phase 2 - Build Real Producer-Style Arrangement**

---

## Overview

Transform LoopArchitect from loop-repeater to real beat arranger by implementing:
- **Layer Engine** - Control which drums/bass/melody are active per section
- **Energy Modulation** - Translate energy levels (0-1.0) to audio effects  
- **Variation Engine** - Add fills, dropouts, and beat variations every 4-8 bars
- **Transition Engine** - Insert risers, impacts, and drops between sections
- **Arrangement Planner** - Convert style direction to concrete production rules

---

## Architecture

```
User Input (Style: "Drake R&B")
    ↓
StyleDirectionEngine.parse() → StyleProfile
    ↓
ProducerEngine.generate() → ProducerArrangement + RenderPlan
    ↓
RenderWorker receives job
    ↓
AudioRenderer processes with:
    ├─ LayerEngine: Control drums/bass/melody per section
    ├─ EnergyModulationEngine: Volume + FX based on energy curve
    ├─ VariationEngine: Insert fills at section boundaries
    └─ TransitionEngine: Add transition audio between sections
    ↓
Output: Unique, structured arrangement (not just repeated loop)
```

---

## Core Services to Create

### 1. LayerEngine (`app/services/layer_engine.py`)

**Purpose:** Control which drums/bass/melody are active in each section.

**Responsibilities:**
- Detect/estimate loop components (kick, snare, hats, bass prominence)
- Apply layer masks (mute/keep drums, bass, melody)
- Use section's `instruments` field to determine what to keep
- Support progressive layer addition (intro sparse → hook full)

**Interface:**
```python
class LayerEngine:
    @staticmethod
    def analyze_loop_components(audio: AudioSegment, bpm: float) -> LoopComponents:
        """Estimate which frequencies/types are in loop (drums, bass, melody)."""
        # Returns: {kick: 0.8, snare: 0.6, hats: 0.7, bass: 0.9, melody: 0.5}
    
    @staticmethod
    def apply_layer_mask(
        audio: AudioSegment,
        section: Section,
        components: LoopComponents,
        energy_level: float,
    ) -> AudioSegment:
        """Keep only specified instruments; adjust presence by energy."""
        # If section.instruments doesn't include KICK, remove low end
        # If section.instruments doesn't include HATS, reduce high end
        # Scale remaining by energy_level
```

**Implementation approach:**
- Use frequency analysis (FFT) to estimate kick (40-100Hz), bass (80-200Hz), hats (8000-15000Hz)
- Apply band-pass filters to isolate/remove layers
- For kick/snare/hats: use onset detection to identify beats, can mute selectively
- For bass: low-pass filter to remove bass below threshold
- For melody: identify vocal frequencies and attenuate if needed
- Use energy_level to scale filter aggressiveness

---

### 2. EnergyModulationEngine (`app/services/energy_engine.py`)

**Purpose:** Translate energy curve (0.0-1.0) to audio effects.

**Mapping:**
- **0.0 (Minimal):** Single layer (pad/texture), minimal drums, reverb heavy
- **0.3 (Low):** Base drums (kick + snare), reduced hats, reverb
- **0.5 (Medium):** Full drums, some bass, moderate effects
- **0.7 (High):** All drums active, bass forward, light effects
- **1.0 (Maximum):** All instruments, aggressive drums, minimal reverb, optional distortion

**Interface:**
```python
class EnergyModulationEngine:
    @staticmethod
    def get_effect_parameters(energy_level: float) -> EffectParameters:
        """Convert 0-1 energy to volume, reverb, distortion, chorus levels."""
        # Returns: {
        #   "volume_db": -12 to -3,
        #   "reverb_wet": 0.8 to 0.1,
        #   "reverb_room": 0.6 to 0.2,
        #   "eq_presence": 0.1 to 0.9,
        #   "compression_ratio": 1.0 to 4.0,
        #   "distortion": 0.0 to 0.3
        # }
    
    @staticmethod
    def apply_energy_effects(
        audio: AudioSegment,
        energy_level: float,
        section_type: SectionType,
    ) -> AudioSegment:
        """Apply EQ, reverb, compression, distortion based on energy."""
```

**Implementation approach:**
- Volume scaling: `20 * log10(energy_level + 0.1)` dB adjustment
- Reverb depth: High energy = dry, low energy = wet (inverse relationship)
- Compression: Higher energy = more aggressive compression (ratio, lower threshold)
- EQ: Low energy = more lows/mids; high energy = presence peak
- Distortion: Only at max energy, subtle (0.1-0.2 drive)

---

### 3. VariationEngine (`app/services/variation_engine.py`)

**Purpose:** Add fills, dropouts, and patterns to prevent loop repetition.

**Variation Types:**
- **Fill:** Add drum pattern intensification (hi-hat roll, snare flam)
- **Dropout:** Mute kick/bass/drums for 1-2 bars before re-entry
- **Chop:** Stutter effect (short muting pulses like "ch-ch-ch-chop")
- **Filter Sweep:** Low-pass filter sweep rising into section
- **Reverse:** Reverse cymbal or sound effect as transition
- **Halt:** Brief silence (0.5 seconds) for tension

**Interface:**
```python
class VariationEngine:
    @staticmethod
    def add_section_variations(
        audio: AudioSegment,
        section: Section,
        components: LoopComponents,
    ) -> AudioSegment:
        """Insert variations (fills, dropouts) every 4-8 bars."""
        # Returns audio with variation events applied
        # Fills at bars 6-7 of 8-bar sections
        # Dropouts 1 bar before section transitions
    
    @staticmethod
    def create_hat_roll(
        audio: AudioSegment,
        bpm: float,
        duration_ms: int = 1000,
        density: float = 1.0,
    ) -> AudioSegment:
        """Synthesize or extract hat roll pattern."""
    
    @staticmethod
    def create_drum_fill(
        duration_ms: int,
        fill_type: str = "snare_flam",
        bpm: float = 120,
    ) -> AudioSegment:
        """Synthesize drum fill (snare flams, kick patterns, etc)."""
```

**Implementation approach:**
- Fills: Extract drum pattern from original loop, increase note density, place at section end
- Dropouts: Mute kick/bass in bars specified by variation event
- Chop: Apply gain envelope with rapid mute/unmute cycles
- Filter Sweep: Low-pass filter with automated cutoff (500Hz → 10kHz over 2 seconds)
- Reverse: Reverse a 2-bar segment of cymbal/effect, place before section
- Halt: Create AudioSegment of silence + small fade

---

### 4. TransitionEngine (`app/services/transition_engine.py`)

**Purpose:** Create audio transitions between sections.

**Transition Types:**
- **Riser:** Synthesized rising tone (kick drum pitch bend up)
- **Impact:** Kick drum or impact sound
- **Reverse Cymbal:** Reversed crash cymbal
- **Filter Sweep:** Low-pass filter automation
- **Silence Drop:** Brief quiet moment for tension
- **Downlifter:** Reverse riser (pitch moving down)
- **Swell:** Volume envelope swelling at section boundary

**Interface:**
```python
class TransitionEngine:
    @staticmethod
    def create_transition(
        transition_type: TransitionType,
        duration_ms: float = 2000,
        intensity: float = 0.5,  # 0 (subtle) to 1.0 (aggressive)
        bpm: float = 120,
    ) -> AudioSegment:
        """Synthesize transition audio."""
    
    @staticmethod
    def apply_transition_before_section(
        base_audio: AudioSegment,
        section: Section,
        transition_type: TransitionType,
        intensity: float = 0.5,
        bpm: float = 120,
    ) -> AudioSegment:
        """Apply transition audio at start of section."""
```

**Implementation approach:**
- Riser: Synthesized tone using pydub, freq sweep 100Hz → 5kHz, exponential curve
- Impact: Sample or synthesize kick drum sound (0.1s, steep decay)
- Reverse Cymbal: Reverse last 2 seconds of loop, apply envelope
- Filter Sweep: Low-pass filter cutoff automation (reverse of normal)
- Silence: AudioSegment of silence (200-500ms)
- Downlifter: Riser played in reverse
- Swell: Volume envelope starting at 0.5x, peaking at section start

---

### 5. ArrangementPlanner (`app/services/arrangement_planner.py`)

**Purpose:** Convert StyleProfile + ProducerArrangement into concrete production rules.

**Responsibilities:**
- Determine section lengths based on style (trap = shorter, soul = longer)
- Map style → layer strategies (Drake R&B = full bass presence, Detroit = sparse high-end)
- Define energy curve shape (trap = aggressive peaks, soul = smooth rises)
- Set variation frequency and intensity per style
- Create transition rules (fast cutting vs smooth blending)

**Interface:**
```python
class ArrangementPlanner:
    @staticmethod
    def plan_from_style(
        style_profile: StyleProfile,
        producer_arrangement: ProducerArrangement,
    ) -> PlaybookArrangement:
        """Convert style + structure into concrete rules."""
        # Returns { sections with layer masks, energy targets, variations list, transitions list }
    
    @staticmethod
    def get_layer_strategy_for_style(
        genre: str,
        section_type: SectionType,
    ) -> LayerStrategy:
        """What drums/bass/melody should be present in this section for this genre?"""
        # E.g., trap verse = less kick; soul verse = less hats, more bass
    
    @staticmethod
    def get_variation_pattern_for_style(genre: str) -> List[VariationRule]:
        """When and how often should variations occur?"""
        # E.g., trap = fills every 8 bars; soul = fills every 16 bars
```

**Implementation approach:**
- Read `style_profile.production_rules` (set by StyleDirectionEngine)
- Map section type to layer intensity per genre
- Define energy curve shape per style (trap = peaks, soul = smooth)
- Create variation schedule (frequency, intensity)
- Define transition style (trap = cuts, soul = blends)

---

## Implementation Order

### **Step 1: Create Core Engines** (Services layer)

✅ Done: PRODUCER_REALITY_AUDIT.md  
→ Create: `layer_engine.py`  
→ Create: `energy_engine.py`  
→ Create: `variation_engine.py`  
→ Create: `transition_engine.py`  
→ Create: `arrangement_planner.py`  

### **Step 2: Fix Audio Renderer** (Use new engines)

→ Update: `audio_renderer.py` to use LayerEngine, EnergyModulationEngine, etc.  
→ Implement: `_render_section()` to call all engines  
→ Implement: `_apply_section_effects()` with real effects  

### **Step 3: Update Render Worker** (Consume render plan events)

→ Update: `render_worker.py` to use render_plan_json events  
→ Add: Event processing loop reading variation/transition events  
→ Add: Logging to prove event-based rendering is used  

### **Step 4: Style Direction Integration** (Connect input → output)

→ Complete: `StyleDirectionEngine` mapping  
→ Create training data: Style text examples → production rules  
→ Test: "Drake R&B" → correct layer/energy/variation strategy  

### **Step 5: Testing & Validation**

→ Create: `test_producer_arrangement_fidelity.py`  
→ Test: Sections are audibly different (layer changes)  
→ Test: Energy curve matches audio loudness  
→ Test: Variations appear at expected bars  
→ Test: Transitions sound professional  

---

## Validation Checklist

- [ ] Arrangement output is **not** just repeated input loop
- [ ] Sections have **audibly different** characteristics (drums change, energy changes)
- [ ] Hooks are **louder/fuller** than verses
- [ ] Verse has **reduced melody** (space for vocals)
- [ ] Bridge is **noticeably reduced** energy
- [ ] Variations (fills) appear **every 4-8 bars**
- [ ] Transitions between sections are **smooth** (riser/impact)
- [ ] Duration is **within ±5% of requested** (e.g., 180s ± 9s)
- [ ] Frequency content changes with **layer masks** (kicks on/off visible in spectrogram)
- [ ] Energy curve **visually matches** audio amplitude envelope

---

## Quick File Checklist

To complete Phase 2, must create/modify:

**New Files:**
- [ ] `app/services/layer_engine.py` (200-300 lines)
- [ ] `app/services/energy_engine.py` (150-200 lines)
- [ ] `app/services/variation_engine.py` (250-350 lines)
- [ ] `app/services/transition_engine.py` (200-300 lines)
- [ ] `app/services/arrangement_planner.py` (150-200 lines)
- [ ] `tests/test_producer_arrangement_fidelity.py` (400-500 lines)

**Modify:**
- [ ] `app/services/audio_renderer.py` (complete stubs, integrate engines)
- [ ] `app/workers/render_worker.py` (improve event logging)
- [ ] `app/services/style_direction_engine.py` (complete mappings)

**Total new code:** ≈ 1500-2000 lines of producer logic

---

## Key Principles

1. **Don't break loop upload** - existing loops/arrangements still work
2. **Use render_plan events** - variation/transition placement is already planned
3. **Frequency analysis first** - detect layers before applying effects
4. **Energy → Effect mapping** - energy curve drives all audio changes
5. **Synthesis-based fills** - Create drum fills locally, don't sample
6. **Audio quality** - All effects use pydub or librosa for clean results

---

**Ready for implementation. Begin with Step 1: Layer Engine.**
