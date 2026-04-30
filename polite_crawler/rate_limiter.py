"""Rate limiter implementation using token bucket algorithm."""

import asyncio
import time
from collections import defaultdict
from typing import Optional


class RateLimiter:
    """A thread-safe async rate limiter using token bucket algorithm.

    Supports global rate limiting and per-domain rate limiting.
    """

    def __init__(
        self,
        rate: float = 10.0,
        burst: int = 10,
        per_domain: bool = False,
    ):
        """Initialize the rate limiter.

        Args:
            rate: Number of requests per second allowed globally.
            burst: Maximum burst size (initial token count).
            per_domain: If True, rate limit per domain instead of globally.
        """
        self._global_rate = rate
        self._burst = burst
        self._per_domain = per_domain
        
        self._global_tokens: float = float(burst)
        self._global_last_update: float = time.time()
        
        self._domain_tokens: dict[str, float] = {}
        self._domain_last_update: dict[str, float] = {}
        self._domain_rates: dict[str, float] = {}
        
        self._lock: asyncio.Lock = asyncio.Lock()

    def set_domain_rate(self, domain: str, rate: float) -> None:
        """Set a specific rate limit for a domain.

        Args:
            domain: The domain (e.g., "example.com").
            rate: Requests per second for this domain.
        """
        self._domain_rates[domain] = rate
        if domain not in self._domain_tokens:
            self._domain_tokens[domain] = float(self._burst)
            self._domain_last_update[domain] = time.time()

    def _update_global_tokens(self) -> None:
        """Update global token count based on elapsed time."""
        now = time.time()
        elapsed = now - self._global_last_update
        self._global_tokens = min(
            self._burst,
            self._global_tokens + elapsed * self._global_rate
        )
        self._global_last_update = now

    def _update_domain_tokens(self, domain: str) -> None:
        """Update domain-specific token count.

        Args:
            domain: The domain to update.
        """
        now = time.time()
        rate = self._domain_rates.get(domain, self._global_rate)
        
        if domain not in self._domain_tokens:
            self._domain_tokens[domain] = float(self._burst)
            self._domain_last_update[domain] = now
        
        elapsed = now - self._domain_last_update[domain]
        self._domain_tokens[domain] = min(
            self._burst,
            self._domain_tokens[domain] + elapsed * rate
        )
        self._domain_last_update[domain] = now

    async def acquire(self, domain: Optional[str] = None) -> None:
        """Acquire a token, waiting if necessary.

        Args:
            domain: Optional domain for per-domain rate limiting.
        """
        async with self._lock:
            while True:
                if self._per_domain and domain:
                    self._update_domain_tokens(domain)
                    if self._domain_tokens[domain] >= 1:
                        self._domain_tokens[domain] -= 1
                        return
                    rate = self._domain_rates.get(domain, self._global_rate)
                    wait_time = 1.0 / rate
                else:
                    self._update_global_tokens()
                    if self._global_tokens >= 1:
                        self._global_tokens -= 1
                        return
                    wait_time = 1.0 / self._global_rate
                
                await asyncio.sleep(wait_time)

    async def acquire_batch(self, count: int, domain: Optional[str] = None) -> None:
        """Acquire multiple tokens.

        Args:
            count: Number of tokens to acquire.
            domain: Optional domain for per-domain rate limiting.
        """
        for _ in range(count):
            await self.acquire(domain)

    def available_tokens(self, domain: Optional[str] = None) -> float:
        """Get the number of available tokens without acquiring.

        Args:
            domain: Optional domain for per-domain check.

        Returns:
            Number of available tokens.
        """
        self._update_global_tokens()
        global_available = self._global_tokens
        
        if self._per_domain and domain:
            self._update_domain_tokens(domain)
            return self._domain_tokens.get(domain, float(self._burst))
        
        return global_available
