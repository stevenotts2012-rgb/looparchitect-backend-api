"""Tests for helper functions in app/routes/render.py."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_lowercases_text(self):
        from app.routes.render import _slugify

        assert _slugify("TRAP") == "trap"

    def test_strips_leading_and_trailing_whitespace(self):
        from app.routes.render import _slugify

        assert _slugify("  hi  ") == "hi"

    def test_replaces_spaces_with_underscore(self):
        from app.routes.render import _slugify

        assert _slugify("dark trap") == "dark_trap"

    def test_removes_special_characters(self):
        from app.routes.render import _slugify

        assert _slugify("lo-fi!@#") == "lo_fi"

    def test_handles_multiple_separators(self):
        from app.routes.render import _slugify

        # Multiple spaces/dashes collapse to single underscore
        result = _slugify("dark  --  trap")
        assert result == "dark_trap"

    def test_empty_string(self):
        from app.routes.render import _slugify

        assert _slugify("") == ""

    def test_already_clean_slug_unchanged(self):
        from app.routes.render import _slugify

        assert _slugify("atl_type") == "atl_type"


# ---------------------------------------------------------------------------
# _generate_sections
# ---------------------------------------------------------------------------


class TestGenerateSections:
    def test_default_structure_returns_four_sections(self):
        from app.routes.render import _generate_sections

        sections = _generate_sections("default", 180)
        assert len(sections) == 4
        names = {s.name for s in sections}
        assert names == {"intro", "verse", "chorus", "outro"}

    def test_non_default_structure_returns_single_main_section(self):
        from app.routes.render import _generate_sections

        sections = _generate_sections("custom", 180)
        assert len(sections) == 1
        assert sections[0].name == "main"

    def test_section_start_bar_of_intro_is_zero(self):
        from app.routes.render import _generate_sections

        sections = _generate_sections("default", 180)
        intro = next(s for s in sections if s.name == "intro")
        assert intro.start_bar == 0

    def test_last_section_ends_at_bars_value(self):
        from app.routes.render import _generate_sections

        sections = _generate_sections("default", 180)
        bars = max(1, 180 // 2)
        outro = next(s for s in sections if s.name == "outro")
        assert outro.end_bar == bars

    def test_minimum_one_bar_for_very_short_audio(self):
        from app.routes.render import _generate_sections

        sections = _generate_sections("default", 1)
        assert all(s.end_bar >= 0 for s in sections)

    def test_main_section_end_bar(self):
        from app.routes.render import _generate_sections

        sections = _generate_sections("other", 60)
        bars = max(1, 60 // 2)
        assert sections[0].end_bar == bars


# ---------------------------------------------------------------------------
# _get_transformations_for_style
# ---------------------------------------------------------------------------


class TestGetTransformationsForStyle:
    def test_atl_returns_low_pass(self):
        from app.routes.render import _get_transformations_for_style

        result = _get_transformations_for_style("ATL Trap")
        assert "low_pass_filter" in result
        assert "normalize" in result

    def test_trap_keyword(self):
        from app.routes.render import _get_transformations_for_style

        result = _get_transformations_for_style("Trap Banger")
        assert "low_pass_filter" in result

    def test_detroit_returns_high_pass(self):
        from app.routes.render import _get_transformations_for_style

        result = _get_transformations_for_style("Detroit Style")
        assert "high_pass" in result

    def test_lofi_returns_low_pass(self):
        from app.routes.render import _get_transformations_for_style

        result = _get_transformations_for_style("lofi vibes")
        assert "low_pass_filter" in result

    def test_lo_fi_with_hyphen_returns_low_pass(self):
        from app.routes.render import _get_transformations_for_style

        result = _get_transformations_for_style("lo-fi beats")
        assert "low_pass_filter" in result

    def test_unknown_style_returns_generic(self):
        from app.routes.render import _get_transformations_for_style

        result = _get_transformations_for_style("unknown genre")
        assert "normalize" in result
        assert "fade_in" in result
        assert "fade_out" in result
        assert "low_pass_filter" not in result
        assert "high_pass" not in result

    def test_all_results_include_fade_in_and_fade_out(self):
        from app.routes.render import _get_transformations_for_style

        for style in ["ATL", "Detroit", "lofi", "other"]:
            result = _get_transformations_for_style(style)
            assert "fade_in" in result
            assert "fade_out" in result


# ---------------------------------------------------------------------------
# _get_default_transformations
# ---------------------------------------------------------------------------


class TestGetDefaultTransformations:
    def test_commercial_returns_basic(self):
        from app.routes.render import _get_default_transformations

        result = _get_default_transformations("commercial")
        assert result == ["normalize", "fade_in", "fade_out"]

    def test_creative_includes_high_pass(self):
        from app.routes.render import _get_default_transformations

        result = _get_default_transformations("creative")
        assert "high_pass" in result

    def test_experimental_includes_low_pass(self):
        from app.routes.render import _get_default_transformations

        result = _get_default_transformations("experimental")
        assert "low_pass_filter" in result

    def test_unknown_name_returns_generic(self):
        from app.routes.render import _get_default_transformations

        result = _get_default_transformations("unknown")
        assert result == ["normalize", "fade_in", "fade_out"]


# ---------------------------------------------------------------------------
# _compute_variation_profiles
# ---------------------------------------------------------------------------


class TestComputeVariationProfiles:
    def test_uses_variation_styles_when_provided(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=2, variation_styles=["ATL", "Detroit"])
        profiles = _compute_variation_profiles(config)
        assert len(profiles) == 2
        assert profiles[0]["name"] == "ATL"
        assert profiles[1]["name"] == "Detroit"

    def test_honors_custom_style_as_source_of_truth(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=3, custom_style="Future Gritwave")
        profiles = _compute_variation_profiles(config)
        assert len(profiles) == 3
        assert all(p["name"].startswith("Future Gritwave —") for p in profiles)

    def test_unknown_genre_still_returns_three_style_variations(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=3, genre="Glassstep Noir")
        profiles = _compute_variation_profiles(config)
        assert len(profiles) == 3
        assert all(p["name"].startswith("Glassstep Noir —") for p in profiles)

    def test_profiles_have_required_keys(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=1)
        profiles = _compute_variation_profiles(config)
        for p in profiles:
            assert "name" in p
            assert "style_hint" in p
            assert "transformations" in p

    def test_does_not_exceed_variations_count(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=2, variation_styles=["A", "B", "C"])
        profiles = _compute_variation_profiles(config)
        assert len(profiles) == 2

    def test_slow_rnb_uses_smooth_moody_spacious(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=3, genre="R&B", mood="emotional", bpm=80)
        profiles = _compute_variation_profiles(config)
        names = [p["name"] for p in profiles]
        assert names == [
            "R&B — clean/smooth",
            "R&B — moody/intimate",
            "R&B — melodic/spacious",
        ]

    def test_gospel_worship_is_not_trap_labeled(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=3, genre="gospel worship", mood="worship")
        profiles = _compute_variation_profiles(config)
        text_blob = " ".join(p["name"].lower() for p in profiles)
        assert "trap" not in text_blob
        assert "bounce" not in text_blob

    def test_trap_uses_clean_dark_melodic_bounce(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=3, genre="trap", bpm=145)
        profiles = _compute_variation_profiles(config)
        names = [p["name"] for p in profiles]
        assert names == [
            "trap — clean/main",
            "trap — darker/heavier",
            "trap — melodic/bounce",
        ]

    def test_cinematic_not_default_when_not_requested(self):
        from app.routes.render import _compute_variation_profiles, RenderConfig

        config = RenderConfig(variations=3, genre="afrobeat")
        profiles = _compute_variation_profiles(config)
        assert all("cinematic" not in p["name"].lower() for p in profiles)


# ---------------------------------------------------------------------------
# _resolve_audio_file_path
# ---------------------------------------------------------------------------


class TestResolveAudioFilePath:
    def test_returns_none_for_http_url(self):
        from app.routes.render import _resolve_audio_file_path

        result = _resolve_audio_file_path("https://example.com/audio.wav")
        assert result is None

    def test_returns_none_for_http_plain_url(self):
        from app.routes.render import _resolve_audio_file_path

        result = _resolve_audio_file_path("http://example.com/audio.wav")
        assert result is None

    def test_raises_400_when_local_file_missing(self):
        from fastapi import HTTPException
        from app.routes.render import _resolve_audio_file_path

        with pytest.raises(HTTPException) as exc_info:
            _resolve_audio_file_path("missing_file.wav")
        assert exc_info.value.status_code == 400

    def test_strips_slash_uploads_prefix(self, tmp_path, monkeypatch):
        from app.routes.render import _resolve_audio_file_path
        import app.routes.render as render_mod

        # Create a fake uploads directory with a file
        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        audio_file = uploads_dir / "myloop.wav"
        audio_file.write_bytes(b"fake")

        original_uploads_dir = render_mod.UPLOADS_DIR
        monkeypatch.setattr(render_mod, "UPLOADS_DIR", str(uploads_dir))
        try:
            result = _resolve_audio_file_path("/uploads/myloop.wav")
        finally:
            render_mod.UPLOADS_DIR = original_uploads_dir

        assert result is not None
        assert result.name == "myloop.wav"

    def test_strips_uploads_prefix_without_slash(self, tmp_path, monkeypatch):
        from app.routes.render import _resolve_audio_file_path
        import app.routes.render as render_mod

        uploads_dir = tmp_path / "uploads"
        uploads_dir.mkdir()
        audio_file = uploads_dir / "myloop2.wav"
        audio_file.write_bytes(b"data")

        original_uploads_dir = render_mod.UPLOADS_DIR
        monkeypatch.setattr(render_mod, "UPLOADS_DIR", str(uploads_dir))
        try:
            result = _resolve_audio_file_path("uploads/myloop2.wav")
        finally:
            render_mod.UPLOADS_DIR = original_uploads_dir

        assert result is not None


# ---------------------------------------------------------------------------
# _get_loop_audio_source
# ---------------------------------------------------------------------------


class TestGetLoopAudioSource:
    def test_returns_presigned_url_when_file_key_present(self):
        from app.routes.render import _get_loop_audio_source

        loop = MagicMock()
        loop.file_key = "uploads/test.wav"
        loop.file_url = None

        with patch("app.routes.render.storage.create_presigned_get_url", return_value="https://s3/url"):
            result = _get_loop_audio_source(loop)

        assert result == "https://s3/url"

    def test_falls_back_to_file_url_when_presign_fails(self):
        from app.routes.render import _get_loop_audio_source

        loop = MagicMock()
        loop.file_key = "uploads/test.wav"
        loop.id = 1
        loop.file_url = "http://cdn.example.com/audio.wav"

        with patch(
            "app.routes.render.storage.create_presigned_get_url",
            side_effect=Exception("S3 error"),
        ):
            result = _get_loop_audio_source(loop)

        assert result == "http://cdn.example.com/audio.wav"

    def test_returns_file_url_when_no_file_key(self):
        from app.routes.render import _get_loop_audio_source

        loop = MagicMock()
        loop.file_key = None
        loop.file_url = "http://example.com/audio.wav"

        result = _get_loop_audio_source(loop)
        assert result == "http://example.com/audio.wav"

    def test_raises_400_when_neither_file_key_nor_file_url(self):
        from fastapi import HTTPException
        from app.routes.render import _get_loop_audio_source

        loop = MagicMock()
        loop.file_key = None
        loop.file_url = None

        with pytest.raises(HTTPException) as exc_info:
            _get_loop_audio_source(loop)

        assert exc_info.value.status_code == 400
        assert "no associated audio file" in exc_info.value.detail.lower()
