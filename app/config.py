import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LoopArchitect API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = "production"
    # Override in production with a restrictive list of allowed origins
    allowed_origins: list[str] = ["*"]
    # Use DATABASE_URL from environment if available, otherwise default to writable SQLite path
    # Note: /tmp is writable on Render; local ./test.db is only for development
    database_url: str = os.getenv(
        "DATABASE_URL", 
        "sqlite:////tmp/looparchitect.db" if os.getenv("RENDER") else "sqlite:///./test.db"
    )

    class Config:
        env_file = ".env"


settings = Settings()
