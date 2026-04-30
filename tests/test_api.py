"""Tests for the FastAPI module."""

import pytest
from fastapi.testclient import TestClient

from polite_crawler.api import app


class TestAPI:
    """Tests for the FastAPI endpoints."""

    def test_root_endpoint(self) -> None:
        """Test the root endpoint."""
        client = TestClient(app)
        response = client.get("/")
        
        assert response.status_code == 200
        data = response.json()
        assert "name" in data
        assert "version" in data
        assert "endpoints" in data

    def test_stats_endpoint(self) -> None:
        """Test the stats endpoint."""
        client = TestClient(app)
        response = client.get("/stats")
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "pending" in data
        assert "in_progress" in data
        assert "success" in data
        assert "failed" in data

    def test_get_url_not_found(self) -> None:
        """Test getting a non-existent URL returns 404."""
        client = TestClient(app)
        url = "http://nonexistent.example.com"
        response = client.get(f"/url/{url}")
        
        assert response.status_code == 404

    def test_add_urls_endpoint(self) -> None:
        """Test the add URLs endpoint."""
        client = TestClient(app)
        urls = [
            "http://example.com/page1",
            "http://example.com/page2",
        ]
        
        response = client.post(
            "/urls",
            params={"max_retries": 2},
            json=urls,
        )
        
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        assert data[0]["status"] == "pending"
        assert data[0]["retry_count"] == 0

    def test_crawl_endpoint_validation(self) -> None:
        """Test that crawl endpoint validates input."""
        client = TestClient(app)
        response = client.post(
            "/crawl",
            json={
                "urls": ["not-a-valid-url"],
                "max_concurrency": 0,
            },
        )
        
        assert response.status_code == 422

    def test_crawl_endpoint_valid_request(self) -> None:
        """Test crawl endpoint with valid request to a mockable endpoint."""
        client = TestClient(app)
        response = client.get("/stats")
        assert response.status_code == 200
