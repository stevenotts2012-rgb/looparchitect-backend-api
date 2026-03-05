# Producer Engine Integration - Action Plan

## Phase 1: Beat Genome System ✅ COMPLETE
**Status:** 9 genomes created, loader built, documentation ready
**Files:** 12 new files, ~2,300 lines added
**Breaking changes:** None
**Ready:** YES ✓

## Phase 2: Producer Engine Integration (NEXT)
**Status:** Ready to start
**Effort:** 8-12 hours (critical path)
**Priority:** HIGH - Unblocks entire producer feature

### Critical Path to Producer System (In Order)

#### Step 1: Route Integration (2-3 hours)
**File:** `app/routes/arrangements.py`
**Current:** Routes call `arrangement_engine` (Phase B)
**Target:** Routes call `ProducerEngine` when available

**Changes needed:**
```python
# Add import at top
from app.services.beat_genome_loader import BeatGenomeLoader
from app.services.producer_engine import ProducerEngine
from app.services.style_direction_engine import StyleDirectionEngine

# In POST /arrangements/{id}/generate endpoint:
# 1. Parse style_input parameter from request (new)
# 2. Call StyleDirectionEngine.parse(style_input) to get style_profile
# 3. Call ProducerEngine.generate(loop_metadata, style_profile, duration)
# 4. Return arrangement with feature flag fallback to Phase B if needed
```

**New parameters to API:**
- `style_input` (string, optional): "Southside type trap", "Drake R&B", etc.

**Feature flag:**
- Add environment variable: `USE_PRODUCER_ENGINE` (default: false for safety)

**Backward compatibility:**
- If `USE_PRODUCER_ENGINE=false` → Use Phase B (current behavior)
- If `USE_PRODUCER_ENGINE=true` → Use ProducerEngine
- If `style_input` provided → Always use ProducerEngine (user explicit choice)

**Testing:**
```bash
# Should work with Phase B (backward compatibility)
curl -X POST http://localhost:8000/arrangements/1/generate

# Should work with ProducerEngine (explicit style)
curl -X POST http://localhost:8000/arrangements/1/generate \
  -H "Content-Type: application/json" \
  -d '{"style_input": "dark trap vibes", "duration_seconds": 180}'
```

---

#### Step 2: ProducerEngine Genome Integration (1-2 hours)
**File:** `app/services/producer_engine.py`
**Current:** Uses hardcoded `INSTRUMENT_PRESETS` dict (~370 lines)
**Target:** Uses `BeatGenomeLoader` to load genomes at runtime

**Changes needed:**
```python
# Around line 375, replace this:
INSTRUMENT_PRESETS = {
    "trap": {...large dict...},
    "rnb": {...},
    ...
}

# With this:
def get_instrument_config(genre: str, mood: Optional[str] = None) -> dict:
    """Load instrument configuration from genome or fallback to preset."""
    try:
        genome = BeatGenomeLoader.load(genre, mood)
        return genome["instrument_layers"]
    except FileNotFoundError:
        # Fallback to legacy preset if genome not found
        return LEGACY_INSTRUMENT_PRESETS.get(genre, LEGACY_INSTRUMENT_PRESETS["trap"])

# In generate() method, change:
# OLD: instruments = self.INSTRUMENT_PRESETS[style_profile["genre"]]
# NEW: instruments = get_instrument_config(style_profile["genre"], style_profile.get("mood"))
```

**Validation:**
- Load each of 9 genomes successfully
- Instrument layers match expected structure
- Energy curves match expected ranges (0.0-1.0)
- No hardcoded fallbacks needed

**Testing:**
```python
# Test genome loading in ProducerEngine
from app.services.producer_engine import ProducerEngine
from app.models.loop import Loop

loop = Loop(name="test", bpm=100, key="C", bars=32)
style = {"genre": "trap", "mood": "dark"}

engine = ProducerEngine()
arrangement = engine.generate(loop, style, 180)

assert arrangement is not None
assert len(arrangement.sections) >= 3  # Validation passes
```

---

#### Step 3: Frontend Style Input (2-3 hours)
**Files:** 
- `src/app/generate/page.tsx` (main form)
- `src/components/StyleInput.tsx` (new component)

**Current:** No style input field
**Target:** Text input field for style direction

**Changes needed:**
```typescript
// In src/app/generate/page.tsx

// Add state for style input
const [styleInput, setStyleInput] = useState("");
const [selectedGenre, setSelectedGenre] = useState("trap");

// Add form fields:
<input
  type="text"
  placeholder="e.g., 'Southside type trap', 'Drake R&B vibes', 'Cinematic orchestral'"
  value={styleInput}
  onChange={(e) => setStyleInput(e.target.value)}
/>

<select value={selectedGenre} onChange={(e) => setSelectedGenre(e.target.value)}>
  <option value="trap">Trap</option>
  <option value="rnb">R&B</option>
  <option value="afrobeats">Afrobeats</option>
  <option value="cinematic">Cinematic</option>
  <option value="edm">EDM</option>
</select>

// When calling API, include style_input:
const response = await api.post(`/arrangements/${loopId}/generate`, {
  duration_seconds: duration,
  style_input: styleInput,  // NEW
  genre: selectedGenre,     // NEW
});
```

**UI Enhancements (Optional but recommended):**
- Genre preset buttons for quick selection
- Example styles in placeholder text
- Energy/intensity slider (0-100)
- Arrangement timeline preview

---

#### Step 4: Worker RenderPlan Integration (3-4 hours)
**File:** `app/workers/render_worker.py`
**Current:** Uses Phase B audio loop repetition
**Target:** Uses RenderPlan events for variations/transitions

**Changes needed:**
```python
# In render_worker.py process_job() method:

# After creating render plan:
render_plan = RenderPlan.from_arrangement(arrangement)

# During synthesis loop:
for bar in range(total_bars):
    # Get events for this bar from RenderPlan
    events = render_plan.get_events_for_bar(bar)
    
    # Apply variations
    for event in events:
        if event["type"] == "variation":
            audio = apply_variation(audio, event["variation_type"], bar)
        elif event["type"] == "transition":
            audio = apply_transition(audio, event["transition_type"], bar)
    
    # Continue with synthesis...
```

**Fallback Strategy:**
- If no RenderPlan → Use Phase B engine (backward compatible)
- If RenderPlan exists but feature disabled → Ignore and use Phase B
- If RenderPlan exists and feature enabled → Use events

---

## Quick Integration Checklist

### Before Starting
- [ ] Have `SYSTEM_AUDIT_REPORT.md` open for reference
- [ ] Have `PRODUCER_ENGINE_ARCHITECTURE.md` open for API design
- [ ] Have beat genome files available in `config/genomes/`
- [ ] Have `BeatGenomeLoader` reviewed and understood

### Implementation Order (Do in this sequence)

1. **Route Integration First** (2-3 hours)
   - Update `arrangements.py` to call ProducerEngine
   - Add `style_input` parameter to API
   - Test with curl (backward compat + new style)

2. **ProducerEngine Genome Wiring** (1-2 hours)
   - Replace hardcoded presets with BeatGenomeLoader
   - Test with each of 9 genres
   - Verify energy curves still correct

3. **Frontend Addition** (2-3 hours)
   - Add style input field to form
   - Add genre selector
   - Connect to API parameter

4. **Worker Integration** (3-4 hours)
   - Wire RenderPlan usage
   - Test render queue with variations
   - Verify backward compatibility

5. **Testing & Validation** (2-3 hours)
   - E2E: style input → arrangement → render
   - Test all 9 genres
   - Test Phase B fallback still works
   - Load test with concurrent requests

---

## Success Criteria

✅ **Phase 2 Complete When:**
- ProducerEngine is called from API routes (not Phase B)
- Style direction input is accepted and used
- All 9 beat genomes load successfully
- RenderPlan events are applied during synthesis
- Phase B is available as fallback
- Zero breaking changes to existing features
- E2E tests pass for new flow
- Deployment checklist updated

---

## File Locations Reference

**Key Files to Modify:**
```
c:\Users\steve\looparchitect-backend-api\
├── app/
│   ├── routes/
│   │   └── arrangements.py         ← UPDATE THIS
│   ├── services/
│   │   ├── producer_engine.py      ← UPDATE THIS
│   │   └── beat_genome_loader.py   ← USE THIS (NEW)
│   └── workers/
│       └── render_worker.py        ← UPDATE THIS
└── frontend/
    └── src/app/generate/
        └── page.tsx                ← UPDATE THIS
```

**Reference Files (Read-only):**
```
c:\Users\steve\looparchitect-backend-api\
├── SYSTEM_AUDIT_REPORT.md                    (read for context)
├── PRODUCER_ENGINE_ARCHITECTURE.md           (read for API design)
├── BEAT_GENOME_SCHEMA.md                     (read for genome structure)
├── BEAT_GENOME_COMPLETION.md                 (reference integration points)
└── config/genomes/*.json                     (9 genres to use)
```

---

## Estimated Timeline

**If working on Phase 2 full-time:**
- 1 day: Route integration + genome wiring
- 0.5 day: Frontend additions
- 1 day: Worker integration + testing
- 0.5 day: Documentation + deployment prep

**Total:** 3 days to full producer system operational

---

## Risk Mitigation

**How to stay safe during integration:**

1. **Feature Flags:** Keep `USE_PRODUCER_ENGINE=false` default
   - Enables gradual rollout to users
   - Maintains Phase B fallback
   - Zero downtime possible

2. **Backward Compatibility:** Don't modify existing endpoints
   - Keep old Phase B calls working
   - Add style_input as OPTIONAL parameter
   - If not provided → Use Phase B (current behavior)

3. **Testing Strategy:**
   - Test each change in isolation
   - Run integration tests after each step
   - Verify Phase B still works
   - Load test before deployment

4. **Rollback Plan:**
   - If issues found → Set `USE_PRODUCER_ENGINE=false`
   - Pull requests revert cleanly (additive only)
   - No database changes = instant rollback

---

## Next Steps (Start Here)

1. Read this file completely ✓
2. Open `app/routes/arrangements.py` 
3. Review current POST /arrangements/{id}/generate endpoint
4. Review PRODUCER_ENGINE_ARCHITECTURE.md section on API integration
5. Start Step 1: Route Integration

**Ready to start integration? Let's go!**
