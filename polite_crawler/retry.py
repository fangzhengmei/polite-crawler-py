"""Retry mechanism for HTTP requests using tenacity."""

import asyncio
import logging
from typing import Any, Callable, Optional, TypeVar

import aiohttp
from tenacity import (
    RetryCallState,
    retry_if_exception_type,
    retry_if_result,
    stop_after_attempt,
    wait_exponential,
    Retrying,
)
from tenacity import retry as tenacity_retry

logger = logging.getLogger(__name__)

T = TypeVar("T")

RETRYABLE_EXCEPTIONS = (
    aiohttp.ClientError,
    aiohttp.ServerDisconnectedError,
    aiohttp.ServerTimeoutError,
    asyncio.TimeoutError,
    ConnectionError,
    TimeoutError,
)

RETRYABLE_STATUS_CODES = {408, 429, 500, 502, 503, 504}


def is_retryable_response(response: Any) -> bool:
    """Check if a response should be retried based on status code.

    Args:
        response: The response object with a 'status' attribute.

    Returns:
        True if the response should be retried, False otherwise.
    """
    if hasattr(response, "status"):
        return response.status in RETRYABLE_STATUS_CODES
    return False


def before_sleep_log(retry_state: RetryCallState) -> None:
    """Log before each retry.

    Args:
        retry_state: The retry call state.
    """
    attempt = retry_state.attempt_number
    wait_time = retry_state.next_action.sleep if retry_state.next_action else 0
    
    if retry_state.outcome and retry_state.outcome.failed:
        exception = retry_state.outcome.exception()
        logger.warning(
            f"Attempt {attempt} failed with error: {exception}. "
            f"Retrying in {wait_time:.2f}s..."
        )
    else:
        logger.warning(
            f"Attempt {attempt} returned retryable response. "
            f"Retrying in {wait_time:.2f}s..."
        )


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(
        self,
        max_attempts: int = 3,
        wait_min: float = 1.0,
        wait_max: float = 30.0,
        wait_multiplier: float = 2.0,
        retryable_exceptions: tuple = RETRYABLE_EXCEPTIONS,
        retryable_status_codes: set[int] = RETRYABLE_STATUS_CODES,
    ):
        """Initialize retry configuration.

        Args:
            max_attempts: Maximum number of attempts (including the first).
            wait_min: Minimum wait time in seconds.
            wait_max: Maximum wait time in seconds.
            wait_multiplier: Multiplier for exponential backoff.
            retryable_exceptions: Tuple of exceptions to retry on.
            retryable_status_codes: Set of HTTP status codes to retry on.
        """
        self.max_attempts = max_attempts
        self.wait_min = wait_min
        self.wait_max = wait_max
        self.wait_multiplier = wait_multiplier
        self.retryable_exceptions = retryable_exceptions
        self.retryable_status_codes = retryable_status_codes


async def with_retry(
    func: Callable[..., Any],
    *args: Any,
    retry_config: Optional[RetryConfig] = None,
    **kwargs: Any,
) -> Any:
    """Execute an async function with retry logic.

    Args:
        func: The async function to execute.
        *args: Arguments to pass to the function.
        retry_config: Configuration for retry behavior.
        **kwargs: Keyword arguments to pass to the function.

    Returns:
        The result of the function if successful.

    Raises:
        The last exception encountered if all retries fail.
    """
    if retry_config is None:
        retry_config = RetryConfig()

    retry_strategy = (
        retry_if_exception_type(retry_config.retryable_exceptions)
        | retry_if_result(is_retryable_response)
    )
    
    wait_strategy = wait_exponential(
        multiplier=retry_config.wait_multiplier,
        min=retry_config.wait_min,
        max=retry_config.wait_max,
    )
    
    stop_strategy = stop_after_attempt(retry_config.max_attempts)

    @tenacity_retry(
        stop=stop_strategy,
        wait=wait_strategy,
        retry=retry_strategy,
        reraise=True,
    )
    async def retry_wrapper():
        return await func(*args, **kwargs)

    return await retry_wrapper()


class RetryableSession:
    """A wrapper around aiohttp session with built-in retry logic."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        retry_config: Optional[RetryConfig] = None,
    ):
        """Initialize the retryable session.

        Args:
            session: The aiohttp ClientSession to wrap.
            retry_config: Configuration for retry behavior.
        """
        self._session = session
        self._retry_config = retry_config or RetryConfig()

    async def get(
        self,
        url: str,
        retry_config: Optional[RetryConfig] = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Make a GET request with retry logic.

        Args:
            url: The URL to request.
            retry_config: Optional override for retry configuration.
            **kwargs: Additional arguments for aiohttp.get.

        Returns:
            The response object.
        """
        config = retry_config or self._retry_config
        return await with_retry(
            self._session.get,
            url,
            retry_config=config,
            **kwargs,
        )

    async def post(
        self,
        url: str,
        retry_config: Optional[RetryConfig] = None,
        **kwargs: Any,
    ) -> aiohttp.ClientResponse:
        """Make a POST request with retry logic.

        Args:
            url: The URL to request.
            retry_config: Optional override for retry configuration.
            **kwargs: Additional arguments for aiohttp.post.

        Returns:
            The response object.
        """
        config = retry_config or self._retry_config
        return await with_retry(
            self._session.post,
            url,
            retry_config=config,
            **kwargs,
        )

    def __getattr__(self, name: str) -> Any:
        """Delegate attribute access to the underlying session."""
        return getattr(self._session, name)
