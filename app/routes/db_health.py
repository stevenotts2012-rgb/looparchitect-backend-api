from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db import get_db

router = APIRouter()


@router.get("/db-health")
def db_health_check(db: Session = Depends(get_db)):
    try:
        db.execute(text("SELECT 1")).scalar()
        return {"db": "ok"}
    except Exception as e:
        return JSONResponse(status_code=500, content={"db": "error", "detail": str(e)})
