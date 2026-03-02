import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LoopArchitect API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = os.getenv("ENVIRONMENT", "development")
    storage_backend: str = os.getenv("STORAGE_BACKEND", "local")
    redis_url: str = os.getenv("REDIS_URL", "")
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_region: str = os.getenv("AWS_REGION", "")
    aws_s3_bucket: str = os.getenv("AWS_S3_BUCKET", "")
    
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
    # Use DATABASE_URL from environment if available, otherwise local SQLite for development
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./test.db")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    def validate_startup(self) -> None:
        """Validate required environment variables for startup safety."""
        backend = (self.storage_backend or "").strip().lower()
        if backend not in {"local", "s3"}:
            raise RuntimeError(
                "Invalid STORAGE_BACKEND. Allowed values: local or s3"
            )

        missing: list[str] = []

        if self.is_production:
            if not os.getenv("DATABASE_URL"):
                missing.append("DATABASE_URL")
            if not os.getenv("REDIS_URL"):
                missing.append("REDIS_URL")

        if backend == "s3":
            if not self.aws_access_key_id:
                missing.append("AWS_ACCESS_KEY_ID")
            if not self.aws_secret_access_key:
                missing.append("AWS_SECRET_ACCESS_KEY")
            if not self.aws_region:
                missing.append("AWS_REGION")
            if not self.aws_s3_bucket:
                missing.append("AWS_S3_BUCKET")

        if self.aws_s3_bucket == "your-bucket-name":
            missing.append("AWS_S3_BUCKET")

        if missing:
            unique_missing = sorted(set(missing))
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(unique_missing)}"
            )

    class Config:
        env_file = ".env"


settings = Settings()
