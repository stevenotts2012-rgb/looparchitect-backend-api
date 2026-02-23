from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
import math

from app.db import get_db
from app.models.loop import Loop
from app.services.arranger import create_arrangement

router = APIRouter(prefix="/api/v1", tags=["arrange"])

# Safety limits to protect server from realtime generation overload
MAX_SECONDS = 21600  # 6 hours
MAX_BARS = 4096


class ArrangeRequest(BaseModel):
    length_seconds: Optional[int] = None
    total_bars: Optional[int] = None
    bpm: Optional[float] = None


class ArrangeResponse(BaseModel):
    loop_id: int
    sections: List[Dict]
    bars_total: int
    length_seconds: int
    bpm: float


@router.post("/arrange/{loop_id}", response_model=ArrangeResponse)
def arrange(
    loop_id: int,
    request: ArrangeRequest = Body(default=ArrangeRequest()),
    db: Session = Depends(get_db),
):
    """
    Create an arrangement blueprint for a loop.
    
    Accepts flexible length specification:
    - total_bars: Directly specify bar count (preferred if both provided)
    - length_seconds: Specify duration in seconds (converted to bars using BPM)
    - bpm: Optional BPM override (defaults to loop's tempo or 140)
    
    If neither length_seconds nor total_bars provided, defaults to length_seconds=180.
    
    Args:
        loop_id: The ID of the loop to arrange
        request: ArrangeRequest with optional length_seconds, total_bars, or bpm
        db: Database session
    
    Returns:
        Arrangement with sections, bars_total, length_seconds, and bpm used
    
    Raises:
        HTTPException 404: If loop not found
        HTTPException 400: If arrangement parameters exceed safety limits
    """
    # Query database for the loop
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    # Check if loop exists
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    
    # Determine BPM to use
    bpm = request.bpm or loop.tempo or 140.0
    
    # Determine bars_total based on priority: total_bars > length_seconds > default
    if request.total_bars is not None:
        bars_total = request.total_bars
    else:
        # Use length_seconds (default to 180 if not provided)
        length_seconds = request.length_seconds or 180
        
        # Validate length_seconds against safety limit
        if length_seconds > MAX_SECONDS:
            raise HTTPException(
                status_code=400,
                detail=f"Length {length_seconds}s exceeds maximum {MAX_SECONDS}s (6 hours). "
                        "Please request a shorter arrangement for realtime generation."
            )
        if length_seconds < 1:
            raise HTTPException(status_code=400, detail="Length must be at least 1 second")
        
        # Convert length_seconds to bars: bars = round((length_seconds / 60) * (bpm / 4))
        bars_total = max(4, round((length_seconds / 60) * (bpm / 4)))
    
    # Validate bars_total against safety limit
    if bars_total > MAX_BARS:
        raise HTTPException(
            status_code=400,
            detail=f"Arrangement size {bars_total} bars exceeds maximum {MAX_BARS} bars. "
                    "Please request a shorter arrangement for realtime generation."
        )
    if bars_total < 4:
        bars_total = 4
    
    # Compute length_seconds from bars_total and BPM
    # seconds_per_bar = (60 / bpm) * 4
    seconds_per_bar = (60 / bpm) * 4
    length_seconds = round(bars_total * seconds_per_bar)
    
    # Generate arrangement blueprint
    arrangement = create_arrangement()
    
    # Calculate current total bars
    current_total_bars = sum(section.get("bars", 4) for section in arrangement)
    
    # Scale sections to match bars_total
    if current_total_bars > 0 and bars_total > 0:
        scale_factor = bars_total / current_total_bars
        scaled_arrangement = []
        
        for i, section in enumerate(arrangement):
            bars = section.get("bars", 4)
            # For the last section, use remaining bars to ensure we hit exactly bars_total
            if i == len(arrangement) - 1:
                scaled_bars = bars_total - sum(s.get("bars", 4) for s in scaled_arrangement)
            else:
                scaled_bars = max(1, round(bars * scale_factor))
            
            scaled_section = section.copy()
            scaled_section["bars"] = scaled_bars
            scaled_arrangement.append(scaled_section)
    else:
        scaled_arrangement = arrangement
    
    return {
        "loop_id": loop_id,
        "sections": scaled_arrangement,
        "bars_total": bars_total,
        "length_seconds": length_seconds,
        "bpm": bpm,
    }