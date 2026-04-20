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

    # Producer Engine Strict Rules — enables additional anti-mud / density guardrails
    # (melodic density cap, low-frequency crowding prevention, sustained source limit).
    # Defaults to False for safe staged rollout; enable with PRODUCER_ENGINE_STRICT_RULES=true.
    feature_producer_engine_strict_rules: bool = Field(
        default=False,
        validation_alias="PRODUCER_ENGINE_STRICT_RULES",
    )

    # Section Identity Engine V2 — deterministic per-section profiles, repeated-section evolution,
    # role choreography, and quality metrics.  Controls both arrangement_planner.py and
    # arrangement_jobs.py integration.  Safe to enable independently of PRODUCER_ENGINE_V2.
    # Enabled by default: this is the primary mechanism that makes sections sound distinct from
    # one another (verse vs hook, hook1 vs hook2, etc.).  Disable with
    # PRODUCER_SECTION_IDENTITY_V2=false only when rolling back to the legacy role picker.
    feature_producer_section_identity_v2: bool = Field(
        default=True,
        validation_alias="PRODUCER_SECTION_IDENTITY_V2",
    )

    # Section Choreography V2 — per-section role hierarchy (leader/support/suppressed/contrast),
    # support-role rotation between repeated sections, intra-section phrase variation, and the
    # five Phase-5 audible-contrast QA metrics.
    # Requires PRODUCER_SECTION_IDENTITY_V2=true to take full effect.
    # Enabled by default alongside PRODUCER_SECTION_IDENTITY_V2 so that hook/verse repeats
    # get intra-section phrase variation and support-role rotation.  Disable with
    # SECTION_CHOREOGRAPHY_V2=false to revert to the non-choreography identity engine path.
    feature_section_choreography_v2: bool = Field(
        default=True,
        validation_alias="SECTION_CHOREOGRAPHY_V2",
    )

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

    # Advanced Stem Separation V2 — two-stage separation pipeline for single-file uploads.
    # Stage 1: broad stem separation (drums / bass / vocals / other).
    # Stage 2: spectral/temporal analysis to derive richer sub-roles
    #   (kick / snare / hi_hat / 808 / piano / guitar / pads / arp / …).
    # When disabled (default) the existing 4-stem builtin separation is used unchanged.
    # Enable with ADVANCED_STEM_SEPARATION_V2=true for staged rollout.
    feature_advanced_stem_separation_v2: bool = Field(
        default=False,
        validation_alias="ADVANCED_STEM_SEPARATION_V2",
    )

    # Preferred stem separation backend for the advanced pipeline.
    # Controls Stage 1 of run_advanced_separation().  The pipeline always falls
    # back to the builtin frequency-based splitter when the preferred backend
    # is unavailable (e.g. Demucs not installed).
    # Valid values: demucs_htdemucs_6s | demucs_htdemucs | demucs | builtin
    # Default: demucs_htdemucs_6s (6-stem model, highest quality when available)
    preferred_stem_backend: str = Field(
        default="demucs_htdemucs_6s",
        validation_alias="PREFERRED_STEM_BACKEND",
    )

    # Arrangement Quality Gates — extended quality gate checks (section contrast,
    # repeat differentiation, hook payoff, melodic overcrowding, low-end mud,
    # source confidence, arrangement audibility) plus auto-repair.
    # Enable with ARRANGEMENT_QUALITY_GATES=true.
    feature_arrangement_quality_gates: bool = Field(
        default=False,
        validation_alias="ARRANGEMENT_QUALITY_GATES",
    )

    # Source Quality Mode — classify stems as true_stems / zip_stems /
    # ai_separated / stereo_fallback and apply per-mode arrangement constraints.
    # Enable with SOURCE_QUALITY_MODES=true.
    feature_source_quality_modes: bool = Field(
        default=False,
        validation_alias="SOURCE_QUALITY_MODES",
    )

    # Arrangement Plan V2 — structured SectionPlan + ArrangementPlanV2 with
    # StemRole model, named VariationStrategy choices, and full decision log.
    # Gates the V2 plan builder in arrangement_plan_v2.py.
    # Enable with ARRANGEMENT_PLAN_V2=true.
    feature_arrangement_plan_v2: bool = Field(
        default=False,
        validation_alias="ARRANGEMENT_PLAN_V2",
    )

    # Arrangement Memory V2 — stateful planning memory that tracks used stems,
    # role combinations, energy history, section occurrence counts, and repeat
    # variation history to prevent flat/identical section output.
    # Requires ARRANGEMENT_PLAN_V2=true to take full effect.
    # Enable with ARRANGEMENT_MEMORY_V2=true.
    feature_arrangement_memory_v2: bool = Field(
        default=False,
        validation_alias="ARRANGEMENT_MEMORY_V2",
    )

    # Arrangement Transitions V2 — ensures every section boundary has an
    # explicit transition plan (riser, drum_fill, reverse_fx, silence_gap,
    # subtractive_entry, re_entry_accent). Requires ARRANGEMENT_PLAN_V2=true.
    # Enable with ARRANGEMENT_TRANSITIONS_V2=true.
    feature_arrangement_transitions_v2: bool = Field(
        default=False,
        validation_alias="ARRANGEMENT_TRANSITIONS_V2",
    )

    # Arrangement Truth Observability V2 — exposes planned vs. actual stem maps,
    # render signatures per section, source quality mode, and section occurrence
    # info so audits can prove the plan survived to render output.
    # Enable with ARRANGEMENT_TRUTH_OBSERVABILITY_V2=true.
    feature_arrangement_truth_observability_v2: bool = Field(
        default=False,
        validation_alias="ARRANGEMENT_TRUTH_OBSERVABILITY_V2",
    )

    # Arranger V2 — fully deterministic, stateful, musically coherent arrangement
    # engine with isolated planning layer (arranger_v2/ module).
    # Replaces the loosely-structured stem selection with a deterministic pipeline:
    #   1. Build ArrangementPlan (planner.py)
    #   2. Select stems per section (density_engine.py)
    #   3. Apply variation strategies (variation_engine.py)
    #   4. Assign transitions (transition_engine.py)
    #   5. Validate plan (validator.py)
    #   6. Pass plan to render_executor — renderer makes NO arrangement decisions.
    # Disable with ARRANGER_V2=false to revert to legacy planner.
    feature_arranger_v2: bool = Field(
        default=True,
        validation_alias="ARRANGER_V2",
    )

    # Timeline Engine Shadow Mode — runs TimelinePlanner + TimelineValidator as a
    # parallel planner during arrangement jobs for observability and plan comparison.
    # Does NOT replace the live render path.  Serialised plan is stored inside
    # render_plan_json under the ``_timeline_plan`` key.
    # Enabled by default so every job emits timeline observability data.
    # Disable with TIMELINE_ENGINE_SHADOW=false to suppress the extra planning pass.
    feature_timeline_engine_shadow: bool = Field(
        default=True,
        validation_alias="TIMELINE_ENGINE_SHADOW",
    )

    # Pattern Variation Engine Shadow Mode — runs PatternVariationEngine as a
    # parallel planner during arrangement jobs for observability.
    # Does NOT apply variations to audio.  Serialised plans are stored inside
    # render_plan_json under the ``_pattern_variation_plans`` key.
    # Enabled by default so every job emits pattern variation observability data.
    # Disable with PATTERN_VARIATION_SHADOW=false to suppress the extra planning pass.
    feature_pattern_variation_shadow: bool = Field(
        default=True,
        validation_alias="PATTERN_VARIATION_SHADOW",
    )

    # Groove Engine Shadow Mode — runs GrooveEngine as a parallel planner during
    # arrangement jobs for observability.  Builds a GroovePlan per section covering
    # microtiming, accent behaviour, swing, and bounce scoring.
    # Does NOT modify rendered audio.  Serialised plans are stored inside
    # render_plan_json under the ``_groove_plans`` key.
    # Enabled by default so every job emits groove observability data.
    # Disable with GROOVE_ENGINE_SHADOW=false to suppress the extra planning pass.
    feature_groove_engine_shadow: bool = Field(
        default=True,
        validation_alias="GROOVE_ENGINE_SHADOW",
    )

    # AI Producer System Shadow Mode — runs the multi-agent producer workflow
    # (PlannerAgent → CriticAgent → RepairAgent → Validator) as a shadow planner
    # during arrangement jobs for observability and plan quality inspection.
    # Does NOT drive live rendering.  Results are stored inside render_plan_json
    # under the ``_ai_producer_plan``, ``_ai_critic_scores``, ``_ai_repair_actions``,
    # ``_ai_rejected_reason``, and ``_ai_fallback_used`` keys.
    # Disabled by default.  Enable with AI_PRODUCER_SYSTEM_SHADOW=true.
    feature_ai_producer_system_shadow: bool = Field(
        default=False,
        validation_alias="AI_PRODUCER_SYSTEM_SHADOW",
    )

    # Drop Engine Shadow Mode — runs the Drop Engine as a shadow planner during
    # arrangement jobs for observability and drop design inspection.
    # Designs pre-hook tension, fakeouts, delayed drops, re-entry accents, and
    # hook payoff moments at every meaningful section boundary.
    # Does NOT drive live rendering.  Results are stored inside render_plan_json
    # under the ``_drop_plan``, ``_drop_scores``, ``_drop_warnings``, and
    # ``_drop_fallback_used`` keys.
    # Enabled by default so every job emits drop design observability data.
    # Disable with DROP_ENGINE_SHADOW=false to suppress the extra planning pass.
    feature_drop_engine_shadow: bool = Field(
        default=True,
        validation_alias="DROP_ENGINE_SHADOW",
    )

    # Track Quality Analysis — DSP-based technical quality report for uploaded audio.
    # Measures sample rate, bit depth, clipping, mono compatibility, integrated
    # loudness (simplified BS.1770-3 LUFS), true peak, phase issues, stereo field
    # width, 4-band tonal profile, and generates actionable mixing suggestions.
    # Enable with TRACK_QUALITY_ANALYSIS=true.
    feature_track_quality_analysis: bool = Field(
        default=False,
        validation_alias="TRACK_QUALITY_ANALYSIS",
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
        "feature_producer_engine_strict_rules",
        "feature_producer_section_identity_v2",
        "feature_section_choreography_v2",
        "feature_reference_guided_arrangement",
        "feature_reference_section_analysis",
        "feature_arrangement_quality_gates",
        "feature_source_quality_modes",
        "feature_arrangement_plan_v2",
        "feature_arrangement_memory_v2",
        "feature_arrangement_transitions_v2",
        "feature_arrangement_truth_observability_v2",
        "feature_track_quality_analysis",
        "feature_arranger_v2",
        "feature_timeline_engine_shadow",
        "feature_pattern_variation_shadow",
        "feature_drop_engine_shadow",
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
