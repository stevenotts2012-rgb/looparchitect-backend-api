from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db import init_db
from app.middleware.cors import add_cors_middleware
from app.routes import api, health, db_health


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title=settings.app_name, debug=settings.debug, lifespan=lifespan)

add_cors_middleware(app)

app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(db_health.router, prefix="/api/v1", tags=["database"])
app.include_router(api.router, prefix="/api/v1", tags=["api"])