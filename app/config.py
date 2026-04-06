from typing import Any, Optional
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_name: str = "LoopArchitect API"
    app_version: str = "1.0.0"
    debug: bool = False
    environment: str = Field(default="development", validation_alias="ENVIRONMENT")
    storage_backend: str = Field(default="", validation_alias="STORAGE_BACKEND")
    redis_url: Optional[str] = Field(default=None, validation_alias="REDIS_URL")
    enable_embedded_rq_worker: bool = Field(default=False, validation_alias="ENABLE_EMBEDDED_RQ_WORKER")
    embedded_rq_worker_count: int = Field(default=2, validation_alias="EMBEDDED_RQ_WORKER_COUNT")
    aws_access_key_id: str = Field(default="", validation_alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str = Field(default="", validation_alias="AWS_SECRET_ACCESS_KEY")
    aws_region: str = Field(default="", validation_alias="AWS_REGION")
    aws_s3_bucket: str = Field(default="", validation_alias="AWS_S3_BUCKET")
    s3_bucket_name: str = Field(default="", validation_alias="S3_BUCKET_NAME")
    frontend_origin: str = Field(default="", validation_alias="FRONTEND_ORIGIN")
    cors_allowed_origins: str = Field(default="", validation_alias="CORS_ALLOWED_ORIGINS")
    api_base_url: str = Field(default="", validation_alias="API_BASE_URL")
    feature_style_engine: bool = Field(default=False, validation_alias="FEATURE_STYLE_ENGINE")
    feature_style_sliders: bool = Field(default=False, validation_alias="FEATURE_STYLE_SLIDERS")
    feature_variations: bool = Field(default=False, validation_alias="FEATURE_VARIATIONS")
    feature_beat_switch: bool = Field(default=False, validation_alias="FEATURE_BEAT_SWITCH")
    feature_midi_export: bool = Field(default=False, validation_alias="FEATURE_MIDI_EXPORT")
    feature_stem_export: bool = Field(default=False, validation_alias="FEATURE_STEM_EXPORT")
    feature_pattern_generation: bool = Field(default=False, validation_alias="FEATURE_PATTERN_GENERATION")
    feature_producer_engine: bool = Field(default=True, validation_alias="FEATURE_PRODUCER_ENGINE")
    feature_stem_separation: bool = Field(default=False, validation_alias="FEATURE_STEM_SEPARATION")
    feature_mastering_stage: bool = Field(default=True, validation_alias="FEATURE_MASTERING_STAGE")
    stem_separation_backend: str = Field(default="builtin", validation_alias="STEM_SEPARATION_BACKEND")
    mastering_profile_default: str = Field(default="transparent", validation_alias="MASTERING_PROFILE_DEFAULT")
    dev_fallback_loop_only: bool = Field(default=False, validation_alias="DEV_FALLBACK_LOOP_ONLY")
    
    # LLM Style Engine V2 settings
    openai_api_key: str = Field(default="", validation_alias="OPENAI_API_KEY")
    openai_base_url: str = Field(default="https://api.openai.com/v1", validation_alias="OPENAI_BASE_URL")
    openai_model: str = Field(default="gpt-4", validation_alias="OPENAI_MODEL")
    openai_timeout: int = Field(default=30, validation_alias="OPENAI_TIMEOUT")
    openai_max_retries: int = Field(default=3, validation_alias="OPENAI_MAX_RETRIES")
    feature_llm_style_parsing: bool = Field(default=False, validation_alias="FEATURE_LLM_STYLE_PARSING")

    # Producer Engine V2 — deterministic section planning with decision log
    feature_producer_engine_v2: bool = Field(default=False, validation_alias="PRODUCER_ENGINE_V2")

    # AI Co-Producer Assist — AI proposes, rules validate, engine executes
    feature_ai_producer_assist: bool = Field(default=False, validation_alias="AI_PRODUCER_ASSIST")

    # AI Style Interpretation — style-specific AI reasoning layer
    feature_ai_style_interpretation: bool = Field(default=False, validation_alias="AI_STYLE_INTERPRETATION")

    # Reference-Guided Arrangement Mode — use an uploaded reference track as a structural blueprint
    # Musical content is NEVER copied; only structure/energy guidance is extracted.
    feature_reference_guided_arrangement: bool = Field(
        default=False,
        validation_alias="REFERENCE_GUIDED_ARRANGEMENT",
    )

    # Reference Section Analysis — enables the reference audio analysis endpoint and analyzer service
    feature_reference_section_analysis: bool = Field(
        default=False,
        validation_alias="REFERENCE_SECTION_ANALYSIS",
    )
    ffmpeg_binary: str = Field(default="", validation_alias="FFMPEG_BINARY")
    ffprobe_binary: str = Field(default="", validation_alias="FFPROBE_BINARY")
    enforce_audio_binaries: str = Field(default="auto", validation_alias="ENFORCE_AUDIO_BINARIES")
    
    # Request size limits
    max_upload_size_mb: int = Field(default=100, validation_alias="MAX_UPLOAD_SIZE_MB")
    max_request_body_size_mb: int = Field(default=100, validation_alias="MAX_REQUEST_BODY_SIZE_MB")
    render_job_timeout_seconds: int = Field(default=900, validation_alias="RENDER_JOB_TIMEOUT_SECONDS")

    @field_validator("enable_embedded_rq_worker", mode="before")
    @classmethod
    def convert_embedded_worker_bool(cls, v: Any) -> bool:
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on")
        return bool(v)

    @field_validator("embedded_rq_worker_count", mode="before")
    @classmethod
    def convert_worker_count(cls, v: Any) -> int:
        try:
            return max(1, int(v))
        except (TypeError, ValueError):
            return 2

    @field_validator(
        "feature_style_engine",
        "feature_style_sliders",
        "feature_variations",
        "feature_beat_switch",
        "feature_midi_export",
        "feature_stem_export",
        "feature_pattern_generation",
        "feature_producer_engine",
        "feature_stem_separation",
        "feature_mastering_stage",
        "dev_fallback_loop_only",
        "feature_llm_style_parsing",
        "feature_producer_engine_v2",
        "feature_ai_producer_assist",
        "feature_ai_style_interpretation",
        "feature_reference_guided_arrangement",
        "feature_reference_section_analysis",
        mode="before",
    )
    @classmethod
    def convert_bool(cls, v: Any) -> bool:
        """Convert string boolean values to actual booleans."""
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "on")
        if isinstance(v, bool):
            return v
        return bool(v)

    @property
    def allowed_origins(self) -> list[str]:
        """Build allowed origins for CORS policy.

        Local development (always included):
          - http://localhost:3000   — canonical Next.js frontend (primary)
          - http://127.0.0.1:3000  — same host via numeric IP (avoids localhost/127.0.0.1 mismatch)
          - http://localhost:5173   — Vite alternative dev server
          - http://127.0.0.1:5173  — Vite via numeric IP

        Production origins come from CORS_ALLOWED_ORIGINS or FRONTEND_ORIGIN env vars.
        A warning is logged in production when neither is configured.
        """
        origins: list[str] = [
            # Canonical local-dev frontend: http://localhost:3000
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            # Vite alternative
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            # Vercel production frontend (also covered by allow_origin_regex in cors middleware)
            "https://looparchitect-frontend.vercel.app",
        ]

        configured_origins = (self.cors_allowed_origins or self.frontend_origin).strip()
        if configured_origins:
            for origin in configured_origins.split(","):
                normalized_origin = origin.strip().rstrip("/")
                if normalized_origin and normalized_origin not in origins:
                    origins.append(normalized_origin)
        elif self.is_production:
            import logging as _logging
            _logging.getLogger(__name__).warning(
                "No CORS_ALLOWED_ORIGINS or FRONTEND_ORIGIN configured for production. "
                "Cross-origin browser requests from the frontend will be blocked. "
                "Set FRONTEND_ORIGIN or CORS_ALLOWED_ORIGINS to your deployed frontend URL."
            )

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
    database_url: str = Field(default="sqlite:///./test.db", validation_alias="DATABASE_URL")

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

    @staticmethod
    def _redis_url_is_local(url: str) -> bool:
        """Return True if *url* resolves to a loopback/localhost address."""
        from urllib.parse import urlparse

        try:
            hostname = urlparse(url).hostname or ""
        except Exception:
            return False
        return hostname in ("127.0.0.1", "::1", "localhost")

    def validate_startup(self) -> None:
        """Validate required environment variables for startup safety."""
        backend = self.get_storage_backend()

        missing: list[str] = []

        if self.is_production:
            if not self.database_url or self.database_url == "sqlite:///./test.db":
                missing.append("DATABASE_URL")
            if not self.redis_url:
                missing.append("REDIS_URL")
            elif self._redis_url_is_local(self.redis_url):
                raise RuntimeError(
                    "REDIS_URL points to localhost in production. "
                    "Set REDIS_URL to the managed Redis URL provided by your platform "
                    "(e.g., Railway/Render/Upstash). "
                    "Production must not depend on a local Redis instance."
                )

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
                missing.append("AWS_S3_BUCKET or S3_BUCKET_NAME (placeholder value must be replaced)")

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

        # Warn if AI producer assist is enabled but API key not configured
        if self.feature_ai_producer_assist and not self.openai_api_key:
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                "AI_PRODUCER_ASSIST is enabled but OPENAI_API_KEY is not configured. "
                "AI co-producer assist will fall back to rules-only mode."
            )

    model_config = {
        "env_file": ".env",
        "extra": "allow",
    }


settings = Settings()
