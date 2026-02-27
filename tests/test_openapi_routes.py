"""Test that all routes are properly registered and visible in OpenAPI schema."""

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """Create a TestClient for the FastAPI app."""
    # Import here to avoid issues if app hasn't started yet
    from app.main import app
    return TestClient(app)


def test_openapi_json_available(client):
    """Verify that /openapi.json endpoint is available."""
    response = client.get("/openapi.json")
    assert response.status_code == 200, "OpenAPI schema should be accessible"
    
    data = response.json()
    assert "openapi" in data, "Should have OpenAPI version"
    assert "paths" in data, "Should have paths defined"
    assert "info" in data, "Should have info section"


def test_openapi_has_expected_routes(client):
    """Verify that OpenAPI schema includes our main route groups."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    
    data = response.json()
    paths = data.get("paths", {})
    
    # Should have more than just the root endpoint
    assert len(paths) > 1, f"Expected multiple routes, got {len(paths)}: {list(paths.keys())}"
    
    # Expected path prefixes (at least one route from each group should exist)
    expected_prefixes = [
        "/api/v1/health",
        "/api/v1/loops",
        "/api/v1/arrangements",
    ]
    
    for prefix in expected_prefixes:
        matching_paths = [path for path in paths.keys() if path.startswith(prefix)]
        assert len(matching_paths) > 0, f"Expected at least one route starting with '{prefix}', found: {list(paths.keys())}"


def test_openapi_has_tags(client):
    """Verify that OpenAPI schema includes proper tags for route grouping."""
    response = client.get("/openapi.json")
    assert response.status_code == 200
    
    data = response.json()
    tags = data.get("tags", [])
    tag_names = [tag.get("name") for tag in tags] if tags else []
    
    # Extract tags from paths
    paths = data.get("paths", {})
    path_tags = set()
    for path_data in paths.values():
        for method_data in path_data.values():
            if isinstance(method_data, dict) and "tags" in method_data:
                path_tags.update(method_data["tags"])
    
    # Should have multiple tag groups
    expected_tags = ["health", "loops", "arrangements"]
    
    for expected_tag in expected_tags:
        assert expected_tag in path_tags, f"Expected tag '{expected_tag}' in routes, found tags: {path_tags}"


def test_root_endpoint_registered(client):
    """Verify that root endpoint works and returns expected structure."""
    response = client.get("/")
    assert response.status_code == 200
    
    data = response.json()
    assert data.get("status") == "ok", "Root endpoint should return status ok"
    assert "version" in data or "message" in data, "Root should include version or message"


def test_health_endpoint_registered(client):
    """Verify that /health endpoint is registered."""
    response = client.get("/health")
    assert response.status_code == 200
    
    data = response.json()
    assert data.get("ok") is True, "Health endpoint should return ok=true"
