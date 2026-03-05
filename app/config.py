import os
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LoopArchitect API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = os.getenv("ENVIRONMENT", "development")
    storage_backend: str = os.getenv("STORAGE_BACKEND", "")
    redis_url: str = os.getenv("REDIS_URL", "")
    aws_access_key_id: str = os.getenv("AWS_ACCESS_KEY_ID", "")
    aws_secret_access_key: str = os.getenv("AWS_SECRET_ACCESS_KEY", "")
    aws_region: str = os.getenv("AWS_REGION", "")
    aws_s3_bucket: str = os.getenv("AWS_S3_BUCKET", "")
    s3_bucket_name: str = os.getenv("S3_BUCKET_NAME", "")
    frontend_origin: str = os.getenv("FRONTEND_ORIGIN", "")
    cors_allowed_origins: str = os.getenv("CORS_ALLOWED_ORIGINS", "")
    api_base_url: str = os.getenv("API_BASE_URL", "")
    feature_style_engine: bool = os.getenv("FEATURE_STYLE_ENGINE", "false").lower() == "true"
    feature_style_sliders: bool = os.getenv("FEATURE_STYLE_SLIDERS", "false").lower() == "true"
    feature_variations: bool = os.getenv("FEATURE_VARIATIONS", "false").lower() == "true"
    feature_beat_switch: bool = os.getenv("FEATURE_BEAT_SWITCH", "false").lower() == "true"
    feature_midi_export: bool = os.getenv("FEATURE_MIDI_EXPORT", "false").lower() == "true"
    feature_stem_export: bool = os.getenv("FEATURE_STEM_EXPORT", "false").lower() == "true"
    feature_pattern_generation: bool = os.getenv("FEATURE_PATTERN_GENERATION", "false").lower() == "true"
    feature_producer_engine: bool = os.getenv("FEATURE_PRODUCER_ENGINE", "false").lower() == "true"
    dev_fallback_loop_only: bool = os.getenv("DEV_FALLBACK_LOOP_ONLY", "false").lower() == "true"
    
    # LLM Style Engine V2 settings
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_base_url: str = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4")
    openai_timeout: int = int(os.getenv("OPENAI_TIMEOUT", "30"))
    openai_max_retries: int = int(os.getenv("OPENAI_MAX_RETRIES", "3"))
    feature_llm_style_parsing: bool = os.getenv("FEATURE_LLM_STYLE_PARSING", "false").lower() == "true"
    ffmpeg_binary: str = os.getenv("FFMPEG_BINARY", "")
    ffprobe_binary: str = os.getenv("FFPROBE_BINARY", "")
    enforce_audio_binaries: str = os.getenv("ENFORCE_AUDIO_BINARIES", "auto")
    
    # Request size limits
    max_upload_size_mb: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "100"))
    max_request_body_size_mb: int = int(os.getenv("MAX_REQUEST_BODY_SIZE_MB", "100"))

    @property
    def allowed_origins(self) -> list[str]:
        """Build allowed origins for CORS policy.

        - Always allow http://localhost:3000 for local development.
        - Always allow http://localhost:5173 for Vite local development.
        - Add production origins from CORS_ALLOWED_ORIGINS or FRONTEND_ORIGIN env vars.
        - If FRONTEND_ORIGIN not set, use Railway default.
        """
        origins: list[str] = ["http://localhost:3000", "http://localhost:5173"]

        configured_origins = (self.cors_allowed_origins or self.frontend_origin).strip()
        if configured_origins:
            for origin in configured_origins.split(","):
                normalized_origin = origin.strip().rstrip("/")
                if normalized_origin and normalized_origin not in origins:
                    origins.append(normalized_origin)
        else:
            default_origin = "https://web-production-3afc5.up.railway.app"
            if default_origin not in origins:
                origins.append(default_origin)

        return origins

    def get_s3_bucket(self) -> str:
        """Return configured S3 bucket using supported env aliases."""
        return (self.aws_s3_bucket or self.s3_bucket_name or "").strip()

    def has_s3_config(self) -> bool:
        """Return True when all required S3 settings are present."""
        return bool(
            self.aws_access_key_id
            and self.aws_secret_access_key
            and self.aws_region
            and self.get_s3_bucket()
        )

    def get_storage_backend(self) -> str:
        """Resolve active storage backend.

        Rules:
        1) If STORAGE_BACKEND is explicitly set, obey it (local|s3).
        2) Else if ENVIRONMENT=production and S3 vars are complete, use s3.
        3) Else use local.
        """
        explicit_backend = (self.storage_backend or "").strip().lower()
        if explicit_backend:
            if explicit_backend not in {"local", "s3"}:
                raise RuntimeError("Invalid STORAGE_BACKEND. Allowed values: local or s3")
            return explicit_backend

        if self.is_production and self.has_s3_config():
            return "s3"

        return "local"

    # Use DATABASE_URL from environment if available, otherwise local SQLite for development
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///./test.db")

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def should_enforce_audio_binaries(self) -> bool:
        policy = (self.enforce_audio_binaries or "auto").strip().lower()
        if policy in {"true", "1", "yes", "on"}:
            return True
        if policy in {"false", "0", "no", "off"}:
            return False
        return self.is_production

    def validate_startup(self) -> None:
        """Validate required environment variables for startup safety."""
        backend = self.get_storage_backend()

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
            if not self.get_s3_bucket():
                missing.append("AWS_S3_BUCKET or S3_BUCKET_NAME")

        if self.get_s3_bucket() == "your-bucket-name":
            missing.append("AWS_S3_BUCKET or S3_BUCKET_NAME")

        if missing:
            unique_missing = sorted(set(missing))
            raise RuntimeError(
                f"Missing required environment variables: {', '.join(unique_missing)}"
            )
        
        # Warn if LLM parsing is enabled but API key not configured
        if self.feature_llm_style_parsing and not self.openai_api_key:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "FEATURE_LLM_STYLE_PARSING is enabled but OPENAI_API_KEY is not configured. "
                "LLM-powered style parsing will fail. Set OPENAI_API_KEY to enable this feature."
            )

    class Config:
        env_file = ".env"


settings = Settings()
