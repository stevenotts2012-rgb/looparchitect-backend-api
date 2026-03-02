import os
from urllib.parse import urlparse
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

    _default_frontend_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "https://web-production-3afc5.up.railway.app",
    )

    @staticmethod
    def _normalize_origin(origin: str) -> str:
        return origin.strip().rstrip("/")

    @staticmethod
    def _is_valid_origin(origin: str) -> bool:
        parsed = urlparse(origin)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @staticmethod
    def _parse_frontend_origin_env(frontend_origin: str) -> list[str]:
        """Support one origin or a comma-separated list in FRONTEND_ORIGIN."""
        if not frontend_origin.strip():
            return []
        parsed_origins: list[str] = []
        for item in frontend_origin.split(","):
            normalized = Settings._normalize_origin(item)
            if not normalized:
                continue
            if Settings._is_valid_origin(normalized):
                parsed_origins.append(normalized)
        return parsed_origins

    @property
    def invalid_frontend_origins(self) -> list[str]:
        """Return invalid FRONTEND_ORIGIN entries for startup diagnostics."""
        if not self.frontend_origin.strip():
            return []

        invalid: list[str] = []
        for item in self.frontend_origin.split(","):
            normalized = self._normalize_origin(item)
            if not normalized:
                continue
            if not self._is_valid_origin(normalized):
                invalid.append(normalized)
        return invalid
    
    @property
    def allowed_origins(self) -> list[str]:
        """Build allowed origins for CORS policy.

        - Always allow local Next.js development on localhost:3000.
        - Allow Railway production frontend by default.
        - If FRONTEND_ORIGIN is set, use its value(s) in addition to localhost.
        """
        configured_origins = self._parse_frontend_origin_env(self.frontend_origin)
        origins = [self._normalize_origin("http://localhost:3000")]

        if configured_origins:
            origins.extend(configured_origins)
        else:
            origins.extend(
                self._normalize_origin(origin)
                for origin in self._default_frontend_origins
                if origin
            )

        deduped: list[str] = []
        seen: set[str] = set()
        for origin in origins:
            if origin and origin not in seen:
                seen.add(origin)
                deduped.append(origin)

        return deduped
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
