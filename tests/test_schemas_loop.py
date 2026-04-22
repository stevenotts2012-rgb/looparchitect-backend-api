"""Tests for app/schemas/loop.py — LoopCreate, LoopUpdate, LoopResponse."""

from datetime import datetime

import pytest

from app.schemas.loop import LoopCreate, LoopResponse, LoopUpdate


# ---------------------------------------------------------------------------
# LoopCreate
# ---------------------------------------------------------------------------


class TestLoopCreate:
    def test_minimal_create_only_requires_name(self):
        loop = LoopCreate(name="My Loop")
        assert loop.name == "My Loop"
        assert loop.filename is None
        assert loop.file_url is None
        assert loop.file_key is None
        assert loop.title is None
        assert loop.tempo is None
        assert loop.bpm is None
        assert loop.bars is None
        assert loop.key is None
        assert loop.musical_key is None
        assert loop.genre is None
        assert loop.duration_seconds is None

    def test_create_with_all_fields(self):
        loop = LoopCreate(
            name="Full Loop",
            filename="full.wav",
            file_url="https://example.com/full.wav",
            file_key="uploads/full.wav",
            title="Full Track",
            tempo=128.0,
            bpm=128.0,
            bars=8,
            key="C",
            musical_key="C Major",
            genre="house",
            duration_seconds=16.0,
        )
        assert loop.name == "Full Loop"
        assert loop.filename == "full.wav"
        assert loop.bpm == 128.0
        assert loop.bars == 8
        assert loop.genre == "house"
        assert loop.duration_seconds == 16.0

    def test_create_rejects_missing_name(self):
        with pytest.raises(Exception):
            LoopCreate()  # type: ignore[call-arg]

    def test_create_bpm_as_float(self):
        loop = LoopCreate(name="Tempo Loop", bpm=90.5)
        assert loop.bpm == 90.5

    def test_create_bars_as_int(self):
        loop = LoopCreate(name="Bar Loop", bars=4)
        assert loop.bars == 4


# ---------------------------------------------------------------------------
# LoopUpdate
# ---------------------------------------------------------------------------


class TestLoopUpdate:
    def test_empty_update_has_all_none_fields(self):
        update = LoopUpdate()
        assert update.name is None
        assert update.bpm is None
        assert update.genre is None
        assert update.status is None
        assert update.processed_file_url is None
        assert update.analysis_json is None

    def test_update_single_field(self):
        update = LoopUpdate(name="Renamed Loop")
        assert update.name == "Renamed Loop"
        assert update.bpm is None

    def test_update_status_field(self):
        update = LoopUpdate(status="complete")
        assert update.status == "complete"

    def test_update_analysis_json_field(self):
        update = LoopUpdate(analysis_json='{"bpm": 120}')
        assert update.analysis_json == '{"bpm": 120}'

    def test_update_multiple_fields(self):
        update = LoopUpdate(bpm=140.0, genre="trap", bars=16)
        assert update.bpm == 140.0
        assert update.genre == "trap"
        assert update.bars == 16

    def test_update_processed_file_url(self):
        update = LoopUpdate(processed_file_url="/renders/output.wav")
        assert update.processed_file_url == "/renders/output.wav"

    def test_update_musical_key(self):
        update = LoopUpdate(musical_key="G Minor")
        assert update.musical_key == "G Minor"


# ---------------------------------------------------------------------------
# LoopResponse
# ---------------------------------------------------------------------------


class TestLoopResponse:
    def _make_response(self, **kwargs):
        defaults = dict(
            id=1,
            name="Response Loop",
            filename=None,
            file_url=None,
            file_key=None,
            title=None,
            tempo=None,
            bpm=None,
            bars=None,
            key=None,
            musical_key=None,
            genre=None,
            duration_seconds=None,
            status=None,
            processed_file_url=None,
            analysis_json=None,
            stem_metadata=None,
            created_at=datetime(2024, 1, 1, 0, 0, 0),
        )
        defaults.update(kwargs)
        return LoopResponse(**defaults)

    def test_minimal_response(self):
        resp = self._make_response()
        assert resp.id == 1
        assert resp.name == "Response Loop"
        assert resp.created_at == datetime(2024, 1, 1, 0, 0, 0)

    def test_response_with_all_fields(self):
        resp = self._make_response(
            id=42,
            name="Rich Loop",
            filename="rich.wav",
            file_url="https://cdn.example.com/rich.wav",
            file_key="uploads/rich.wav",
            title="Rich Track",
            tempo=120.0,
            bpm=120.0,
            bars=8,
            key="A",
            musical_key="A Minor",
            genre="drill",
            duration_seconds=8.0,
            status="complete",
            processed_file_url="/renders/rich_out.wav",
            analysis_json='{"bpm": 120}',
            stem_metadata={"stems": ["drums", "bass"]},
        )
        assert resp.id == 42
        assert resp.bpm == 120.0
        assert resp.genre == "drill"
        assert resp.stem_metadata == {"stems": ["drums", "bass"]}

    def test_response_model_config_from_attributes(self):
        """LoopResponse.Config.from_attributes must be True for ORM compatibility."""
        assert LoopResponse.model_config.get("from_attributes") is True

    def test_response_stem_metadata_defaults_to_none(self):
        resp = self._make_response()
        assert resp.stem_metadata is None
