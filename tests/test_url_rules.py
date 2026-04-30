"""Tests for the URL rules module.

This test suite verifies:
1. Decision boundaries for all four scenarios
2. Consistent return semantics (URLRuleResult)
3. Proper message prioritization
4. Rule priority (highest to lowest)
"""

from datetime import timedelta
from typing import Optional
from unittest.mock import MagicMock

import pytest

from polite_crawler.models import CrawledURL
from polite_crawler.url_rules import (
    URLAction,
    URLRuleConfig,
    URLRuleEngine,
    URLRuleResult,
    URLScenario,
)
from polite_crawler.utils import utc_now


def create_mock_record(
    url: str,
    status: str,
    is_success: bool = False,
    started_at: Optional[str] = None,
    completed_at: Optional[str] = None,
    retry_count: int = 0,
    max_retries: int = 3,
) -> CrawledURL:
    """Create a mock CrawledURL record for testing.

    Args:
        url: The URL
        status: Status string ("pending", "in_progress", "completed", "failed")
        is_success: Whether the crawl was successful
        started_at: ISO string for started time (or "now" for current time)
        completed_at: ISO string for completed time (or "now" for current time)
        retry_count: Number of retries attempted
        max_retries: Maximum retries allowed

    Returns:
        Mock CrawledURL object
    """
    record = MagicMock(spec=CrawledURL)
    record.url = url
    record.status = status
    record.is_success = is_success
    record.retry_count = retry_count
    record.max_retries = max_retries
    
    now = utc_now()
    
    if started_at == "now":
        record.started_at = now
    elif started_at and isinstance(started_at, str):
        from datetime import datetime
        record.started_at = datetime.fromisoformat(started_at)
    else:
        record.started_at = started_at
    
    if completed_at == "now":
        record.completed_at = now
    elif completed_at and isinstance(completed_at, str):
        from datetime import datetime
        record.completed_at = datetime.fromisoformat(completed_at)
    else:
        record.completed_at = completed_at
    
    return record


class TestURLRuleResult:
    """Tests for URLRuleResult class."""

    def test_default_values(self) -> None:
        """Test default values for URLRuleResult."""
        result = URLRuleResult(
            action=URLAction.CREATE,
            scenario=URLScenario.NORMAL,
            message="Test message",
            url="https://example.com",
        )
        
        assert result.action == URLAction.CREATE
        assert result.scenario == URLScenario.NORMAL
        assert result.message == "Test message"
        assert result.url == "https://example.com"
        assert result.existing_record is None
        assert result.is_success is True
        assert result.metadata == {}
        assert result.warnings == []

    def test_is_duplicate_property(self) -> None:
        """Test is_duplicate convenience property."""
        result_duplicate = URLRuleResult(
            action=URLAction.SKIP,
            scenario=URLScenario.DUPLICATE_DEPENDENCY,
            message="Duplicate",
            url="https://example.com",
        )
        
        result_normal = URLRuleResult(
            action=URLAction.CREATE,
            scenario=URLScenario.NORMAL,
            message="Normal",
            url="https://example.com",
        )
        
        assert result_duplicate.is_duplicate is True
        assert result_normal.is_duplicate is False

    def test_is_circular_property(self) -> None:
        """Test is_circular convenience property."""
        result_circular = URLRuleResult(
            action=URLAction.SKIP,
            scenario=URLScenario.CIRCULAR_DEPENDENCY,
            message="Circular",
            url="https://example.com",
        )
        
        result_normal = URLRuleResult(
            action=URLAction.CREATE,
            scenario=URLScenario.NORMAL,
            message="Normal",
            url="https://example.com",
        )
        
        assert result_circular.is_circular is True
        assert result_normal.is_circular is False

    def test_needs_warning_property(self) -> None:
        """Test needs_warning convenience property."""
        result_warning = URLRuleResult(
            action=URLAction.WARN,
            scenario=URLScenario.DIRTY_DATA_WARNING,
            message="Warning",
            url="https://example.com",
            is_success=False,
        )
        
        result_with_warnings = URLRuleResult(
            action=URLAction.SKIP,
            scenario=URLScenario.NORMAL,
            message="Normal",
            url="https://example.com",
            warnings=["Warning 1"],
        )
        
        result_clean = URLRuleResult(
            action=URLAction.CREATE,
            scenario=URLScenario.NORMAL,
            message="Normal",
            url="https://example.com",
        )
        
        assert result_warning.needs_warning is True
        assert result_with_warnings.needs_warning is True
        assert result_clean.needs_warning is False


class TestURLRuleConfig:
    """Tests for URLRuleConfig class."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = URLRuleConfig()
        
        assert config.dirty_data_threshold_minutes == 60
        assert config.allow_duplicate_pending is False
        assert config.allow_retry_completed is False
        assert config.max_retries_default == 3
        assert "completed" in config.circular_check_states
        assert "in_progress" in config.circular_check_states

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = URLRuleConfig(
            dirty_data_threshold_minutes=30,
            allow_duplicate_pending=True,
            allow_retry_completed=True,
            max_retries_default=5,
            circular_check_states=("completed",),
        )
        
        assert config.dirty_data_threshold_minutes == 30
        assert config.allow_duplicate_pending is True
        assert config.allow_retry_completed is True
        assert config.max_retries_default == 5
        assert config.circular_check_states == ("completed",)


class TestURLRuleEngineScenarios:
    """Tests for each URL scenario evaluation."""

    def test_evaluate_add_normal_new_url(self) -> None:
        """Test NORMAL scenario: new URL with default parameters."""
        engine = URLRuleEngine()
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=None,
        )
        
        assert result.action == URLAction.CREATE
        assert result.scenario == URLScenario.NORMAL
        assert result.is_success is True
        assert "added successfully" in result.message.lower()
        assert result.metadata["has_optional_params"] is False
        assert result.metadata["max_retries"] == 3

    def test_evaluate_add_new_optional(self) -> None:
        """Test NEW_OPTIONAL scenario: new URL with non-default parameters."""
        engine = URLRuleEngine()
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=5,
        )
        
        assert result.action == URLAction.CREATE
        assert result.scenario == URLScenario.NEW_OPTIONAL
        assert result.is_success is True
        assert "optional parameters" in result.message
        assert result.metadata["has_optional_params"] is True
        assert result.metadata["max_retries"] == 5

    def test_evaluate_add_duplicate_pending(self) -> None:
        """Test DUPLICATE_DEPENDENCY scenario: existing pending URL."""
        engine = URLRuleEngine()
        existing = create_mock_record(
            url="https://example.com",
            status="pending",
        )
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.action == URLAction.SKIP
        assert result.scenario == URLScenario.DUPLICATE_DEPENDENCY
        assert result.is_success is True
        assert "duplicate" in result.message.lower()
        assert "pending" in result.message.lower()

    def test_evaluate_add_duplicate_failed(self) -> None:
        """Test DUPLICATE_DEPENDENCY scenario: existing failed URL."""
        engine = URLRuleEngine()
        existing = create_mock_record(
            url="https://example.com",
            status="failed",
            retry_count=3,
            max_retries=3,
        )
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.action == URLAction.SKIP
        assert result.scenario == URLScenario.DUPLICATE_DEPENDENCY
        assert result.is_success is True
        assert "duplicate" in result.message.lower()
        assert "failed" in result.message.lower()

    def test_evaluate_add_circular_completed_success(self) -> None:
        """Test CIRCULAR_DEPENDENCY scenario: completed successful URL."""
        engine = URLRuleEngine()
        existing = create_mock_record(
            url="https://example.com",
            status="completed",
            is_success=True,
            completed_at="now",
        )
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.action == URLAction.SKIP
        assert result.scenario == URLScenario.CIRCULAR_DEPENDENCY
        assert result.is_success is True
        assert "circular" in result.message.lower()
        assert "completed" in result.message.lower()

    def test_evaluate_add_circular_in_progress(self) -> None:
        """Test CIRCULAR_DEPENDENCY scenario: in_progress URL."""
        engine = URLRuleEngine()
        existing = create_mock_record(
            url="https://example.com",
            status="in_progress",
            started_at="now",
        )
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.action == URLAction.SKIP
        assert result.scenario == URLScenario.CIRCULAR_DEPENDENCY
        assert result.is_success is True
        assert "circular" in result.message.lower()
        assert "in_progress" in result.message.lower() or "in progress" in result.message.lower()

    def test_evaluate_add_dirty_data_stuck_in_progress(self) -> None:
        """Test DIRTY_DATA_WARNING scenario: stuck in_progress URL."""
        config = URLRuleConfig(dirty_data_threshold_minutes=60)
        engine = URLRuleEngine(config=config)
        
        now = utc_now()
        two_hours_ago = now - timedelta(hours=2)
        
        existing = MagicMock(spec=CrawledURL)
        existing.url = "https://example.com"
        existing.status = "in_progress"
        existing.is_success = False
        existing.started_at = two_hours_ago
        existing.completed_at = None
        existing.retry_count = 0
        existing.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.action == URLAction.WARN
        assert result.scenario == URLScenario.DIRTY_DATA_WARNING
        assert result.is_success is False
        assert "dirty" in result.message.lower() or "stuck" in result.message.lower()
        assert result.needs_warning is True


class TestURLRulePriority:
    """Tests for rule priority ordering.

    Rule Priority (highest to lowest):
    1. DIRTY_DATA_WARNING > CIRCULAR_DEPENDENCY > DUPLICATE_DEPENDENCY
    2. These scenarios have overlapping conditions, so priority matters
    """

    def test_dirty_data_overrides_circular(self) -> None:
        """Test that DIRTY_DATA_WARNING takes priority over CIRCULAR_DEPENDENCY.
        
        A URL can be both:
        - "in_progress" (circular condition)
        - Stuck beyond threshold (dirty data condition)
        
        Dirty data should win because it indicates a problem that needs attention.
        """
        config = URLRuleConfig(dirty_data_threshold_minutes=60)
        engine = URLRuleEngine(config=config)
        
        now = utc_now()
        two_hours_ago = now - timedelta(hours=2)
        
        existing = MagicMock(spec=CrawledURL)
        existing.url = "https://example.com"
        existing.status = "in_progress"
        existing.is_success = False
        existing.started_at = two_hours_ago
        existing.completed_at = None
        existing.retry_count = 0
        existing.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.scenario == URLScenario.DIRTY_DATA_WARNING
        assert result.action == URLAction.WARN

    def test_circular_overrides_duplicate(self) -> None:
        """Test that CIRCULAR_DEPENDENCY takes priority over DUPLICATE_DEPENDENCY.
        
        A completed successful URL is a "circular" condition because:
        - It has already been successfully processed
        - Re-processing would be redundant
        
        This is different from a "pending" or "failed" URL (duplicate), which:
        - Hasn't been successfully processed yet
        - May still need processing
        """
        engine = URLRuleEngine()
        
        completed_success = create_mock_record(
            url="https://example.com",
            status="completed",
            is_success=True,
            completed_at="now",
        )
        
        pending = create_mock_record(
            url="https://example.com",
            status="pending",
        )
        
        result_completed = engine.evaluate_add(
            url="https://example.com",
            existing_record=completed_success,
        )
        
        result_pending = engine.evaluate_add(
            url="https://example.com",
            existing_record=pending,
        )
        
        assert result_completed.scenario == URLScenario.CIRCULAR_DEPENDENCY
        assert result_pending.scenario == URLScenario.DUPLICATE_DEPENDENCY


class TestURLRuleEngineBatch:
    """Tests for batch URL evaluation."""

    def test_evaluate_batch_empty(self) -> None:
        """Test evaluating an empty batch."""
        engine = URLRuleEngine()
        
        results = engine.evaluate_batch(urls=[], existing_records={})
        
        assert len(results) == 0

    def test_evaluate_batch_mixed(self) -> None:
        """Test evaluating a batch with mixed scenarios."""
        engine = URLRuleEngine()
        
        urls = [
            "https://new.com",
            "https://pending.com",
            "https://completed.com",
        ]
        
        existing_records = {
            "https://pending.com": create_mock_record(
                url="https://pending.com",
                status="pending",
            ),
            "https://completed.com": create_mock_record(
                url="https://completed.com",
                status="completed",
                is_success=True,
                completed_at="now",
            ),
        }
        
        results = engine.evaluate_batch(
            urls=urls,
            existing_records=existing_records,
        )
        
        assert len(results) == 3
        
        scenarios = {r.url: r.scenario for r in results}
        
        assert scenarios["https://new.com"] == URLScenario.NORMAL
        assert scenarios["https://pending.com"] == URLScenario.DUPLICATE_DEPENDENCY
        assert scenarios["https://completed.com"] == URLScenario.CIRCULAR_DEPENDENCY

    def test_get_stats_summary(self) -> None:
        """Test generating stats summary from batch results."""
        engine = URLRuleEngine()
        
        results = [
            URLRuleResult(
                action=URLAction.CREATE,
                scenario=URLScenario.NORMAL,
                message="Normal",
                url="https://normal.com",
            ),
            URLRuleResult(
                action=URLAction.SKIP,
                scenario=URLScenario.DUPLICATE_DEPENDENCY,
                message="Duplicate",
                url="https://duplicate.com",
            ),
            URLRuleResult(
                action=URLAction.SKIP,
                scenario=URLScenario.CIRCULAR_DEPENDENCY,
                message="Circular",
                url="https://circular.com",
            ),
        ]
        
        stats = engine.get_stats_summary(results)
        
        assert stats["total"] == 3
        assert stats["by_scenario"]["normal"] == 1
        assert stats["by_scenario"]["duplicate_dependency"] == 1
        assert stats["by_scenario"]["circular_dependency"] == 1
        assert stats["by_action"]["create"] == 1
        assert stats["by_action"]["skip"] == 2


class TestURLRuleBoundaryConditions:
    """Tests for boundary conditions.

    These tests verify the exact decision boundaries:
    - Dirty data threshold
    - Max retries for NEW_OPTIONAL
    """

    def test_dirty_data_at_threshold(self) -> None:
        """Test dirty data detection at exactly the threshold.
        
        URL started at threshold boundary should NOT be dirty.
        """
        config = URLRuleConfig(dirty_data_threshold_minutes=60)
        engine = URLRuleEngine(config=config)
        
        now = utc_now()
        fifty_nine_minutes_ago = now - timedelta(minutes=59)
        
        existing = MagicMock(spec=CrawledURL)
        existing.url = "https://example.com"
        existing.status = "in_progress"
        existing.is_success = False
        existing.started_at = fifty_nine_minutes_ago
        existing.completed_at = None
        existing.retry_count = 0
        existing.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.scenario == URLScenario.CIRCULAR_DEPENDENCY
        assert result.scenario != URLScenario.DIRTY_DATA_WARNING

    def test_dirty_data_above_threshold(self) -> None:
        """Test dirty data detection above the threshold.
        
        URL started beyond threshold should be dirty.
        """
        config = URLRuleConfig(dirty_data_threshold_minutes=60)
        engine = URLRuleEngine(config=config)
        
        now = utc_now()
        sixty_one_minutes_ago = now - timedelta(minutes=61)
        
        existing = MagicMock(spec=CrawledURL)
        existing.url = "https://example.com"
        existing.status = "in_progress"
        existing.is_success = False
        existing.started_at = sixty_one_minutes_ago
        existing.completed_at = None
        existing.retry_count = 0
        existing.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=existing,
        )
        
        assert result.scenario == URLScenario.DIRTY_DATA_WARNING

    def test_new_optional_boundary(self) -> None:
        """Test NEW_OPTIONAL detection at max_retries boundary.
        
        max_retries == default should be NORMAL, not NEW_OPTIONAL.
        """
        engine = URLRuleEngine()
        
        result_default = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=3,
        )
        
        result_custom = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=5,
        )
        
        assert result_default.scenario == URLScenario.NORMAL
        assert result_custom.scenario == URLScenario.NEW_OPTIONAL
