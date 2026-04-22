"""Tests for app/services/task_service.py — TaskService with mocked dependencies."""

import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_task_service():
    """Return TaskService instance without triggering real DB/settings imports."""
    from app.services.task_service import TaskService
    return TaskService()


def _make_mock_loop(loop_id: int = 1, file_url: str = "/uploads/test.wav", bpm: float = 120.0):
    loop = MagicMock()
    loop.id = loop_id
    loop.file_url = file_url
    loop.bpm = bpm
    loop.status = "pending"
    return loop


# ===========================================================================
# TaskService initialisation
# ===========================================================================

class TestTaskServiceInit:
    def test_instantiation_succeeds(self):
        svc = _make_task_service()
        assert svc is not None

    def test_module_level_instance_exists(self):
        from app.services.task_service import task_service
        from app.services.task_service import TaskService
        assert isinstance(task_service, TaskService)


# ===========================================================================
# analyze_loop_task
# ===========================================================================

class TestAnalyzeLoopTask:
    def _run(self, loop_id: int, loop_obj=None, file_path_obj=None, analysis=None):
        """Run analyze_loop_task with mocked DB/storage/audio."""
        from app.services.task_service import TaskService
        svc = TaskService()

        mock_loop = loop_obj or _make_mock_loop(loop_id)
        mock_file_path = MagicMock()
        mock_file_path.exists.return_value = True
        mock_analysis = analysis or {"bpm": 120.0, "key": "C Major", "duration_seconds": 8.0}

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loop

        mock_session_local = MagicMock(return_value=mock_db)

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=mock_session_local), \
             patch("app.services.task_service.storage_service") as mock_storage, \
             patch("app.services.task_service.audio_service") as mock_audio:

            mock_storage.get_file_path.return_value = mock_file_path
            mock_audio.analyze_loop.return_value = mock_analysis

            svc.analyze_loop_task(loop_id)

        return mock_loop, mock_db, mock_storage, mock_audio

    def test_sets_status_to_processing_then_complete(self):
        mock_loop, _, _, _ = self._run(1)
        assert mock_loop.status == "complete"

    def test_updates_bpm_from_analysis(self):
        analysis = {"bpm": 140.0, "key": "G Major", "duration_seconds": 4.0}
        mock_loop, _, _, _ = self._run(1, analysis=analysis)
        assert mock_loop.bpm == 140.0

    def test_updates_musical_key_from_analysis(self):
        analysis = {"bpm": 120.0, "key": "A Minor", "duration_seconds": 8.0}
        mock_loop, _, _, _ = self._run(1, analysis=analysis)
        assert mock_loop.musical_key == "A Minor"

    def test_updates_duration_from_analysis(self):
        analysis = {"bpm": 120.0, "key": "C", "duration_seconds": 16.0}
        mock_loop, _, _, _ = self._run(1, analysis=analysis)
        assert mock_loop.duration_seconds == 16.0

    def test_stores_analysis_json(self):
        mock_loop, _, _, _ = self._run(1)
        assert mock_loop.analysis_json is not None

    def test_db_close_called(self):
        _, mock_db, _, _ = self._run(1)
        mock_db.close.assert_called_once()

    def test_loop_not_found_exits_early(self):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)):
            svc.analyze_loop_task(999)

        mock_db.close.assert_called_once()

    def test_s3_file_raises_and_marks_failed(self):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_loop = _make_mock_loop()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loop

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)), \
             patch("app.services.task_service.storage_service") as mock_storage:
            # Simulate S3 (get_file_path returns None)
            mock_storage.get_file_path.return_value = None
            svc.analyze_loop_task(1)

        # Status should be set to "failed"
        assert mock_loop.status == "failed"

    def test_missing_file_marks_failed(self):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_loop = _make_mock_loop()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loop

        mock_file_path = MagicMock()
        mock_file_path.exists.return_value = False

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)), \
             patch("app.services.task_service.storage_service") as mock_storage:
            mock_storage.get_file_path.return_value = mock_file_path
            svc.analyze_loop_task(1)

        assert mock_loop.status == "failed"


# ===========================================================================
# generate_beat_task
# ===========================================================================

class TestGenerateBeatTask:
    def _run(self, loop_id: int = 1, loop_obj=None):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_loop = loop_obj or _make_mock_loop(loop_id)

        mock_file_path = MagicMock()
        mock_file_path.exists.return_value = True
        mock_file_path.__str__ = lambda self: "/uploads/test.wav"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loop

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)), \
             patch("app.services.task_service.storage_service") as mock_storage, \
             patch("app.services.task_service.audio_service") as mock_audio, \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"audio"))),
                 __exit__=MagicMock(return_value=False)
             ))):

            mock_storage.get_file_path.return_value = mock_file_path
            mock_audio.generate_full_beat.return_value = ("/renders/out.wav", {"bpm": 120.0})
            mock_storage.upload_file.return_value = "/uploads/out.wav"

            svc.generate_beat_task(loop_id, target_length_seconds=60, output_filename="out.wav")

        return mock_loop, mock_db

    def test_sets_status_to_complete(self):
        mock_loop, _ = self._run(1)
        assert mock_loop.status == "complete"

    def test_sets_processed_file_url(self):
        mock_loop, _ = self._run(1)
        assert mock_loop.processed_file_url is not None

    def test_db_close_called(self):
        _, mock_db = self._run(1)
        mock_db.close.assert_called_once()

    def test_loop_not_found_exits_early(self):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)):
            svc.generate_beat_task(999, 60, "out.wav")

        mock_db.close.assert_called_once()

    def test_s3_file_marks_failed(self):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_loop = _make_mock_loop()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loop

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)), \
             patch("app.services.task_service.storage_service") as mock_storage:
            mock_storage.get_file_path.return_value = None
            svc.generate_beat_task(1, 60, "out.wav")

        assert mock_loop.status == "failed"


# ===========================================================================
# extend_loop_task
# ===========================================================================

class TestExtendLoopTask:
    def _run(self, loop_id: int = 1, loop_obj=None):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_loop = loop_obj or _make_mock_loop(loop_id)

        mock_file_path = MagicMock()
        mock_file_path.exists.return_value = True
        mock_file_path.__str__ = lambda self: "/uploads/test.wav"

        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loop

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)), \
             patch("app.services.task_service.storage_service") as mock_storage, \
             patch("app.services.task_service.audio_service") as mock_audio, \
             patch("builtins.open", MagicMock(return_value=MagicMock(
                 __enter__=MagicMock(return_value=MagicMock(read=MagicMock(return_value=b"audio"))),
                 __exit__=MagicMock(return_value=False)
             ))):

            mock_storage.get_file_path.return_value = mock_file_path
            mock_audio.extend_loop.return_value = ("/renders/extended.wav", {"bars": 8})
            mock_storage.upload_file.return_value = "/uploads/extended.wav"

            svc.extend_loop_task(loop_id, bars=8, output_filename="extended.wav")

        return mock_loop, mock_db

    def test_sets_status_to_complete(self):
        mock_loop, _ = self._run(1)
        assert mock_loop.status == "complete"

    def test_sets_processed_file_url(self):
        mock_loop, _ = self._run(1)
        assert mock_loop.processed_file_url is not None

    def test_db_close_called(self):
        _, mock_db = self._run(1)
        mock_db.close.assert_called_once()

    def test_loop_not_found_exits_early(self):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = None

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)):
            svc.extend_loop_task(999, bars=4, output_filename="out.wav")

        mock_db.close.assert_called_once()

    def test_s3_file_marks_failed(self):
        from app.services.task_service import TaskService
        svc = TaskService()
        mock_loop = _make_mock_loop()
        mock_db = MagicMock()
        mock_db.query.return_value.filter.return_value.first.return_value = mock_loop

        with patch("app.services.task_service.create_engine"), \
             patch("app.services.task_service.sessionmaker", return_value=MagicMock(return_value=mock_db)), \
             patch("app.services.task_service.storage_service") as mock_storage:
            mock_storage.get_file_path.return_value = None
            svc.extend_loop_task(1, bars=4, output_filename="out.wav")

        assert mock_loop.status == "failed"
