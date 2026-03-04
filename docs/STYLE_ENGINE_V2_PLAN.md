# Style Engine V2 - LLM-Powered Natural Language Style Input

## Overview

This document outlines the comprehensive plan for implementing Style Engine V2, which adds LLM-powered natural language style input to LoopArchitect. Users will be able to type phrases like "Southside type, Lil Baby vibe, Metro but darker, beat switch after hook" and the system will parse their intent into a structured `StyleProfile` for arrangement generation.

---

## Current Architecture (Baseline)

### Upload Flow
```
User uploads loop → POST /loops/upload
  ↓
loop_service.validate_audio_file()
  ↓
loop_service.upload_loop_file() → S3 or local storage
  ↓
loop_analyzer.analyze_from_s3() → BPM, key, duration, bars
  ↓
Create Loop record in DB (id, name, bpm, key, bars, file_key, file_url)
```

### Generate Flow (Current)
```
User submits generate request → POST /arrangements/generate
  ↓
AudioArrangementGenerateRequest:
  - loop_id: int
  - target_seconds: int (10-3600)
  - genre: Optional[str]
  - intensity: Optional[str]
  - include_stems: bool
  - style_preset: Optional[str] (atl/dark/melodic/drill/cinematic/club/experimental)
  - style_params: Optional[dict]
  - seed: Optional[int | str]
  - variation_count: int (1-3)
  ↓
if style_preset provided:
  style_service.preview_structure() → generates section plan (intro/hook/verse/bridge/drop/outro)
  ↓
  Saves arrangement_json: {"seed": 123, "sections": [...]}
  ↓
Create Arrangement record (status="queued", progress=0.0)
  ↓
Schedule background_tasks.add_task(run_arrangement_job)
```

### Worker Flow (Current)
```
run_arrangement_job(arrangement_id):
  ↓
Load Arrangement + Loop from DB
  ↓
Download loop audio from S3 (presigned URL)
  ↓
Parse style sections from arrangement_json
  ↓
render_phase_b_arrangement(loop_audio, bpm, target_seconds, sections_override, seed)
  ↓
Export to WAV, upload to S3
  ↓
Update Arrangement (status="done", output_s3_key, output_url, progress=100.0)
```

### Current Style System
- **7 hardcoded presets** in `app/style_engine/presets.py`:
  - ATL, DARK, MELODIC, DRILL, CINEMATIC, CLUB, EXPERIMENTAL
- Each preset has:
  - `StyleParameters`: tempo_multiplier, drum_density, hat_roll_probability, glide_probability, swing, aggression, melody_complexity, fx_intensity
  - `section_templates`: Default structure (intro/hook/verse/bridge/drop/outro)
- **Feature flags** in `app/config.py`:
  - `FEATURE_STYLE_ENGINE` (enables preset selection)
  - `FEATURE_STYLE_SLIDERS` (reserved for UI overrides)
  - `FEATURE_VARIATIONS` (planned for multiple outputs)

### Database Schema
- **loops** table: id, name, bpm, musical_key, duration_seconds, bars, file_key, file_url
- **arrangements** table:
  - id, loop_id, status, progress, progress_message, target_seconds
  - genre, intensity, include_stems
  - output_s3_key, output_url
  - arrangement_json (TEXT) - stores `{"seed": 123, "sections": [...]}`
  - error_message
  - created_at, updated_at

### Frontend (Current)
- **generate/page.tsx**:
  - Loop ID input
  - Bars/duration selector
  - Style preset dropdown (fetches from `/api/styles`)
  - Seed input (optional)
  - Generate button → `generateArrangement()`
  - Progress polling → `getArrangementStatus()`
  - Download button + WaveformViewer + BeforeAfterComparison

---

## What Will Be Added (Style Engine V2)

### 1. LLM Integration Module
**File**: `app/services/llm_style_parser.py` (NEW)

**Purpose**: Parse natural language style descriptions into structured `StyleProfile`

**Architecture**:
```python
class LLMStyleParser:
    def __init__(self):
        self.client = OpenAI(api_key=settings.openai_api_key, base_url=settings.openai_base_url)
        self.model = settings.openai_model  # "gpt-4" or compatible
    
    async def parse_style_intent(
        self,
        user_input: str,
        loop_metadata: dict,  # {bpm, key, duration, bars}
        overrides: Optional[StyleOverrides] = None,
    ) -> StyleProfile:
        """
        Parse user's natural language style input into structured StyleProfile.
        
        Flow:
        1. Build prompt with user input + loop metadata + archetype library
        2. Call LLM with structured schema enforcement
        3. Parse response → StyleIntent (archetype + attributes + transitions)
        4. Map archetype → base StylePreset
        5. Apply attribute modifiers (aggression, darkness, bounce, etc.)
        6. Integrate user overrides (if any)
        7. Generate sections with beat switch logic
        8. Return validated StyleProfile
        """
        
    def _build_prompt(self, user_input: str, loop_metadata: dict) -> str:
        """Construct LLM prompt with examples and archetype library"""
        
    def _map_archetype_to_preset(self, archetype: str) -> StylePreset:
        """Map LLM archetype to existing StylePreset"""
        
    def _apply_attribute_modifiers(
        self,
        base_params: StyleParameters,
        attributes: dict[str, float],  # {aggression, darkness, bounce, ...}
    ) -> StyleParameters:
        """Adjust StyleParameters based on LLM-extracted attributes"""
        
    def _generate_sections_with_transitions(
        self,
        target_seconds: int,
        bpm: float,
        loop_bars: int,
        transitions: list[dict],  # [{"type": "beat_switch", "bar": 32, "new_energy": 0.9}]
        base_template: tuple[SectionTemplate, ...],
    ) -> list[dict]:
        """Generate section plan with beat switches and transitions"""
```

**Archetype Mapping**:
```python
ARCHETYPE_MAP = {
    "atl_aggressive": ("atl", {"aggression": +0.2, "drum_density": +0.1}),
    "atl_melodic": ("melodic", {"melody_complexity": +0.15, "aggression": -0.1}),
    "dark_drill": ("drill", {"aggression": +0.25, "fx_intensity": +0.1}),
    "melodic_trap": ("melodic", {"glide_probability": +0.1}),
    "cinematic_dark": ("cinematic", {"aggression": +0.15, "fx_intensity": +0.15}),
    "club_bounce": ("club", {"hat_roll_probability": +0.2, "swing": +0.05}),
    # 20+ total archetypes
}
```

**Attribute Dimensions** (0.0 - 1.0 scale):
- `aggression`: Drum intensity, transition harshness
- `darkness`: Bass weight, minor tonality preference
- `bounce`: Swing, hat roll probability, groove emphasis
- `melody_complexity`: Melody density, harmonic richness
- `energy_variance`: How much energy fluctuates between sections
- `transition_intensity`: Abruptness of section changes
- `fx_density`: Reverb, delay, filter sweeps
- `bass_presence`: Low-end weight

**Fallback Logic**:
```python
try:
    profile = await llm_parser.parse_style_intent(user_input, loop_metadata, overrides)
except (OpenAIError, ValidationError) as e:
    logger.warning("LLM parsing failed, falling back to rule-based: %s", e)
    profile = rule_based_parser.parse(user_input, loop_metadata)
```

### 2. Pydantic Models
**File**: `app/schemas/style_profile.py` (NEW)

```python
from pydantic import BaseModel, Field

class StyleIntent(BaseModel):
    """LLM-parsed intent from user's natural language input."""
    
    archetype: str = Field(..., description="Mapped archetype (atl_aggressive, etc.)")
    attributes: dict[str, float] = Field(
        default_factory=dict,
        description="Attribute modifiers (aggression, darkness, bounce, etc.)",
    )
    transitions: list[dict] = Field(
        default_factory=list,
        description="Special transitions like beat switches",
    )
    confidence: float = Field(default=1.0, ge=0.0, le=1.0, description="LLM confidence score")
    raw_input: str = Field(..., description="Original user input for audit")


class StyleOverrides(BaseModel):
    """User-specified overrides from frontend sliders."""
    
    aggression: Optional[float] = Field(None, ge=0.0, le=1.0)
    darkness: Optional[float] = Field(None, ge=0.0, le=1.0)
    bounce: Optional[float] = Field(None, ge=0.0, le=1.0)
    melody_complexity: Optional[float] = Field(None, ge=0.0, le=1.0)
    energy_variance: Optional[float] = Field(None, ge=0.0, le=1.0)
    transition_intensity: Optional[float] = Field(None, ge=0.0, le=1.0)
    fx_density: Optional[float] = Field(None, ge=0.0, le=1.0)
    bass_presence: Optional[float] = Field(None, ge=0.0, le=1.0)
    
    # Legacy StyleParameters overrides
    tempo_multiplier: Optional[float] = Field(None, ge=0.5, le=2.0)
    drum_density: Optional[float] = Field(None, ge=0.0, le=1.0)
    hat_roll_probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    glide_probability: Optional[float] = Field(None, ge=0.0, le=1.0)
    swing: Optional[float] = Field(None, ge=0.0, le=1.0)


class StyleProfile(BaseModel):
    """Complete style profile for arrangement rendering."""
    
    intent: StyleIntent
    overrides: Optional[StyleOverrides] = None
    resolved_preset: str = Field(..., description="Base preset after archetype mapping")
    resolved_params: dict = Field(..., description="Final StyleParameters as dict")
    sections: list[dict] = Field(..., description="Section plan with beat switches")
    seed: Optional[int] = Field(None, description="Seed for deterministic generation")
    
    class Config:
        json_schema_extra = {
            "example": {
                "intent": {
                    "archetype": "atl_aggressive",
                    "attributes": {"aggression": 0.85, "darkness": 0.6, "bounce": 0.7},
                    "transitions": [{"type": "beat_switch", "bar": 32, "new_energy": 0.95}],
                    "confidence": 0.92,
                    "raw_input": "Southside type, aggressive, beat switch after hook",
                },
                "resolved_preset": "atl",
                "resolved_params": {"aggression": 0.88, "drum_density": 0.82, ...},
                "sections": [
                    {"name": "intro", "bars": 8, "energy": 0.4},
                    {"name": "hook", "bars": 8, "energy": 0.85},
                    {"name": "beat_switch", "bars": 16, "energy": 0.95},
                ],
                "seed": 42,
            }
        }
```

### 3. Updated Request/Response Schemas
**File**: `app/schemas/arrangement.py` (MODIFIED)

```python
class AudioArrangementGenerateRequest(BaseModel):
    loop_id: int
    target_seconds: int
    
    # New V2 fields
    style_text_input: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Natural language style description (e.g., 'Southside type, Lil Baby vibe')",
    )
    use_ai_parsing: bool = Field(
        default=False,
        description="Enable LLM-powered style parsing (requires OPENAI_API_KEY)",
    )
    style_overrides: Optional[StyleOverrides] = Field(
        default=None,
        description="Manual slider overrides for style attributes",
    )
    
    # Legacy fields (still supported)
    style_preset: Optional[str] = Field(default=None, description="Legacy: atl/dark/melodic/...")
    style_params: Optional[dict] = Field(default=None, description="Legacy: direct parameter overrides")
    genre: Optional[str] = None
    intensity: Optional[str] = None
    seed: Optional[int | str] = None
    variation_count: int = Field(default=1, ge=1, le=5, description="Number of variations")
    variation_mode: str = Field(
        default="remix",
        description="Variation strategy: remix/energy/transition/experimental",
    )
    include_stems: bool = False


class AudioArrangementGenerateResponse(BaseModel):
    arrangement_id: int
    loop_id: int
    status: str
    created_at: datetime
    
    # New V2 fields
    style_profile_summary: Optional[dict] = Field(
        default=None,
        description="Parsed style profile summary for UI display",
    )
    ai_parsing_used: bool = Field(default=False, description="Whether LLM parsing was used")
    
    # Existing fields
    render_job_ids: list[str] = []
    seed_used: Optional[int] = None
    style_preset: Optional[str] = None
    structure_preview: list[StructurePreviewItem] = []
```

### 4. Database Migration
**File**: `migrations/versions/008_add_style_profile_to_arrangements.py` (NEW)

```python
"""Add style_profile_json column to arrangements table

Revision ID: 008
Revises: 007
Create Date: 2025-01-XX
"""

def upgrade():
    op.add_column(
        "arrangements",
        sa.Column("style_profile_json", sa.Text(), nullable=True),
    )
    op.add_column(
        "arrangements",
        sa.Column("ai_parsing_used", sa.Boolean(), nullable=True, default=False),
    )


def downgrade():
    op.drop_column("arrangements", "ai_parsing_used")
    op.drop_column("arrangements", "style_profile_json")
```

### 5. Config Updates
**File**: `app/config.py` (MODIFIED)

```python
class Settings(BaseSettings):
    # Existing fields...
    
    # New LLM settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4")
    openai_timeout: int = int(os.getenv("OPENAI_TIMEOUT", "30"))
    openai_max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
    
    # Feature flag for LLM parsing
    feature_llm_style_parsing: bool = os.getenv("FEATURE_LLM_STYLE_PARSING", "false").lower() == "true"
    
    def validate_startup(self):
        # Existing validation...
        
        if self.feature_llm_style_parsing:
            if not self.openai_api_key:
                logger.warning("FEATURE_LLM_STYLE_PARSING enabled but OPENAI_API_KEY not set. LLM parsing will fail.")
```

### 6. Updated Generate Endpoint
**File**: `app/routes/arrangements.py` (MODIFIED)

```python
from app.services.llm_style_parser import llm_style_parser, rule_based_fallback
from app.schemas.style_profile import StyleProfile

@router.post("/generate", ...)
async def generate_arrangement(
    request: AudioArrangementGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    # Validate loop exists
    loop = db.query(Loop).filter(Loop.id == request.loop_id).first()
    if not loop:
        raise HTTPException(404, f"Loop {request.loop_id} not found")
    
    style_profile_json = None
    style_profile_summary = None
    ai_parsing_used = False
    seed_used = request.seed or random.randint(1, 2**31 - 1)
    
    # V2 style processing: Natural language input
    if request.style_text_input and request.use_ai_parsing:
        if not settings.feature_llm_style_parsing or not settings.openai_api_key:
            raise HTTPException(400, "LLM style parsing not configured. Set OPENAI_API_KEY.")
        
        try:
            loop_metadata = {
                "bpm": loop.bpm or 120.0,
                "key": loop.musical_key,
                "duration": loop.duration_seconds,
                "bars": loop.bars or 4,
            }
            
            style_profile: StyleProfile = await llm_style_parser.parse_style_intent(
                user_input=request.style_text_input,
                loop_metadata=loop_metadata,
                overrides=request.style_overrides,
            )
            
            style_profile.seed = seed_used
            style_profile_json = style_profile.model_dump_json()
            style_profile_summary = {
                "archetype": style_profile.intent.archetype,
                "confidence": style_profile.intent.confidence,
                "sections_count": len(style_profile.sections),
            }
            ai_parsing_used = True
            
        except Exception as e:
            logger.exception("LLM parsing failed, falling back to rule-based")
            # Fallback to rule-based parsing
            style_profile = rule_based_fallback.parse(
                request.style_text_input,
                loop_metadata,
            )
            style_profile_json = style_profile.model_dump_json()
            ai_parsing_used = False
    
    # Legacy V1 style processing: Preset selection
    elif request.style_preset and settings.feature_style_engine:
        # Existing logic: style_service.preview_structure()
        ...
    
    # Create arrangement record
    arrangement = Arrangement(
        loop_id=request.loop_id,
        status="queued",
        target_seconds=request.target_seconds,
        arrangement_json=...,  # Legacy field for backward compat
        style_profile_json=style_profile_json,  # NEW
        ai_parsing_used=ai_parsing_used,  # NEW
        ...
    )
    db.add(arrangement)
    db.commit()
    db.refresh(arrangement)
    
    # Schedule worker
    background_tasks.add_task(run_arrangement_job, arrangement.id)
    
    return AudioArrangementGenerateResponse(
        arrangement_id=arrangement.id,
        style_profile_summary=style_profile_summary,
        ai_parsing_used=ai_parsing_used,
        ...
    )
```

### 7. Updated Worker
**File**: `app/services/arrangement_jobs.py` (MODIFIED)

```python
from app.schemas.style_profile import StyleProfile

def run_arrangement_job(arrangement_id: int):
    db = SessionLocal()
    try:
        arrangement = db.query(Arrangement).filter(...).first()
        loop = db.query(Loop).filter(...).first()
        
        # Download loop audio...
        
        # Parse style profile (V2 takes precedence over V1)
        style_sections = None
        seed = None
        resolved_params = None
        
        if arrangement.style_profile_json:
            # V2: Use StyleProfile
            style_profile = StyleProfile.model_validate_json(arrangement.style_profile_json)
            style_sections = style_profile.sections
            seed = style_profile.seed
            resolved_params = style_profile.resolved_params
            logger.info("Using StyleProfile from LLM parsing")
        
        elif arrangement.arrangement_json:
            # V1: Legacy preset-based sections
            style_sections = _parse_style_sections(arrangement.arrangement_json)
            seed = _parse_seed_from_json(arrangement.arrangement_json)
        
        # Render arrangement with resolved parameters
        arranged_audio, timeline_json = render_phase_b_arrangement(
            loop_audio=loop_audio,
            bpm=bpm,
            target_seconds=target_seconds,
            sections_override=style_sections,
            seed=seed,
            style_params_override=resolved_params,  # NEW parameter
        )
        
        # Upload to S3...
        # Update arrangement status...
    
    except Exception as e:
        logger.exception("Arrangement job failed")
        arrangement.status = "failed"
        arrangement.error_message = str(e)
        db.commit()
    
    finally:
        db.close()
```

### 8. Frontend Natural Language Input
**File**: `src/app/generate/page.tsx` (MODIFIED)

New state variables:
```typescript
const [styleMode, setStyleMode] = useState<'preset' | 'natural'>('preset')
const [styleTextInput, setStyleTextInput] = useState('')
const [useAiParsing, setUseAiParsing] = useState(true)
const [styleOverrides, setStyleOverrides] = useState<StyleOverrides>({})
const [showAdvancedControls, setShowAdvancedControls] = useState(false)
const [variationCount, setVariationCount] = useState(1)
const [variationMode, setVariationMode] = useState('remix')
```

New UI sections:
```tsx
{/* Style Input Mode Toggle */}
<div className="flex gap-2 mb-4">
  <button onClick={() => setStyleMode('preset')} className={...}>
    Preset Mode
  </button>
  <button onClick={() => setStyleMode('natural')} className={...}>
    Natural Language 🤖
  </button>
</div>

{styleMode === 'natural' ? (
  <>
    {/* Natural Language Input */}
    <textarea
      value={styleTextInput}
      onChange={(e) => setStyleTextInput(e.target.value)}
      placeholder="Describe the style you want... (e.g., 'Southside type, Lil Baby vibe, Metro but darker, beat switch after hook')"
      className="w-full h-32 p-3 border rounded-lg"
      maxLength={500}
    />
    
    {/* AI Parsing Toggle */}
    <label className="flex items-center gap-2 mt-2">
      <input
        type="checkbox"
        checked={useAiParsing}
        onChange={(e) => setUseAiParsing(e.target.checked)}
      />
      Use AI style parsing (requires OpenAI API key)
    </label>
    
    {/* Advanced Controls Accordion */}
    <details className="mt-4">
      <summary className="cursor-pointer font-semibold">
        Advanced Controls (Optional Overrides)
      </summary>
      <div className="grid grid-cols-2 gap-4 mt-4">
        {/* Aggression Slider */}
        <div>
          <label>Aggression: {styleOverrides.aggression ?? 0.5}</label>
          <input
            type="range"
            min="0"
            max="1"
            step="0.01"
            value={styleOverrides.aggression ?? 0.5}
            onChange={(e) => setStyleOverrides({
              ...styleOverrides,
              aggression: parseFloat(e.target.value)
            })}
          />
        </div>
        
        {/* Darkness Slider */}
        <div>
          <label>Darkness: {styleOverrides.darkness ?? 0.5}</label>
          <input type="range" ... />
        </div>
        
        {/* Bounce, Melody Complexity, Energy Variance, etc. */}
        {/* ... 8 total sliders ... */}
      </div>
    </details>
    
    {/* Variations Selector */}
    <div className="mt-4">
      <label>Generate Variations:</label>
      <select value={variationCount} onChange={(e) => setVariationCount(Number(e.target.value))}>
        <option value={1}>1 (single output)</option>
        <option value={3}>3 variations</option>
        <option value={5}>5 variations</option>
      </select>
      
      <label className="ml-4">Variation Mode:</label>
      <select value={variationMode} onChange={(e) => setVariationMode(e.target.value)}>
        <option value="remix">Remix (different sections)</option>
        <option value="energy">Energy (vary intensity)</option>
        <option value="transition">Transition (different drops)</option>
        <option value="experimental">Experimental (max variance)</option>
      </select>
    </div>
  </>
) : (
  /* Existing preset dropdown */
  <select value={stylePreset} onChange={...}>
    {stylePresets.map(p => <option key={p.id}>{p.display_name}</option>)}
  </select>
)}
```

### 9. API Client Updates
**File**: `api/client.ts` (MODIFIED)

```typescript
export interface StyleOverrides {
  aggression?: number
  darkness?: number
  bounce?: number
  melody_complexity?: number
  energy_variance?: number
  transition_intensity?: number
  fx_density?: number
  bass_presence?: number
}

export interface GenerateArrangementRequest {
  loop_id: number
  target_seconds: number
  
  // V2 fields
  style_text_input?: string
  use_ai_parsing?: boolean
  style_overrides?: StyleOverrides
  variation_count?: number
  variation_mode?: string
  
  // Legacy fields
  style_preset?: string
  genre?: string
  intensity?: string
  seed?: number | string
  include_stems?: boolean
}

export interface GenerateArrangementResponse {
  arrangement_id: number
  loop_id: number
  status: string
  created_at: string
  
  // V2 fields
  style_profile_summary?: {
    archetype: string
    confidence: number
    sections_count: number
  }
  ai_parsing_used?: boolean
  
  // Existing fields
  seed_used?: number
  style_preset?: string
  structure_preview: Array<{name: string; bars: number; energy: number}>
}

export async function generateArrangement(
  request: GenerateArrangementRequest
): Promise<GenerateArrangementResponse> {
  const response = await fetch(`${API_BASE_URL}/arrangements/generate`, {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(request),
  })
  if (!response.ok) throw new LoopArchitectApiError(...)
  return response.json()
}
```

---

## Data Flow Diagram (V2)

```
┌──────────────────────────────────────────────────────────────────┐
│ FRONTEND (Generate Page)                                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  User Input:                                                      │
│  ┌─────────────────────────────────────────────────────┐        │
│  │ Style Text: "Southside type, Lil Baby vibe,        │        │
│  │              Metro but darker, beat switch at 32"   │        │
│  └─────────────────────────────────────────────────────┘        │
│                                                                   │
│  Optional Overrides (Sliders):                                   │
│  ┌──────────┬──────────┬──────────┬──────────────┐             │
│  │Aggression│ Darkness │  Bounce  │ Melody Comp. │ ...         │
│  │   0.75   │   0.80   │   0.65   │    0.50      │             │
│  └──────────┴──────────┴──────────┴──────────────┘             │
│                                                                   │
│  Variations: [3 variations, "remix" mode]                        │
│                                                                   │
│  ✅ Use AI Parsing                                               │
│                                                                   │
│  [Generate Arrangement] ──────────────────────────────────────┐ │
└───────────────────────────────────────────────────────────────┼──┘
                                                                 │
                                                                 ▼
┌──────────────────────────────────────────────────────────────────┐
│ BACKEND API (POST /arrangements/generate)                        │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. Validate loop exists                                         │
│  2. Check feature flag: FEATURE_LLM_STYLE_PARSING                │
│  3. Prepare loop metadata: {bpm, key, duration, bars}            │
│                                                                   │
│  ┌────────────────────────────────────────────────────┐         │
│  │ LLM Style Parser (app/services/llm_style_parser.py)│         │
│  │                                                     │         │
│  │  Input:                                            │         │
│  │    - user_input: "Southside type, ..."            │         │
│  │    - loop_metadata: {bpm: 135, key: "A Minor", ...}│         │
│  │    - overrides: {aggression: 0.75, ...}           │         │
│  │                                                     │         │
│  │  ┌──────────────────────────────────────────┐    │         │
│  │  │ Step 1: Call OpenAI API                   │    │         │
│  │  │   Prompt:                                 │    │         │
│  │  │   "Parse this style description: ..."    │    │         │
│  │  │   "Available archetypes: atl_aggressive, │    │         │
│  │  │    dark_drill, melodic_trap, ..."        │    │         │
│  │  │   "Output JSON schema: {...}"            │    │         │
│  │  │                                           │    │         │
│  │  │   Response:                               │    │         │
│  │  │   {                                       │    │         │
│  │  │     "archetype": "atl_aggressive",       │    │         │
│  │  │     "attributes": {                       │    │         │
│  │  │       "aggression": 0.85,                │    │         │
│  │  │       "darkness": 0.70,                  │    │         │
│  │  │       "bounce": 0.60                     │    │         │
│  │  │     },                                    │    │         │
│  │  │     "transitions": [                      │    │         │
│  │  │       {"type": "beat_switch", "bar": 32} │    │         │
│  │  │     ]                                     │    │         │
│  │  │   }                                       │    │         │
│  │  └──────────────────────────────────────────┘    │         │
│  │                                                     │         │
│  │  ┌──────────────────────────────────────────┐    │         │
│  │  │ Step 2: Map archetype → StylePreset       │    │         │
│  │  │   "atl_aggressive" → ATL preset          │    │         │
│  │  │   Base params: {                          │    │         │
│  │  │     aggression: 0.68, drum_density: 0.72 │    │         │
│  │  │   }                                       │    │         │
│  │  └──────────────────────────────────────────┘    │         │
│  │                                                     │         │
│  │  ┌──────────────────────────────────────────┐    │         │
│  │  │ Step 3: Apply attribute modifiers         │    │         │
│  │  │   LLM attributes: {aggression: 0.85}     │    │         │
│  │  │   User overrides: {aggression: 0.75}     │    │         │
│  │  │   → Final: aggression = 0.75 (override)  │    │         │
│  │  │   → darkness: 0.70 (from LLM)            │    │         │
│  │  │                                           │    │         │
│  │  │   Apply blending:                         │    │         │
│  │  │   final_aggression = base * (1 + modifier)│   │         │
│  │  │   = 0.68 * (1 + 0.10) = 0.748           │    │         │
│  │  └──────────────────────────────────────────┘    │         │
│  │                                                     │         │
│  │  ┌──────────────────────────────────────────┐    │         │
│  │  │ Step 4: Generate sections with transitions │   │         │
│  │  │   Base template: intro/hook/verse/...     │    │         │
│  │  │   Insert beat_switch at bar 32:          │    │         │
│  │  │   [                                       │    │         │
│  │  │     {name: "intro", bars: 8, energy: 0.4}│    │         │
│  │  │     {name: "hook", bars: 8, energy: 0.85}│    │         │
│  │  │     {name: "verse", bars: 16, energy: 0.7}│   │         │
│  │  │     {name: "beat_switch", bars: 8, ...}  │    │         │
│  │  │     {name: "drop", bars: 8, energy: 0.95}│    │         │
│  │  │   ]                                       │    │         │
│  │  └──────────────────────────────────────────┘    │         │
│  │                                                     │         │
│  │  Output: StyleProfile                             │         │
│  │  {                                                 │         │
│  │    intent: StyleIntent {...},                     │         │
│  │    resolved_preset: "atl",                        │         │
│  │    resolved_params: {aggression: 0.75, ...},      │         │
│  │    sections: [{...}, {...}],                      │         │
│  │    seed: 42                                        │         │
│  │  }                                                 │         │
│  └────────────────────────────────────────────────────┘         │
│                                                                   │
│  4. Serialize StyleProfile → JSON                                │
│  5. Create Arrangement record:                                   │
│     - status: "queued"                                           │
│     - style_profile_json: "{...}"                                │
│     - ai_parsing_used: true                                      │
│  6. Schedule background job: run_arrangement_job(arrangement_id) │
│  7. Return response with style_profile_summary                   │
│                                                                   │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ WORKER (run_arrangement_job)                                     │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. Load Arrangement + Loop from database                        │
│  2. Download loop audio from S3 (presigned URL)                  │
│  3. Deserialize StyleProfile from style_profile_json             │
│                                                                   │
│  ┌────────────────────────────────────────────────────┐         │
│  │ StyleProfile:                                       │         │
│  │   sections: [intro(8), hook(8), verse(16), ...]   │         │
│  │   resolved_params: {aggression: 0.75, ...}        │         │
│  │   seed: 42                                          │         │
│  └────────────────────────────────────────────────────┘         │
│                                                                   │
│  4. Call render_phase_b_arrangement():                           │
│     - loop_audio: AudioSegment                                   │
│     - bpm: 135                                                   │
│     - target_seconds: 180                                        │
│     - sections_override: [...] (from StyleProfile)               │
│     - seed: 42                                                   │
│     - style_params_override: {...} (from StyleProfile)           │
│                                                                   │
│  ┌────────────────────────────────────────────────────┐         │
│  │ Arrangement Engine (render_phase_b_arrangement)    │         │
│  │                                                     │         │
│  │  - Apply resolved_params to audio synthesis        │         │
│  │  - Generate drums with aggression=0.75             │         │
│  │  - Generate bass with darkness=0.70                │         │
│  │  - Apply beat_switch transition at bar 32          │         │
│  │  - Use seed=42 for deterministic pattern gen       │         │
│  │  - Build timeline with section markers             │         │
│  │                                                     │         │
│  │  Output: (arranged_audio, timeline_json)           │         │
│  └────────────────────────────────────────────────────┘         │
│                                                                   │
│  5. Export arranged_audio to WAV (temp file)                     │
│  6. Upload WAV to S3: arrangements/{arrangement_id}.wav          │
│  7. Generate presigned URL (expires in 1 hour)                   │
│  8. Update Arrangement:                                          │
│     - status: "done"                                             │
│     - progress: 100.0                                            │
│     - output_s3_key: "arrangements/123.wav"                      │
│     - output_url: "https://s3.amazonaws.com/..."                │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│ FRONTEND (Polling)                                               │
├──────────────────────────────────────────────────────────────────┤
│                                                                   │
│  1. Poll GET /arrangements/{id} every 2 seconds                  │
│  2. Display progress bar: 0% → 25% → 50% → 75% → 100%          │
│  3. When status="done":                                          │
│     - Show "✅ Generation Complete!"                             │
│     - Display style_profile_summary:                             │
│       "Archetype: atl_aggressive (92% confidence)"               │
│     - Show download button                                       │
│     - Load waveform in BeforeAfterComparison component           │
│                                                                   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Files That Will Change

### Backend Changes

#### 🆕 NEW FILES
1. `app/services/llm_style_parser.py` - LLM integration (~300 lines)
2. `app/services/rule_based_fallback.py` - Fallback parser (~150 lines)
3. `app/schemas/style_profile.py` - Pydantic models (~200 lines)
4. `migrations/versions/008_add_style_profile_to_arrangements.py` - Migration (~30 lines)
5. `tests/test_llm_style_parser.py` - LLM parser tests (~200 lines)
6. `tests/test_style_profile_serialization.py` - Serialization tests (~100 lines)
7. `tests/test_determinism_with_style_profile.py` - Seed determinism tests (~150 lines)
8. `docs/STYLE_ENGINE_V2_PLAN.md` - This document (~1500 lines)
9. `docs/SMOKE_STYLE_ENGINE_V2.md` - Smoke testing guide (~300 lines)

#### ✏️ MODIFIED FILES
1. `app/config.py` - Add OpenAI settings (+15 lines)
2. `app/models/arrangement.py` - Add `style_profile_json`, `ai_parsing_used` columns (+2 lines)
3. `app/schemas/arrangement.py` - Extend request/response models (+50 lines)
4. `app/routes/arrangements.py` - Add LLM parsing logic to `/generate` (+80 lines)
5. `app/services/arrangement_jobs.py` - Parse and use StyleProfile in worker (+40 lines)
6. `app/services/arrangement_engine.py` - Accept `style_params_override` parameter (+20 lines)
7. `requirements.txt` - Add `openai>=1.0.0` (+1 line)
8. `.env.example` - Add OpenAI env vars (+5 lines)
9. `README.md` - Document LLM feature (+30 lines)

### Frontend Changes

#### ✏️ MODIFIED FILES
1. `src/app/generate/page.tsx` - Add natural language input UI (+200 lines)
2. `api/client.ts` - Update TypeScript types for V2 API (+50 lines)
3. `src/components/StyleOverridesSliders.tsx` (NEW) - Slider component (~150 lines)
4. `src/components/StyleProfileSummary.tsx` (NEW) - Display parsed style (~80 lines)
5. `.env.example` - Document backend env requirements (+5 lines)

---

## Implementation Order

### Phase 1: Backend Foundation (Days 1-2)
1. ✅ Create `app/schemas/style_profile.py` with Pydantic models
2. ✅ Update `app/config.py` with OpenAI settings
3. ✅ Add database migration for `style_profile_json` column
4. ✅ Run migration: `alembic upgrade head`
5. ✅ Update `app/models/arrangement.py` with new columns
6. ✅ Update `requirements.txt` with `openai>=1.0.0`
7. ✅ Run `pip install openai`

### Phase 2: LLM Integration Module (Days 2-3)
1. ✅ Create `app/services/llm_style_parser.py`:
   - Implement `LLMStyleParser` class
   - Implement `_build_prompt()` with archetype library
   - Implement `_map_archetype_to_preset()`
   - Implement `_apply_attribute_modifiers()`
   - Implement `_generate_sections_with_transitions()`
   - Add error handling and retries
2. ✅ Create `app/services/rule_based_fallback.py`:
   - Simple keyword matching parser
   - Fallback for when LLM fails or API key not set
3. ✅ Write unit tests:
   - `tests/test_llm_style_parser.py`
   - Test archetype mapping
   - Test attribute blending
   - Test beat switch insertion
   - Mock OpenAI API responses

### Phase 3: API Integration (Day 3)
1. ✅ Update `app/schemas/arrangement.py`:
   - Add `style_text_input`, `use_ai_parsing`, `style_overrides` to request
   - Add `style_profile_summary`, `ai_parsing_used` to response
2. ✅ Update `app/routes/arrangements.py`:
   - Add LLM parsing logic to `/generate` endpoint
   - Implement fallback logic
   - Serialize StyleProfile to JSON
   - Store in `arrangement.style_profile_json`
3. ✅ Test API endpoint:
   ```bash
   curl -X POST http://localhost:8000/arrangements/generate \
     -H "Content-Type: application/json" \
     -d '{
       "loop_id": 1,
       "target_seconds": 180,
       "style_text_input": "Southside type, aggressive, beat switch after hook",
       "use_ai_parsing": true,
       "style_overrides": {"aggression": 0.80}
     }'
   ```

### Phase 4: Worker Integration (Day 4)
1. ✅ Update `app/services/arrangement_jobs.py`:
   - Deserialize `StyleProfile` from `style_profile_json`
   - Extract `sections` and `resolved_params`
   - Pass to `render_phase_b_arrangement()`
2. ✅ Update `app/services/arrangement_engine.py`:
   - Accept `style_params_override` parameter
   - Apply overrides to audio synthesis
   - Handle beat_switch transitions
3. ✅ Test end-to-end generation:
   ```bash
   # Upload loop
   curl -X POST http://localhost:8000/loops/upload -F "file=@test_loop.wav"
   
   # Generate with LLM style
   curl -X POST http://localhost:8000/arrangements/generate -d '{...}'
   
   # Poll status
   curl http://localhost:8000/arrangements/123
   
   # Download result
   curl http://localhost:8000/arrangements/123/download -o result.wav
   ```

### Phase 5: Frontend UI (Days 5-6)
1. ✅ Update `api/client.ts`:
   - Add `StyleOverrides` interface
   - Update `GenerateArrangementRequest` type
   - Update `GenerateArrangementResponse` type
2. ✅ Create `src/components/StyleOverridesSliders.tsx`:
   - 8 sliders (aggression, darkness, bounce, etc.)
   - Range: 0.0 - 1.0, step 0.01
   - Display current value
   - Reset button
3. ✅ Create `src/components/StyleProfileSummary.tsx`:
   - Display archetype, confidence, sections count
   - Show section timeline visualization
4. ✅ Update `src/app/generate/page.tsx`:
   - Add styleMode toggle (preset vs natural)
   - Add natural language textarea
   - Add "Use AI Parsing" checkbox
   - Add advanced controls accordion
   - Add variations selector
   - Update generateArrangement() call
   - Display StyleProfileSummary after generation

### Phase 6: Testing & Validation (Day 7)
1. ✅ Determinism tests:
   ```python
   # tests/test_determinism_with_style_profile.py
   def test_same_seed_same_output():
       profile1 = parse_style("Southside type", seed=42)
       profile2 = parse_style("Southside type", seed=42)
       assert profile1.sections == profile2.sections
       assert profile1.resolved_params == profile2.resolved_params
   ```

2. ✅ Validation tests:
   ```python
   def test_invalid_style_text_input():
       with pytest.raises(ValidationError):
           AudioArrangementGenerateRequest(
               loop_id=1,
               target_seconds=180,
               style_text_input="a" * 501,  # exceeds max_length=500
           )
   ```

3. ✅ S3 path tests:
   ```python
   def test_style_profile_s3_storage():
       arrangement = create_arrangement_with_style_profile()
       assert arrangement.style_profile_json is not None
       profile = StyleProfile.model_validate_json(arrangement.style_profile_json)
       assert profile.intent.archetype in ARCHETYPE_MAP
   ```

4. ✅ End-to-end smoke test (manual):
   - See `docs/SMOKE_STYLE_ENGINE_V2.md`

### Phase 7: Documentation & Deployment (Day 8)
1. ✅ Create `docs/SMOKE_STYLE_ENGINE_V2.md`:
   - Step-by-step testing procedure
   - Expected outputs
   - Troubleshooting guide
2. ✅ Update `README.md`:
   - Document new feature
   - Environment variables
   - Example usage
3. ✅ Update `.env.example`:
   ```bash
   # LLM Style Parsing
   OPENAI_API_KEY=sk-...
   OPENAI_BASE_URL=https://api.openai.com/v1  # Or compatible endpoint
   OPENAI_MODEL=gpt-4
   FEATURE_LLM_STYLE_PARSING=true
   ```
4. ✅ Railway deployment:
   - Set environment variables in Railway dashboard
   - Test LLM parsing in production
   - Verify S3 paths work correctly
   - Monitor logs for errors

---

## Testing Strategy

### Unit Tests

#### 1. LLM Parser Tests
```python
# tests/test_llm_style_parser.py

@pytest.mark.asyncio
async def test_parse_style_intent_basic():
    parser = LLMStyleParser()
    profile = await parser.parse_style_intent(
        user_input="Southside type, aggressive",
        loop_metadata={"bpm": 135, "key": "A Minor", "duration": 10, "bars": 4},
    )
    assert profile.intent.archetype in ["atl_aggressive", "atl", "dark"]
    assert profile.intent.attributes["aggression"] > 0.7
    assert profile.resolved_preset in ["atl", "dark"]


@pytest.mark.asyncio
async def test_archetype_mapping():
    parser = LLMStyleParser()
    preset = parser._map_archetype_to_preset("dark_drill")
    assert preset.id == StylePresetName.DRILL
    

def test_attribute_modifiers():
    parser = LLMStyleParser()
    base_params = StyleParameters(aggression=0.5, drum_density=0.6)
    attributes = {"aggression": 0.2, "darkness": 0.3}  # +20% aggression
    
    modified = parser._apply_attribute_modifiers(base_params, attributes)
    assert modified.aggression > 0.5  # Should be increased
    

def test_beat_switch_insertion():
    parser = LLMStyleParser()
    transitions = [{"type": "beat_switch", "bar": 32, "new_energy": 0.9}]
    sections = parser._generate_sections_with_transitions(
        target_seconds=180,
        bpm=135,
        loop_bars=4,
        transitions=transitions,
        base_template=DEFAULT_TEMPLATE,
    )
    
    # Should have beat_switch section around bar 32
    beat_switches = [s for s in sections if "switch" in s["name"].lower()]
    assert len(beat_switches) > 0
```

#### 2. Determinism Tests
```python
# tests/test_determinism_with_style_profile.py

@pytest.mark.asyncio
async def test_same_seed_produces_identical_profile():
    parser = LLMStyleParser()
    
    profile1 = await parser.parse_style_intent(
        user_input="ATL style, bouncy",
        loop_metadata={"bpm": 140, "key": "C Minor", "duration": 10, "bars": 4},
    )
    profile1.seed = 42
    
    profile2 = await parser.parse_style_intent(
        user_input="ATL style, bouncy",
        loop_metadata={"bpm": 140, "key": "C Minor", "duration": 10, "bars": 4},
    )
    profile2.seed = 42
    
    # Sections should be deterministic with same seed
    assert profile1.sections == profile2.sections
```

#### 3. Serialization Tests
```python
# tests/test_style_profile_serialization.py

def test_style_profile_json_roundtrip():
    profile = StyleProfile(
        intent=StyleIntent(
            archetype="atl_aggressive",
            attributes={"aggression": 0.85},
            transitions=[],
            confidence=0.92,
            raw_input="Southside type",
        ),
        resolved_preset="atl",
        resolved_params={"aggression": 0.85, "drum_density": 0.72},
        sections=[{"name": "intro", "bars": 8, "energy": 0.4}],
        seed=42,
    )
    
    # Serialize to JSON
    json_str = profile.model_dump_json()
    
    # Deserialize
    profile2 = StyleProfile.model_validate_json(json_str)
    
    assert profile.intent.archetype == profile2.intent.archetype
    assert profile.seed == profile2.seed
```

### Integration Tests

#### 4. API Endpoint Tests
```python
# tests/test_arrangements_api_v2.py

def test_generate_with_style_text_input(client, db_with_loop):
    response = client.post("/arrangements/generate", json={
        "loop_id": 1,
        "target_seconds": 180,
        "style_text_input": "Southside type, aggressive",
        "use_ai_parsing": True,
    })
    
    assert response.status_code == 202
    data = response.json()
    assert data["ai_parsing_used"] is True
    assert "style_profile_summary" in data
    assert data["style_profile_summary"]["archetype"] in ARCHETYPE_MAP


def test_fallback_when_llm_fails(client, db_with_loop, monkeypatch):
    # Mock OpenAI to raise error
    monkeypatch.setattr("app.services.llm_style_parser.openai.chat.completions.create", lambda **kwargs: (_ for _ in ()).throw(Exception("API error")))
    
    response = client.post("/arrangements/generate", json={
        "loop_id": 1,
        "target_seconds": 180,
        "style_text_input": "dark style",
        "use_ai_parsing": True,
    })
    
    assert response.status_code == 202
    # Should fall back to rule-based parsing
    data = response.json()
    assert data["ai_parsing_used"] is False
```

#### 5. Worker Tests
```python
# tests/test_arrangement_jobs_with_style_profile.py

def test_worker_uses_style_profile(db_with_loop_and_arrangement):
    arrangement = db_with_loop_and_arrangement
    
    # Create StyleProfile and serialize
    profile = StyleProfile(...)
    arrangement.style_profile_json = profile.model_dump_json()
    
    # Run worker
    run_arrangement_job(arrangement.id)
    
    # Verify output
    db = SessionLocal()
    arrangement = db.query(Arrangement).filter(Arrangement.id == arrangement.id).first()
    assert arrangement.status == "done"
    assert arrangement.output_s3_key is not None
```

### Manual Smoke Tests

See `docs/SMOKE_STYLE_ENGINE_V2.md` for comprehensive manual testing procedure.

---

## Environment Variables

### Development (.env)
```bash
# Existing vars...
ENVIRONMENT=development
STORAGE_BACKEND=local
DATABASE_URL=sqlite:///./looparchitect.db

# NEW: OpenAI settings
OPENAI_API_KEY=sk-proj-...
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4
OPENAI_TIMEOUT=30
OPENAI_MAX_RETRIES=3

# NEW: Feature flag
FEATURE_LLM_STYLE_PARSING=true
```

### Production (Railway)
```bash
# Existing vars...
ENVIRONMENT=production
STORAGE_BACKEND=s3
DATABASE_URL=${DATABASE_URL}  # From Railway
AWS_S3_BUCKET=looparchitect-prod
AWS_ACCESS_KEY_ID=...
AWS_SECRET_ACCESS_KEY=...
AWS_REGION=us-east-1

# NEW: OpenAI settings
OPENAI_API_KEY=sk-proj-...  # Production key with higher rate limits
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_MODEL=gpt-4
FEATURE_LLM_STYLE_PARSING=true
```

---

## Risks & Mitigations

### Risk 1: OpenAI API Costs
**Impact**: High usage could result in significant API costs

**Mitigation**:
- Add rate limiting (e.g., 10 requests/minute per user)
- Cache LLM responses for identical inputs (TTL: 1 hour)
- Implement usage tracking and alerts
- Provide rule-based fallback as free alternative
- Consider self-hosted models (Ollama, vLLM) for cost-sensitive deployments

### Risk 2: LLM Response Quality
**Impact**: LLM may misinterpret user intent or return invalid JSON

**Mitigation**:
- Use structured output enforcement (OpenAI JSON mode)
- Validate LLM response against Pydantic schema
- Implement confidence scoring
- Fall back to rule-based parsing on low confidence (<0.5)
- Log all LLM responses for quality monitoring

### Risk 3: Backward Compatibility
**Impact**: Existing preset-based generation must continue working

**Mitigation**:
- Keep legacy `style_preset` field functional
- V2 only activates when `style_text_input` is provided
- Worker checks `style_profile_json` first, falls back to `arrangement_json`
- No breaking changes to existing API contracts

### Risk 4: Database Migration Failure
**Impact**: Production migration could fail or cause downtime

**Mitigation**:
- Test migration on development DB first
- Use `nullable=True` for new columns (non-breaking)
- Create rollback migration script
- Schedule migration during low-traffic window
- Monitor Railway logs during deployment

### Risk 5: Performance Degradation
**Impact**: LLM API calls could slow down generate endpoint

**Mitigation**:
- Make LLM call async (don't block request)
- Set timeout (30s default)
- Return 202 immediately, process LLM in worker if needed
- Add performance monitoring (track p50, p95, p99 latency)
- Consider moving LLM parsing to worker entirely

---

## Success Criteria

### Functional Requirements
- ✅ Users can input natural language style descriptions (max 500 chars)
- ✅ LLM parses input into structured `StyleProfile`
- ✅ System maps archetypes to existing presets
- ✅ Attribute modifiers correctly adjust audio parameters
- ✅ Beat switches appear at specified bar positions
- ✅ Users can override LLM output with sliders
- ✅ Variations system generates multiple outputs (1/3/5)
- ✅ Rule-based fallback works when LLM unavailable
- ✅ Legacy preset mode continues working
- ✅ All tests pass (unit + integration)

### Non-Functional Requirements
- ✅ Generate endpoint responds within 5 seconds (LLM call excluded)
- ✅ LLM parsing completes within 30 seconds (95th percentile)
- ✅ Database migration runs without errors
- ✅ Railway deployment succeeds with no downtime
- ✅ Backend logs contain no critical errors
- ✅ Frontend UI is responsive and intuitive
- ✅ API documentation is up-to-date (Swagger/OpenAPI)

### User Acceptance Criteria
- User can type "Southside type, Metro but darker" and get appropriate output
- User can request "beat switch after hook" and hear it in the result
- User can adjust sliders to fine-tune LLM output
- User can toggle between preset mode and natural language mode
- User sees confidence score and archetype in response
- User can download arrangement with same quality as V1

---

## Next Steps

1. **Review this plan** with stakeholders/team
2. **Set up OpenAI API account** and get production API key
3. **Create GitHub issues** for each phase (8 total)
4. **Start Phase 1**: Backend foundation (Pydantic models + config)
5. **Daily standups** to track progress
6. **Code reviews** for LLM integration module (critical component)
7. **QA testing** before Railway deployment
8. **Create SMOKE_STYLE_ENGINE_V2.md** with detailed test scenarios
9. **Deploy to Railway** with monitoring enabled
10. **Gather user feedback** and iterate

---

## Appendix A: Example LLM Prompt

```
You are a music production assistant that parses style descriptions into structured data.

User Input: "{user_input}"

Loop Metadata:
- BPM: {bpm}
- Key: {key}
- Duration: {duration}s
- Bars: {bars}

Available Archetypes:
- atl_aggressive: High-energy Atlanta trap with punchy drums
- atl_melodic: Smoother ATL with more melody
- dark_drill: Heavy, aggressive drill with sliding bass
- melodic_trap: Melodic-focused trap with rich harmony
- cinematic_dark: Atmospheric with tension and releases
- club_bounce: Groove-forward, repetitive, high energy
- experimental: Unpredictable patterns and transitions

Parse the user's style description into JSON:

{
  "archetype": "atl_aggressive",
  "attributes": {
    "aggression": 0.85,
    "darkness": 0.70,
    "bounce": 0.60,
    "melody_complexity": 0.45,
    "energy_variance": 0.50,
    "transition_intensity": 0.75,
    "fx_density": 0.60,
    "bass_presence": 0.80
  },
  "transitions": [
    {"type": "beat_switch", "bar": 32, "new_energy": 0.95}
  ],
  "confidence": 0.92
}

Guidelines:
- All attribute values must be between 0.0 and 1.0
- "confidence" reflects how well you understand the user's intent
- If user mentions "beat switch" or "drop", include in transitions array
- Map producer names to archetypes:
  - "Southside", "808 Mafia" → atl_aggressive
  - "Metro Boomin" → dark_drill or atl_aggressive
  - "Lil Baby", "Gunna" → melodic_trap
  - "Pierre Bourne" → melodic_trap
  - "Wheezy" → atl_melodic
  - "Tay Keith" → dark_drill
- Adjectives:
  - "aggressive", "hard" → high aggression
  - "dark", "heavy" → high darkness
  - "bouncy", "groovy" → high bounce
  - "melodic", "smooth" → high melody_complexity
  
Return only valid JSON, no extra text.
```

---

## Appendix B: Archetype Library (Full List)

```python
ARCHETYPE_MAP = {
    # ATL Variants
    "atl": ("atl", {}),
    "atl_aggressive": ("atl", {"aggression": +0.20, "drum_density": +0.10}),
    "atl_melodic": ("melodic", {"melody_complexity": +0.15, "aggression": -0.10}),
    "atl_bouncy": ("atl", {"bounce": +0.15, "swing": +0.05}),
    
    # Dark Variants
    "dark": ("dark", {}),
    "dark_drill": ("drill", {"aggression": +0.15, "darkness": +0.10}),
    "dark_cinematic": ("cinematic", {"darkness": +0.20, "fx_intensity": +0.15}),
    "dark_trap": ("dark", {"bass_presence": +0.15}),
    
    # Melodic Variants
    "melodic": ("melodic", {}),
    "melodic_trap": ("melodic", {"glide_probability": +0.10}),
    "melodic_drill": ("drill", {"melody_complexity": +0.20, "aggression": -0.10}),
    "melodic_ambient": ("cinematic", {"melody_complexity": +0.25, "fx_intensity": +0.20}),
    
    # Drill Variants
    "drill": ("drill", {}),
    "drill_aggressive": ("drill", {"aggression": +0.15, "hat_roll_probability": +0.10}),
    "drill_uk": ("drill", {"bounce": +0.20, "tempo_multiplier": +0.05}),
    "drill_melodic": ("drill", {"melody_complexity": +0.15}),
    
    # Cinematic Variants
    "cinematic": ("cinematic", {}),
    "cinematic_dark": ("cinematic", {"darkness": +0.20, "bass_presence": +0.15}),
    "cinematic_epic": ("cinematic", {"energy_variance": +0.25, "transition_intensity": +0.20}),
    
    # Club Variants
    "club": ("club", {}),
    "club_bounce": ("club", {"bounce": +0.20, "swing": +0.10}),
    "club_aggressive": ("club", {"aggression": +0.15, "drum_density": +0.10}),
    
    # Experimental
    "experimental": ("experimental", {}),
    "experimental_chaotic": ("experimental", {"transition_intensity": +0.25, "fx_density": +0.20}),
}
```

---

## Appendix C: Variations System Design

### Variation Modes

**1. Remix Mode** (default):
- Generate N different section arrangements
- Same style profile, different section order
- Example: Intro→Hook→Verse vs Intro→Verse→Hook

**2. Energy Mode**:
- Vary energy curve across sections
- Same structure, different intensity levels
- Example: V1 calm→intense, V2 intense throughout, V3 wave pattern

**3. Transition Mode**:
- Different transition types between sections
- Example: V1 hard cuts, V2 smooth fades, V3 beat switches

**4. Experimental Mode**:
- Max randomization within bounds
- Different seeds for each variation
- Different archetypes within same family

### Implementation
```python
class VariationGenerator:
    def generate_variations(
        self,
        base_profile: StyleProfile,
        count: int,
        mode: str,
    ) -> list[StyleProfile]:
        """Generate N variations of a base profile."""
        
        if mode == "remix":
            return self._remix_sections(base_profile, count)
        elif mode == "energy":
            return self._vary_energy(base_profile, count)
        elif mode == "transition":
            return self._vary_transitions(base_profile, count)
        elif mode == "experimental":
            return self._experimental_variations(base_profile, count)
```

---

**End of Plan Document**

This plan provides a comprehensive roadmap for implementing Style Engine V2. Estimated total development time: **8-10 days** for a single developer, or **4-5 days** for a team of 2-3.

**Priority**: Implement Phases 1-4 first (backend foundation + LLM integration + worker) to validate technical feasibility. Frontend UI (Phase 5) can be developed in parallel by a separate team member.

**Recommended Next Action**: Create `docs/SMOKE_STYLE_ENGINE_V2.md` with detailed manual testing procedures, then begin Phase 1 implementation.
