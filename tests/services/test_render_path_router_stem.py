"""Tests for _arrange_via_stems and StemRenderOrchestrator in render_path_router.py."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from app.services.render_path_router import RenderPathRouter, StemRenderOrchestrator
from app.services.stem_arrangement_engine import StemRole


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_stem_loop(
    loop_id: int = 1,
    bpm: float = 120.0,
    musical_key: str = "C major",
    roles: dict | None = None,
) -> MagicMock:
    """Build a mock stem-pack Loop."""
    if roles is None:
        roles = {
            "drums": {"url": "s3://bucket/drums.wav"},
            "bass": {"url": "s3://bucket/bass.wav"},
            "melody": {"url": "s3://bucket/melody.wav"},
        }
    loop = MagicMock()
    loop.id = loop_id
    loop.bpm = bpm
    loop.musical_key = musical_key
    loop.key = None
    loop.is_stem_pack = "true"
    loop.stem_files_json = json.dumps(roles)
    loop.stem_validation_json = json.dumps({"is_valid": True})
    return loop


# ===========================================================================
# route_and_arrange — stem path
# ===========================================================================


class TestRouteAndArrangeStemPath:
    def test_routes_to_stem_path(self):
        loop = _make_stem_loop()

        mock_engine = MagicMock()
        mock_section = MagicMock()
        mock_section.to_dict.return_value = {
            "name": "Verse",
            "section_type": "verse",
            "bar_start": 0,
            "bars": 8,
        }
        mock_engine.generate_arrangement.return_value = [mock_section]

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            path, arrangement = RenderPathRouter.route_and_arrange(
                loop, target_seconds=30
            )

        assert path == "stem"

    def test_arrangement_data_contains_type_stem(self):
        loop = _make_stem_loop()

        mock_engine = MagicMock()
        mock_section = MagicMock()
        mock_section.to_dict.return_value = {"name": "Verse", "bar_start": 0, "bars": 8}
        mock_engine.generate_arrangement.return_value = [mock_section]

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            path, arrangement = RenderPathRouter.route_and_arrange(
                loop, target_seconds=30
            )

        assert arrangement.get("type") == "stem"

    def test_arrangement_data_contains_bpm(self):
        loop = _make_stem_loop(bpm=140.0)

        mock_engine = MagicMock()
        mock_section = MagicMock()
        mock_section.to_dict.return_value = {"name": "Verse", "bar_start": 0, "bars": 8}
        mock_engine.generate_arrangement.return_value = [mock_section]

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            _, arrangement = RenderPathRouter.route_and_arrange(loop, target_seconds=60)

        assert arrangement.get("bpm") == 140.0

    def test_genre_and_intensity_forwarded(self):
        loop = _make_stem_loop()

        mock_engine = MagicMock()
        mock_engine.generate_arrangement.return_value = []

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            _, arrangement = RenderPathRouter.route_and_arrange(
                loop, target_seconds=30, genre="hip-hop", intensity="high"
            )

        assert arrangement.get("genre") == "hip-hop"
        assert arrangement.get("intensity") == "high"

    def test_sections_serialized_in_arrangement(self):
        loop = _make_stem_loop()

        mock_engine = MagicMock()
        mock_section = MagicMock()
        mock_section.to_dict.return_value = {"name": "Hook", "bar_start": 0, "bars": 4}
        mock_engine.generate_arrangement.return_value = [mock_section, mock_section]

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            _, arrangement = RenderPathRouter.route_and_arrange(
                loop, target_seconds=30
            )

        assert len(arrangement.get("sections", [])) == 2

    def test_stem_roles_in_arrangement(self):
        loop = _make_stem_loop(
            roles={
                "drums": {"url": "s3://bucket/drums.wav"},
                "bass": {"url": "s3://bucket/bass.wav"},
            }
        )

        mock_engine = MagicMock()
        mock_engine.generate_arrangement.return_value = []

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            _, arrangement = RenderPathRouter.route_and_arrange(loop, target_seconds=30)

        stem_roles = arrangement.get("stem_roles", {})
        assert len(stem_roles) >= 1


# ===========================================================================
# _arrange_via_stems — edge cases
# ===========================================================================


class TestArrangeViaStemsEdgeCases:
    def test_raises_when_no_stems_found(self):
        loop = MagicMock()
        loop.id = 99
        loop.bpm = 120.0
        loop.musical_key = "C major"
        loop.key = None
        # stem_files_json has no valid stems
        loop.stem_files_json = json.dumps({"unknown_role_xyz": {"url": "s3://bucket/x.wav"}})
        loop.is_stem_pack = "true"
        loop.stem_validation_json = json.dumps({"is_valid": True})

        with pytest.raises(ValueError, match="no stems found"):
            RenderPathRouter._arrange_via_stems(loop, target_seconds=30)

    def test_target_bars_clamped_to_minimum_8(self):
        """Very short duration should produce at least 8 bars."""
        loop = _make_stem_loop(bpm=120.0)

        mock_engine = MagicMock()
        mock_engine.generate_arrangement.return_value = []

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            RenderPathRouter._arrange_via_stems(loop, target_seconds=1)

        # Verify that generate_arrangement was called with target_bars >= 8
        call_args = mock_engine.generate_arrangement.call_args
        target_bars = call_args[1].get("target_bars") or call_args[0][0]
        assert target_bars >= 8

    def test_target_bars_clamped_to_maximum_256(self):
        """Very long duration should be capped at 256 bars."""
        loop = _make_stem_loop(bpm=60.0)

        mock_engine = MagicMock()
        mock_engine.generate_arrangement.return_value = []

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ):
            RenderPathRouter._arrange_via_stems(loop, target_seconds=10000)

        call_args = mock_engine.generate_arrangement.call_args
        target_bars = call_args[1].get("target_bars") or call_args[0][0]
        assert target_bars <= 256

    def test_defaults_bpm_to_120_when_none(self):
        loop = _make_stem_loop()
        loop.bpm = None  # trigger default

        mock_engine = MagicMock()
        mock_engine.generate_arrangement.return_value = []

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ) as mock_cls:
            RenderPathRouter._arrange_via_stems(loop, target_seconds=30)

        # tempo kwarg passed to constructor should be 120
        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("tempo") == 120

    def test_uses_musical_key_when_available(self):
        loop = _make_stem_loop(musical_key="D minor")

        mock_engine = MagicMock()
        mock_engine.generate_arrangement.return_value = []

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ) as mock_cls:
            RenderPathRouter._arrange_via_stems(loop, target_seconds=30)

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("key") == "D minor"

    def test_falls_back_to_key_when_musical_key_none(self):
        loop = _make_stem_loop()
        loop.musical_key = None
        loop.key = "A minor"

        mock_engine = MagicMock()
        mock_engine.generate_arrangement.return_value = []

        with patch(
            "app.services.render_path_router.StemArrangementEngine",
            return_value=mock_engine,
        ) as mock_cls:
            RenderPathRouter._arrange_via_stems(loop, target_seconds=30)

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("key") == "A minor"


# ===========================================================================
# StemRenderOrchestrator.render_arrangement_async
# ===========================================================================


class TestStemRenderOrchestratorAsync:
    def test_raises_when_no_stem_arrangement_json(self):
        import asyncio

        arrangement = MagicMock()
        arrangement.id = 1
        arrangement.stem_arrangement_json = None

        async def _run():
            await StemRenderOrchestrator.render_arrangement_async(
                arrangement, "output/test.wav", MagicMock()
            )

        with pytest.raises(ValueError, match="no stem arrangement data"):
            asyncio.run(_run())

    def test_raises_on_invalid_json(self):
        import asyncio

        arrangement = MagicMock()
        arrangement.id = 1
        arrangement.stem_arrangement_json = "{ invalid json !!!"

        async def _run():
            await StemRenderOrchestrator.render_arrangement_async(
                arrangement, "output/test.wav", MagicMock()
            )

        with pytest.raises(ValueError, match="Invalid stem arrangement JSON"):
            asyncio.run(_run())

    def test_raises_when_sections_missing(self):
        import asyncio

        arrangement = MagicMock()
        arrangement.id = 1
        arrangement.stem_arrangement_json = json.dumps({
            "sections": [],
            "stem_roles": {"drums": "drums.wav"},
        })

        async def _run():
            await StemRenderOrchestrator.render_arrangement_async(
                arrangement, "output/test.wav", MagicMock()
            )

        with pytest.raises(ValueError, match="missing sections"):
            asyncio.run(_run())

    def test_raises_when_stem_roles_missing(self):
        import asyncio

        arrangement = MagicMock()
        arrangement.id = 1
        arrangement.stem_arrangement_json = json.dumps({
            "sections": [{"name": "Verse", "bars": 4, "bar_start": 0, "section_type": "verse"}],
            "stem_roles": {},
        })

        async def _run():
            await StemRenderOrchestrator.render_arrangement_async(
                arrangement, "output/test.wav", MagicMock()
            )

        with pytest.raises(ValueError, match="missing sections"):
            asyncio.run(_run())
