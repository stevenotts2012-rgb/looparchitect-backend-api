"""Extended tests for app/services/loop_service.py — exception paths.

Covers previously-untested branches:
- create_loop DB error path (lines 50-53)
- update_loop DB error path (lines 142-145)
- delete_loop file deletion error (lines 179-180)
- delete_loop DB delete error (lines 188-191)
- upload_loop_file storage upload error (lines 229-231)
- validate_audio_file invalid extension (line 270) and empty file (line 278)
- sanitize_filename length truncation (lines 303-304)
"""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.models.base import Base
from app.models.loop import Loop
from app.models.schemas import LoopCreate, LoopUpdate
from app.services.loop_service import LoopService


@pytest.fixture(scope="module")
def engine_and_session(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("loop_svc_ext_db")
    engine = create_engine(
        f"sqlite:///{tmp_dir / 'loop_svc_ext.sqlite'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    yield engine, Session
    engine.dispose()


@pytest.fixture
def db(engine_and_session):
    _, Session = engine_and_session
    session = Session()
    yield session
    session.rollback()
    session.close()


# ---------------------------------------------------------------------------
# create_loop — exception path
# ---------------------------------------------------------------------------


def test_create_loop_rolls_back_and_reraises_on_db_error(db):
    """When db.commit() raises, create_loop rolls back and re-raises."""
    data = LoopCreate(name="Error Loop")
    with patch.object(db, "commit", side_effect=Exception("db error")):
        with pytest.raises(Exception, match="db error"):
            LoopService.create_loop(db, data)
    # After rollback the session should be usable
    db.rollback()


# ---------------------------------------------------------------------------
# update_loop — exception path
# ---------------------------------------------------------------------------


def test_update_loop_rolls_back_and_reraises_on_db_error(db):
    """When db.commit() raises during update, update_loop rolls back and re-raises."""
    created = LoopService.create_loop(db, LoopCreate(name="Update Error Loop"))
    loop_id = created.id
    update = LoopUpdate(name="New Name")
    with patch.object(db, "commit", side_effect=Exception("commit error")):
        with pytest.raises(Exception, match="commit error"):
            LoopService.update_loop(db, loop_id, update)
    db.rollback()


# ---------------------------------------------------------------------------
# delete_loop — file deletion failure (lines 179-180)
# ---------------------------------------------------------------------------


def test_delete_loop_continues_when_file_deletion_fails(db):
    """When storage.delete_file raises, the DB record is still deleted."""
    created = LoopService.create_loop(db, LoopCreate(name="File Error Loop"))
    created.file_key = "uploads/some_file.wav"
    db.commit()
    loop_id = created.id

    with patch(
        "app.services.loop_service.storage.delete_file",
        side_effect=Exception("S3 error"),
    ):
        result = LoopService.delete_loop(db, loop_id, delete_file=True)

    assert result is True
    assert LoopService.get_loop(db, loop_id) is None


# ---------------------------------------------------------------------------
# delete_loop — DB delete exception (lines 188-191)
# ---------------------------------------------------------------------------


def test_delete_loop_rolls_back_and_reraises_on_db_error(db):
    """When db.delete() raises, delete_loop rolls back and re-raises."""
    created = LoopService.create_loop(db, LoopCreate(name="DB Delete Error Loop"))
    with patch.object(db, "delete", side_effect=Exception("delete error")):
        with pytest.raises(Exception, match="delete error"):
            LoopService.delete_loop(db, created.id)
    db.rollback()


# ---------------------------------------------------------------------------
# upload_loop_file — storage upload error (lines 229-231)
# ---------------------------------------------------------------------------


def test_upload_loop_file_reraises_on_storage_error():
    """When storage.upload_file raises, upload_loop_file re-raises."""
    with patch(
        "app.services.loop_service.storage.upload_file",
        side_effect=Exception("storage unavailable"),
    ):
        with pytest.raises(Exception, match="storage unavailable"):
            LoopService.upload_loop_file(
                file_content=b"fake audio",
                filename="track.wav",
                content_type="audio/wav",
            )


# ---------------------------------------------------------------------------
# validate_audio_file — invalid extension and empty file
# ---------------------------------------------------------------------------


def test_validate_audio_file_invalid_extension_returns_error():
    """A .flac file (not in allowed extensions) returns an error (line 270)."""
    ok, err = LoopService.validate_audio_file("track.flac", "audio/wav", 1024)
    assert ok is False
    assert err is not None
    assert ".flac" in err


def test_validate_audio_file_empty_file_returns_error():
    """An empty file (0 bytes) returns an error (line 278)."""
    ok, err = LoopService.validate_audio_file("track.wav", "audio/wav", 0)
    assert ok is False
    assert "empty" in err.lower()


def test_validate_audio_file_wav_extension_valid():
    """A .wav file with valid MIME type is accepted."""
    ok, err = LoopService.validate_audio_file("track.wav", "audio/wav", 1024)
    assert ok is True
    assert err is None


def test_validate_audio_file_mp3_extension_valid():
    """A .mp3 file with audio/mpeg MIME is accepted."""
    ok, err = LoopService.validate_audio_file("track.mp3", "audio/mpeg", 1024)
    assert ok is True
    assert err is None


# ---------------------------------------------------------------------------
# sanitize_filename — length truncation (lines 303-304)
# ---------------------------------------------------------------------------


def test_sanitize_filename_truncates_very_long_name():
    """A filename longer than 255 chars is truncated (lines 303-304)."""
    long_name = "a" * 300 + ".wav"
    result = LoopService.sanitize_filename(long_name)
    assert len(result) <= 255
    assert result.endswith(".wav")


def test_sanitize_filename_short_name_unchanged():
    """A short filename is not modified."""
    result = LoopService.sanitize_filename("my_track.wav")
    assert result == "my_track.wav"


def test_sanitize_filename_removes_path_components():
    """Path traversal characters are handled via os.path.basename."""
    result = LoopService.sanitize_filename("../../etc/passwd.wav")
    assert "/" not in result
    assert ".." not in result


def test_sanitize_filename_replaces_special_chars():
    """Non-alphanumeric chars (except dots/dashes/underscores) become underscores."""
    result = LoopService.sanitize_filename("my file (1).wav")
    assert " " not in result
    assert "(" not in result
    assert ")" not in result
