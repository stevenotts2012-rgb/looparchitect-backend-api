# STEM Producer Engine

## Overview
LoopArchitect now features a **complete stem-driven producer engine** that builds full musical arrangements from multiple instrumental stems instead of repeatedly processing a single stereo loop.

**Key Phases Implemented**:
- ✅ Phase 1: Stem input (ZIP extraction)
- ✅ Phase 2: Stem classification (role detection)
- ✅ Phase 3: Stem validation (compatibility checking)
- ✅ Phase 4: **Arrangement engine** (NEW - generates section plans)
- ✅ Phase 5: **Render executor** (NEW - mixes stems)
- ✅ Phase 6: **Producer moves** (NEW - musical events)
- ✅ Phase 7: **Hook evolution** (NEW - progressive intensity)
- ✅ Phase 8: **Render path router** (NEW - stem vs. loop decision)
- ✅ Phase 9: Database extensions (NEW - stem metadata fields)
- ✅ Phase 10: Comprehensive tests (NEW - full coverage)

## Input Modes
### Supported Input Formats

`POST /api/v1/loops/with-file` accepts:
- **`file`**: Single stereo loop (uses fallback LoopVariationEngine)
- **`stem_files`**: Multiple WAV/MP3 files, auto-classified by filename
- **`stem_zip`**: ZIP archive containing stem files (auto-extracted and classified)

**Classification Priority**:
1. Filename-based (fast): kick/drum/perc → drums; 808/bass → bass; lead/melody → melody, etc.
2. Audio-based (fallback): Frequency analysis (low/mid/high ratio) if filename unclear

**Result**: Loop model decorated with stem metadata (JSON in new database columns)

## Core Services
### Existing Services (Phases 1-3)
- **`stem_pack_extractor.py`**: Extracts audio from ZIP archives
- **`stem_classifier.py`**: Filename + audio analysis for role assignment
- **`stem_validation.py`**: Sample rate normalization and duration checking
- **`stem_pack_service.py`**: Coordinates extraction, classification, validation

### NEW Services (Phases 4-8)

#### `stem_arrangement_engine.py` (500 lines)
**Purpose**: Generates complete track arrangements from available stems

**Key Classes**:
- `StemArrangementEngine`
- `SectionConfig`: Section specification with active stems and processing
- `StemState`: Per-stem gain, pan, filter configuration
- Enums: `StemRole`, `ProducerMove`, `SectionType`

**Key Methods**:
```python
generate_arrangement(
    available_roles: Dict[StemRole, Path],
    target_bars: int,
    genre: str = "generic",
    intensity: float = 1.0,
) -> List[SectionConfig]
```

**What It Does**:
1. Plans section structure (intro → verse → hook → bridge → hook → outro)
2. Calculates energy level for each section (0.0-1.0 progression)
3. Selects which stems activate per section based on energy
4. Adds producer moves (drum_fill, riser, crash, etc.)
5. Returns complete section-by-section arrangement

**Example Output**: 
- Section 1: Intro, energy=0.3, active=[harmony, melody]
- Section 2: Verse, energy=0.5, active=[drums, bass]
- Section 3: Hook 1, energy=0.8, active=[drums, bass, melody], moves=[drum_fill, silence]
- Section 4: Hook 2, energy=0.9, active=[drums, bass, melody, harmony], moves=[snare_roll, riser]
- Section 5: Hook 3, energy=1.0, active=[all], moves=[crash_hit]

#### `stem_render_executor.py` (400 lines)
**Purpose**: Renders full audio by mixing stems according to arrangement plan

**Key Class**: `StemRenderExecutor`

**Key Methods**:
```python
render_from_stems(
    stem_files: Dict[StemRole, Path],
    sections: List[SectionConfig],
    apply_master: bool = True,
) -> AudioSegment
```

**What It Does**:
1. Loads all stem files into cache (memory-efficient)
2. For each section in order:
   - Extracts relevant time slice from each active stem
   - Applies per-stem processing (gain, pan, filter)
   - Applies producer moves (fills, silence, risers)
   - Mixes all active stems at -3dB each (prevents clipping)
3. Applies master limiting/normalization
4. Returns final AudioSegment ready for export

**Key Features**:
- **Stem looping**: If stem shorter than section, automatically loops
- **Producer move application**: Drum fills, silence gaps, riser effects
- **Gain staging**: -3dB mixing to prevent clipping
- **Pan implementation**: Stereo width for harmony/melody contrast

#### `render_path_router.py` (350 lines)
**Purpose**: Routes arrangements and orchestrates rendering

**Key Classes**:
- `RenderPathRouter`: Decision logic for stem vs. loop path
- `StemRenderOrchestrator`: Async rendering coordination

**Key Methods**:
```python
should_use_stem_path(loop: Loop) -> bool
route_and_arrange(
    loop: Loop,
    target_seconds: int,
    genre: str,
    intensity: float,
) -> Tuple[str, Dict]  # Returns ("stem" or "loop", arrangement_data)

render_arrangement_async(
    arrangement: Arrangement,
    output_key: str,
    storage_client,
) -> asyncio.Task
```

**Routing Logic**:
```
IF is_stem_pack AND stem_files_valid AND stem_validation_OK:
    → Use StemArrangementEngine + StemRenderExecutor (PHASE 4-5)
ELSE:
    → USE LoopVariationEngine (FALLBACK)
```

**Phase 8 Fallback**: Maintains 100% backward compatibility

## Role Model
### Stem Roles (5 Primary Categories)

```python
class StemRole(Enum):
  DRUMS = "drums"         # Percussion, kicks, snare, hi-hat
  BASS = "bass"           # 808, synth bass, bass guitar
  MELODY = "melody"       # Lead, vocal, main melodic element
  HARMONY = "harmony"     # Pads, chords, harmonic support
  FX = "fx"               # Effects, risers, transitions, impacts
```

**Auto-Detection Priority**:
| Filename Pattern | Role |
|-----------------|------|
| kick, drum, perc, snare, hh | drums |
| 808, bass, sub | bass |
| lead, melody, arp, guitar | melody |
| pad, chord, key, harmony, strings | harmony |
| fx, riser, impact, noise, atmos | fx |

## Arrangement Behavior
### How Arrangements Work

**Energy-Based Composition**:
- Each section has an energy level (0.0 = silence, 1.0 = maximum)
- Energy determines which stems activate
- Energy progression creates natural musical arc

**Hook Evolution Example**:
```
Hook 1 (energy 0.8):  [drums, bass, melody]
Hook 2 (energy 0.9):  [drums, bass, melody, harmony]  ← harmony added
Hook 3 (energy 1.0):  [drums, bass, melody, harmony, fx]  ← all active
```

**Pro Moves Applied**:
- Hook 1: drum_fill + pre_hook_silence  
- Hook 2: snare_roll + riser_fx
- Hook 3: crash_hit + pre_drop_buildout

**Result**: Professional-sounding multi-layered track with natural progression

### Database Extensions (Phase 9)

**Loop Model** - New Columns:
- `is_stem_pack` (bool): Marks stem pack inputs
- `stem_roles_json` (str): Available roles detected
- `stem_files_json` (str): File locations and metadata per role
- `stem_validation_json` (str): Validation status and any errors

**Arrangement Model** - New Columns:
- `stem_arrangement_json` (str): Full section-by-section arrangement plan
- `stem_render_path` (str): "stem" or "loop" indicator
- `rendered_from_stems` (bool): Flag for render path used

**Backward Compatibility**: All new columns nullable=True

## Compatibility
### Backward Compatibility ✅

✅ **No breaking changes**:
- Single-loop uploads always work (fallback to LoopVariationEngine)
- Old Arrangement responses unchanged
- Existing database rows unaffected (nullable columns)
- All existing API routes still functional
- Railway deployment compatible (no env var changes)

✅ **Graceful degradation**:
- Stems missing? → Uses loop path automatically
- Stems invalid? → Uses loop path automatically
- Fallback completely transparent to users

## Testing & Validation

Run tests with:
```bash
pytest tests/services/test_stem_engine.py -v
```

Coverage includes:
- ✅ ZIP extraction (Phase 1)
- ✅ Filename + audio classification (Phase 2)
- ✅ Arrangement generation (Phase 4)
- ✅ Hook evolution (Phase 7)
- ✅ Stem rendering (Phase 5)
- ✅ Path routing (Phase 8)
- ✅ End-to-end pipeline

## Next Steps for Deployment

1. **Run database migration**: Add 7 new columns to loops + arrangements tables
2. **Integrate routes**: Connect `/arrangements/generate` to new router
3. **Test locally**: Verify stem uploads classified correctly
4. **Deploy to Railway**: All changes backward compatible
5. **Monitor logs**: Verify stems load and render correctly
