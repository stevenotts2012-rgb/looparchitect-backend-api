"""Extended tests for SQLAlchemy model properties.

Covers previously-untested branches in:
- app/models/loop.py  — stem_metadata (exception + non-dict), stems_dict, stem_roles
- app/models/arrangement.py — mastering_metadata (with data, missing data, exception)
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.loop import Loop
from app.models.arrangement import Arrangement


@pytest.fixture(scope="module")
def db_session(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("models_ext_db")
    engine = create_engine(
        f"sqlite:///{tmp_dir / 'models_ext.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    engine.dispose()


# ---------------------------------------------------------------------------
# Loop.stem_metadata
# ---------------------------------------------------------------------------


class TestLoopStemMetadata:
    def test_returns_none_when_no_analysis_json(self):
        loop = Loop(name="no-analysis", analysis_json=None)
        assert loop.stem_metadata is None

    def test_returns_stem_separation_when_present(self):
        payload = {"stem_separation": {"vocals": "url1", "drums": "url2"}}
        loop = Loop(name="stems", analysis_json=json.dumps(payload))
        result = loop.stem_metadata
        assert result == {"vocals": "url1", "drums": "url2"}

    def test_returns_none_when_key_absent(self):
        """analysis_json is valid but has no stem_separation key."""
        payload = {"other_key": "value"}
        loop = Loop(name="no-stem-sep", analysis_json=json.dumps(payload))
        assert loop.stem_metadata is None

    def test_returns_none_for_non_dict_json(self):
        """JSON is valid but the top-level value is not a dict (line 53)."""
        loop = Loop(name="list-json", analysis_json=json.dumps([1, 2, 3]))
        assert loop.stem_metadata is None

    def test_returns_none_for_invalid_json(self):
        """Invalid JSON triggers the except branch (lines 51-52)."""
        loop = Loop(name="bad-json", analysis_json="NOT VALID JSON {{")
        assert loop.stem_metadata is None


# ---------------------------------------------------------------------------
# Loop.stems_dict
# ---------------------------------------------------------------------------


class TestLoopStemsDict:
    def test_returns_empty_dict_when_no_stem_files_json(self):
        """stems_dict returns {} when stem_files_json is None/empty."""
        loop = Loop(name="no-stems", stem_files_json=None)
        assert loop.stems_dict == {}

    def test_returns_empty_dict_for_empty_string(self):
        loop = Loop(name="empty-stems", stem_files_json="")
        assert loop.stems_dict == {}

    def test_returns_parsed_dict_for_valid_json(self):
        payload = {"kick": {"url": "/uploads/kick.wav"}}
        loop = Loop(name="valid-stems", stem_files_json=json.dumps(payload))
        assert loop.stems_dict == payload

    def test_returns_empty_dict_for_invalid_json(self):
        """Invalid JSON triggers the except branch (lines 62-63)."""
        loop = Loop(name="bad-stems-json", stem_files_json="INVALID {{{")
        assert loop.stems_dict == {}


# ---------------------------------------------------------------------------
# Loop.stem_roles
# ---------------------------------------------------------------------------


class TestLoopStemRoles:
    def test_returns_empty_dict_when_no_stem_roles_json(self):
        loop = Loop(name="no-roles", stem_roles_json=None)
        assert loop.stem_roles == {}

    def test_returns_empty_dict_for_empty_string(self):
        loop = Loop(name="empty-roles", stem_roles_json="")
        assert loop.stem_roles == {}

    def test_returns_parsed_dict_for_valid_json(self):
        payload = {"kick": "uploads/kick.wav", "bass": "uploads/bass.wav"}
        loop = Loop(name="valid-roles", stem_roles_json=json.dumps(payload))
        assert loop.stem_roles == payload

    def test_returns_empty_dict_for_invalid_json(self):
        """Invalid JSON triggers the except branch (lines 72-73)."""
        loop = Loop(name="bad-roles-json", stem_roles_json="}{invalid")
        assert loop.stem_roles == {}


# ---------------------------------------------------------------------------
# Arrangement.mastering_metadata
# ---------------------------------------------------------------------------


class TestArrangementMasteringMetadata:
    def test_returns_none_when_no_render_plan_json(self):
        arr = Arrangement(loop_id=1, target_seconds=60, render_plan_json=None)
        assert arr.mastering_metadata is None

    def test_returns_mastering_when_present(self):
        """Full valid payload with nested mastering block."""
        payload = {
            "render_profile": {
                "postprocess": {
                    "mastering": {"loudness": -14, "limiter": True}
                }
            }
        }
        arr = Arrangement(
            loop_id=1,
            target_seconds=60,
            render_plan_json=json.dumps(payload),
        )
        result = arr.mastering_metadata
        assert result == {"loudness": -14, "limiter": True}

    def test_returns_none_when_render_profile_missing(self):
        """render_plan_json valid but no render_profile key → None (line 69)."""
        payload = {"sections": []}
        arr = Arrangement(
            loop_id=1,
            target_seconds=60,
            render_plan_json=json.dumps(payload),
        )
        assert arr.mastering_metadata is None

    def test_returns_none_when_postprocess_missing(self):
        """render_profile exists but no postprocess → None."""
        payload = {"render_profile": {"quality": "high"}}
        arr = Arrangement(
            loop_id=1,
            target_seconds=60,
            render_plan_json=json.dumps(payload),
        )
        assert arr.mastering_metadata is None

    def test_returns_none_when_mastering_not_in_postprocess(self):
        """postprocess dict without mastering key → None."""
        payload = {
            "render_profile": {
                "postprocess": {"normalise": True}
            }
        }
        arr = Arrangement(
            loop_id=1,
            target_seconds=60,
            render_plan_json=json.dumps(payload),
        )
        assert arr.mastering_metadata is None

    def test_returns_none_for_invalid_json(self):
        """Invalid JSON triggers the except branch (lines 67-68)."""
        arr = Arrangement(
            loop_id=1,
            target_seconds=60,
            render_plan_json="INVALID {{{",
        )
        assert arr.mastering_metadata is None

    def test_render_profile_not_dict_returns_none(self):
        """render_profile is not a dict (e.g. a list) → None."""
        payload = {"render_profile": ["not", "a", "dict"]}
        arr = Arrangement(
            loop_id=1,
            target_seconds=60,
            render_plan_json=json.dumps(payload),
        )
        assert arr.mastering_metadata is None
