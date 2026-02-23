import logging
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from sqlalchemy import text

from app.db import get_db

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/db/health")
def db_health_check(db: Session = Depends(get_db)):
    """Check database connectivity.
    
    Returns:
        {"status": "ok"} if database is accessible
        {"status": "error", "detail": "error message"} with 500 status on failure
    """
    try:
        db.execute(text("SELECT 1")).scalar()
        return {"status": "ok"}
    except Exception as e:
        logger.exception("Database health check failed")
        return JSONResponse(
            status_code=500, 
            content={"status": "error", "detail": str(e)}
        )
