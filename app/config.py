import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LoopArchitect API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "production"
    
    @property
    def allowed_origins(self) -> list[str]:
        """
        Build allowed origins from default list + FRONTEND_ORIGIN env var.
        
        Defaults include localhost for dev and production Render domain.
        FRONTEND_ORIGIN env var allows adding additional production domains.
        """
        origins = [
            "https://looparchitect-backend-api.onrender.com",
            "http://localhost:3000",
            "http://localhost:5173",
        ]
        # Add production frontend domain if specified
        frontend_origin = os.getenv("FRONTEND_ORIGIN")
        if frontend_origin:
            origins.append(frontend_origin)
        return origins
    # Use DATABASE_URL from environment if available, otherwise default to writable SQLite path
    # Note: /tmp is writable on Render; local ./test.db is only for development
    database_url: str = os.getenv(
        "DATABASE_URL", 
        "sqlite:////tmp/looparchitect.db" if os.getenv("RENDER") else "sqlite:///./test.db"
    )

    class Config:
        env_file = ".env"


settings = Settings()
