from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopResponse

router = APIRouter()


@router.post("/loops", response_model=LoopResponse, status_code=201)
def create_loop(loop_in: LoopCreate, db: Session = Depends(get_db)):
    loop = Loop(**loop_in.model_dump())
    db.add(loop)
    try:
        db.commit()
        db.refresh(loop)
    except Exception:
        db.rollback()
        raise
    return loop


@router.get("/loops", response_model=list[LoopResponse])
def list_loops(db: Session = Depends(get_db)):
    return db.query(Loop).all()


@router.get("/loops/{loop_id}", response_model=LoopResponse)
def get_loop(loop_id: int, db: Session = Depends(get_db)):
    loop = db.query(Loop).filter(Loop.id == loop_id).first()
    if loop is None:
        raise HTTPException(status_code=404, detail="Loop not found")
    return loop
