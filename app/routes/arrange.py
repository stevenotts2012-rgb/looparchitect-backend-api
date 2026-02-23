from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, List
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.services.arranger import create_arrangement

router = APIRouter(prefix="/api/v1", tags=["arrange"])


class ArrangeResponse(BaseModel):
    loop_id: int
    sections: List[Dict]


@router.post("/arrange/{loop_id}", response_model=ArrangeResponse)
def arrange(loop_id: int, db: Session = Depends(get_db)):
    """
    Create an arrangement blueprint for a loop.
    
    Args:
        loop_id: The ID of the loop to arrange
        db: Database session
    
    Returns:
        Arrangement with sections and loop_id
    """
    # Query database for the loop
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    
    # Check if loop exists
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    
    # Generate arrangement blueprint
    arrangement = create_arrangement()
    
    return {
        "loop_id": loop_id,
        "sections": arrangement,
    }