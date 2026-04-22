"""Tests for app/services/render_service.py — RenderPipeline and helpers."""

import asyncio
import os
import pytest

from app.services.render_service import RenderPipeline, render_loop, render_loop_sync


# ===========================================================================
# RenderPipeline initialisation
# ===========================================================================


class TestRenderPipelineInit:
    def test_stores_render_id(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pipeline = RenderPipeline("abc123")
        assert pipeline.render_id == "abc123"

    def test_outputs_starts_empty(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        pipeline = RenderPipeline("test-init")
        assert pipeline.outputs == {}

    def test_creates_renders_dir(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        RenderPipeline("dir-test")
        assert (tmp_path / "renders").is_dir()


# ===========================================================================
# analyze_loop — remote URL path (no file needed)
# ===========================================================================


class TestAnalyzeLoopRemote:
    @pytest.fixture
    def pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return RenderPipeline("remote-test")

    def test_remote_url_returns_defaults(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.analyze_loop("https://example.com/track.wav")
        )
        assert result["bpm"] == 120.0
        assert result["key"] == "C Major"
        assert result["confidence"] == 0.5
        assert "note" in result

    def test_remote_url_http_also_handled(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.analyze_loop("http://example.com/track.wav")
        )
        assert result["bpm"] == 120.0


# ===========================================================================
# analyze_loop — file-not-found path (graceful fallback)
# ===========================================================================


class TestAnalyzeLoopMissingFile:
    @pytest.fixture
    def pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return RenderPipeline("missing-test")

    def test_missing_file_returns_defaults_with_error(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.analyze_loop("/nonexistent/path/to/file.wav")
        )
        assert result["bpm"] == 120.0
        assert result["confidence"] == 0.0
        assert "error" in result


# ===========================================================================
# slice_loop — remote URL (mock slices)
# ===========================================================================


class TestSliceLoopRemote:
    @pytest.fixture
    def pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return RenderPipeline("slice-remote")

    def test_remote_url_returns_mock_slices(self, pipeline):
        slices = asyncio.get_event_loop().run_until_complete(
            pipeline.slice_loop("https://example.com/track.wav", bpm=120.0)
        )
        assert isinstance(slices, list)
        assert len(slices) == 4
        assert all(isinstance(s, bytes) for s in slices)


# ===========================================================================
# generate_arrangement
# ===========================================================================


class TestGenerateArrangement:
    @pytest.fixture
    def pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return RenderPipeline("arrange-test")

    def test_returns_sections_list(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.generate_arrangement(loop_id=1, bpm=120.0)
        )
        assert "sections" in result
        assert isinstance(result["sections"], list)
        assert len(result["sections"]) > 0

    def test_sections_have_required_fields(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.generate_arrangement(loop_id=1, bpm=120.0)
        )
        for section in result["sections"]:
            assert "name" in section
            assert "bars" in section
            assert "start_bar" in section
            assert "start_sec" in section

    def test_bpm_stored_in_result(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.generate_arrangement(loop_id=1, bpm=140.0)
        )
        assert result["bpm"] == 140.0

    def test_total_bars_and_seconds_positive(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.generate_arrangement(loop_id=1, bpm=120.0, duration_seconds=180)
        )
        assert result["total_bars"] > 0
        assert result["total_seconds"] > 0

    def test_section_bars_at_least_four(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.generate_arrangement(loop_id=1, bpm=120.0)
        )
        for section in result["sections"]:
            assert section["bars"] >= 4

    def test_loop_id_in_each_section(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.generate_arrangement(loop_id=7, bpm=120.0)
        )
        for section in result["sections"]:
            assert section["loop_id"] == 7


# ===========================================================================
# render_stems
# ===========================================================================


class TestRenderStems:
    @pytest.fixture
    def pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return RenderPipeline("stems-test")

    def test_renders_requested_num_stems(self, pipeline):
        arrangement = {"total_seconds": 30}
        stems = asyncio.get_event_loop().run_until_complete(
            pipeline.render_stems(loop_id=1, file_path="/any", arrangement=arrangement, num_stems=2)
        )
        assert len(stems) == 2

    def test_stem_files_created(self, pipeline, tmp_path):
        arrangement = {"total_seconds": 30}
        stems = asyncio.get_event_loop().run_until_complete(
            pipeline.render_stems(loop_id=1, file_path="/any", arrangement=arrangement, num_stems=3)
        )
        for stem_name, stem_path in stems.items():
            assert os.path.exists(stem_path), f"Stem file missing: {stem_path}"

    def test_stem_names_from_known_list(self, pipeline):
        known = {"drums", "bass", "melody", "harmony", "pad"}
        arrangement = {"total_seconds": 30}
        stems = asyncio.get_event_loop().run_until_complete(
            pipeline.render_stems(loop_id=1, file_path="/any", arrangement=arrangement, num_stems=5)
        )
        assert set(stems.keys()).issubset(known)

    def test_stems_stored_in_outputs(self, pipeline):
        arrangement = {"total_seconds": 10}
        asyncio.get_event_loop().run_until_complete(
            pipeline.render_stems(loop_id=1, file_path="/any", arrangement=arrangement, num_stems=2)
        )
        assert "stems" in pipeline.outputs


# ===========================================================================
# export_mixdown
# ===========================================================================


class TestExportMixdown:
    @pytest.fixture
    def pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return RenderPipeline("mixdown-test")

    def test_empty_stems_creates_silence_file(self, pipeline):
        arrangement = {"total_seconds": 2}
        output_path = asyncio.get_event_loop().run_until_complete(
            pipeline.export_mixdown(stems={}, arrangement=arrangement)
        )
        assert os.path.exists(output_path)

    def test_output_path_contains_render_id(self, pipeline):
        arrangement = {"total_seconds": 1}
        output_path = asyncio.get_event_loop().run_until_complete(
            pipeline.export_mixdown(stems={}, arrangement=arrangement)
        )
        assert pipeline.render_id in output_path

    def test_mixdown_stored_in_outputs(self, pipeline):
        arrangement = {"total_seconds": 1}
        asyncio.get_event_loop().run_until_complete(
            pipeline.export_mixdown(stems={}, arrangement=arrangement)
        )
        assert "mixdown" in pipeline.outputs


# ===========================================================================
# render_full_pipeline — remote URL (fast path)
# ===========================================================================


class TestRenderFullPipeline:
    @pytest.fixture
    def pipeline(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        return RenderPipeline("full-pipeline")

    def test_remote_url_returns_completed_status(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.render_full_pipeline(
                loop_id=1,
                file_path="https://example.com/loop.wav",
                target_duration_seconds=30,
            )
        )
        assert result["status"] == "completed"
        assert result["render_id"] == "full-pipeline"
        assert result["loop_id"] == 1

    def test_result_contains_download_url(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.render_full_pipeline(
                loop_id=1,
                file_path="https://example.com/loop.wav",
                target_duration_seconds=30,
            )
        )
        assert "download_url" in result
        assert result["download_url"].startswith("/renders/")

    def test_result_contains_analysis(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.render_full_pipeline(
                loop_id=1,
                file_path="https://example.com/loop.wav",
                target_duration_seconds=30,
            )
        )
        analysis = result.get("analysis", {})
        assert "bpm" in analysis
        assert "key" in analysis

    def test_bpm_override_respected(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.render_full_pipeline(
                loop_id=1,
                file_path="https://example.com/loop.wav",
                bpm=140.0,
            )
        )
        assert result["analysis"]["bpm"] == 140.0

    def test_key_override_respected(self, pipeline):
        result = asyncio.get_event_loop().run_until_complete(
            pipeline.render_full_pipeline(
                loop_id=1,
                file_path="https://example.com/loop.wav",
                key="F# Minor",
            )
        )
        assert result["analysis"]["key"] == "F# Minor"


# ===========================================================================
# render_loop standalone function
# ===========================================================================


class TestRenderLoop:
    def test_render_loop_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            render_loop(loop_id=1, file_path="https://example.com/loop.wav")
        )
        assert isinstance(result, dict)
        assert "render_id" in result

    def test_render_loop_default_duration(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = asyncio.get_event_loop().run_until_complete(
            render_loop(loop_id=2, file_path="https://example.com/loop.wav")
        )
        assert result.get("status") == "completed"


# ===========================================================================
# render_loop_sync standalone function
# ===========================================================================


class TestRenderLoopSync:
    def test_render_loop_sync_returns_dict(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = render_loop_sync(loop_id=1, file_path="https://example.com/loop.wav")
        assert isinstance(result, dict)

    def test_render_loop_sync_completes_successfully(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        result = render_loop_sync(
            loop_id=3,
            file_path="https://example.com/loop.wav",
            target_duration_seconds=30,
        )
        assert result.get("status") == "completed"
