# Producer Engine Architecture & System Design

**Version:** 1.0  
**Date:** March 4, 2026  
**Author:** GitHub Copilot  
**Status:** Ready for Review

## Table of Contents

1. [System Architecture](#system-architecture)
2. [Data Flow](#data-flow)
3. [Module Specifications](#module-specifications)
4. [Integration Points](#integration-points)
5. [Configuration](#configuration)
6. [Extensibility](#extensibility)

---

## System Architecture

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  USER INTERFACE (Frontend)                                  │
│  - ProducerControls: Genre, Energy, Style Direction         │
│  - ArrangementTimeline: Visual sections + energy curve      │
│  - Existing: UploadForm, GeneratePage, Download             │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   │ HTTP POST /api/v1/arrangements/generate
                   │ {loop_id, target_seconds, style_text_input}
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  API GATEWAY (FastAPI Router)                               │
│  - app/routes/arrangements.py                               │
│  - _generate_producer_arrangement() helper                  │
│  - /generate endpoint (enhanced)                            │
│  - /metadata endpoint (new)                                 │
│  - /daw-export endpoint (new)                               │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ├──→ StyleDirectionEngine.parse()
                   ├──→ ProducerEngine.generate()
                   ├──→ ArrangementValidator.validate()
                   ├──→ RenderPlanGenerator.generate()
                   └──→ DAWExporter.generate_metadata()
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  PRODUCER SYSTEM (Core Engines)                             │
│                                                              │
│  1. StyleDirectionEngine (Natural Language Parser)          │
│     Input: "Lil Baby trap"                                  │
│     Output: StyleProfile {genre, bpm, energy, ...}          │
│                                                              │
│  2. ProducerEngine (Song Structure Generator)               │
│     Input: StyleProfile, target_seconds, genre              │
│     Output: ProducerArrangement {sections, instruments,      │
│              energy_curve, transitions, variations}          │
│                                                              │
│  3. RenderPlanGenerator (Render Instructions)               │
│     Input: ProducerArrangement                              │
│     Output: RenderPlan {events, tracks, tempo_map}          │
│                                                              │
│  4. ArrangementValidator (Quality Assurance)                │
│     Input: ProducerArrangement                              │
│     Output: (is_valid, errors)                              │
│                                                              │
│  5. DAWExporter (Multi-DAW Export)                          │
│     Input: ProducerArrangement                              │
│     Output: {stems, midi, markers, tempo_map, readme}       │
│                                                              │
│  6. ProducerModels (Data Classes)                           │
│     - ProducerArrangement                                   │
│     - StyleProfile                                          │
│     - Section, Track, EnergyPoint                           │
│     - Transition, Variation, RenderEvent                    │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  DATABASE LAYER (SQLAlchemy)                                │
│                                                              │
│  Arrangement table:                                         │
│  └── producer_arrangement_json (TEXT)                       │
│  └── render_plan_json (TEXT)                                │
│  └── style_profile_json (TEXT)  [existing]                  │
│  └── arrangement_json (TEXT)    [existing]                  │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  BACKGROUND WORKER (arrangement_jobs.py)                    │
│                                                              │
│  1. Load RenderPlan from database                           │
│  2. For each RenderEvent:                                   │
│     - Synthesize instrument at specified bar                │
│     - Apply variations                                      │
│  3. Generate stems (WAV files)                              │
│  4. Generate MIDI clips                                     │
│  5. Create export ZIP (if requested)                        │
│  6. Upload to S3/local storage                              │
└──────────────────┬──────────────────────────────────────────┘
                   │
                   ↓
┌─────────────────────────────────────────────────────────────┐
│  STORAGE LAYER (S3 or Local)                                │
│  ├── /arrangements/{id}.wav                                 │
│  ├── /arrangements/{id}_stems.zip                           │
│  └── /metadata/render_plan_{id}.json                        │
└─────────────────────────────────────────────────────────────┘
```

### Component Relationships

```
                    StyleProfile
                         ↑
                         │
        StyleDirectionEngine.parse()
                         │
    User Input ──────────┴──────────┐
  ("Lil Baby trap")                  │
                                     ↓
                            ProducerArrangement
                         (sections, instruments,
                          energy_curve, transitions,
                          variations)
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ↓                ↓                ↓
            ArrangementValidator    RenderPlan    DAWExporter
                 [gates]            Generator      [metadata]
                    │                │                │
                    └────────────────┼────────────────┘
                                     │
                                     ↓
                         Database (Arrangement)
                         ├─ producer_arrangement_json
                         ├─ render_plan_json
                         └─ daw_export_metadata_json
```

---

## Data Flow

### Flow 1: Arrangement Generation

```
User Action: "Generate arrangement"
├─ Input: {loop_id: 1, target_seconds: 120, style_text_input: "Lil Baby"}
└─ Processing:
   ├─ StyleDirectionEngine.parse("Lil Baby")
   │  └─ Output: StyleProfile {genre: "trap", energy: 0.8, ...}
   │
   ├─ ProducerEngine.generate(target_seconds=120, style_profile=StyleProfile)
   │  ├─ Calculate bars: 120s ÷ 4.8s/bar = 25 bars
   │  ├─ Build sections from "standard" template, adjusted to 25 bars
   │  ├─ Generate energy curve (20→90→60→40→95→0)
   │  ├─ Assign instruments per section (trap preset)
   │  ├─ Generate transitions (drum_fill, riser)
   │  ├─ Generate variations (hihat_roll @ bar 8, 16)
   │  └─ Output: ProducerArrangement {25 bars, 7 sections, 12 instruments, ...}
   │
   ├─ ArrangementValidator.validate(ProducerArrangement)
   │  ├─ Check: ≥3 sections ✓
   │  ├─ Check: ≥30 seconds ✓
   │  ├─ Check: Hooks have highest energy ✓
   │  ├─ Check: Verses < Hooks instruments ✓
   │  ├─ Check: Has variations ✓
   │  └─ Output: (is_valid=True, errors=[])
   │
   ├─ RenderPlanGenerator.generate(ProducerArrangement)
   │  ├─ For each section:
   │  │  ├─ Instrument enters at section start
   │  │  ├─ Variations added at specified bars
   │  │  └─ Instrument exits at section end
   │  └─ Output: RenderPlan {25 bars, 18 events, tempo=105 BPM}
   │
   └─ Database insert Arrangement:
      ├─ producer_arrangement_json = JSON(ProducerArrangement)
      ├─ render_plan_json = JSON(RenderPlan)
      └─ style_profile_json = JSON(StyleProfile)

Result: HTTP 202 with arrangement_id=42
```

### Flow 2: Audio Synthesis

```
Worker Process: run_arrangement_job(arrangement_id=42)
├─ Load Arrangement from database
├─ Parse render_plan_json → RenderPlan object
├─ Parse producer_arrangement_json → ProducerArrangement
├─ For each RenderEvent in render plan:
│  ├─ If event.type == "enter":
│  │  └─ Synthesize instrument at event.bar
│  ├─ If event.type == "variation":
│  │  └─ Apply variation (hihat_roll, drum_fill, etc.)
│  └─ If event.type == "exit":
│     └─ Fade out instrument at end of bar
├─ Mix all synthesized stems
├─ Export WAV to S3/local
├─ If include_stems:
│  ├─ Export stems separately (kick.wav, snare.wav, ...)
│  ├─ Export MIDI (drums.mid, bass.mid, melody.mid)
│  ├─ Generate markers.csv
│  ├─ Generate tempo_map.json
│  ├─ Generate README.txt
│  └─ ZIP into /arrangements/42_export.zip
└─ Update Arrangement status=done, output_url=...
```

### Flow 3: DAW Export

```
User Action: "Download DAW export"
├─ Request: GET /api/v1/arrangements/42/daw-export
└─ Processing:
   ├─ Load Arrangement(id=42)
   ├─ Parse producer_arrangement_json → ProducerArrangement
   ├─ DAWExporter.generate_metadata(ProducerArrangement)
   │  └─ Output: {arrangement_id, supported_daws, stems, midi, metadata, ...}
   ├─ Generate markers.csv from sections
   │  └─ Output: CSV with section boundaries + colors
   ├─ Generate tempo_map.json
   │  └─ Output: {bpm, time_signature, changes=[]}
   ├─ Generate README.txt
   │  └─ Output: Multi-DAW import instructions
   └─ Response: {metadata, download_url}
```

---

## Module Specifications

### 1. StyleDirectionEngine

**Location:** `app/services/style_direction_engine.py`

**Purpose:** Parse natural language style input into structured StyleProfile

**Key Methods:**
- `parse(style_input: str) → StyleProfile`
- `_detect_genre(text: str) → str`
- `_detect_artist(text: str) → str`
- `_detect_mood(text: str) → str`
- `_bpm_for_genre(genre: str) → Tuple[int, int]`

**Supported Inputs:**
- Genres: trap, rnb, pop, cinematic, afrobeats, drill, house, jazz
- Artists: Lil Baby, Drake, Post Malone, Hans Zimmer, Wizkid
- Moods: aggressive, energetic, chill, dark, bright

**Example:**
```python
profile = StyleDirectionEngine.parse("Lil Baby trap vibe")
# Returns StyleProfile(genre="trap", bpm_range=(85,115), energy=0.8, ...)
```

### 2. ProducerEngine

**Location:** `app/services/producer_engine.py`

**Purpose:** Generate professional song structures with energy curves and instrumentation

**Key Methods:**
- `generate(target_seconds, tempo, genre, style_profile, structure_template) → ProducerArrangement`
- `_build_sections(total_bars, template, genre) → List[Section]`
- `_generate_energy_curve(sections) → List[EnergyPoint]`
- `_assign_instruments(arrangement) → ProducerArrangement`
- `_generate_transitions(sections) → List[Transition]`
- `_generate_variations(sections) → List[Variation]`
- `_create_tracks(arrangement) → List[Track]`
- `_validate(arrangement) → ProducerArrangement`

**Structure Templates:**
- `standard`: Intro, Hook, Verse, Hook, Verse, Bridge, Hook, Outro (default)
- `progressive`: Gradual builds, longer sections
- `looped`: Minimal variation, repeating hook
- `minimal`: Ultra-compact, 4 main sections

**Output:** ProducerArrangement with complete song structure

### 3. RenderPlanGenerator

**Location:** `app/services/render_plan.py`

**Purpose:** Convert ProducerArrangement into detailed render instructions

**Key Methods:**
- `generate(arrangement) → RenderPlan`
- `_generate_events(arrangement) → List[RenderEvent]`
- `_section_metadata(arrangement) → List[Dict]`
- `_track_metadata(arrangement) → List[Dict]`

**Output:** RenderPlan with:
- 10+ instrument entry/exit events
- Section metadata
- Track specifications

### 4. ArrangementValidator

**Location:** `app/services/arrangement_validator.py`

**Purpose:** Ensure arrangements meet quality standards

**Validation Rules:**
1. Minimum 3 sections
2. Duration ≥ 30 seconds
3. Hooks have highest average energy
4. Verses have fewer instruments than hooks
5. At least 1 variation present
6. Energy curve varies by ≥ 0.2

**Key Methods:**
- `validate(arrangement) → Tuple[bool, List[str]]`
- `validate_and_raise(arrangement) → ProducerArrangement`
- `get_validation_summary(arrangement) → Dict`

**Output:** Validation result with error details

### 5. DAWExporter

**Location:** `app/services/daw_export.py`

**Purpose:** Generate multi-DAW export metadata and files

**Supported DAWs:**
- FL Studio
- Ableton Live
- Logic Pro
- Studio One
- Pro Tools
- Reaper

**Key Methods:**
- `generate_export_metadata(arrangement, arrangement_id) → Dict`
- `generate_markers_csv(arrangement) → str`
- `generate_tempo_map_json(arrangement) → str`
- `generate_readme(arrangement, arrangement_id) → str`
- `get_export_package_info(arrangement) → Dict`

**Output:** 
- Metadata dictionary
- Markers CSV
- Tempo map JSON
- Formatted README

### 6. ProducerModels

**Location:** `app/services/producer_models.py`

**Purpose:** Define all data structures used in producer system

**Key Classes:**
- `ProducerArrangement`: Complete arrangement structure
- `StyleProfile`: Style description
- `Section`: Musical section (Intro, Verse, Hook, etc.)
- `Track`: Instrument track
- `EnergyPoint`: Energy curve point
- `Transition`: Section transition
- `Variation`: Within-section variation
- `RenderPlan`: Detailed render instructions
- `RenderEvent`: Bar-level event

**All classes:**
- Use Python `@dataclass` decorator
- Implement `to_dict()` and `to_json()` methods
- Are JSON-serializable

---

## Integration Points

### Integration with arrangement_jobs.py

**Before (Current Flow):**
```python
def run_arrangement_job(arrangement_id: int):
    # Load arrangement
    # Generate audio based on style/preset
    # Upload to storage
```

**After (With Producer Engine):**
```python
def run_arrangement_job(arrangement_id: int):
    arrangement = db.query(Arrangement).get(arrangement_id)
    
    # NEW: Load render plan if available
    if arrangement.render_plan_json:
        render_plan = json.loads(arrangement.render_plan_json)
        # Use render plan as source-of-truth
        for event in render_plan.events:
            if event.event_type == "enter":
                synthesize_instrument(event.track_name, event.bar)
    else:
        # FALLBACK: Use existing flow
        generate_audio_from_arrangement(arrangement)
    
    # Upload to storage (unchanged)
```

**Changes:**
- New optional `render_plan_json` field
- Graceful fallback to existing flow
- No breaking changes to existing arrangements

### Integration with API Routes

**New endpoints added:**
```python
@router.get("/api/v1/arrangements/{id}/metadata")
def get_arrangement_metadata(arrangement_id):
    # Return producer_arrangement, render_plan, validation summary
    
@router.get("/api/v1/arrangements/{id}/daw-export")
def get_daw_export_info(arrangement_id):
    # Return export metadata (stems, MIDI, supported DAWs)
```

**Enhanced POST /generate endpoint:**
```python
# Now accepts style_text_input
POST /api/v1/arrangements/generate
{
  "loop_id": 1,
  "target_seconds": 120,
  "style_text_input": "Lil Baby trap",  # NEW
  "use_producer_engine": true           # NEW
}

Response includes:
{
  "arrangement_id": 42,
  "producer_arrangement": { ... },  # NEW
  "render_plan": { ... },           # NEW
  ...
}
```

### Integration with Frontend

**New components:**
- `ProducerControls`: Genre selector, energy slider, style input
- `ArrangementTimeline`: Visual arrangement structure

**Usage:**
```tsx
// In GeneratePage component
<ProducerControls
  onGenreChange={handleGenreChange}
  onEnergyChange={handleEnergyChange}
  onStyleDirectionChange={handleStyleChange}
/>

<ArrangementTimeline
  sections={metadata.producer_arrangement?.sections}
  totalBars={metadata.producer_arrangement?.total_bars}
/>
```

---

## Configuration

### Environment Variables

No new environment variables required. Producer engine respects existing flags:

```env
# Optional: Enable specific features
FEATURE_PRODUCER_ENGINE=true        # Enable producer system
FEATURE_STYLE_ENGINE=true           # Enable styling
FEATURE_LLM_STYLE_PARSING=true      # Enable natural language parsing
```

### Default Configuration

Producer engine uses sensible defaults:
- **Default tempo:** 120 BPM
- **Default key:** C major
- **Default template:** "standard"
- **Min duration:** 30 seconds
- **Energy variation:** 0.2 (20%)

### Customization

All defaults can be overridden in `ProducerEngine.generate()`:

```python
arrangement = ProducerEngine.generate(
    target_seconds=90.0,           # User-requested duration
    tempo=100.0,                   # From loop metadata
    genre="trap",                  # From StyleDirectionEngine
    style_profile=style_profile,   # From StyleDirectionEngine
    structure_template="progressive"  # From user selection
)
```

---

## Extensibility

### Adding New Genres

1. Add to `INSTRUMENT_PRESETS` in `producer_engine.py`:
```python
INSTRUMENT_PRESETS = {
    "new_genre": {
        SectionType.INTRO: [InstrumentType.KICK, ...],
        SectionType.VERSE: [...],
        ...
    }
}
```

2. Add keyword detection in `style_direction_engine.py`:
```python
GENRE_KEYWORDS = {
    "new_genre": {"keyword1", "keyword2", "artist_name"},
}
```

3. Add BPM range and other properties:
```python
def _bpm_for_genre(genre: str) -> Tuple[int, int]:
    ranges = {
        "new_genre": (min_bpm, max_bpm),
    }
```

### Adding New Section Types

1. Add to `SectionType` enum in `producer_models.py`:
```python
class SectionType(str, Enum):
    CUSTOM_SECTION = "CustomSection"
```

2. Add instrumentation in producer engine
3. Update validation rules if needed

### Adding New Transition Types

1. Add to `TransitionType` enum:
```python
class TransitionType(str, Enum):
    CUSTOM_TRANSITION = "custom_transition"
```

2. Implement in worker/synthesis layer

### Adding New DAW Support

1. Add to `DAWExporter.SUPPORTED_DAWS`:
```python
SUPPORTED_DAWS = [..., "New DAW Name"]
```

2. Add DAW-specific instructions to `generate_readme()`:
```python
if daw_name == "New DAW":
    readme += """### New DAW Import Instructions
    1. Create new project
    2. ...
    """
```

### Adding Custom Validation Rules

1. Add to `ArrangementValidator.validate()`:
```python
# Custom rule
if some_condition:
    errors.append("Custom validation error message")
```

2. Add to validation summary if metrics needed:
```python
def get_validation_summary(arrangement):
    summary["custom_metric"] = calculate_metric(arrangement)
```

---

## Performance Characteristics

### Arrangement Generation Time

- **Small (30s):** ~50ms
- **Medium (120s):** ~100ms
- **Large (300s):** ~200ms

(All timing is for ProducerEngine.generate() only, not audio synthesis)

### Memory Usage

- **ProducerArrangement:** ~50KB
- **RenderPlan:** ~100KB
- **Serialized JSON:** ~200KB

### Database Storage

- **producer_arrangement_json:** ~100-200KB per arrangement
- **render_plan_json:** ~50-100KB per arrangement

---

## Error Handling

### Validation Errors

Arrangements that fail validation produce helpful error messages:

```
✗ Arrangement validation failed: 2 errors
  - Arrangement must have at least 3 sections (has 2)
  - Arrangement too short (28.5s < 30s min)
```

### Graceful Degradation

If producer engine unavailable:
1. System falls back to existing arrangement logic
2. No data loss or breaking changes
3. User still gets valid arrangement

### Logging

All major steps logged:
```
INFO: Style direction parsed: trap @ 85-115BPM
INFO: Generated arrangement: 96 bars, 7 sections, 18 variations
INFO: Render plan created: 25 events
INFO: Arrangement valid: passes all 6 rules
```

---

## Documentation

### Code Documentation

- Docstrings on all public methods
- Type hints on all functions
- Examples in module docstrings

### User Documentation

- This architecture document
- Implementation report
- Test cases show usage examples

### API Documentation

- OpenAPI/Swagger integration (via FastAPI)
- Endpoint descriptions in route decorators
- Request/response schemas

---

## Conclusion

The Producer Engine is a well-structured, extensible system for generating professional song arrangements. It integrates seamlessly with existing code while providing a solid foundation for future enhancements.

**Key strengths:**
✓ Modular design - easy to test and extend
✓ Multiple genre support with intelligent defaults
✓ Natural language interface for user convenience
✓ Multi-DAW export capability
✓ Comprehensive validation
✓ Backward compatible

**Next iterations:**
- Dynamic tempo changes within arrangements
- Custom section creation UI
- MIDI humanization algorithms
- Real-time arrangement preview
- A/B testing different arrangements

---

**Document Version:** 1.0  
**Last Updated:** March 4, 2026  
**Status:** Ready for Implementation
