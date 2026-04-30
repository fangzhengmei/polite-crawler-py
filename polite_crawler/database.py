"""Database configuration and session management."""

import hashlib
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, List, Optional

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from polite_crawler.models import Base, CrawledURL


def url_hash(url: str) -> str:
    """Generate a SHA-256 hash of the URL."""
    return hashlib.sha256(url.encode("utf-8")).hexdigest()


class Database:
    """Async database manager for the crawler."""

    def __init__(self, database_url: str = "sqlite+aiosqlite:///:memory:"):
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            echo=False,
            connect_args={"check_same_thread": False} if "sqlite" in database_url else {},
        )
        self.async_session = async_sessionmaker(
            self.engine,
            class_=AsyncSession,
            expire_on_commit=False,
        )

    async def init_db(self) -> None:
        """Initialize database tables."""
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """Get an async session context."""
        async with self.async_session() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    async def add_url(
        self,
        url: str,
        max_retries: int = 3,
    ) -> CrawledURL:
        """Add a URL to the queue if it doesn't exist."""
        url_hash_hex = url_hash(url)
        
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url_hash == url_hash_hex)
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                return existing
            
            new_url = CrawledURL(
                url=url,
                url_hash=url_hash_hex,
                max_retries=max_retries,
                status="pending",
            )
            session.add(new_url)
        
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url_hash == url_hash_hex)
            )
            return result.scalar_one()

    async def add_urls(
        self,
        urls: List[str],
        max_retries: int = 3,
    ) -> List[CrawledURL]:
        """Add multiple URLs to the queue."""
        results = []
        for url in urls:
            crawled_url = await self.add_url(url, max_retries)
            results.append(crawled_url)
        return results

    async def get_url(self, url: str) -> Optional[CrawledURL]:
        """Get a URL record by URL."""
        url_hash_hex = url_hash(url)
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url_hash == url_hash_hex)
            )
            return result.scalar_one_or_none()

    async def get_pending_urls(self, limit: int = 100) -> List[CrawledURL]:
        """Get pending URLs that need to be crawled."""
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL)
                .where(CrawledURL.status == "pending")
                .order_by(CrawledURL.created_at)
                .limit(limit)
            )
            return list(result.scalars().all())

    async def mark_started(self, url: str) -> Optional[CrawledURL]:
        """Mark a URL as started crawling."""
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url == url)
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = "in_progress"
                record.started_at = datetime.utcnow()
                session.add(record)
        
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url == url)
            )
            return result.scalar_one_or_none()

    async def mark_completed(
        self,
        url: str,
        response_status: int,
        content_type: Optional[str] = None,
        content_length: Optional[int] = None,
        content: Optional[str] = None,
    ) -> Optional[CrawledURL]:
        """Mark a URL as successfully crawled."""
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url == url)
            )
            record = result.scalar_one_or_none()
            if record:
                record.status = "completed"
                record.is_success = True
                record.response_status = response_status
                record.content_type = content_type
                record.content_length = content_length
                record.content = content
                record.completed_at = datetime.utcnow()
                session.add(record)
        
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url == url)
            )
            return result.scalar_one_or_none()

    async def mark_failed(
        self,
        url: str,
        error: str,
        response_status: Optional[int] = None,
    ) -> Optional[CrawledURL]:
        """Mark a URL as failed, checking if it should be retried."""
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url == url)
            )
            record = result.scalar_one_or_none()
            if record:
                record.retry_count += 1
                record.last_error = error
                record.response_status = response_status
                
                if record.retry_count > record.max_retries:
                    record.status = "failed"
                    record.is_success = False
                    record.completed_at = datetime.utcnow()
                else:
                    record.status = "pending"
                session.add(record)
        
        async with self.session() as session:
            result = await session.execute(
                select(CrawledURL).where(CrawledURL.url == url)
            )
            return result.scalar_one_or_none()

    async def get_stats(self) -> dict:
        """Get crawling statistics."""
        async with self.session() as session:
            total_result = await session.execute(
                select(CrawledURL)
            )
            total = len(total_result.scalars().all())
            
            pending_result = await session.execute(
                select(CrawledURL).where(CrawledURL.status == "pending")
            )
            pending = len(pending_result.scalars().all())
            
            success_result = await session.execute(
                select(CrawledURL).where(CrawledURL.is_success == True)
            )
            success = len(success_result.scalars().all())
            
            failed_result = await session.execute(
                select(CrawledURL).where(CrawledURL.status == "failed")
            )
            failed = len(failed_result.scalars().all())

        return {
            "total": total,
            "pending": pending,
            "success": success,
            "failed": failed,
            "in_progress": total - pending - success - failed,
        }

    async def close(self) -> None:
        """Close the database engine."""
        await self.engine.dispose()
