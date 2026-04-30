"""Concurrent crawler engine with rate limiting and retry."""

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Callable, Optional, List
from urllib.parse import urlparse

import aiohttp

from polite_crawler.database import Database
from polite_crawler.rate_limiter import RateLimiter
from polite_crawler.retry import RetryConfig, with_retry

logger = logging.getLogger(__name__)


@dataclass
class CrawlResult:
    """Result of a single URL crawl."""

    url: str
    success: bool
    status_code: Optional[int] = None
    content: Optional[str] = None
    content_type: Optional[str] = None
    error: Optional[str] = None


@dataclass
class CrawlerConfig:
    """Configuration for the crawler."""

    max_concurrency: int = 10
    rate_limit: float = 10.0
    rate_burst: int = 10
    per_domain_rate_limit: bool = False
    request_timeout: float = 30.0
    max_attempts: int = 3
    retry_wait_min: float = 1.0
    retry_wait_max: float = 30.0
    user_agent: str = "PoliteCrawler/0.1.0"
    follow_redirects: bool = True


def extract_domain(url: str) -> str:
    """Extract the domain from a URL.

    Args:
        url: The URL to extract domain from.

    Returns:
        The domain (netloc) part of the URL.
    """
    if not url.startswith(("http://", "https://")):
        url = "http://" + url
    
    parsed = urlparse(url)
    return parsed.netloc or "unknown"


class Crawler:
    """Concurrent web crawler with rate limiting and retry.

    Features:
    - Concurrent crawling using asyncio
    - Global rate limiting
    - Optional per-domain rate limiting
    - Automatic retry on failure
    - URL persistence with SQLAlchemy
    """

    def __init__(
        self,
        config: Optional[CrawlerConfig] = None,
        database: Optional[Database] = None,
        session: Optional[aiohttp.ClientSession] = None,
    ):
        """Initialize the crawler.

        Args:
            config: Crawler configuration.
            database: Database for URL persistence. If None, uses in-memory DB.
            session: Optional aiohttp session for requests.
        """
        self._config = config or CrawlerConfig()
        self._db = database or Database()
        self._external_session = session
        
        self._rate_limiter = RateLimiter(
            rate=self._config.rate_limit,
            burst=self._config.rate_burst,
            per_domain=self._config.per_domain_rate_limit,
        )
        
        self._retry_config = RetryConfig(
            max_attempts=self._config.max_attempts,
            wait_min=self._config.retry_wait_min,
            wait_max=self._config.retry_wait_max,
        )
        
        self._semaphore: Optional[asyncio.Semaphore] = None
        self._session: Optional[aiohttp.ClientSession] = None
        self._is_running = False

    async def init(self) -> None:
        """Initialize the crawler and database."""
        await self._db.init_db()
        
        if self._semaphore is None:
            self._semaphore = asyncio.Semaphore(self._config.max_concurrency)

    def _get_session(self) -> aiohttp.ClientSession:
        """Get or create an aiohttp session.

        Returns:
            An aiohttp ClientSession.
        """
        if self._external_session:
            return self._external_session
        
        if self._session is None:
            timeout = aiohttp.ClientTimeout(total=self._config.request_timeout)
            headers = {"User-Agent": self._config.user_agent}
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers=headers,
            )
        
        return self._session

    async def _fetch_url(
        self,
        url: str,
    ) -> CrawlResult:
        """Fetch a single URL with rate limiting and retry.

        Args:
            url: The URL to fetch.

        Returns:
            A CrawlResult object.
        """
        domain = extract_domain(url)
        
        try:
            await self._rate_limiter.acquire(domain if self._config.per_domain_rate_limit else None)
            
            async with self._semaphore:
                session = self._get_session()
                
                async def make_request() -> aiohttp.ClientResponse:
                    return await session.get(
                        url,
                        allow_redirects=self._config.follow_redirects,
                    )
                
                response = await with_retry(
                    make_request,
                    retry_config=self._retry_config,
                )
                
                content = None
                content_type = None
                
                try:
                    content = await response.text()
                    content_type = response.headers.get("Content-Type")
                except Exception as e:
                    logger.warning(f"Failed to read response content for {url}: {e}")
                
                return CrawlResult(
                    url=url,
                    success=True,
                    status_code=response.status,
                    content=content,
                    content_type=content_type,
                )
                
        except Exception as e:
            logger.error(f"Error fetching {url}: {e}")
            return CrawlResult(
                url=url,
                success=False,
                error=str(e),
            )

    async def crawl_url(
        self,
        url: str,
        max_retries: int = 3,
    ) -> CrawlResult:
        """Crawl a single URL and persist the result.

        Args:
            url: The URL to crawl.
            max_retries: Maximum number of retries.

        Returns:
            A CrawlResult object.
        """
        await self.init()
        
        record = await self._db.add_url(url, max_retries=max_retries)
        
        if record.status == "completed" and record.is_success:
            return CrawlResult(
                url=url,
                success=True,
                status_code=record.response_status,
                content=record.content,
                content_type=record.content_type,
            )
        
        if record.status == "failed":
            return CrawlResult(
                url=url,
                success=False,
                status_code=record.response_status,
                error=record.last_error,
            )
        
        await self._db.mark_started(url)
        
        result = await self._fetch_url(url)
        
        if result.success:
            await self._db.mark_completed(
                url=url,
                response_status=result.status_code,
                content_type=result.content_type,
                content_length=len(result.content) if result.content else 0,
                content=result.content,
            )
        else:
            await self._db.mark_failed(
                url=url,
                error=result.error or "Unknown error",
                response_status=result.status_code,
            )
        
        return result

    async def crawl_urls(
        self,
        urls: List[str],
        max_retries: int = 3,
        on_progress: Optional[Callable[[str, CrawlResult], None]] = None,
    ) -> List[CrawlResult]:
        """Crawl multiple URLs concurrently.

        Args:
            urls: List of URLs to crawl.
            max_retries: Maximum number of retries per URL.
            on_progress: Optional callback called after each URL completes.

        Returns:
            List of CrawlResult objects in the same order as input URLs.
        """
        await self.init()
        self._is_running = True
        
        tasks = []
        url_task_map = {}
        
        for url in urls:
            task = asyncio.create_task(self.crawl_url(url, max_retries))
            tasks.append(task)
            url_task_map[id(task)] = url
        
        results = []
        completed_tasks = []
        
        for task in asyncio.as_completed(tasks):
            try:
                result = await task
                results.append(result)
                completed_tasks.append(task)
                
                if on_progress:
                    on_progress(url_task_map.get(id(task), ""), result)
            except Exception as e:
                url = url_task_map.get(id(task), "")
                results.append(CrawlResult(url=url, success=False, error=str(e)))
        
        self._is_running = False
        return results

    async def get_stats(self) -> dict:
        """Get crawler statistics.

        Returns:
            Dictionary of statistics.
        """
        db_stats = await self._db.get_stats()
        
        return {
            **db_stats,
            "config": {
                "max_concurrency": self._config.max_concurrency,
                "rate_limit": self._config.rate_limit,
                "per_domain_rate_limit": self._config.per_domain_rate_limit,
            },
        }

    async def close(self) -> None:
        """Close the crawler and cleanup resources."""
        if self._session and not self._external_session:
            await self._session.close()
            self._session = None
        
        if self._db:
            await self._db.close()
        
        self._is_running = False
