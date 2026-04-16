"""Tests for LoopService (app/services/loop_service.py)."""

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
    tmp_dir = tmp_path_factory.mktemp("loop_svc_db")
    db_path = tmp_dir / "loop_svc.sqlite"
    engine = create_engine(
        f"sqlite:///{db_path}",
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
# create_loop
# ---------------------------------------------------------------------------

def test_create_loop_persists_record(db):
    data = LoopCreate(name="Test Loop", bpm=120, genre="trap")
    loop = LoopService.create_loop(db, data)
    assert loop.id is not None
    assert loop.name == "Test Loop"
    assert loop.bpm == 120
    assert loop.genre == "trap"


def test_create_loop_returns_loop_instance(db):
    data = LoopCreate(name="Another Loop")
    loop = LoopService.create_loop(db, data)
    assert isinstance(loop, Loop)


def test_create_loop_without_optional_fields(db):
    data = LoopCreate(name="Minimal Loop")
    loop = LoopService.create_loop(db, data)
    assert loop.id is not None
    assert loop.genre is None
    assert loop.bpm is None


# ---------------------------------------------------------------------------
# list_loops
# ---------------------------------------------------------------------------

def test_list_loops_returns_list(db):
    LoopService.create_loop(db, LoopCreate(name="List Test Loop"))
    loops = LoopService.list_loops(db)
    assert isinstance(loops, list)
    assert len(loops) >= 1


def test_list_loops_filter_by_genre(db):
    LoopService.create_loop(db, LoopCreate(name="Trap Loop", genre="trap"))
    LoopService.create_loop(db, LoopCreate(name="Drill Loop", genre="drill"))
    trap_loops = LoopService.list_loops(db, genre="trap")
    assert all(l.genre == "trap" for l in trap_loops)


def test_list_loops_filter_by_status(db):
    loop = LoopService.create_loop(db, LoopCreate(name="Processing Loop"))
    loop.status = "processing"
    db.commit()
    processing = LoopService.list_loops(db, status="processing")
    assert any(l.id == loop.id for l in processing)


def test_list_loops_respects_limit(db):
    for i in range(5):
        LoopService.create_loop(db, LoopCreate(name=f"Limit Loop {i}"))
    results = LoopService.list_loops(db, limit=2)
    assert len(results) <= 2


def test_list_loops_respects_offset(db):
    for i in range(3):
        LoopService.create_loop(db, LoopCreate(name=f"Offset Loop {i}"))
    all_loops = LoopService.list_loops(db, limit=100)
    offset_loops = LoopService.list_loops(db, limit=100, offset=1)
    assert len(offset_loops) == len(all_loops) - 1


# ---------------------------------------------------------------------------
# get_loop
# ---------------------------------------------------------------------------

def test_get_loop_returns_correct_loop(db):
    created = LoopService.create_loop(db, LoopCreate(name="Get Test Loop"))
    fetched = LoopService.get_loop(db, created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.name == "Get Test Loop"


def test_get_loop_returns_none_for_missing_id(db):
    result = LoopService.get_loop(db, 999999)
    assert result is None


# ---------------------------------------------------------------------------
# update_loop
# ---------------------------------------------------------------------------

def test_update_loop_updates_fields(db):
    created = LoopService.create_loop(db, LoopCreate(name="Update Test Loop"))
    update = LoopUpdate(name="Updated Loop Name", bpm=140)
    updated = LoopService.update_loop(db, created.id, update)
    assert updated is not None
    assert updated.name == "Updated Loop Name"
    assert updated.bpm == 140


def test_update_loop_only_sets_provided_fields(db):
    created = LoopService.create_loop(db, LoopCreate(name="Partial Update Loop", genre="trap"))
    update = LoopUpdate(bpm=130)
    updated = LoopService.update_loop(db, created.id, update)
    # genre should remain unchanged
    assert updated.genre == "trap"
    assert updated.bpm == 130


def test_update_loop_returns_none_for_missing_id(db):
    update = LoopUpdate(name="Ghost Loop")
    result = LoopService.update_loop(db, 999999, update)
    assert result is None


# ---------------------------------------------------------------------------
# delete_loop
# ---------------------------------------------------------------------------

def test_delete_loop_removes_record(db):
    created = LoopService.create_loop(db, LoopCreate(name="Delete Test Loop"))
    loop_id = created.id
    with patch("app.services.loop_service.storage.delete_file"):
        result = LoopService.delete_loop(db, loop_id)
    assert result is True
    assert LoopService.get_loop(db, loop_id) is None


def test_delete_loop_returns_false_for_missing_id(db):
    result = LoopService.delete_loop(db, 999999)
    assert result is False


def test_delete_loop_skips_file_deletion_when_no_file_key(db):
    """Should succeed without calling storage.delete_file when no file_key."""
    created = LoopService.create_loop(db, LoopCreate(name="No File Loop"))
    with patch("app.services.loop_service.storage.delete_file") as mock_del:
        LoopService.delete_loop(db, created.id, delete_file=True)
    mock_del.assert_not_called()


def test_delete_loop_calls_storage_delete_when_file_key_set(db):
    created = LoopService.create_loop(db, LoopCreate(name="File Loop"))
    # Manually set a file_key
    created.file_key = "uploads/some_file.wav"
    db.commit()
    with patch("app.services.loop_service.storage.delete_file") as mock_del:
        LoopService.delete_loop(db, created.id, delete_file=True)
    mock_del.assert_called_once_with("uploads/some_file.wav")


# ---------------------------------------------------------------------------
# validate_audio_file
# ---------------------------------------------------------------------------

def test_validate_audio_valid_wav():
    ok, err = LoopService.validate_audio_file("track.wav", "audio/wav", 1024 * 1024)
    assert ok is True
    assert err is None


def test_validate_audio_valid_mp3():
    ok, err = LoopService.validate_audio_file("track.mp3", "audio/mpeg", 1024 * 1024)
    assert ok is True
    assert err is None


def test_validate_audio_invalid_content_type():
    ok, err = LoopService.validate_audio_file("image.png", "image/png", 1024)
    assert ok is False
    assert err is not None


def test_validate_audio_file_too_large():
    ok, err = LoopService.validate_audio_file(
        "huge.wav", "audio/wav", 60 * 1024 * 1024  # 60 MB > 50 MB limit
    )
    assert ok is False
    assert err is not None
