from fastapi import APIRouter, Depends, HTTPException, Body
from pydantic import BaseModel
from typing import Dict, List, Optional
from sqlalchemy.orm import Session
import math

from app.db import get_db
from app.models.loop import Loop
from app.services.arranger import create_arrangement

router = APIRouter(prefix="/api/v1", tags=["arrange"])


class ArrangeRequest(BaseModel):
    length_seconds: Optional[int] = 180


class ArrangeResponse(BaseModel):
    loop_id: int
    sections: List[Dict]
    bars_total: int
    length_seconds: int


@router.post("/arrange/{loop_id}", response_model=ArrangeResponse)
def arrange(
    loop_id: int,
    request: ArrangeRequest = Body(default=ArrangeRequest()),
    db: Session = Depends(get_db),
):
    """
    Create an arrangement blueprint for a loop.
    
    Accepts optional length_seconds to scale the arrangement sections.
    Uses BPM (default 140) to calculate total bars and scale sections.
    
    Args:
        loop_id: The ID of the loop to arrange
        request: ArrangeRequest with optional length_seconds
        db: Database session
    
    Returns:
        Arrangement with sections, bars_total, and length_seconds
    """
    # Query database for the loop
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    # Check if loop exists
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    
    # Get parameters
    length_seconds = request.length_seconds or 180
    bpm = loop.tempo or 140.0  # Default BPM is 140
    
    # Calculate total bars
    # seconds_per_bar = (60 / bpm) * 4
    seconds_per_bar = (60 / bpm) * 4
    bars_total = math.ceil(length_seconds / seconds_per_bar)
    
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
    }