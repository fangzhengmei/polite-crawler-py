"""Tests for the database module."""

import pytest

from polite_crawler.database import Database, url_hash
from polite_crawler.models import CrawledURL


class TestURLHash:
    """Tests for the url_hash function."""

    def test_url_hash_consistent(self) -> None:
        """Test that the same URL produces the same hash."""
        url = "https://example.com/page"
        hash1 = url_hash(url)
        hash2 = url_hash(url)
        
        assert hash1 == hash2
        assert isinstance(hash1, str)
        assert len(hash1) == 64

    def test_url_hash_different(self) -> None:
        """Test that different URLs produce different hashes."""
        url1 = "https://example.com/page1"
        url2 = "https://example.com/page2"
        
        hash1 = url_hash(url1)
        hash2 = url_hash(url2)
        
        assert hash1 != hash2


class TestDatabase:
    """Tests for the Database class."""

    @pytest.mark.asyncio
    async def test_init_db(self, in_memory_db: Database) -> None:
        """Test that database initialization works."""
        stats = await in_memory_db.get_stats()
        assert stats["total"] == 0

    @pytest.mark.asyncio
    async def test_add_url(self, in_memory_db: Database) -> None:
        """Test adding a URL."""
        url = "https://example.com"
        result = await in_memory_db.add_url(url)
        
        assert result.url == url
        assert result.status == "pending"
        assert result.retry_count == 0
        
        stats = await in_memory_db.get_stats()
        assert stats["total"] == 1
        assert stats["pending"] == 1

    @pytest.mark.asyncio
    async def test_add_url_duplicate(self, in_memory_db: Database) -> None:
        """Test adding a duplicate URL returns existing record."""
        url = "https://example.com"
        
        result1 = await in_memory_db.add_url(url)
        result2 = await in_memory_db.add_url(url)
        
        stats = await in_memory_db.get_stats()
        assert stats["total"] == 1

    @pytest.mark.asyncio
    async def test_add_urls(self, in_memory_db: Database) -> None:
        """Test adding multiple URLs."""
        urls = [
            "https://example.com/1",
            "https://example.com/2",
            "https://example.com/3",
        ]
        
        results = await in_memory_db.add_urls(urls)
        
        assert len(results) == 3
        
        stats = await in_memory_db.get_stats()
        assert stats["total"] == 3

    @pytest.mark.asyncio
    async def test_get_url(self, in_memory_db: Database) -> None:
        """Test getting a URL."""
        url = "https://example.com"
        await in_memory_db.add_url(url)
        
        result = await in_memory_db.get_url(url)
        
        assert result is not None
        assert result.url == url

    @pytest.mark.asyncio
    async def test_get_url_not_found(self, in_memory_db: Database) -> None:
        """Test getting a non-existent URL returns None."""
        result = await in_memory_db.get_url("https://nonexistent.com")
        
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pending_urls(self, in_memory_db: Database) -> None:
        """Test getting pending URLs."""
        urls = [
            "https://example.com/1",
            "https://example.com/2",
        ]
        await in_memory_db.add_urls(urls)
        
        pending = await in_memory_db.get_pending_urls()
        
        assert len(pending) == 2

    @pytest.mark.asyncio
    async def test_mark_started(self, in_memory_db: Database) -> None:
        """Test marking a URL as started."""
        url = "https://example.com"
        await in_memory_db.add_url(url)
        
        result = await in_memory_db.mark_started(url)
        
        assert result is not None
        assert result.status == "in_progress"
        assert result.started_at is not None

    @pytest.mark.asyncio
    async def test_mark_completed(self, in_memory_db: Database) -> None:
        """Test marking a URL as completed."""
        url = "https://example.com"
        await in_memory_db.add_url(url)
        
        result = await in_memory_db.mark_completed(
            url=url,
            response_status=200,
            content_type="text/html",
            content_length=100,
            content="<html></html>",
        )
        
        assert result is not None
        assert result.status == "completed"
        assert result.is_success is True
        assert result.response_status == 200
        assert result.completed_at is not None
        
        stats = await in_memory_db.get_stats()
        assert stats["success"] == 1

    @pytest.mark.asyncio
    async def test_mark_failed_no_retries_left(self, in_memory_db: Database) -> None:
        """Test marking a URL as failed when no retries are left."""
        url = "https://example.com"
        await in_memory_db.add_url(url, max_retries=1)
        
        await in_memory_db.mark_failed(url, "First error")
        
        record = await in_memory_db.get_url(url)
        assert record is not None
        assert record.status == "pending"
        assert record.retry_count == 1
        
        await in_memory_db.mark_failed(url, "Second error")
        
        record = await in_memory_db.get_url(url)
        assert record is not None
        assert record.status == "failed"
        assert record.is_success is False
        assert record.retry_count == 2
        
        stats = await in_memory_db.get_stats()
        assert stats["failed"] == 1

    @pytest.mark.asyncio
    async def test_get_stats(self, in_memory_db: Database) -> None:
        """Test getting statistics."""
        url1 = "https://example.com/1"
        url2 = "https://example.com/2"
        url3 = "https://example.com/3"
        
        await in_memory_db.add_url(url1)
        await in_memory_db.add_url(url2)
        await in_memory_db.add_url(url3)
        
        await in_memory_db.mark_completed(url1, 200)
        await in_memory_db.mark_started(url2)
        
        stats = await in_memory_db.get_stats()
        
        assert stats["total"] == 3
        assert stats["success"] == 1
        assert stats["pending"] == 1


class TestDatabaseTimestamps:
    """Tests for timestamp semantic consistency.
    
    These tests verify that all timestamps use naive datetime (without timezone info)
    while representing UTC time. This maintains backward compatibility with the
    original datetime.utcnow() implementation behavior.
    """

    @pytest.mark.asyncio
    async def test_created_at_is_naive_datetime(self, in_memory_db: Database) -> None:
        """Test that created_at is a naive datetime (without timezone info)."""
        url = "https://example.com"
        result = await in_memory_db.add_url(url)
        
        assert result.created_at is not None
        assert result.created_at.tzinfo is None

    @pytest.mark.asyncio
    async def test_started_at_is_naive_datetime(self, in_memory_db: Database) -> None:
        """Test that started_at is a naive datetime (without timezone info)."""
        url = "https://example.com"
        await in_memory_db.add_url(url)
        
        result = await in_memory_db.mark_started(url)
        
        assert result is not None
        assert result.started_at is not None
        assert result.started_at.tzinfo is None

    @pytest.mark.asyncio
    async def test_completed_at_is_naive_datetime_on_success(self, in_memory_db: Database) -> None:
        """Test that completed_at is a naive datetime on successful crawl."""
        url = "https://example.com"
        await in_memory_db.add_url(url)
        
        result = await in_memory_db.mark_completed(
            url=url,
            response_status=200,
        )
        
        assert result is not None
        assert result.completed_at is not None
        assert result.completed_at.tzinfo is None

    @pytest.mark.asyncio
    async def test_completed_at_is_naive_datetime_on_failure(self, in_memory_db: Database) -> None:
        """Test that completed_at is a naive datetime on failed crawl (no retries left)."""
        url = "https://example.com"
        await in_memory_db.add_url(url, max_retries=0)
        
        await in_memory_db.mark_failed(url, "Test error")
        
        record = await in_memory_db.get_url(url)
        
        assert record is not None
        assert record.completed_at is not None
        assert record.completed_at.tzinfo is None

    @pytest.mark.asyncio
    async def test_timestamps_are_utc_values(self, in_memory_db: Database) -> None:
        """Test that timestamps approximately match current UTC time.
        
        This verifies that while timestamps are naive (no tzinfo), their values
        represent UTC time, not local time.
        """
        from datetime import datetime, UTC
        
        url = "https://example.com"
        result = await in_memory_db.add_url(url)
        
        current_utc = datetime.now(UTC).replace(tzinfo=None)
        time_diff = (current_utc - result.created_at).total_seconds()
        
        assert abs(time_diff) < 5.0

    @pytest.mark.asyncio
    async def test_all_timestamp_fields_same_semantics(self, in_memory_db: Database) -> None:
        """Test that all timestamp fields follow the same naive-UTC semantics."""
        url = "https://example.com"
        await in_memory_db.add_url(url)
        
        await in_memory_db.mark_started(url)
        
        record = await in_memory_db.get_url(url)
        assert record is not None
        assert record.created_at.tzinfo is None
        assert record.started_at is not None
        assert record.started_at.tzinfo is None
        
        await in_memory_db.mark_completed(url, 200)
        
        record = await in_memory_db.get_url(url)
        assert record is not None
        assert record.completed_at is not None
        assert record.completed_at.tzinfo is None
