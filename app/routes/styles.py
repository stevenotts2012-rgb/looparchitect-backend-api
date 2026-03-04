from __future__ import annotations

from fastapi import APIRouter

from app.services.style_service import style_service

router = APIRouter()


@router.get("/styles")
def list_styles() -> dict[str, object]:
    """Phase 0 skeleton endpoint (not yet registered in router map)."""
    return {"styles": style_service.get_styles()}
