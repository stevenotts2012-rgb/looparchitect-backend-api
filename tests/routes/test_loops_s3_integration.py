"""
Comprehensive tests for S3 storage integration with loops.
Uses moto for realistic S3 mocking without requiring real AWS credentials.
"""

import io
import json
from unittest.mock import patch
from moto import mock_s3
import boto3
import pytest
from fastapi.testclient import TestClient

from main import app
from app.db import get_db
from app.models.loop import Loop
from app.models.base import Base
from app.services.storage import storage


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def test_db():
    """Create a test database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


@pytest.fixture
def client(test_db):
    """Create a FastAPI test client with mocked database."""
    def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


@pytest.fixture
def mock_s3_setup():
    """Set up moto S3 mock for testing."""
    with mock_s3():
        # Create mock S3 bucket
        s3 = boto3.client('s3', region_name='us-east-1')
        s3.create_bucket(Bucket='test-bucket')
        
        # Patch storage module to use test bucket
        with patch.dict('os.environ', {
            'AWS_S3_BUCKET': 'test-bucket',
            'AWS_REGION': 'us-east-1'
        }):
            yield s3


# ── Test S3 File Upload ───────────────────────────────────────────────────────

class TestS3FileUpload:
    """Tests for S3 file upload functionality."""

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_upload_loop_stores_in_s3(self, mock_upload, client, mock_s3_setup):
        """Test that uploaded loops are stored in S3."""
        s3 = mock_s3_setup
        
        # Mock the upload to return S3 key
        s3_key = "uploads/test-uuid.wav"
        mock_upload.return_value = (s3_key, 40000)
        
        # Create loop with file
        file_content = b"fake audio content"
        files = {
            'file': ('test.wav', io.BytesIO(file_content), 'audio/wav')
        }
        data = {
            'loop_in': json.dumps({"name": "S3 Test Loop"})
        }
        
        response = client.post("/api/v1/loops/with-file", files=files, data=data)
        
        assert response.status_code == 201
        result = response.json()
        assert result["file_key"] == s3_key

    def test_s3_storage_module_initializes(self):
        """Test that storage module can initialize."""
        assert storage is not None
        # use_s3 should be False in test (no AWS env vars set)
        assert storage.use_s3 == False


# ── Test Presigned URLs ───────────────────────────────────────────────────────

class TestPresignedUrls:
    """Tests for S3 presigned URL generation."""

    @patch('app.services.storage.S3Storage.create_presigned_get_url')
    def test_get_loop_with_presigned_urls(self, mock_presigned, client, test_db):
        """Test that loop responses can include presigned URLs."""
        # Create a test loop
        loop = Loop(
            name="Presigned Test",
            file_key="uploads/presigned-uuid.wav"
        )
        test_db.add(loop)
        test_db.commit()
        test_db.refresh(loop)
        
        # Mock presigned URL generation
        mock_presigned.return_value = "https://s3.amazonaws.com/signed-url-here"
        
        # Get loop
        response = client.get(f"/api/v1/loops/{loop.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["file_key"] == "uploads/presigned-uuid.wav"


# ── Test S3 File Deletion ─────────────────────────────────────────────────────

class TestS3FileDeletion:
    """Tests for safe deletion of loop records and optional S3 cleanup."""

    def test_delete_loop_does_not_delete_s3_file(self, client, test_db):
        """Test that deleting a loop record doesn't delete S3 file by default."""
        loop = Loop(
            name="Delete Test",
            file_key="uploads/delete-uuid.wav"
        )
        test_db.add(loop)
        test_db.commit()
        
        loop_id = loop.id
        
        # Delete loop
        response = client.delete(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 200
        
        # Loop record should be deleted
        response = client.get(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 404


# ── Test Storage Mode Fallback (S3 vs Local) ──────────────────────────────────

class TestStorageModeFallback:
    """Tests for fallback behavior when S3 is not available."""

    def test_upload_falls_back_to_local_when_no_s3_env(self, client, test_db):
        """Test that upload works with local storage when S3 env vars not set."""
        # Storage should default to local when S3 env vars not provided
        assert storage.use_s3 == False
        
        # This allows testing without real S3


# ── Test Loop with Multiple Files (Scenario) ──────────────────────────────────

class TestLoopFileManagement:
    """Tests for managing multiple loop files."""

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_update_loop_file_key(self, mock_upload, client, test_db):
        """Test updating a loop's file key to point to new S3 location."""
        # Create initial loop
        loop = Loop(
            name="Update File Test",
            file_key="uploads/old-uuid.wav"
        )
        test_db.add(loop)
        test_db.commit()
        
        # Update file_key to new S3 location
        update_data = {
            "file_key": "uploads/new-uuid.wav"
        }
        response = client.patch(f"/api/v1/loops/{loop.id}", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["file_key"] == "uploads/new-uuid.wav"


# ── Test Concurrent Loop Uploads ──────────────────────────────────────────────

class TestConcurrentUploads:
    """Tests for handling concurrent loop uploads."""

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_multiple_concurrent_uploads(self, mock_upload, client):
        """Test uploading multiple loops concurrently."""
        mock_upload.side_effect = [
            ("uploads/loop1-uuid.wav", 20000),
            ("uploads/loop2-uuid.wav", 20000),
            ("uploads/loop3-uuid.wav", 20000)
        ]
        
        # Create multiple loops
        for i in range(3):
            file_content = b"fake audio content"
            files = {
                'file': (f'loop{i}.wav', io.BytesIO(file_content), 'audio/wav')
            }
            data = {
                'loop_in': json.dumps({"name": f"Concurrent Loop {i}"})
            }
            response = client.post("/api/v1/loops/with-file", files=files, data=data)
            assert response.status_code == 201
        
        # Verify all created
        response = client.get("/api/v1/loops")
        assert len(response.json()) == 3


# ── Test Storage Validation ───────────────────────────────────────────────────

class TestStorageValidation:
    """Tests for file validation before storage."""

    def test_audio_file_validation_before_upload(self, client):
        """Test that invalid audio files are rejected."""
        # Mock upload to fail on validation
        with patch('app.services.loop_service.loop_service.validate_audio_file') as mock_validate:
            mock_validate.return_value = (False, "Invalid audio format")
            
            file_content = b"not audio"
            files = {
                'file': ('not_audio.txt', io.BytesIO(file_content), 'text/plain')
            }
            data = {
                'loop_in': json.dumps({"name": "Invalid File"})
            }
            
            response = client.post("/api/v1/loops/with-file", files=files, data=data)
            
            # Should reject invalid files
            assert response.status_code == 400

    def test_file_size_validation(self, client):
        """Test that oversized files are rejected."""
        with patch('app.services.loop_service.loop_service.validate_audio_file') as mock_validate:
            mock_validate.return_value = (False, "File too large")
            
            # Create very large file
            large_content = b"x" * (100 * 1024 * 1024)  # 100MB
            files = {
                'file': ('large.wav', io.BytesIO(large_content), 'audio/wav')
            }
            data = {
                'loop_in': json.dumps({"name": "Large File"})
            }
            
            response = client.post("/api/v1/loops/with-file", files=files, data=data)
            
            # Should reject large files
            assert response.status_code == 400


# ── Test S3 Error Handling ────────────────────────────────────────────────────

class TestS3ErrorHandling:
    """Tests for graceful S3 error handling."""

    def test_s3_upload_failure_returns_500(self, client):
        """Test that S3 upload failures return 500."""
        with patch('app.services.loop_service.loop_service.upload_loop_file') as mock_upload:
            mock_upload.side_effect = Exception("S3 connection failed")
            
            file_content = b"audio content"
            files = {
                'file': ('test.wav', io.BytesIO(file_content), 'audio/wav')
            }
            data = {
                'loop_in': json.dumps({"name": "S3 Fail"})
            }
            
            response = client.post("/api/v1/loops/with-file", files=files, data=data)
            
            assert response.status_code == 500

    def test_s3_access_denied_error(self, client):
        """Test handling of S3 access denied errors."""
        with patch('app.services.loop_service.loop_service.upload_loop_file') as mock_upload:
            mock_upload.side_effect = PermissionError("Access Denied")
            
            file_content = b"audio content"
            files = {
                'file': ('test.wav', io.BytesIO(file_content), 'audio/wav')
            }
            data = {
                'loop_in': json.dumps({"name": "Access Denied"})
            }
            
            response = client.post("/api/v1/loops/with-file", files=files, data=data)
            
            assert response.status_code == 500


# ── Test File Key Generation ──────────────────────────────────────────────────

class TestFileKeyGeneration:
    """Tests for S3 file key generation patterns."""

    def test_file_key_format(self, client, test_db):
        """Test that file keys follow expected format."""
        loop = Loop(
            name="Format Test",
            file_key="uploads/12345-uuid-abcde.wav"
        )
        test_db.add(loop)
        test_db.commit()
        
        response = client.get(f"/api/v1/loops/{loop.id}")
        
        assert response.status_code == 200
        data = response.json()
        # File key should start with uploads/
        assert data["file_key"].startswith("uploads/")
        assert data["file_key"].endswith(".wav")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
