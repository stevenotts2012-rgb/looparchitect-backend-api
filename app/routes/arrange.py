"""Arrangement generation endpoint for loops.

Supports flexible duration specification:
- duration_seconds: Generate arrangement for exact duration (preferred)
- bars: Directly specify bar count
- sections: Reserved for advanced use

Uses BPM to convert duration_seconds to bars, then generates
repeating verse/chorus patterns that fill the target exactly.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Body
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.schemas.arrangement import (
    ArrangeGenerateRequest,
    ArrangeGenerateResponse,
    ArrangementSection,
)
from app.services.arranger import generate_arrangement, duration_to_bars, bars_to_duration

router = APIRouter(tags=["arrange"])

logger = logging.getLogger(__name__)

# Safety limits to protect from unreasonable requests
MAX_DURATION_SECONDS = 3600  # 60 minutes
MAX_BARS = 4096
MIN_DURATION_SECONDS = 15
MIN_BARS = 4


@router.post("/arrange/{loop_id}", response_model=ArrangeGenerateResponse)
async def arrange_loop(
    loop_id: int,
    request: ArrangeGenerateRequest = Body(default_factory=ArrangeGenerateRequest),
    db: Session = Depends(get_db),
) -> ArrangeGenerateResponse:
    """Generate an arrangement for a loop with flexible duration.

    Supports three ways to specify arrangement length (in priority order):
    1. **bars**: Directly specify bar count (if provided)
    2. **duration_seconds**: Generate arrangement to fill exact duration (preferred)
    3. **Default**: 180 seconds (3 minutes)

    The endpoint uses the loop's detected BPM to convert duration to bars.
    If BPM is unavailable, defaults to 120 BPM.

    **Duration Validation:**
    - Minimum: 15 seconds
    - Maximum: 3600 seconds (60 minutes)
    - Default: 180 seconds (3 minutes)

    **Arrangement Structure:**
    - Intro: 4 bars (intro section)
    - Body: Repeating Verse (8 bars) + Hook (8 bars), with Bridge (8 bars) every 2 cycles
    - Outro: 4 bars (always ends the arrangement)

    The arrangement is built to fill exactly the target duration,
    with the last section trimmed as needed.

    Args:
        loop_id: The ID of the loop to arrange
        request: ArrangeGenerateRequest with optional duration/bars parameters
        db: Database session

    Returns:
        ArrangeGenerateResponse with sections, bar positions, and timing info

    Raises:
        HTTPException 404: If loop not found
        HTTPException 400: If parameters invalid or exceed safety limits
        HTTPException 422: If request validation fails

    Example:
        ```json
        POST /arrange/1
        {
            "duration_seconds": 120
        }

        Response:
        {
            "loop_id": 1,
            "bpm": 140.0,
            "key": "D Minor",
            "target_duration_seconds": 120,
            "actual_duration_seconds": 120,
            "total_bars": 56,
            "sections": [
                {"name": "Intro", "bars": 4, "start_bar": 0, "end_bar": 3},
                {"name": "Verse", "bars": 8, "start_bar": 4, "end_bar": 11},
                ...
            ]
        }
        ```
    """
    logger.info(f"Arrange request for loop {loop_id}: {request}")

    # Query database for the loop
    loop = db.query(Loop).filter(Loop.id == loop_id).first()

    if loop is None:
        logger.warning(f"Loop {loop_id} not found")
        raise HTTPException(status_code=404, detail=f"Loop {loop_id} not found")

    # Determine BPM (use detected BPM, fallback to tempo, then default)
    bpm = loop.bpm or loop.tempo or 120.0
    logger.debug(f"Using BPM: {bpm} (detected: {loop.bpm}, tempo: {loop.tempo})")

    # Determine target bars and duration using priority:
    # 1. bars (if provided)
    # 2. duration_seconds (if provided)
    # 3. default 180 seconds
    if request.bars is not None:
        logger.info(f"Using bars parameter: {request.bars}")
        target_bars = request.bars
        target_duration_seconds = bars_to_duration(target_bars, bpm)
    else:
        # Use duration_seconds (already defaulted to 180 in schema)
        target_duration_seconds = request.duration_seconds or 180
        logger.info(f"Using duration_seconds: {target_duration_seconds}s")

        # Validate duration
        if target_duration_seconds < MIN_DURATION_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"duration_seconds must be at least {MIN_DURATION_SECONDS} seconds, "
                f"got {target_duration_seconds}",
            )
        if target_duration_seconds > MAX_DURATION_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"duration_seconds must not exceed {MAX_DURATION_SECONDS} seconds "
                f"({MAX_DURATION_SECONDS // 60} minutes), got {target_duration_seconds}",
            )

        # Convert duration to bars
        try:
            target_bars = duration_to_bars(target_duration_seconds, bpm)
            logger.debug(
                f"Converted {target_duration_seconds}s at {bpm} BPM to {target_bars} bars"
            )
        except ValueError as e:
            logger.error(f"Duration to bars conversion failed: {str(e)}")
            raise HTTPException(status_code=400, detail=str(e))

    # Validate bars
    if target_bars < MIN_BARS:
        raise HTTPException(
            status_code=400,
            detail=f"Arrangement must have at least {MIN_BARS} bars, got {target_bars}",
        )
    if target_bars > MAX_BARS:
        raise HTTPException(
            status_code=400,
            detail=f"Arrangement cannot exceed {MAX_BARS} bars, got {target_bars}",
        )

    # Generate arrangement
    logger.info(f"Generating arrangement: {target_bars} bars at {bpm} BPM")
    try:
        sections_data, actual_bars = generate_arrangement(target_bars, bpm)
    except Exception as e:
        logger.exception(f"Arrangement generation failed: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Arrangement generation failed: {str(e)}")

    # Convert sections to response format
    sections = [
        ArrangementSection(
            name=section["name"],
            bars=section["bars"],
            start_bar=section["start_bar"],
            end_bar=section["end_bar"],
        )
        for section in sections_data
    ]

    # Calculate actual duration from generated bars
    actual_duration_seconds = bars_to_duration(actual_bars, bpm)

    logger.info(
        f"Arrangement generated: {len(sections)} sections, {actual_bars} bars, "
        f"{actual_duration_seconds}s duration"
    )

    return ArrangeGenerateResponse(
        loop_id=loop_id,
        bpm=float(bpm),
        key=loop.musical_key or loop.key,
        target_duration_seconds=target_duration_seconds,
        actual_duration_seconds=actual_duration_seconds,
        total_bars=actual_bars,
        sections=sections,
    )


@router.post("/arrange/{loop_id}/bars/{bars}", response_model=ArrangeGenerateResponse)
async def arrange_loop_with_bars(
    loop_id: int,
    bars: int,
    db: Session = Depends(get_db),
) -> ArrangeGenerateResponse:
    """Generate an arrangement by specifying exact bar count.

    Shorthand endpoint for specifying bars directly in the URL.

    Args:
        loop_id: The ID of the loop to arrange
        bars: Number of 4/4 bars for the arrangement (4-4096)
        db: Database session

    Returns:
        ArrangeGenerateResponse with the generated arrangement

    Raises:
        HTTPException 404: If loop not found
        HTTPException 400: If bars out of range

    Example:
        ```
        POST /arrange/1/bars/64
        
        Generates a 64-bar arrangement for loop 1
        ```
    """
    request = ArrangeGenerateRequest(bars=bars)
    return await arrange_loop(loop_id, request, db)


@router.post("/arrange/{loop_id}/duration/{duration_seconds}", response_model=ArrangeGenerateResponse)
async def arrange_loop_with_duration(
    loop_id: int,
    duration_seconds: int,
    db: Session = Depends(get_db),
) -> ArrangeGenerateResponse:
    """Generate an arrangement by specifying exact duration.

    Shorthand endpoint for specifying duration directly in the URL.

    Args:
        loop_id: The ID of the loop to arrange
        duration_seconds: Target duration in seconds (15-3600)
        db: Database session

    Returns:
        ArrangeGenerateResponse with the generated arrangement

    Raises:
        HTTPException 404: If loop not found
        HTTPException 400: If duration out of range

    Example:
        ```
        POST /arrange/1/duration/120
        
        Generates a 2-minute (120 second) arrangement for loop 1
        ```
    """
    request = ArrangeGenerateRequest(duration_seconds=duration_seconds)
    return await arrange_loop(loop_id, request, db)