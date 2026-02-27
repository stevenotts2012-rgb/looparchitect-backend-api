"""
Comprehensive tests for loop CRUD operations and file upload endpoints.
Tests POST, GET, PUT, PATCH, DELETE operations with S3 mocking.
"""

import io
import json
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from main import app
from app.models.loop import Loop
from app.db import get_db


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def test_db():
    """Create a test database session."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.models.base import Base

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
def test_loop(test_db):
    """Create a test loop record in the database."""
    loop = Loop(
        name="Test Loop",
        filename="test_loop.wav",
        file_key="uploads/test-uuid.wav",
        title="Test Title",
        bpm=140,
        bars=16,
        tempo=140,
        key="C",
        musical_key="C",
        genre="Trap",
        duration_seconds=8.0,
        status="pending"
    )
    test_db.add(loop)
    test_db.commit()
    test_db.refresh(loop)
    return loop


# ── Test POST /api/v1/loops (Create) ──────────────────────────────────────────

class TestLoopCreate:
    """Tests for POST /api/v1/loops endpoint."""

    def test_create_loop_minimal(self, client):
        """Test creating a loop with minimal required fields."""
        payload = {"name": "Minimal Loop"}
        response = client.post("/api/v1/loops", json=payload)
        
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Minimal Loop"
        assert data["id"] is not None
        assert "created_at" in data

    def test_create_loop_full(self, client):
        """Test creating a loop with all fields."""
        payload = {
            "name": "Full Loop",
            "filename": "full.wav",
            "file_key": "uploads/full-uuid.wav",
            "title": "Full Title",
            "bpm": 120,
            "bars": 8,
            "tempo": 120,
            "key": "D",
            "musical_key": "D",
            "genre": "Hip-Hop",
            "duration_seconds": 4.0
        }
        response = client.post("/api/v1/loops", json=payload)
        
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Full Loop"
        assert data["bpm"] == 120
        assert data["bars"] == 8
        assert data["genre"] == "Hip-Hop"

    def test_create_loop_missing_name(self, client):
        """Test creating a loop without required name field."""
        payload = {"bpm": 140}
        response = client.post("/api/v1/loops", json=payload)
        
        # Pydantic should reject this
        assert response.status_code == 422  # Validation error

    def test_create_loop_with_optional_bars(self, client):
        """Test creating a loop with optional bars field."""
        payload = {
            "name": "Loop with bars",
            "bpm": 140,
            "bars": 32
        }
        response = client.post("/api/v1/loops", json=payload)
        
        assert response.status_code == 201
        data = response.json()
        assert data["bars"] == 32


# ── Test GET /api/v1/loops (List) ──────────────────────────────────────────────

class TestLoopList:
    """Tests for GET /api/v1/loops endpoint."""

    def test_list_loops_empty(self, client):
        """Test listing loops when there are none."""
        response = client.get("/api/v1/loops")
        
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) == 0

    def test_list_loops_with_results(self, client, test_loop):
        """Test listing loops when records exist."""
        response = client.get("/api/v1/loops")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Test Loop"
        assert data[0]["id"] == test_loop.id

    def test_list_loops_with_status_filter(self, client, test_db):
        """Test listing loops filtered by status."""
        # Create two loops with different statuses
        loop1 = Loop(name="Loop 1", status="pending")
        loop2 = Loop(name="Loop 2", status="processing")
        test_db.add_all([loop1, loop2])
        test_db.commit()
        
        response = client.get("/api/v1/loops?status=processing")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["name"] == "Loop 2"

    def test_list_loops_with_genre_filter(self, client, test_db):
        """Test listing loops filtered by genre."""
        loop1 = Loop(name="Trap Loop", genre="Trap")
        loop2 = Loop(name="Hip-Hop Loop", genre="Hip-Hop")
        test_db.add_all([loop1, loop2])
        test_db.commit()
        
        response = client.get("/api/v1/loops?genre=Trap")
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["genre"] == "Trap"

    def test_list_loops_with_pagination(self, client, test_db):
        """Test listing loops with limit and offset."""
        for i in range(5):
            loop = Loop(name=f"Loop {i}")
            test_db.add(loop)
        test_db.commit()
        
        # Get first 2
        response = client.get("/api/v1/loops?limit=2&offset=0")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        
        # Get next 2
        response = client.get("/api/v1/loops?limit=2&offset=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2


# ── Test GET /api/v1/loops/{id} (Get Single) ──────────────────────────────────

class TestLoopGet:
    """Tests for GET /api/v1/loops/{loop_id} endpoint."""

    def test_get_loop_exists(self, client, test_loop):
        """Test getting an existing loop."""
        response = client.get(f"/api/v1/loops/{test_loop.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_loop.id
        assert data["name"] == "Test Loop"
        assert data["file_key"] == "uploads/test-uuid.wav"

    def test_get_loop_not_found(self, client):
        """Test getting a non-existent loop."""
        response = client.get("/api/v1/loops/99999")
        
        assert response.status_code == 404

    def test_get_loop_includes_all_fields(self, client, test_loop):
        """Test that response includes all loop fields."""
        response = client.get(f"/api/v1/loops/{test_loop.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "id" in data
        assert "name" in data
        assert "file_key" in data
        assert "bpm" in data
        assert "bars" in data
        assert "genre" in data
        assert "created_at" in data


# ── Test PUT /api/v1/loops/{id} (Full Update) ────────────────────────────────

class TestLoopUpdate:
    """Tests for PUT /api/v1/loops/{loop_id} endpoint."""

    def test_update_loop_full(self, client, test_loop):
        """Test fully updating a loop record."""
        update_data = {
            "name": "Updated Loop",
            "bpm": 160,
            "bars": 32,
            "genre": "House",
            "duration_seconds": 16.0
        }
        response = client.put(f"/api/v1/loops/{test_loop.id}", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "Updated Loop"
        assert data["bpm"] == 160
        assert data["bars"] == 32
        assert data["genre"] == "House"

    def test_update_loop_partial_via_put(self, client, test_loop):
        """Test that PUT accepts partial updates (although it's semantically PUT)."""
        update_data = {"bpm": 160}
        response = client.put(f"/api/v1/loops/{test_loop.id}", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["bpm"] == 160
        # Original values should be preserved or modified
        assert data["id"] == test_loop.id

    def test_update_loop_not_found(self, client):
        """Test updating a non-existent loop."""
        update_data = {"name": "Updated"}
        response = client.put("/api/v1/loops/99999", json=update_data)
        
        assert response.status_code == 404

    def test_update_loop_bars_field(self, client, test_loop):
        """Test updating the new bars field."""
        assert test_loop.bars == 16
        
        update_data = {"bars": 64}
        response = client.put(f"/api/v1/loops/{test_loop.id}", json=update_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["bars"] == 64


# ── Test PATCH /api/v1/loops/{id} (Partial Update) ───────────────────────────

class TestLoopPatch:
    """Tests for PATCH /api/v1/loops/{loop_id} endpoint."""

    def test_patch_loop_single_field(self, client, test_loop):
        """Test patching a single field."""
        patch_data = {"bpm": 180}
        response = client.patch(f"/api/v1/loops/{test_loop.id}", json=patch_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["bpm"] == 180
        assert data["name"] == "Test Loop"  # Unchanged

    def test_patch_loop_multiple_fields(self, client, test_loop):
        """Test patching multiple fields."""
        patch_data = {
            "bpm": 170,
            "bars": 48,
            "genre": "Dubstep"
        }
        response = client.patch(f"/api/v1/loops/{test_loop.id}", json=patch_data)
        
        assert response.status_code == 200
        data = response.json()
        assert data["bpm"] == 170
        assert data["bars"] == 48
        assert data["genre"] == "Dubstep"

    def test_patch_loop_empty_body(self, client, test_loop):
        """Test patching with empty body (no changes)."""
        response = client.patch(f"/api/v1/loops/{test_loop.id}", json={})
        
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == test_loop.id
        assert data["name"] == "Test Loop"  # Unchanged

    def test_patch_loop_not_found(self, client):
        """Test patching a non-existent loop."""
        patch_data = {"name": "Updated"}
        response = client.patch("/api/v1/loops/99999", json=patch_data)
        
        assert response.status_code == 404


# ── Test DELETE /api/v1/loops/{id} ────────────────────────────────────────────

class TestLoopDelete:
    """Tests for DELETE /api/v1/loops/{loop_id} endpoint."""

    def test_delete_loop_exists(self, client, test_loop):
        """Test deleting an existing loop."""
        loop_id = test_loop.id
        
        # Verify it exists
        response = client.get(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 200
        
        # Delete it
        response = client.delete(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 200
        
        # Verify it's gone
        response = client.get(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 404

    def test_delete_loop_not_found(self, client):
        """Test deleting a non-existent loop."""
        response = client.delete("/api/v1/loops/99999")
        
        assert response.status_code == 404

    def test_delete_loop_response(self, client, test_loop):
        """Test delete response format."""
        response = client.delete(f"/api/v1/loops/{test_loop.id}")
        
        assert response.status_code == 200
        data = response.json()
        # Should return success message or similar
        assert "id" in data or "message" in data


# ── Test POST /api/v1/loops/with-file ──────────────────────────────────────────

class TestLoopWithFile:
    """Tests for POST /api/v1/loops/with-file endpoint (multipart upload)."""

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_create_loop_with_file_minimal(self, mock_upload, client):
        """Test creating a loop with file upload (minimal metadata)."""
        # Mock file upload to S3
        mock_upload.return_value = ("uploads/test-uuid.wav", 20000)
        
        # Create multipart payload
        file_content = b"fake audio data"
        files = {
            'file': ('test.wav', io.BytesIO(file_content), 'audio/wav')
        }
        data = {
            'loop_in': json.dumps({"name": "Loop from File"})
        }
        
        response = client.post("/api/v1/loops/with-file", files=files, data=data)
        
        assert response.status_code == 201
        result = response.json()
        assert result["name"] == "Loop from File"
        assert result["file_key"] == "uploads/test-uuid.wav"
        mock_upload.assert_called_once()

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_create_loop_with_file_full_metadata(self, mock_upload, client):
        """Test creating a loop with full metadata."""
        mock_upload.return_value = ("uploads/full-uuid.wav", 40000)
        
        file_content = b"fake audio content"
        files = {
            'file': ('full.wav', io.BytesIO(file_content), 'audio/wav')
        }
        data = {
            'loop_in': json.dumps({
                "name": "Full Loop",
                "bpm": 140,
                "bars": 16,
                "genre": "Trap",
                "duration_seconds": 8.0
            })
        }
        
        response = client.post("/api/v1/loops/with-file", files=files, data=data)
        
        assert response.status_code == 201
        result = response.json()
        assert result["name"] == "Full Loop"
        assert result["bpm"] == 140
        assert result["bars"] == 16

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_create_loop_with_invalid_json(self, mock_upload, client):
        """Test creating a loop with invalid JSON metadata."""
        file_content = b"fake audio"
        files = {
            'file': ('test.wav', io.BytesIO(file_content), 'audio/wav')
        }
        data = {
            'loop_in': 'invalid json {{'
        }
        
        response = client.post("/api/v1/loops/with-file", files=files, data=data)
        
        assert response.status_code == 422  # Validation error

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_create_loop_with_missing_file(self, mock_upload, client):
        """Test creating a loop without a file."""
        data = {
            'loop_in': json.dumps({"name": "No File Loop"})
        }
        
        response = client.post("/api/v1/loops/with-file", data=data)
        
        # Should fail without file
        assert response.status_code in [400, 422]

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_create_loop_with_file_storage_error(self, mock_upload, client):
        """Test handling S3 upload errors."""
        mock_upload.side_effect = Exception("S3 upload failed")
        
        file_content = b"fake audio"
        files = {
            'file': ('test.wav', io.BytesIO(file_content), 'audio/wav')
        }
        data = {
            'loop_in': json.dumps({"name": "Upload Fail Loop"})
        }
        
        response = client.post("/api/v1/loops/with-file", files=files, data=data)
        
        assert response.status_code == 500


# ── Test POST /api/v1/loops/upload (Legacy Upload) ────────────────────────────

class TestLoopUpload:
    """Tests for POST /api/v1/loops/upload endpoint (legacy)."""

    @patch('app.services.loop_service.loop_service.upload_loop_file')
    def test_upload_loop_file(self, mock_upload, client):
        """Test uploading a loop file without metadata."""
        mock_upload.return_value = ("uploads/simple-uuid.wav", 15000)
        
        file_content = b"fake audio"
        files = {
            'file': ('simple.wav', io.BytesIO(file_content), 'audio/wav')
        }
        
        response = client.post("/api/v1/loops/upload", files=files)
        
        assert response.status_code == 201
        result = response.json()
        assert "loop_id" in result
        assert "play_url" in result
        assert "download_url" in result
        mock_upload.assert_called_once()


# ── Test Integration: Create → Read → Update → Delete ──────────────────────────

class TestLoopIntegration:
    """Integration tests for the complete loop CRUD lifecycle."""

    def test_full_loop_lifecycle(self, client):
        """Test complete lifecycle: create, read, update, delete."""
        # 1. Create
        create_data = {
            "name": "Lifecycle Loop",
            "bpm": 140,
            "bars": 16,
            "genre": "Trap"
        }
        response = client.post("/api/v1/loops", json=create_data)
        assert response.status_code == 201
        loop_id = response.json()["id"]
        
        # 2. Read
        response = client.get(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 200
        assert response.json()["name"] == "Lifecycle Loop"
        
        # 3. Update
        update_data = {"bpm": 160, "genre": "House"}
        response = client.put(f"/api/v1/loops/{loop_id}", json=update_data)
        assert response.status_code == 200
        assert response.json()["bpm"] == 160
        
        # 4. Verify update persisted
        response = client.get(f"/api/v1/loops/{loop_id}")
        assert response.json()["bpm"] == 160
        
        # 5. Delete
        response = client.delete(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 200
        
        # 6. Verify deletion
        response = client.get(f"/api/v1/loops/{loop_id}")
        assert response.status_code == 404

    def test_list_after_multiple_creates(self, client):
        """Test listing after creating multiple loops."""
        # Create 3 loops
        for i in range(3):
            client.post("/api/v1/loops", json={"name": f"Loop {i}"})
        
        # List and verify
        response = client.get("/api/v1/loops")
        assert response.status_code == 200
        loops = response.json()
        assert len(loops) == 3
        
        # Verify names
        names = {loop["name"] for loop in loops}
        assert "Loop 0" in names
        assert "Loop 1" in names
        assert "Loop 2" in names


# ── Test Response Schemas ─────────────────────────────────────────────────────

class TestLoopResponseSchema:
    """Tests for response schema validation."""

    def test_response_includes_bars_field(self, client, test_loop):
        """Test that loop response includes the bars field."""
        response = client.get(f"/api/v1/loops/{test_loop.id}")
        
        assert response.status_code == 200
        data = response.json()
        assert "bars" in data
        assert data["bars"] == 16

    def test_response_datetime_format(self, client, test_loop):
        """Test that created_at is properly formatted."""
        response = client.get(f"/api/v1/loops/{test_loop.id}")
        
        assert response.status_code == 200
        data = response.json()
        # Should be ISO format string
        assert isinstance(data["created_at"], str)
        assert "T" in data["created_at"]  # ISO format indicator

    def test_nullable_fields_in_response(self, client):
        """Test that nullable fields are handled properly."""
        # Create loop with minimal fields
        response = client.post("/api/v1/loops", json={"name": "Minimal"})
        assert response.status_code == 201
        data = response.json()
        
        # Nullable fields should be None or omitted
        assert data.get("file_key") in [None, ""]
        assert data.get("bpm") in [None, ""]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
