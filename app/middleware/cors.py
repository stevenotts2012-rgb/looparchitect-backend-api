from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


def add_cors_middleware(app: FastAPI) -> None:
    # Upload and API requests do not rely on browser credentials/cookies.
    # Keep credentials disabled and allow Railway frontend origins via regex
    # to avoid brittle per-environment allowlist drift.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=r"https://.*\.railway\.app",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
