"""Unit tests for RenderPathRouter."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.render_path_router import RenderPathRouter
from app.services.stem_arrangement_engine import StemRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(
    is_stem_pack: str = "false",
    stem_files_json: str | None = None,
    stem_validation_json: str | None = None,
    bpm: int = 120,
    musical_key: str = "C major",
    key: str | None = None,
) -> MagicMock:
    """Create a mock Loop object with the given attributes."""
    loop = MagicMock()
    loop.id = 1
    loop.is_stem_pack = is_stem_pack
    loop.stem_files_json = stem_files_json
    loop.stem_validation_json = stem_validation_json
    loop.bpm = bpm
    loop.musical_key = musical_key
    loop.key = key
    return loop


def _valid_stem_files_json() -> str:
    return json.dumps({
        "drums": {"url": "s3://bucket/loop1/drums.wav", "duration": 4.0},
        "bass": {"url": "s3://bucket/loop1/bass.wav", "duration": 4.0},
        "melody": {"url": "s3://bucket/loop1/melody.wav", "duration": 4.0},
    })


def _valid_validation_json() -> str:
    return json.dumps({"is_valid": True, "errors": []})


# ---------------------------------------------------------------------------
# should_use_stem_path()
# ---------------------------------------------------------------------------


class TestShouldUseStemPath:
    def test_non_stem_loop_returns_false(self):
        loop = _make_loop(is_stem_pack="false")
        assert RenderPathRouter.should_use_stem_path(loop) is False

    def test_stem_pack_with_files_and_valid_validation_returns_true(self):
        loop = _make_loop(
            is_stem_pack="true",
            stem_files_json=_valid_stem_files_json(),
            stem_validation_json=_valid_validation_json(),
        )
        assert RenderPathRouter.should_use_stem_path(loop) is True

    def test_stem_pack_without_files_returns_false(self):
        loop = _make_loop(is_stem_pack="true", stem_files_json=None)
        assert RenderPathRouter.should_use_stem_path(loop) is False

    def test_stem_pack_empty_files_json_returns_false(self):
        loop = _make_loop(is_stem_pack="true", stem_files_json="")
        assert RenderPathRouter.should_use_stem_path(loop) is False

    def test_stem_pack_failed_validation_returns_false(self):
        loop = _make_loop(
            is_stem_pack="true",
            stem_files_json=_valid_stem_files_json(),
            stem_validation_json=json.dumps({"is_valid": False, "errors": ["bad stems"]}),
        )
        assert RenderPathRouter.should_use_stem_path(loop) is False

    def test_stem_pack_no_validation_json_returns_true(self):
        """No validation JSON present — should still pass (trusts stem_files_json)."""
        loop = _make_loop(
            is_stem_pack="true",
            stem_files_json=_valid_stem_files_json(),
            stem_validation_json=None,
        )
        assert RenderPathRouter.should_use_stem_path(loop) is True

    def test_stem_pack_invalid_validation_json_returns_false(self):
        loop = _make_loop(
            is_stem_pack="true",
            stem_files_json=_valid_stem_files_json(),
            stem_validation_json="not valid json",
        )
        assert RenderPathRouter.should_use_stem_path(loop) is False

    def test_loop_without_is_stem_pack_attr_returns_false(self):
        loop = MagicMock(spec=[])  # no attributes
        assert RenderPathRouter.should_use_stem_path(loop) is False

    def test_is_stem_pack_true_uppercase_recognized(self):
        """Implementation strips and lowercases is_stem_pack, so 'TRUE' → 'true'."""
        loop = _make_loop(
            is_stem_pack="TRUE",
            stem_files_json=_valid_stem_files_json(),
            stem_validation_json=_valid_validation_json(),
        )
        assert RenderPathRouter.should_use_stem_path(loop) is True

    def test_is_stem_pack_none_returns_false(self):
        loop = _make_loop(is_stem_pack=None, stem_files_json=_valid_stem_files_json())
        assert RenderPathRouter.should_use_stem_path(loop) is False


# ---------------------------------------------------------------------------
# get_available_stem_roles()
# ---------------------------------------------------------------------------


class TestGetAvailableStemRoles:
    def test_returns_dict(self):
        loop = _make_loop(stem_files_json=_valid_stem_files_json())
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert isinstance(result, dict)

    def test_known_roles_extracted(self):
        loop = _make_loop(stem_files_json=_valid_stem_files_json())
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert StemRole.DRUMS in result
        assert StemRole.BASS in result
        assert StemRole.MELODY in result

    def test_urls_extracted(self):
        loop = _make_loop(stem_files_json=_valid_stem_files_json())
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert "s3://bucket/loop1/drums.wav" in result.values()

    def test_empty_stem_files_json_returns_empty(self):
        loop = _make_loop(stem_files_json=None)
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert result == {}

    def test_loop_without_stem_files_json_attr_returns_empty(self):
        loop = MagicMock(spec=["id"])
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert result == {}

    def test_unknown_role_is_skipped(self):
        stem_files = json.dumps({
            "totally_unknown_role_xyz": {"url": "s3://bucket/unknown.wav"},
            "drums": {"url": "s3://bucket/drums.wav"},
        })
        loop = _make_loop(stem_files_json=stem_files)
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert StemRole.DRUMS in result
        # Unknown roles should not appear
        roles_as_strs = {r.value for r in result.keys()}
        assert "totally_unknown_role_xyz" not in roles_as_strs

    def test_s3_key_fallback_when_no_url(self):
        stem_files = json.dumps({
            "drums": {"s3_key": "uploads/loop1/drums.wav"},
        })
        loop = _make_loop(stem_files_json=stem_files)
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert StemRole.DRUMS in result
        assert result[StemRole.DRUMS] == "uploads/loop1/drums.wav"

    def test_file_key_fallback_when_no_url_or_s3_key(self):
        stem_files = json.dumps({
            "bass": {"file_key": "uploads/loop1/bass.wav"},
        })
        loop = _make_loop(stem_files_json=stem_files)
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert StemRole.BASS in result
        assert result[StemRole.BASS] == "uploads/loop1/bass.wav"

    def test_invalid_json_returns_empty(self):
        loop = _make_loop(stem_files_json="this is not json at all {")
        result = RenderPathRouter.get_available_stem_roles(loop)
        assert result == {}


# ---------------------------------------------------------------------------
# route_and_arrange() – loop path (no stem pack)
# ---------------------------------------------------------------------------


class TestRouteAndArrangeLoopPath:
    def test_non_stem_loop_routes_to_loop_path(self):
        loop = _make_loop(is_stem_pack="false")
        path, arrangement = RenderPathRouter.route_and_arrange(loop, target_seconds=60)
        assert path == "loop"

    def test_loop_path_returns_empty_dict(self):
        loop = _make_loop(is_stem_pack="false")
        path, arrangement = RenderPathRouter.route_and_arrange(loop, target_seconds=60)
        assert arrangement == {}


# ---------------------------------------------------------------------------
# save_arrangement_metadata()
# ---------------------------------------------------------------------------


class TestSaveArrangementMetadata:
    def test_stem_path_sets_rendered_from_stems(self):
        arrangement = MagicMock()
        RenderPathRouter.save_arrangement_metadata(arrangement, "stem", {"type": "stem"})
        assert arrangement.rendered_from_stems is True

    def test_stem_path_sets_stem_render_path(self):
        arrangement = MagicMock()
        RenderPathRouter.save_arrangement_metadata(arrangement, "stem", {"type": "stem"})
        assert arrangement.stem_render_path == "stem"

    def test_stem_path_serializes_data_to_json(self):
        arrangement = MagicMock()
        data = {"type": "stem", "bpm": 120}
        RenderPathRouter.save_arrangement_metadata(arrangement, "stem", data)
        assert arrangement.stem_arrangement_json == json.dumps(data)

    def test_loop_path_sets_rendered_from_stems_false(self):
        arrangement = MagicMock()
        RenderPathRouter.save_arrangement_metadata(arrangement, "loop", {})
        assert arrangement.rendered_from_stems is False

    def test_loop_path_sets_stem_render_path_loop(self):
        arrangement = MagicMock()
        RenderPathRouter.save_arrangement_metadata(arrangement, "loop", {})
        assert arrangement.stem_render_path == "loop"
