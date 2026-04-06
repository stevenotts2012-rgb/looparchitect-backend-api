from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings


def add_cors_middleware(app: FastAPI) -> None:
    # Upload and API requests do not rely on browser credentials/cookies.
    # Keep credentials disabled and allow Vercel and Railway frontend origins via
    # regex to avoid brittle per-environment allowlist drift. The Vercel regex
    # covers both the production domain and all preview-deployment subdomains
    # (e.g. looparchitect-frontend-git-main-<hash>-*.vercel.app).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_origin_regex=r"https://(.*\.vercel\.app|.*\.railway\.app)",
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
