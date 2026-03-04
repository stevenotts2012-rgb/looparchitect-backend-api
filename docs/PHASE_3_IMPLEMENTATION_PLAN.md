# PHASE 3: Style Direction Engine Implementation Plan

**Status:** Planning Phase  
**Target:** Parameterized style control with UI sliders and validation

---

## Overview

PHASE 3 will transform the Style Direction Engine from **text-only input** to a **comprehensive parameterized system** with:

1. **Style Parameter Sliders** — Granular control over audio generation
2. **Reference & Avoid Lists** — Reference artists/styles and exclusions
3. **Validation & Preview** — Real-time style validation without rendering
4. **DAW Export Preparation** — Structure for stems/MIDI export

---

## Architecture

```
┌─────────────────────────────┐
│  Frontend (Next.js)         │
├─────────────────────────────┤
│ StyleDirection Component    │
│ - Natural Language Input    │ (text)
│ - Parameter Sliders         │ (energy, darkness, bounce, etc.)
│ - Reference/Avoid Lists     │ (chips)
│ - Style Preview (no render) │ (validation only)
└────────┬──────────────────┘
         │ POST /api/v1/arrangements/validate-style
         │ (new endpoint: validate without rendering)
         │
         ↓
┌─────────────────────────────┐
│  Backend (FastAPI)          │
├─────────────────────────────┤
│ StyleProfile (Pydantic)     │
│ - intent: str               │ (from LLM or text input)
│ - energy: float (0-1)       │ (loud/quiet)
│ - darkness: float (0-1)     │ (dark/bright)
│ - bounce: float (0-1)       │ (laid-back/driving)
│ - warmth: float (0-1)       │ (warm/cold)
│ - texture: str              │ (smooth/gritty)
│ - references: List[str]     │ (artists/tracks to reference)
│ - avoid: List[str]          │ (styles/elements to avoid)
│ - seed: int                 │ (for reproducibility)
│ - confidence: float (0-1)   │ (how certain the parser is)
├─────────────────────────────┤
│ Validation Service          │
│ - Validate parameters       │
│ - Check if style possible   │
│ - Return normalized profile │
└────────┬──────────────────┘
         │ Stores in Arrangement.style_profile_json
         │
         ↓ (when user clicks "Generate")
┌─────────────────────────────┐
│ Background Render Job       │
│ - Fetch style_profile       │
│ - Render using parameters   │
│ - (Future: separate stems)  │
└─────────────────────────────┘
```

---

## Implementation Tasks

### Task 1: Backend StyleProfile Schema

**File:** `app/models/style_profile.py` (new)

```python
from pydantic import BaseModel, Field
from typing import List, Optional

class StyleProfile(BaseModel):
    """Parameterized style direction for arrangement rendering."""
    
    # Text-based intent (from LLM or natural language input)
    intent: str = Field(..., description="High-level style description", min_length=1, max_length=500)
    
    # Energy/intensity spectrum
    energy: float = Field(default=0.5, ge=0, le=1, description="Energy level: 0=quiet, 1=loud")
    
    # Tone/darkness spectrum
    darkness: float = Field(default=0.5, ge=0, le=1, description="Tone: 0=bright/uplifting, 1=dark/moody")
    
    # Rhythm/groove spectrum
    bounce: float = Field(default=0.5, ge=0, le=1, description="Groove: 0=laid-back, 1=driving/tight")
    
    # Timbre/texture spectrum
    warmth: float = Field(default=0.5, ge=0, le=1, description="Timbre: 0=cold/clinical, 1=warm/organic")
    
    # Texture quality
    texture: str = Field(default="balanced", description="Texture type: smooth, balanced, gritty")
    
    # Reference materials
    references: List[str] = Field(default_factory=list, description="Artists/tracks to reference")
    avoid: List[str] = Field(default_factory=list, description="Styles/elements to avoid")
    
    # Processing control
    seed: int = Field(default=42, description="Random seed for reproducibility")
    confidence: float = Field(default=0.8, ge=0, le=1, description="Parser confidence")
    
    class Config:
        json_schema_extra = {
            "example": {
                "intent": "cinematic dark atmospheric synthwave",
                "energy": 0.6,
                "darkness": 0.8,
                "bounce": 0.3,
                "warmth": 0.4,
                "texture": "gritty",
                "references": ["Vangelis", "The Midnight"],
                "avoid": ["vocals", "upbeat"],
                "seed": 42,
                "confidence": 0.85
            }
        }
```

**Changes:**
- Add `StyleProfile` model to `app/models/__init__.py`
- Update `Arrangement` model to use `StyleProfile` for JSON serialization

### Task 2: Frontend Zod Schema

**File:** `src/lib/schema.ts` (new)

```typescript
import { z } from 'zod';

export const StyleProfileSchema = z.object({
  intent: z.string().min(1).max(500),
  energy: z.number().min(0).max(1).default(0.5),
  darkness: z.number().min(0).max(1).default(0.5),
  bounce: z.number().min(0).max(1).default(0.5),
  warmth: z.number().min(0).max(1).default(0.5),
  texture: z.enum(['smooth', 'balanced', 'gritty']).default('balanced'),
  references: z.array(z.string()).default([]),
  avoid: z.array(z.string()).default([]),
  seed: z.number().int().default(42),
  confidence: z.number().min(0).max(1).default(0.8),
});

export type StyleProfile = z.infer<typeof StyleProfileSchema>;

export const ArrangementRequestSchema = z.object({
  loop_id: z.number().int().positive(),
  target_seconds: z.number().int().positive(),
  style_profile: StyleProfileSchema,
  use_ai_parsing: z.boolean().default(true),
});

export type ArrangementRequest = z.infer<typeof ArrangementRequestSchema>;
```

**Changes:**
- Export from `src/lib/schema.ts`
- Update `api/client.ts` to use Zod validation

### Task 3: Style Sliders Component

**File:** `src/components/StyleSliders.tsx` (new)

```typescript
'use client';

import { useState } from 'react';
import { StyleProfile } from '@/lib/schema';

interface StyleSlidersProps {
  initialValues?: Partial<StyleProfile>;
  onStyleChange: (style: Partial<StyleProfile>) => void;
}

export function StyleSliders({ initialValues, onStyleChange }: StyleSlidersProps) {
  const [style, setStyle] = useState<Partial<StyleProfile>>(
    initialValues || {
      energy: 0.5,
      darkness: 0.5,
      bounce: 0.5,
      warmth: 0.5,
      texture: 'balanced',
    }
  );

  const handleSliderChange = (key: string, value: number) => {
    const updated = { ...style, [key]: value };
    setStyle(updated);
    onStyleChange(updated);
  };

  const sliders = [
    { key: 'energy', label: 'Energy', min: 0, max: 1, step: 0.01, tooltip: 'Loud vs. Quiet' },
    { key: 'darkness', label: 'Darkness', min: 0, max: 1, step: 0.01, tooltip: 'Dark vs. Bright' },
    { key: 'bounce', label: 'Bounce', min: 0, max: 1, step: 0.01, tooltip: 'Laid-back vs. Driving' },
    { key: 'warmth', label: 'Warmth', min: 0, max: 1, step: 0.01, tooltip: 'Cold vs. Warm' },
  ];

  return (
    <div className="flex flex-col gap-6 p-4 bg-slate-900 rounded-lg">
      <div>
        <h3 className="text-lg font-semibold text-white mb-4">Style Parameters</h3>
        {sliders.map(({ key, label, tooltip, step }) => (
          <div key={key} className="mb-4">
            <label className="flex justify-between text-sm font-medium text-gray-300 mb-2">
              <span>{label}</span>
              <span title={tooltip} className="text-xs text-gray-500">
                {((style[key as keyof StyleProfile] || 0) * 100).toFixed(0)}%
              </span>
            </label>
            <input
              type="range"
              min="0"
              max="1"
              step={step}
              value={style[key as keyof StyleProfile] || 0}
              onChange={(e) => handleSliderChange(key, parseFloat(e.target.value))}
              className="w-full h-2 bg-slate-700 rounded-lg appearance-none cursor-pointer"
            />
          </div>
        ))}
      </div>

      {/* Texture selector */}
      <div>
        <label className="text-sm font-medium text-gray-300 mb-2 block">Texture</label>
        <div className="flex gap-2">
          {['smooth', 'balanced', 'gritty'].map((tex) => (
            <button
              key={tex}
              onClick={() => handleSliderChange('texture', tex as any)}
              className={`px-3 py-1 rounded text-sm font-medium transition ${
                style.texture === tex
                  ? 'bg-blue-600 text-white'
                  : 'bg-slate-700 text-gray-300 hover:bg-slate-600'
              }`}
            >
              {tex.charAt(0).toUpperCase() + tex.slice(1)}
            </button>
          ))}
        </div>
      </div>
    </div>
  );
}
```

### Task 4: Style Validation Endpoint

**File:** `app/routes/style_validation.py` (new)

```python
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from app.models.style_profile import StyleProfile
from app.services.style_service import validate_and_normalize_style

router = APIRouter(prefix="/api/v1/styles", tags=["styles"])

class StyleValidationRequest(BaseModel):
    profile: StyleProfile

class StyleValidationResponse(BaseModel):
    valid: bool
    normalized_profile: StyleProfile
    warnings: List[str] = []
    message: str

@router.post("/validate")
async def validate_style(request: StyleValidationRequest) -> StyleValidationResponse:
    """Validate and normalize a style profile without rendering."""
    try:
        normalized, warnings = validate_and_normalize_style(request.profile)
        return StyleValidationResponse(
            valid=True,
            normalized_profile=normalized,
            warnings=warnings,
            message="Style is valid and ready for rendering"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e)
        )
```

### Task 5: Integration with Generate Page

**File:** `src/app/generate/page.tsx` (update)

Replace the current natural language input with:

```typescript
// Tabs: Preset | Natural Language | Advanced Parameters
// Tab 1: Style Presets (existing)
// Tab 2: Natural Language
// Tab 3: Advanced Sliders (NEW)

// When user clicks "Generate":
// 1. Collect style info (natural language + slider values)
// 2. Send to /api/v1/arrangements/generate with complete StyleProfile
// 3. Poll status until done
// 4. Download WAV
```

---

## API Changes

### New Endpoints

| Method | Endpoint | Purpose |
|--------|----------|---------|
| `POST` | `/api/v1/styles/validate` | Validate style profile without rendering |
| `GET` | `/api/v1/styles/presets` | List available style presets (enhanced) |

### Updated Endpoints

| Endpoint | Change |
|----------|--------|
| `POST /api/v1/arrangements/generate` | Accept full `StyleProfile` object instead of text |

---

## Database Changes

### Arrangement Model Update

```python
# OLD:
style_preset: str  # e.g., "cinematic"
style_text_input: str  # e.g., "dark moody"
ai_parsing_used: bool

# NEW:
style_profile_json: str  # Full StyleProfile serialized
ai_parsing_used: bool
style_preset_name: str  # Optional reference to preset (if used)
```

No breaking changes — new field alongside existing ones.

---

## Frontend Components to Create

| Component | Purpose |
|-----------|---------|
| `StyleSliders.tsx` | Slider inputs for energy, darkness, bounce, warmth |
| `StyleTextInput.tsx` | Natural language text area |
| `StyleReferences.tsx` | Chip input for references & avoid |
| `StylePreview.tsx` | Display current style profile (no audio preview yet) |
| `StyleTabs.tsx` | Tab switcher: Preset | Natural Language | Advanced |

---

## Implementation Sequence

1. **Backend Models** (10 min)
   - Create `app/models/style_profile.py`
   - Update imports

2. **Frontend Schema** (5 min)
   - Create `src/lib/schema.ts` with Zod

3. **Style Sliders Component** (15 min)
   - Build `src/components/StyleSliders.tsx`
   - Basic styling with Tailwind

4. **Validation Endpoint** (10 min)
   - Create `app/routes/style_validation.py`
   - Wire into main.py router

5. **Integration** (15 min)
   - Update `src/app/generate/page.tsx` with tabs
   - Connect sliders to state
   - Update arrange request builder

6. **Testing** (10 min)
   - Manual test: load generate page, adjust sliders, submit

---

## Success Criteria

- ✅ Sliders appear on generate page
- ✅ Slider values update style profile in real-time
- ✅ Generate request includes full StyleProfile
- ✅ Backend validates style without error
- ✅ Arrangement renders successfully with slider parameters
- ✅ Zero API breaking changes (backward compatible)

---

## Out of Scope (for PHASE 4+)

- Audio preview (real-time rendering too slow)
- AI-powered reference suggestions
- Style matching ("sounds like X")
- Stem separation
- MIDI export
- DAW import guide

---

**Next Step:** Confirm plan, then proceed with implementation.
