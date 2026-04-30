"""Tests for the rate limiter module."""

import asyncio
import time

import pytest

from polite_crawler.rate_limiter import RateLimiter


class TestRateLimiter:
    """Tests for the RateLimiter class."""

    def test_available_tokens_initial(self) -> None:
        """Test that initial available tokens equals burst size."""
        limiter = RateLimiter(rate=10.0, burst=5)
        
        assert limiter.available_tokens() == 5.0

    @pytest.mark.asyncio
    async def test_acquire_consumes_token(self) -> None:
        """Test that acquire consumes a token."""
        limiter = RateLimiter(rate=10.0, burst=5)
        
        await limiter.acquire()
        
        assert limiter.available_tokens() == 4.0

    @pytest.mark.asyncio
    async def test_acquire_multiple(self) -> None:
        """Test that multiple acquires consume multiple tokens."""
        limiter = RateLimiter(rate=10.0, burst=5)
        
        await limiter.acquire()
        await limiter.acquire()
        await limiter.acquire()
        
        assert limiter.available_tokens() == 2.0

    @pytest.mark.asyncio
    async def test_acquire_batch(self) -> None:
        """Test acquire_batch."""
        limiter = RateLimiter(rate=10.0, burst=5)
        
        await limiter.acquire_batch(3)
        
        assert limiter.available_tokens() == 2.0

    @pytest.mark.asyncio
    async def test_tokens_refill_over_time(self) -> None:
        """Test that tokens refill over time."""
        rate = 10.0
        limiter = RateLimiter(rate=rate, burst=1)
        
        await limiter.acquire()
        assert limiter.available_tokens() < 1.0
        
        await asyncio.sleep(0.15)
        
        available = limiter.available_tokens()
        assert available > 0.0

    @pytest.mark.asyncio
    async def test_rate_limiting_blocks(self) -> None:
        """Test that rate limiting blocks when no tokens are available."""
        rate = 10.0
        limiter = RateLimiter(rate=rate, burst=1)
        
        await limiter.acquire()
        
        start_time = time.time()
        await limiter.acquire()
        elapsed = time.time() - start_time
        
        assert elapsed >= 0.08

    @pytest.mark.asyncio
    async def test_per_domain_rate_limiting(self) -> None:
        """Test per-domain rate limiting."""
        limiter = RateLimiter(rate=10.0, burst=2, per_domain=True)
        
        await limiter.acquire("example.com")
        await limiter.acquire("example.com")
        
        assert limiter.available_tokens("example.com") == 0.0
        assert limiter.available_tokens("other.com") == 2.0

    @pytest.mark.asyncio
    async def test_set_domain_rate(self) -> None:
        """Test setting specific rate for a domain."""
        limiter = RateLimiter(rate=10.0, burst=2, per_domain=True)
        
        limiter.set_domain_rate("example.com", 2.0)
        
        await limiter.acquire("example.com")
        await limiter.acquire("example.com")
        
        assert limiter.available_tokens("example.com") == 0.0
        
        start_time = time.time()
        await limiter.acquire("example.com")
        elapsed = time.time() - start_time
        
        assert elapsed >= 0.4
