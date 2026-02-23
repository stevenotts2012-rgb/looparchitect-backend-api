from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


def add_cors_middleware(app: FastAPI) -> None:
    # allow_credentials=True is incompatible with allow_origins=["*"] per the CORS
    # spec; browsers will reject such responses.  Only enable credentials when the
    # caller has configured explicit (non-wildcard) origins.
    allow_credentials = "*" not in settings.allowed_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=allow_credentials,
        allow_methods=["*"],
        allow_headers=["*"],
    )
