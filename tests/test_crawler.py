"""Tests for the crawler module."""

import asyncio
from typing import List
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from polite_crawler.crawler import (
    Crawler,
    CrawlerConfig,
    CrawlResult,
    extract_domain,
)
from polite_crawler.database import Database


class TestExtractDomain:
    """Tests for extract_domain function."""

    def test_extract_domain_https(self) -> None:
        """Test extracting domain from HTTPS URL."""
        url = "https://example.com/path/to/page?query=1"
        domain = extract_domain(url)
        assert domain == "example.com"

    def test_extract_domain_http(self) -> None:
        """Test extracting domain from HTTP URL."""
        url = "http://sub.example.com:8080/page"
        domain = extract_domain(url)
        assert domain == "sub.example.com:8080"

    def test_extract_domain_no_scheme(self) -> None:
        """Test extracting domain from URL without scheme."""
        url = "example.com/path"
        domain = extract_domain(url)
        assert domain == "example.com"

    def test_extract_domain_invalid(self) -> None:
        """Test extracting domain from invalid URL."""
        url = ""
        domain = extract_domain(url)
        assert domain == "unknown"
        
        url2 = "not-a-url"
        domain2 = extract_domain(url2)
        assert domain2 == "not-a-url"


class TestCrawlerConfig:
    """Tests for CrawlerConfig class."""

    def test_default_config(self) -> None:
        """Test default configuration."""
        config = CrawlerConfig()
        
        assert config.max_concurrency == 10
        assert config.rate_limit == 10.0
        assert config.rate_burst == 10
        assert config.per_domain_rate_limit is False
        assert config.request_timeout == 30.0
        assert config.max_attempts == 3
        assert config.retry_wait_min == 1.0
        assert config.retry_wait_max == 30.0
        assert "PoliteCrawler" in config.user_agent

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = CrawlerConfig(
            max_concurrency=5,
            rate_limit=2.0,
            per_domain_rate_limit=True,
            max_attempts=5,
        )
        
        assert config.max_concurrency == 5
        assert config.rate_limit == 2.0
        assert config.per_domain_rate_limit is True
        assert config.max_attempts == 5


class TestCrawler:
    """Tests for the Crawler class."""

    @pytest.mark.asyncio
    async def test_init(self, in_memory_db: Database) -> None:
        """Test crawler initialization."""
        config = CrawlerConfig()
        crawler = Crawler(config=config, database=in_memory_db)
        
        await crawler.init()
        
        assert crawler._semaphore is not None
        
        await crawler.close()

    @pytest.mark.asyncio
    async def test_crawl_url_success(
        self,
        test_http_server: str,
        aiohttp_session: aiohttp.ClientSession,
        in_memory_db: Database,
    ) -> None:
        """Test crawling a URL successfully."""
        config = CrawlerConfig(max_concurrency=1, rate_limit=100.0)
        crawler = Crawler(
            config=config,
            database=in_memory_db,
            session=aiohttp_session,
        )
        
        await crawler.init()
        
        url = f"{test_http_server}/hello"
        result = await crawler.crawl_url(url, max_retries=1)
        
        assert result.success is True
        assert result.status_code == 200
        assert "Hello" in (result.content or "")
        
        record = await in_memory_db.get_url(url)
        assert record is not None
        assert record.is_success is True
        assert record.status == "completed"
        
        await crawler.close()

    @pytest.mark.asyncio
    async def test_crawl_url_failure(
        self,
        aiohttp_session: aiohttp.ClientSession,
        in_memory_db: Database,
    ) -> None:
        """Test crawling an invalid URL."""
        config = CrawlerConfig(max_concurrency=1, rate_limit=100.0, max_attempts=1)
        crawler = Crawler(
            config=config,
            database=in_memory_db,
            session=aiohttp_session,
        )
        
        await crawler.init()
        
        url = "http://nonexistent.domain.invalid/404"
        result = await crawler.crawl_url(url, max_retries=1)
        
        assert result.success is False
        assert result.error is not None
        
        await crawler.close()

    @pytest.mark.asyncio
    async def test_crawl_urls_concurrent(
        self,
        test_http_server: str,
        aiohttp_session: aiohttp.ClientSession,
        in_memory_db: Database,
    ) -> None:
        """Test crawling multiple URLs concurrently."""
        config = CrawlerConfig(max_concurrency=3, rate_limit=100.0)
        crawler = Crawler(
            config=config,
            database=in_memory_db,
            session=aiohttp_session,
        )
        
        await crawler.init()
        
        urls = [
            f"{test_http_server}/hello",
            f"{test_http_server}/json",
            f"{test_http_server}/status/200",
        ]
        
        results = await crawler.crawl_urls(urls, max_retries=1)
        
        assert len(results) == 3
        for result in results:
            assert result.success is True
        
        stats = await crawler.get_stats()
        assert stats["success"] == 3
        
        await crawler.close()

    @pytest.mark.asyncio
    async def test_crawl_urls_with_progress_callback(
        self,
        test_http_server: str,
        aiohttp_session: aiohttp.ClientSession,
        in_memory_db: Database,
    ) -> None:
        """Test crawling with progress callback."""
        config = CrawlerConfig(max_concurrency=2, rate_limit=100.0)
        crawler = Crawler(
            config=config,
            database=in_memory_db,
            session=aiohttp_session,
        )
        
        await crawler.init()
        
        urls = [
            f"{test_http_server}/hello",
            f"{test_http_server}/json",
        ]
        
        progress_received: List[tuple] = []
        
        def on_progress(url: str, result: CrawlResult) -> None:
            progress_received.append((url, result))
        
        await crawler.crawl_urls(urls, max_retries=1, on_progress=on_progress)
        
        assert len(progress_received) == 2
        
        await crawler.close()

    @pytest.mark.asyncio
    async def test_get_stats(
        self,
        test_http_server: str,
        aiohttp_session: aiohttp.ClientSession,
        in_memory_db: Database,
    ) -> None:
        """Test getting crawler stats."""
        config = CrawlerConfig(max_concurrency=1, rate_limit=100.0)
        crawler = Crawler(
            config=config,
            database=in_memory_db,
            session=aiohttp_session,
        )
        
        await crawler.init()
        
        url = f"{test_http_server}/hello"
        await crawler.crawl_url(url, max_retries=1)
        
        stats = await crawler.get_stats()
        
        assert stats["total"] == 1
        assert stats["success"] == 1
        assert "config" in stats
        
        await crawler.close()

    @pytest.mark.asyncio
    async def test_already_crawled_url_returns_from_db(
        self,
        test_http_server: str,
        aiohttp_session: aiohttp.ClientSession,
        in_memory_db: Database,
    ) -> None:
        """Test that already crawled URLs return from DB without re-fetching."""
        config = CrawlerConfig(max_concurrency=1, rate_limit=100.0)
        crawler = Crawler(
            config=config,
            database=in_memory_db,
            session=aiohttp_session,
        )
        
        await crawler.init()
        
        url = f"{test_http_server}/hello"
        
        result1 = await crawler.crawl_url(url, max_retries=1)
        assert result1.success is True
        
        record1 = await in_memory_db.get_url(url)
        assert record1 is not None
        assert record1.is_success is True
        
        result2 = await crawler.crawl_url(url, max_retries=1)
        assert result2.success is True
        
        await crawler.close()
