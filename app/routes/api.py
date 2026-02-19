from fastapi import APIRouter

from app.config import settings
from app.models.schemas import StatusResponse

router = APIRouter()


@router.get("/")
async def read_root():
    return {"Hello": "World"}


@router.get("/status", response_model=StatusResponse)
async def get_status():
    return StatusResponse(
        status="ok",
        version=settings.app_version,
        environment=settings.environment,
    )
