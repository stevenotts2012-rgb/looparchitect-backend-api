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
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "")

    @property
    def allowed_origins(self) -> list[str]:
        """Build allowed origins for CORS policy.

        - Always allow http://localhost:3000 for local development.
        - Add production origins from FRONTEND_ORIGIN env var (comma-separated).
        - If FRONTEND_ORIGIN not set, use Railway default.
        """
        # Always include localhost for development
        origins: list[str] = ["http://localhost:3000"]
        
        # Add production origins from environment or use default
        frontend_env = self.frontend_origin.strip()
        if frontend_env:
            # Parse comma-separated origins from FRONTEND_ORIGIN
            for origin in frontend_env.split(","):
                origin = origin.strip().rstrip("/")
                if origin and origin not in origins:
                    origins.append(origin)
        else:
            # Default Railway frontend
            default_origin = "https://web-production-3afc5.up.railway.app"
            if default_origin not in origins:
                origins.append(default_origin)
        
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
