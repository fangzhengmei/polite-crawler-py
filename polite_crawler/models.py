"""Database models for URL persistence."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, String, Text, Integer, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base class for all models."""
    pass


class CrawledURL(Base):
    """Model for storing crawled URLs and their metadata."""

    __tablename__ = "crawled_urls"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    url: Mapped[str] = mapped_column(String(2048), unique=True, nullable=False, index=True)
    url_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    
    status: Mapped[str] = mapped_column(String(20), default="pending", index=True)
    
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    content_length: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, default=3)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    started_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    
    is_success: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    def __repr__(self) -> str:
        return f"<CrawledURL(url={self.url!r}, status={self.status!r})>"
