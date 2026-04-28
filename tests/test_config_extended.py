"""Extended tests for app/config.py to improve coverage.

Covers:
- convert_embedded_worker_bool with non-str values (line 694)
- convert_worker_count with invalid/None values (lines 701-702)
- convert_bool with non-bool, non-str values (line 764)
- allowed_origins with configured CORS origins (lines 792-795)
- allowed_origins in production mode without configured origins (lines 796-798)
- get_storage_backend with invalid backend string (lines 829-830)
- get_storage_backend in production with full S3 config (line 834)
- should_enforce_audio_binaries returning False (line 851)
- _redis_url_is_local — all branches (lines 857-863)
- validate_startup — production mode, S3 mode, LLM/AI warnings
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock


# ---------------------------------------------------------------------------
# Helpers: build a fresh Settings-like object without environment pollution
# ---------------------------------------------------------------------------


def _make_settings(**overrides):
    """Return a fresh Settings instance with controlled defaults.

    Overrides are applied as environment-variable patches via the
    ``validation_alias`` names so that pydantic_settings reads them
    from os.environ.
    """
    from app.config import Settings

    env_overrides = {
        "DATABASE_URL": "sqlite:///./test.db",
        "REDIS_URL": "",
        "ENVIRONMENT": "development",
        "STORAGE_BACKEND": "",
        "AWS_ACCESS_KEY_ID": "",
        "AWS_SECRET_ACCESS_KEY": "",
        "AWS_REGION": "",
        "AWS_S3_BUCKET": "",
        "S3_BUCKET_NAME": "",
        "CORS_ALLOWED_ORIGINS": "",
        "FRONTEND_ORIGIN": "",
        "ENFORCE_AUDIO_BINARIES": "auto",
        "ENABLE_EMBEDDED_RQ_WORKER": "false",
        "EMBEDDED_RQ_WORKER_COUNT": "2",
        "FEATURE_LLM_STYLE_PARSING": "false",
        "AI_PRODUCER_ASSIST": "false",
        "OPENAI_API_KEY": "",
    }
    env_overrides.update(overrides)

    with patch.dict("os.environ", env_overrides, clear=False):
        return Settings()


# ---------------------------------------------------------------------------
# convert_embedded_worker_bool — non-str branch (line 694)
# ---------------------------------------------------------------------------


class TestConvertEmbeddedWorkerBool:
    def test_integer_1_returns_true(self):
        """Passing an integer 1 (already-parsed bool-like) returns True."""
        from app.config import Settings

        result = Settings.convert_embedded_worker_bool(1)
        assert result is True

    def test_integer_0_returns_false(self):
        from app.config import Settings

        result = Settings.convert_embedded_worker_bool(0)
        assert result is False

    def test_true_bool_returns_true(self):
        from app.config import Settings

        result = Settings.convert_embedded_worker_bool(True)
        assert result is True

    def test_false_bool_returns_false(self):
        from app.config import Settings

        result = Settings.convert_embedded_worker_bool(False)
        assert result is False

    def test_string_true_returns_true(self):
        from app.config import Settings

        assert Settings.convert_embedded_worker_bool("true") is True

    def test_string_false_returns_false(self):
        from app.config import Settings

        assert Settings.convert_embedded_worker_bool("false") is False


# ---------------------------------------------------------------------------
# convert_worker_count — exception branch (lines 701-702)
# ---------------------------------------------------------------------------


class TestConvertWorkerCount:
    def test_valid_integer_string_returns_int(self):
        from app.config import Settings

        result = Settings.convert_worker_count("3")
        assert result == 3

    def test_invalid_string_returns_default_2(self):
        """Non-numeric string triggers the except branch and returns 2."""
        from app.config import Settings

        result = Settings.convert_worker_count("not-a-number")
        assert result == 2

    def test_none_returns_default_2(self):
        """None triggers the except branch and returns 2."""
        from app.config import Settings

        result = Settings.convert_worker_count(None)
        assert result == 2

    def test_value_below_1_is_clamped_to_1(self):
        from app.config import Settings

        result = Settings.convert_worker_count("0")
        assert result == 1


# ---------------------------------------------------------------------------
# convert_bool — non-bool, non-str branch (line 764)
# ---------------------------------------------------------------------------


class TestConvertBool:
    def test_string_true_converts_to_true(self):
        from app.config import Settings

        assert Settings.convert_bool("true") is True

    def test_string_false_converts_to_false(self):
        from app.config import Settings

        assert Settings.convert_bool("false") is False

    def test_bool_true_passthrough(self):
        from app.config import Settings

        assert Settings.convert_bool(True) is True

    def test_bool_false_passthrough(self):
        from app.config import Settings

        assert Settings.convert_bool(False) is False

    def test_integer_1_converted_via_bool(self):
        """Integer 1 hits the return bool(v) branch (line 764)."""
        from app.config import Settings

        assert Settings.convert_bool(1) is True

    def test_integer_0_converted_via_bool(self):
        from app.config import Settings

        assert Settings.convert_bool(0) is False


# ---------------------------------------------------------------------------
# allowed_origins — configured_origins branches
# ---------------------------------------------------------------------------


class TestAllowedOrigins:
    def test_extra_cors_origin_is_included(self):
        """CORS_ALLOWED_ORIGINS is appended to the default list."""
        settings = _make_settings(CORS_ALLOWED_ORIGINS="https://my-app.example.com")
        origins = settings.allowed_origins
        assert "https://my-app.example.com" in origins

    def test_multiple_cors_origins_all_included(self):
        """Comma-separated CORS_ALLOWED_ORIGINS are all appended."""
        settings = _make_settings(
            CORS_ALLOWED_ORIGINS="https://a.example.com,https://b.example.com"
        )
        origins = settings.allowed_origins
        assert "https://a.example.com" in origins
        assert "https://b.example.com" in origins

    def test_trailing_slash_stripped_in_cors_origin(self):
        settings = _make_settings(CORS_ALLOWED_ORIGINS="https://my-app.example.com/")
        origins = settings.allowed_origins
        assert "https://my-app.example.com" in origins
        assert "https://my-app.example.com/" not in origins

    def test_duplicate_origins_not_added_twice(self):
        """Origins already in the default list are not duplicated."""
        settings = _make_settings(CORS_ALLOWED_ORIGINS="http://localhost:3000")
        count = settings.allowed_origins.count("http://localhost:3000")
        assert count == 1

    def test_production_without_origins_logs_warning(self):
        """In production with no CORS config a warning is logged."""
        settings = _make_settings(ENVIRONMENT="production")
        import logging
        with patch.object(
            logging.getLogger("app.config"), "warning"
        ) as mock_warn:
            _ = settings.allowed_origins
        mock_warn.assert_called_once()

    def test_localhost_always_in_default_origins(self):
        settings = _make_settings()
        assert "http://localhost:3000" in settings.allowed_origins


# ---------------------------------------------------------------------------
# get_storage_backend
# ---------------------------------------------------------------------------


class TestGetStorageBackend:
    def test_explicit_local_returns_local(self):
        settings = _make_settings(STORAGE_BACKEND="local")
        assert settings.get_storage_backend() == "local"

    def test_explicit_s3_returns_s3(self):
        settings = _make_settings(STORAGE_BACKEND="s3")
        assert settings.get_storage_backend() == "s3"

    def test_invalid_backend_raises_runtime_error(self):
        """An unrecognised STORAGE_BACKEND raises RuntimeError."""
        settings = _make_settings(STORAGE_BACKEND="gcs")
        with pytest.raises(RuntimeError, match="Invalid STORAGE_BACKEND"):
            settings.get_storage_backend()

    def test_production_with_s3_config_returns_s3(self):
        """No STORAGE_BACKEND set, but production + full S3 config → 's3'."""
        settings = _make_settings(
            ENVIRONMENT="production",
            STORAGE_BACKEND="",
            AWS_ACCESS_KEY_ID="key",
            AWS_SECRET_ACCESS_KEY="secret",
            AWS_REGION="us-east-1",
            AWS_S3_BUCKET="my-bucket",
        )
        assert settings.get_storage_backend() == "s3"

    def test_development_without_s3_config_returns_local(self):
        settings = _make_settings(ENVIRONMENT="development", STORAGE_BACKEND="")
        assert settings.get_storage_backend() == "local"

    def test_production_without_s3_config_returns_local(self):
        """Production without S3 config falls back to local."""
        settings = _make_settings(
            ENVIRONMENT="production",
            STORAGE_BACKEND="",
            AWS_ACCESS_KEY_ID="",
        )
        assert settings.get_storage_backend() == "local"


# ---------------------------------------------------------------------------
# should_enforce_audio_binaries
# ---------------------------------------------------------------------------


class TestShouldEnforceAudioBinaries:
    def test_true_string_returns_true(self):
        settings = _make_settings(ENFORCE_AUDIO_BINARIES="true")
        assert settings.should_enforce_audio_binaries is True

    def test_false_string_returns_false(self):
        settings = _make_settings(ENFORCE_AUDIO_BINARIES="false")
        assert settings.should_enforce_audio_binaries is False

    def test_off_string_returns_false(self):
        settings = _make_settings(ENFORCE_AUDIO_BINARIES="off")
        assert settings.should_enforce_audio_binaries is False

    def test_auto_in_production_returns_true(self):
        settings = _make_settings(ENFORCE_AUDIO_BINARIES="auto", ENVIRONMENT="production")
        assert settings.should_enforce_audio_binaries is True

    def test_auto_in_development_returns_false(self):
        settings = _make_settings(ENFORCE_AUDIO_BINARIES="auto", ENVIRONMENT="development")
        assert settings.should_enforce_audio_binaries is False


# ---------------------------------------------------------------------------
# _redis_url_is_local
# ---------------------------------------------------------------------------


class TestRedisUrlIsLocal:
    def test_localhost_is_local(self):
        from app.config import Settings

        assert Settings._redis_url_is_local("redis://localhost:6379") is True

    def test_127_0_0_1_is_local(self):
        from app.config import Settings

        assert Settings._redis_url_is_local("redis://127.0.0.1:6379") is True

    def test_ipv6_loopback_is_local(self):
        from app.config import Settings

        assert Settings._redis_url_is_local("redis://[::1]:6379") is True

    def test_remote_host_is_not_local(self):
        from app.config import Settings

        assert Settings._redis_url_is_local("redis://redis.example.com:6379") is False

    def test_invalid_url_returns_false(self):
        from app.config import Settings

        assert Settings._redis_url_is_local("not-a-url-at-all!!!") is False

    def test_empty_string_returns_false(self):
        from app.config import Settings

        assert Settings._redis_url_is_local("") is False


# ---------------------------------------------------------------------------
# validate_startup
# ---------------------------------------------------------------------------


class TestValidateStartup:
    def test_development_mode_passes_without_redis_or_db(self):
        """Development mode does not require REDIS_URL or a production DB."""
        settings = _make_settings(ENVIRONMENT="development")
        # Should not raise
        settings.validate_startup()

    def test_production_missing_database_url_raises(self):
        """Production with default SQLite DB raises RuntimeError."""
        settings = _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL="sqlite:///./test.db",
            REDIS_URL="redis://redis.example.com:6379",
        )
        with pytest.raises(RuntimeError, match="DATABASE_URL"):
            settings.validate_startup()

    def test_production_missing_redis_url_raises(self):
        """Production with no REDIS_URL raises RuntimeError."""
        settings = _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:pass@host/db",
            REDIS_URL="",
        )
        with pytest.raises(RuntimeError, match="REDIS_URL"):
            settings.validate_startup()

    def test_production_local_redis_raises(self):
        """Production with localhost Redis raises RuntimeError."""
        settings = _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:pass@host/db",
            REDIS_URL="redis://localhost:6379",
        )
        with pytest.raises(RuntimeError, match="localhost"):
            settings.validate_startup()

    def test_s3_backend_missing_credentials_raises(self):
        """STORAGE_BACKEND=s3 without credentials raises RuntimeError."""
        settings = _make_settings(
            STORAGE_BACKEND="s3",
            AWS_ACCESS_KEY_ID="",
            AWS_SECRET_ACCESS_KEY="",
            AWS_REGION="",
            AWS_S3_BUCKET="",
        )
        with pytest.raises(RuntimeError, match="AWS"):
            settings.validate_startup()

    def test_s3_backend_placeholder_bucket_raises(self):
        """Placeholder bucket name is rejected."""
        settings = _make_settings(
            STORAGE_BACKEND="s3",
            AWS_ACCESS_KEY_ID="key",
            AWS_SECRET_ACCESS_KEY="secret",
            AWS_REGION="us-east-1",
            AWS_S3_BUCKET="your-bucket-name",
        )
        with pytest.raises(RuntimeError, match="placeholder"):
            settings.validate_startup()

    def test_llm_enabled_without_openai_key_logs_warning(self):
        """When LLM parsing is on but no API key, a warning is logged."""
        settings = _make_settings(FEATURE_LLM_STYLE_PARSING="true", OPENAI_API_KEY="")
        import logging
        with patch.object(
            logging.getLogger("app.config"), "warning"
        ) as mock_warn:
            settings.validate_startup()
        assert mock_warn.called

    def test_ai_producer_assist_without_openai_key_logs_warning(self):
        """When AI producer assist is on but no API key, a warning is logged."""
        settings = _make_settings(AI_PRODUCER_ASSIST="true", OPENAI_API_KEY="")
        import logging
        with patch.object(
            logging.getLogger("app.config"), "warning"
        ) as mock_warn:
            settings.validate_startup()
        assert mock_warn.called

    def test_production_with_all_required_vars_passes(self):
        """Full production config with all required vars should not raise."""
        settings = _make_settings(
            ENVIRONMENT="production",
            DATABASE_URL="postgresql://user:pass@host/db",
            REDIS_URL="redis://redis.example.com:6379",
            STORAGE_BACKEND="local",
        )
        # Should not raise
        settings.validate_startup()
