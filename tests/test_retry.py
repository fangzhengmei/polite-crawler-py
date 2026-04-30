"""Tests for the retry module."""

import asyncio
from typing import Any, List
from unittest.mock import MagicMock, patch

import aiohttp
import pytest

from polite_crawler.retry import (
    RETRYABLE_EXCEPTIONS,
    RETRYABLE_STATUS_CODES,
    RetryConfig,
    is_retryable_response,
    with_retry,
)


class TestIsRetryableResponse:
    """Tests for is_retryable_response function."""

    def test_retryable_status_code(self) -> None:
        """Test that retryable status codes return True."""
        for code in RETRYABLE_STATUS_CODES:
            mock_response = MagicMock()
            mock_response.status = code
            
            assert is_retryable_response(mock_response) is True

    def test_non_retryable_status_code(self) -> None:
        """Test that non-retryable status codes return False."""
        mock_response = MagicMock()
        mock_response.status = 200
        
        assert is_retryable_response(mock_response) is False
        
        mock_response.status = 404
        assert is_retryable_response(mock_response) is False

    def test_no_status_attribute(self) -> None:
        """Test that objects without status attribute return False."""
        assert is_retryable_response("not a response") is False
        assert is_retryable_response(None) is False


class TestRetryConfig:
    """Tests for RetryConfig class."""

    def test_default_config(self) -> None:
        """Test default configuration."""
        config = RetryConfig()
        
        assert config.max_attempts == 3
        assert config.wait_min == 1.0
        assert config.wait_max == 30.0
        assert config.wait_multiplier == 2.0
        assert config.retryable_exceptions == RETRYABLE_EXCEPTIONS
        assert config.retryable_status_codes == RETRYABLE_STATUS_CODES

    def test_custom_config(self) -> None:
        """Test custom configuration."""
        config = RetryConfig(
            max_attempts=5,
            wait_min=0.5,
            wait_max=10.0,
            wait_multiplier=1.5,
        )
        
        assert config.max_attempts == 5
        assert config.wait_min == 0.5
        assert config.wait_max == 10.0
        assert config.wait_multiplier == 1.5


class TestWithRetry:
    """Tests for with_retry function."""

    @pytest.mark.asyncio
    async def test_success_no_retries(self) -> None:
        """Test that successful function doesn't retry."""
        call_count = 0
        
        async def success_func() -> str:
            nonlocal call_count
            call_count += 1
            return "success"
        
        config = RetryConfig(max_attempts=3, wait_min=0.01)
        
        result = await with_retry(success_func, retry_config=config)
        
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_exception(self) -> None:
        """Test that function retries on retryable exception."""
        call_count = 0
        
        async def failing_func() -> str:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Connection failed")
            return "success"
        
        config = RetryConfig(max_attempts=3, wait_min=0.01)
        
        result = await with_retry(failing_func, retry_config=config)
        
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self) -> None:
        """Test that exception is raised after max retries."""
        call_count = 0
        
        async def always_fails() -> str:
            nonlocal call_count
            call_count += 1
            raise ConnectionError("Always fails")
        
        config = RetryConfig(max_attempts=3, wait_min=0.01)
        
        with pytest.raises(ConnectionError):
            await with_retry(always_fails, retry_config=config)
        
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_no_retry_on_non_retryable_exception(self) -> None:
        """Test that non-retryable exceptions are not retried."""
        call_count = 0
        
        async def raises_value_error() -> str:
            nonlocal call_count
            call_count += 1
            raise ValueError("Non-retryable error")
        
        config = RetryConfig(max_attempts=3, wait_min=0.01)
        
        with pytest.raises(ValueError):
            await with_retry(raises_value_error, retry_config=config)
        
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_retryable_status(self) -> None:
        """Test that function retries on retryable status code."""
        call_count = 0
        
        async def returns_503() -> MagicMock:
            nonlocal call_count
            call_count += 1
            mock_response = MagicMock()
            if call_count < 3:
                mock_response.status = 503
            else:
                mock_response.status = 200
            return mock_response
        
        config = RetryConfig(max_attempts=3, wait_min=0.01)
        
        result = await with_retry(returns_503, retry_config=config)
        
        assert result.status == 200
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_with_args_and_kwargs(self) -> None:
        """Test that with_retry passes args and kwargs."""
        captured_args: tuple = ()
        captured_kwargs: dict = {}
        
        async def func(*args: Any, **kwargs: Any) -> tuple:
            nonlocal captured_args, captured_kwargs
            captured_args = args
            captured_kwargs = kwargs
            return args, kwargs
        
        config = RetryConfig(wait_min=0.01)
        
        result = await with_retry(
            func,
            "arg1",
            "arg2",
            retry_config=config,
            key1="value1",
            key2="value2",
        )
        
        assert captured_args == ("arg1", "arg2")
        assert captured_kwargs == {"key1": "value1", "key2": "value2"}
