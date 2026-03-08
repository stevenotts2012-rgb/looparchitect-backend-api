"""Loop Analysis API Routes: Metadata-based genre, mood, and energy detection.

Provides endpoint for analyzing loop metadata to automatically detect:
- Genre (trap, dark_trap, melodic_trap, drill, rage)
- Mood (dark, aggressive, emotional, cinematic, energetic)
- Energy level (0.0-1.0)
- Arrangement template recommendations
- Suggested instruments

No audio file processing required - works with metadata only.
"""

import logging
from fastapi import APIRouter, HTTPException, Depends
from sqlalchemy.orm import Session
from typing import Optional

from app.db import get_db
from app.models.loop import Loop
from app.schemas.loop_analysis import (
    LoopAnalysisRequest,
    LoopAnalysisResponse,
    LoopMetadataInput
)
from app.services.loop_metadata_analyzer import LoopMetadataAnalyzer

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/loops", tags=["Loop Analysis"])


@router.post("/analyze-metadata", response_model=LoopAnalysisResponse)
def analyze_loop_metadata(
    request: LoopAnalysisRequest,
    db: Session = Depends(get_db),
) -> LoopAnalysisResponse:
    """Analyze loop metadata to detect genre, mood, energy level, and provide recommendations.
    
    This endpoint uses rule-based analysis (no ML/AI) to detect:
    - Genre: trap, dark_trap, melodic_trap, drill, rage
    - Mood: dark, aggressive, emotional, cinematic, energetic
    - Energy: 0.0-1.0 scale
    - Recommended template: standard, progressive, looped, minimal
    - Suggested instruments based on genre/mood
    
    Example request:
    ```json
    {
        "bpm": 145,
        "tags": ["dark", "trap", "evil"],
        "filename": "dark_trap_loop_145bpm.wav",
        "mood_keywords": ["aggressive", "dark"],
        "bars": 4,
        "musical_key": "Am"
    }
    ```
    
    Example response:
    ```json
    {
        "detected_genre": "dark_trap",
        "detected_mood": "dark",
        "energy_level": 0.78,
        "recommended_template": "progressive",
        "confidence": 0.87,
        "suggested_instruments": ["kick", "snare", "hats", "808_bass", "dark_pad", "fx"],
        "analysis_version": "1.0.0",
        "source_signals": {...},
        "reasoning": "Detected dark_trap based on..."
    }
    ```
    
    Args:
        request: LoopAnalysisRequest with metadata fields
        db: Database session
        
    Returns:
        LoopAnalysisResponse with analysis results
        
    Raises:
        HTTPException 400: Invalid input data
    """
    try:
        logger.info(f"Received loop metadata analysis request: {request.model_dump()}")
        
        # Perform analysis
        result = LoopMetadataAnalyzer.analyze(
            bpm=request.bpm,
            tags=request.tags,
            filename=request.filename,
            mood_keywords=request.mood_keywords,
            genre_hint=request.genre_hint,
            bars=request.bars,
            musical_key=request.musical_key,
        )
        
        # Convert to response model
        response = LoopAnalysisResponse(**result)
        
        logger.info(
            f"Loop metadata analysis successful: genre={response.detected_genre}, "
            f"mood={response.detected_mood}, energy={response.energy_level}, "
            f"confidence={response.confidence}"
        )
        
        return response
        
    except ValueError as e:
        logger.error(f"Validation error during loop analysis: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Unexpected error during loop analysis: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Internal server error during analysis")


@router.post("/loops/{loop_id}/analyze-metadata", response_model=LoopAnalysisResponse)
def analyze_existing_loop_metadata(
    loop_id: int,
    db: Session = Depends(get_db),
    genre_hint: Optional[str] = None,
) -> LoopAnalysisResponse:
    """Analyze metadata for an existing loop in the database.
    
    This endpoint retrieves loop data from the database and performs metadata analysis
    to detect genre, mood, energy level, and provide recommendations.
    
    Example usage:
    ```
    POST /api/v1/loops/123/analyze-metadata
    POST /api/v1/loops/123/analyze-metadata?genre_hint=dark_trap
    ```
    
    Args:
        loop_id: Database ID of the loop to analyze
        db: Database session
        genre_hint: Optional genre hint to guide analysis
        
    Returns:
        LoopAnalysisResponse with analysis results
        
    Raises:
        HTTPException 404: Loop not found
        HTTPException 400: Invalid loop data
    """
    # Fetch loop from database
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        logger.warning(f"Loop {loop_id} not found for analysis")
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    logger.info(f"Analyzing metadata for existing loop {loop_id}: {loop.filename}")
    
    try:
        # Extract tags from loop (assuming tags are stored as comma-separated or JSON)
        tags = []
        if hasattr(loop, 'tags') and loop.tags:
            if isinstance(loop.tags, str):
                tags = [t.strip() for t in loop.tags.split(',')]
            elif isinstance(loop.tags, list):
                tags = loop.tags
        
        # Perform analysis using loop metadata
        result = LoopMetadataAnalyzer.analyze(
            bpm=loop.bpm or loop.tempo,
            tags=tags,
            filename=loop.filename,
            mood_keywords=[],  # Could be extracted from loop metadata if available
            genre_hint=genre_hint or loop.genre,
            bars=loop.bars,
            musical_key=loop.musical_key,
        )
        
        response = LoopAnalysisResponse(**result)
        
        logger.info(
            f"Loop {loop_id} analysis successful: genre={response.detected_genre}, "
            f"mood={response.detected_mood}, energy={response.energy_level}"
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Error analyzing loop {loop_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Error analyzing loop metadata")


@router.get("/loops/{loop_id}/metadata", response_model=LoopMetadataInput)
def get_loop_metadata_for_analysis(
    loop_id: int,
    db: Session = Depends(get_db),
) -> LoopMetadataInput:
    """Get loop metadata in a format suitable for arrangement generation.
    
    This is a convenience endpoint that extracts metadata from a loop
    and returns it in the LoopMetadataInput format for use with other endpoints.
    
    Args:
        loop_id: Database ID of the loop
        db: Database session
        
    Returns:
        LoopMetadataInput with loop metadata
        
    Raises:
        HTTPException 404: Loop not found
    """
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    if not loop:
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")
    
    # Extract tags
    tags = []
    if hasattr(loop, 'tags') and loop.tags:
        if isinstance(loop.tags, str):
            tags = [t.strip() for t in loop.tags.split(',')]
        elif isinstance(loop.tags, list):
            tags = loop.tags
    
    return LoopMetadataInput(
        bpm=loop.bpm or loop.tempo,
        tags=tags,
        filename=loop.filename,
        bars=loop.bars,
        musical_key=loop.musical_key,
    )
