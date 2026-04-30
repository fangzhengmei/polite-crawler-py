"""FastAPI interface for the polite crawler."""

import asyncio
from contextlib import asynccontextmanager
from typing import Any, Dict, List, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel, HttpUrl, Field

from polite_crawler.crawler import Crawler, CrawlerConfig, CrawlResult
from polite_crawler.database import Database


class CrawlRequest(BaseModel):
    """Request model for crawling URLs."""

    urls: List[HttpUrl] = Field(..., description="List of URLs to crawl")
    max_concurrency: int = Field(default=10, ge=1, le=100, description="Maximum concurrent requests")
    rate_limit: float = Field(default=10.0, gt=0, le=1000.0, description="Requests per second")
    max_retries: int = Field(default=3, ge=0, le=10, description="Maximum retries per URL")


class CrawlResultResponse(BaseModel):
    """Response model for a single crawl result."""

    url: str
    success: bool
    status_code: Optional[int] = None
    content_type: Optional[str] = None
    error: Optional[str] = None


class CrawlResponse(BaseModel):
    """Response model for a crawl request."""

    total: int
    success: int
    failed: int
    results: List[CrawlResultResponse]


class StatsResponse(BaseModel):
    """Response model for statistics."""

    total: int
    pending: int
    in_progress: int
    success: int
    failed: int


class URLRecordResponse(BaseModel):
    """Response model for a URL record."""

    url: str
    status: str
    is_success: bool
    response_status: Optional[int]
    content_type: Optional[str]
    retry_count: int
    max_retries: int
    last_error: Optional[str]
    created_at: Optional[datetime]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


_active_crawler: Optional[Crawler] = None


async def get_crawler() -> Crawler:
    """Get or create the global crawler instance.

    Returns:
        The crawler instance.
    """
    global _active_crawler
    
    if _active_crawler is None:
        db = Database("sqlite+aiosqlite:///crawler.db")
        config = CrawlerConfig()
        _active_crawler = Crawler(config=config, database=db)
        await _active_crawler.init()
    
    return _active_crawler


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan handler."""
    yield
    global _active_crawler
    if _active_crawler:
        await _active_crawler.close()
        _active_crawler = None


app = FastAPI(
    title="Polite Crawler API",
    description="A rate-limited web crawler API with concurrency and persistence",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/")
async def root() -> Dict[str, Any]:
    """Root endpoint."""
    return {
        "name": "Polite Crawler API",
        "version": "0.1.0",
        "endpoints": {
            "crawl": "POST /crawl",
            "stats": "GET /stats",
            "url/{url}": "GET /url/{url}",
        },
    }


@app.post("/crawl", response_model=CrawlResponse)
async def crawl_urls(request: CrawlRequest) -> CrawlResponse:
    """Crawl one or more URLs.

    Args:
        request: The crawl request with URLs and options.

    Returns:
        The crawl results.
    """
    crawler = await get_crawler()
    
    crawler._config.max_concurrency = request.max_concurrency
    crawler._config.rate_limit = request.rate_limit
    crawler._config.max_attempts = request.max_retries
    
    urls = [str(url) for url in request.urls]
    
    results = await crawler.crawl_urls(
        urls=urls,
        max_retries=request.max_retries,
    )
    
    response_results = [
        CrawlResultResponse(
            url=r.url,
            success=r.success,
            status_code=r.status_code,
            content_type=r.content_type,
            error=r.error,
        )
        for r in results
    ]
    
    success_count = sum(1 for r in results if r.success)
    
    return CrawlResponse(
        total=len(results),
        success=success_count,
        failed=len(results) - success_count,
        results=response_results,
    )


@app.get("/stats", response_model=StatsResponse)
async def get_stats() -> StatsResponse:
    """Get crawl statistics.

    Returns:
        The current statistics.
    """
    crawler = await get_crawler()
    stats = await crawler.get_stats()
    
    return StatsResponse(
        total=stats["total"],
        pending=stats["pending"],
        in_progress=stats["in_progress"],
        success=stats["success"],
        failed=stats["failed"],
    )


@app.get("/url/{url:path}", response_model=Optional[URLRecordResponse])
async def get_url_record(url: str) -> Optional[URLRecordResponse]:
    """Get a URL record by URL.

    Args:
        url: The URL to look up (URL-encoded).

    Returns:
        The URL record if found, otherwise None.
    """
    crawler = await get_crawler()
    record = await crawler._db.get_url(url)
    
    if record is None:
        raise HTTPException(status_code=404, detail="URL not found")
    
    return URLRecordResponse.model_validate(record)


@app.post("/urls", response_model=List[URLRecordResponse])
async def add_urls(urls: List[str], max_retries: int = 3) -> List[URLRecordResponse]:
    """Add URLs to the crawl queue without crawling them yet.

    Args:
        urls: List of URLs to add.
        max_retries: Maximum retries for each URL.

    Returns:
        The added URL records.
    """
    crawler = await get_crawler()
    
    records = await crawler._db.add_urls(urls, max_retries=max_retries)
    
    return [URLRecordResponse.model_validate(r) for r in records]


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("polite_crawler.api:app", host="0.0.0.0", port=8000, reload=True)
