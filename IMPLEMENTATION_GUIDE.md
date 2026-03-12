# Stem Producer Engine Implementation Guide

## Overview

This guide explains how to integrate the new stem producer engine (Phases 4-8) with the existing LoopArchitect API.

## Architecture Summary

The stem producer engine operates alongside the existing loop variation engine:

```
User Upload (Loop or Stems)
    ↓
RenderPathRouter.route_and_arrange()
    ├─→ Stem Path: StemArrangementEngine + StemRenderExecutor
    └─→ Loop Path: LoopVariationEngine (existing, untouched)
```

**Key Principle**: Router automatically decides which path to use based on input type.

## Integration Points

### 1. POST /api/v1/loops/with-file (Existing Route - No Changes)

This route already handles stem files via:
- `stem_pack_extractor.py` (Phase 1) - existing
- `stem_classifier.py` (Phase 2) - existing  
- `stem_validation.py` (Phase 3) - existing
- `stem_pack_service.py` (Phases 1-3) - existing

**Action Required**: None - these services already exist and are working.

### 2. POST /api/v1/arrangements/generate (Existing Route - Update Here)

**Current Flow** (before integration):
```python
@router.post("/arrangements/generate")
async def generate_arrangement(req: GenerateArrangementRequest):
    loop = await db.get_loop(req.loop_id)
    
    # Direct call to old engine
    arrangement_data = arrangement_engine.generate_arrangement(
        loop=loop,
        target_seconds=req.duration_sec,
        genre=req.genre,
        intensity=req.intensity,
    )
    
    arrangement = await save_and_render_arrangement(arrangement_data)
    return arrangement
```

**NEW Flow** (after integration):
```python
from app.services.render_path_router import RenderPathRouter, StemRenderOrchestrator

@router.post("/arrangements/generate")
async def generate_arrangement(req: GenerateArrangementRequest):
    loop = await db.get_loop(req.loop_id)
    
    # NEW: Route to appropriate engine
    render_path, arrangement_data = RenderPathRouter.route_and_arrange(
        loop=loop,
        target_seconds=req.duration_sec,
        genre=req.genre or "generic",
        intensity=req.intensity or 1.0,
    )
    
    # Create arrangement record
    arrangement = Arrangement(
        loop_id=loop.id,
        duration_ms=int(req.duration_sec * 1000),
        genre=req.genre,
        intensity=req.intensity,
        stem_render_path=render_path,  # NEW
        stem_arrangement_json=json.dumps(arrangement_data),  # NEW
        rendered_from_stems=(render_path == "stem"),  # NEW
    )
    await db.add_and_flush(arrangement)
    
    # Async render in background
    render_key = f"arrangements/{arrangement.id}/output"
    task = await StemRenderOrchestrator.render_arrangement_async(
        arrangement=arrangement,
        output_key=render_key,
        storage_client=storage,
    )
    
    return ArrangementResponse(
        id=arrangement.id,
        loop_id=loop.id,
        status="processing",
        render_path=render_path,  # NEW: inform client which path used
        samples_ready=False,
    )
```

**Key Changes**:
1. Add `render_path_router` import
2. Replace direct `arrangement_engine` call with `RenderPathRouter.route_and_arrange()`
3. Populate new database columns with stem data
4. Use `StemRenderOrchestrator.render_arrangement_async()` for rendering

### 3. Database Integration

**Before Migration**:
```python
class Loop(Base):
    # existing fields only
```

**After Migration**:
```python
class Loop(Base):
    # Existing fields...
    
    # NEW: Stem metadata (Phase 9)
    is_stem_pack = Column(String(10), nullable=True)
    stem_roles_json = Column(Text, nullable=True)
    stem_files_json = Column(Text, nullable=True)
    stem_validation_json = Column(Text, nullable=True)
    
    # Properties for convenient access
    @property
    def stems_dict(self) -> Dict:
        """Parse stem_files_json to dict"""
        if not self.stem_files_json:
            return {}
        return json.loads(self.stem_files_json)
    
    @property
    def stem_roles(self) -> List[str]:
        """Get list of detected roles"""
        if not self.stem_roles_json:
            return []
        return json.loads(self.stem_roles_json).get("detected_roles", [])
```

**Before Migration**:
```python
class Arrangement(Base):
    # existing fields only
```

**After Migration**:
```python
class Arrangement(Base):
    # Existing fields...
    
    # NEW: Stem rendering metadata (Phase 9)
    stem_arrangement_json = Column(Text, nullable=True)
    stem_render_path = Column(String(50), nullable=True)  # "stem" or "loop"
    rendered_from_stems = Column(Boolean, nullable=True)
```

### 4. Configuration & Settings

**No new environment variables required** - the router auto-detects stem availability.

Optional enhancements:
```python
# config.py
STEM_CACHE_SIZE_MB = 512  # Cache size for loaded stems
STEM_MIXING_GAIN_DB = -3  # Per-stem gain during mixing (-3dB prevents clipping)
MASTER_LIMITING_THRESHOLD_DB = -1  # Master limiter threshold
```

## File Locations

### New Files Created

```
app/services/
  ├── stem_arrangement_engine.py      (500 lines) - Phase 4: Arrangement generation
  ├── stem_render_executor.py         (400 lines) - Phase 5: Audio rendering
  └── render_path_router.py           (350 lines) - Phases 6-8: Routing + orchestration

tests/services/
  └── test_stem_engine.py             (400 lines) - Phase 10: Comprehensive tests

models/ (Modified)
  ├── loop.py                         (+4 columns, +2 properties)
  └── arrangement.py                  (+3 columns)

Documentation/
  ├── ARRANGEMENT_LOGIC.md            (UPDATED) - Phase 11: Core algorithm
  ├── STEM_PRODUCER_ENGINE.md         (UPDATED) - Phase 11: Service overview
  ├── STEM_RENDER_PIPELINE.md         (UPDATED) - Phase 11: Pipeline details
  ├── DATABASE_SCHEMA_MIGRATION.md    (NEW)    - Phase 9: Migration scripts
  └── IMPLEMENTATION_GUIDE.md         (THIS FILE)
```

## Detailed Integration Example

Here's a complete example of integrating the router into an arrangement route:

```python
# app/routers/arrangements.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.models import Loop, Arrangement
from app.services.render_path_router import RenderPathRouter, StemRenderOrchestrator
from app.services.storage import StorageClient
from app.db import get_session
import json
from typing import Optional

router = APIRouter(prefix="/api/v1/arrangements", tags=["arrangements"])

class GenerateArrangementRequest(BaseModel):
    loop_id: str
    duration_sec: float = 32.0
    genre: Optional[str] = "generic"
    intensity: Optional[float] = 1.0

class ArrangementResponse(BaseModel):
    id: str
    loop_id: str
    status: str
    render_path: str  # NEW: inform client of path used
    samples_ready: bool

@router.post("/generate", response_model=ArrangementResponse)
async def generate_arrangement(
    req: GenerateArrangementRequest,
    session: AsyncSession = Depends(get_session),
    storage: StorageClient = Depends(get_storage_client),
):
    """Generate a new arrangement from a loop or stem pack"""
    
    # 1. Load loop (with stem metadata)
    loop = await session.get(Loop, req.loop_id)
    if not loop:
        raise HTTPException(status_code=404, detail="Loop not found")
    
    # 2. Route and arrange (NEW - handles both stem and loop paths)
    try:
        render_path, arrangement_data = RenderPathRouter.route_and_arrange(
            loop=loop,
            target_seconds=req.duration_sec,
            genre=req.genre or "generic",
            intensity=req.intensity or 1.0,
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Arrangement generation failed: {str(e)}")
    
    # 3. Create arrangement record with stem metadata (NEW)
    arrangement = Arrangement(
        loop_id=loop.id,
        duration_ms=int(req.duration_sec * 1000),
        genre=req.genre or "generic",
        intensity=req.intensity or 1.0,
        
        # NEW: Stem rendering fields
        stem_render_path=render_path,
        stem_arrangement_json=json.dumps(arrangement_data) if arrangement_data else None,
        rendered_from_stems=(render_path == "stem"),
    )
    
    session.add(arrangement)
    await session.flush()  # Ensure ID is populated
    
    # 4. Async rendering in background (NEW)
    render_key = f"arrangements/{arrangement.id}/output"
    task = await StemRenderOrchestrator.render_arrangement_async(
        arrangement=arrangement,
        output_key=render_key,
        storage_client=storage,
    )
    
    # Save arrangement to DB
    await session.commit()
    
    return ArrangementResponse(
        id=arrangement.id,
        loop_id=loop.id,
        status="processing",
        render_path=render_path,  # NEW: client can see which path was used
        samples_ready=False,
    )

@router.get("/{arrangement_id}")
async def get_arrangement(
    arrangement_id: str,
    session: AsyncSession = Depends(get_session),
):
    """Retrieve arrangement details including stem metadata (NEW fields)"""
    
    arrangement = await session.get(Arrangement, arrangement_id)
    if not arrangement:
        raise HTTPException(status_code=404, detail="Arrangement not found")
    
    # Parse stem_arrangement_json if present (NEW)
    arrangement_data = None
    if arrangement.stem_arrangement_json:
        arrangement_data = json.loads(arrangement.stem_arrangement_json)
    
    return {
        "id": arrangement.id,
        "loop_id": arrangement.loop_id,
        "duration_ms": arrangement.duration_ms,
        "genre": arrangement.genre,
        "stem_render_path": arrangement.stem_render_path,  # NEW
        "rendered_from_stems": arrangement.rendered_from_stems,  # NEW
        "arrangement_data": arrangement_data,  # NEW
        "output_url": f"s3://bucket/arrangements/{arrangement.id}/output.wav",
    }
```

## Testing Integration

### Unit Tests

```bash
# Test individual services
pytest tests/services/test_stem_engine.py -v

# Test specific classes
pytest tests/services/test_stem_engine.py::TestRenderPathRouter -v
pytest tests/services/test_stem_engine.py::TestStemRenderExecutor -v
```

### Integration Test Example

```python
# tests/test_arrangement_integration.py

async def test_stem_arrangement_generation():
    """Test full stem path through the router"""
    
    # 1. Create a stem pack loop
    loop = Loop(
        id="test_loop",
        is_stem_pack="true",
        stem_roles_json='{"detected_roles": ["drums", "bass", "melody"]}',
        stem_files_json='{"drums": {...}, "bass": {...}, "melody": {...}}',
        stem_validation_json='{"is_valid": true}',
    )
    
    # 2. Route and arrange
    render_path, arrangement_data = RenderPathRouter.route_and_arrange(
        loop=loop,
        target_seconds=32.0,
        genre="trap",
        intensity=1.0,
    )
    
    # 3. Verify stem path was used
    assert render_path == "stem"
    assert arrangement_data is not None
    assert len(arrangement_data["sections"]) > 0
    
    # 4. Verify hook evolution
    hooks = [s for s in arrangement_data["sections"] if s["section_type"] == "hook"]
    energies = [h["energy_level"] for h in hooks]
    for i in range(len(energies) - 1):
        assert energies[i] < energies[i+1], "Hook energy should progress"

async def test_fallback_to_loop_path():
    """Test fallback when stems unavailable"""
    
    loop = Loop(
        id="single_loop",
        is_stem_pack="false",
        # No stem metadata
    )
    
    render_path, arrangement_data = RenderPathRouter.route_and_arrange(
        loop=loop,
        target_seconds=32.0,
    )
    
    # Should fallback to loop path
    assert render_path == "loop"
```

## Deployment Checklist

- [ ] **Database Migration**: Run migration script (`DATABASE_SCHEMA_MIGRATION.md`)
- [ ] **Code Changes**: Update `/api/v1/arrangements/generate` route
- [ ] **Import Statements**: Add `from app.services.render_path_router import ...`
- [ ] **Model Updates**: Verify Loop and Arrangement models have new columns
- [ ] **Test Locally**: Run integration tests against local DB
- [ ] **Test Staging**: Deploy to staging environment, run full E2E tests
- [ ] **Documentation**: Update API docs to include new `stem_render_path` response field
- [ ] **Monitoring**: Set up alerts for stem rendering errors
- [ ] **Deploy to Production**: Follow Railway deployment process

## Troubleshooting

### "stem_render_path not found" Error

**Cause**: Database migration not run
**Solution**: Run `DATABASE_SCHEMA_MIGRATION.md` script

### "RenderPathRouter not found" Error

**Cause**: Import missing or file not in correct location
**Solution**: Verify `app/services/render_path_router.py` exists at correct path

### All arrangements falling back to loop path

**Cause**: `should_use_stem_path()` returning false - check stem metadata
**Solution**: Verify Loop.is_stem_pack, stem_files_json populated correctly

### Audio rendering fails

**Cause**: Stems not accessible in storage or incorrect file paths
**Solution**: Check S3 paths in stem_files_json, verify audio file integrity

## Performance Considerations

- **Memory**: Stem caching loads all stems into memory (manageable for typical stems < 2 GB total)
- **Processing**: Section-by-section rendering is sequential; consider parallelization for performance
- **Storage**: JSON fields grow with larger arrangements (< 100 KB typical per arrangement)

## Next Steps

1. **Implement Route Integration** (above code example)
2. **Run Database Migration** (DATABASE_SCHEMA_MIGRATION.md)
3. **Test Locally** (run test_stem_engine.py)
4. **Deploy to Staging** (verify with real stems)
5. **Update Frontend** (Phase 9) - add multi-file upload UI
6. **Deploy to Production** (Railway)

## References

- [ARRANGEMENT_LOGIC.md](ARRANGEMENT_LOGIC.md) - Core algorithm explanation
- [STEM_PRODUCER_ENGINE.md](STEM_PRODUCER_ENGINE.md) - Service overview
- [STEM_RENDER_PIPELINE.md](STEM_RENDER_PIPELINE.md) - Pipeline details
- [DATABASE_SCHEMA_MIGRATION.md](DATABASE_SCHEMA_MIGRATION.md) - Migration scripts
- Source: `app/services/stem_arrangement_engine.py`, `stem_render_executor.py`, `render_path_router.py`
