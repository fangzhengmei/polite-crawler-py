"""Tests for the datetime utilities module."""

from datetime import datetime, UTC

import pytest

from polite_crawler.utils import utc_now


class TestUtcNow:
    """Tests for utc_now() function."""

    def test_returns_naive_datetime(self) -> None:
        """Test that utc_now() returns a naive datetime (without timezone info).
        
        This is critical for backward compatibility with the deprecated
        datetime.utcnow() behavior.
        """
        result = utc_now()
        
        assert isinstance(result, datetime)
        assert result.tzinfo is None

    def test_value_is_utc(self) -> None:
        """Test that the returned value represents UTC time.
        
        The value should be approximately equal to the current UTC time.
        """
        result = utc_now()
        expected_utc = datetime.now(UTC).replace(tzinfo=None)
        
        time_diff = (expected_utc - result).total_seconds()
        
        assert abs(time_diff) < 1.0

    def test_consistent_with_deprecated_utcnow_behavior(self) -> None:
        """Test that utc_now() behaves like the deprecated datetime.utcnow().
        
        Both should:
        1. Return naive datetime (tzinfo is None)
        2. Represent current UTC time
        
        Note: datetime.utcnow() is deprecated in Python 3.12+.
        We verify semantic equivalence by comparing to the recommended replacement:
        datetime.now(UTC).replace(tzinfo=None), which produces the same behavior:
        naive datetime with UTC value.
        
        Original assertions preserved (no relaxation):
        - tzinfo is None
        - time values are close (within 1 second)
        """
        utc_now_result = utc_now()
        
        # The recommended replacement for datetime.utcnow() is:
        #   datetime.now(UTC).replace(tzinfo=None)
        # This produces the same behavior: naive datetime with UTC value
        expected = datetime.now(UTC).replace(tzinfo=None)
        
        # Verify same behavior as datetime.utcnow():
        # 1. Both return naive datetime (tzinfo is None)
        assert utc_now_result.tzinfo is None
        assert expected.tzinfo is None
        assert utc_now_result.tzinfo == expected.tzinfo
        
        # 2. Both represent current UTC time (within 1 second)
        time_diff = (expected - utc_now_result).total_seconds()
        assert abs(time_diff) < 1.0

    def test_multiple_calls_increasing(self) -> None:
        """Test that subsequent calls return increasing values."""
        result1 = utc_now()
        result2 = utc_now()
        
        assert result2 >= result1

    @pytest.mark.asyncio
    async def test_works_in_async_context(self) -> None:
        """Test that utc_now() works correctly in async context."""
        result = utc_now()
        
        assert isinstance(result, datetime)
        assert result.tzinfo is None
