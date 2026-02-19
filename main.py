from fastapi import FastAPI

from app.config import settings
from app.middleware.cors import add_cors_middleware
from app.routes import api, health

app = FastAPI(title=settings.app_name, debug=settings.debug)

add_cors_middleware(app)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(api.router, prefix="/api/v1", tags=["api"])