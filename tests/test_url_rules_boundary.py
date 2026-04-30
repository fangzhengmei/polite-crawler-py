"""Boundary Tests for URL Rules Module.

This test suite focuses on:
1. Equivalent inputs with different representations (should produce same results)
2. Abnormal inputs that should degrade gracefully (not raise exceptions)

Rule Priority Confirmation:
    INVALID_INPUT > DIRTY_DATA_WARNING > CIRCULAR_DEPENDENCY > DUPLICATE_DEPENDENCY > NEW_OPTIONAL > NORMAL
"""

from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

import pytest

from polite_crawler.url_rules import (
    URLAction,
    URLRuleConfig,
    URLRuleEngine,
    URLRuleResult,
    URLScenario,
    URLNormalizer,
)
from polite_crawler.utils import utc_now


class TestURLEquivalence:
    """Tests for equivalent inputs producing consistent results.

    These tests verify that semantically equivalent inputs
    produce the same output, regardless of representation.
    """

    def test_url_with_trailing_slash_equivalent(self) -> None:
        """Test that URLs with/without trailing slash are treated equivalently.
        
        Equivalence:
            https://example.com/page ≡ https://example.com/page/
        """
        normalizer = URLNormalizer()
        
        url1 = "https://example.com/page"
        url2 = "https://example.com/page/"
        
        assert normalizer.are_urls_equivalent(url1, url2)
        assert normalizer.normalize_url(url1) == normalizer.normalize_url(url2)

    def test_url_with_root_slash_equivalent(self) -> None:
        """Test that root URL keeps its trailing slash.
        
        Special case:
            https://example.com ≡ https://example.com/
            https://example.com/ should remain https://example.com/
        """
        normalizer = URLNormalizer()
        
        url1 = "https://example.com"
        url2 = "https://example.com/"
        
        normalized1 = normalizer.normalize_url(url1)
        normalized2 = normalizer.normalize_url(url2)
        
        assert "example.com" in normalized1
        assert "example.com" in normalized2

    def test_url_case_insensitive_scheme(self) -> None:
        """Test that scheme case is normalized.
        
        Equivalence:
            HTTPS://EXAMPLE.COM ≡ https://example.com
        """
        normalizer = URLNormalizer()
        
        url1 = "HTTPS://EXAMPLE.COM/PATH"
        url2 = "https://example.com/path"
        
        normalized1 = normalizer.normalize_url(url1)
        normalized2 = normalizer.normalize_url(url2)
        
        assert normalized1.lower() == normalized2.lower()
        assert "https" in normalized1.lower()

    def test_url_with_whitespace_equivalent(self) -> None:
        """Test that leading/trailing whitespace is stripped.
        
        Equivalence:
            "  https://example.com  " ≡ "https://example.com"
        """
        normalizer = URLNormalizer()
        
        url1 = "  https://example.com  "
        url2 = "https://example.com"
        
        assert normalizer.are_urls_equivalent(url1, url2)

    def test_max_retries_none_vs_default(self) -> None:
        """Test that max_retries=None and max_retries=<default> produce same scenario.
        
        Equivalence:
            max_retries=None ≡ max_retries=3 (when default is 3)
        
        Both should produce NORMAL scenario, not NEW_OPTIONAL.
        """
        engine = URLRuleEngine()
        
        result_none = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=None,
        )
        
        result_default = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=3,
        )
        
        assert result_none.scenario == URLScenario.NORMAL
        assert result_default.scenario == URLScenario.NORMAL
        assert result_none.action == URLAction.CREATE
        assert result_default.action == URLAction.CREATE

    def test_custom_default_max_retries_equivalence(self) -> None:
        """Test equivalence with custom default max_retries.
        
        When default is 5:
            max_retries=None ≡ max_retries=5
            max_retries=3 ≠ max_retries=5 (should be NEW_OPTIONAL)
        """
        config = URLRuleConfig(max_retries_default=5)
        engine = URLRuleEngine(config=config)
        
        result_none = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=None,
        )
        
        result_5 = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=5,
        )
        
        result_3 = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=3,
        )
        
        assert result_none.scenario == URLScenario.NORMAL
        assert result_5.scenario == URLScenario.NORMAL
        assert result_3.scenario == URLScenario.NEW_OPTIONAL


class TestURLInvalidInputDegradation:
    """Tests for abnormal input handling (graceful degradation).

    These tests verify that abnormal inputs are handled without raising
    exceptions, and produce consistent results with appropriate warnings.
    """

    def test_empty_url_rejected(self) -> None:
        """Test that empty URL is rejected with INVALID_INPUT scenario."""
        engine = URLRuleEngine()
        
        result = engine.evaluate_add(
            url="",
            existing_record=None,
        )
        
        assert result.scenario == URLScenario.INVALID_INPUT
        assert result.action == URLAction.ERROR
        assert result.is_success is False
        assert result.needs_warning is True
        assert "empty" in result.message.lower()

    def test_whitespace_only_url_rejected(self) -> None:
        """Test that whitespace-only URL is rejected with INVALID_INPUT scenario."""
        engine = URLRuleEngine()
        
        result = engine.evaluate_add(
            url="   \t\n  ",
            existing_record=None,
        )
        
        assert result.scenario == URLScenario.INVALID_INPUT
        assert result.action == URLAction.ERROR
        assert result.is_success is False

    def test_allow_empty_urls_config(self) -> None:
        """Test that reject_empty_urls=False allows empty URLs."""
        config = URLRuleConfig(reject_empty_urls=False)
        engine = URLRuleEngine(config=config)
        
        result = engine.evaluate_add(
            url="",
            existing_record=None,
        )
        
        assert result.scenario == URLScenario.NORMAL
        assert result.action == URLAction.CREATE
        assert result.is_success is True

    def test_negative_max_retries_clamped(self) -> None:
        """Test that negative max_retries is clamped to valid range with warning."""
        engine = URLRuleEngine()
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=-5,
        )
        
        assert result.metadata["max_retries"] >= 0
        assert len(result.warnings) > 0
        assert "clamped" in result.warnings[0].lower()

    def test_excessive_max_retries_clamped(self) -> None:
        """Test that max_retries above maximum is clamped with warning."""
        engine = URLRuleEngine()
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=100,
        )
        
        assert result.metadata["max_retries"] <= 10
        assert len(result.warnings) > 0

    def test_custom_max_retries_range(self) -> None:
        """Test custom max_retries range configuration."""
        config = URLRuleConfig(
            max_retries_default=3,
            max_retries_min=1,
            max_retries_max=5,
        )
        engine = URLRuleEngine(config=config)
        
        result_low = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=0,
        )
        
        result_high = engine.evaluate_add(
            url="https://example.com",
            existing_record=None,
            max_retries=10,
        )
        
        assert result_low.metadata["max_retries"] == 1
        assert result_high.metadata["max_retries"] == 5


class TestAbnormalRecordDegradation:
    """Tests for handling abnormal database records.

    These tests verify that records with inconsistent or invalid
    state are handled gracefully with appropriate warnings.
    """

    def test_unknown_status_warns_and_treats_as_pending(self) -> None:
        """Test that unknown status values generate warnings but are handled.
        
        Unknown status should:
        1. Generate a warning
        2. Be treated as "pending" (DUPLICATE_DEPENDENCY scenario)
        """
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "unknown_status_xyz"
        record.is_success = False
        record.started_at = None
        record.completed_at = None
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert len(result.warnings) > 0
        assert "unknown" in result.warnings[0].lower()
        assert result.scenario == URLScenario.DUPLICATE_DEPENDENCY
        assert result.action == URLAction.SKIP

    def test_completed_but_not_success_warns(self) -> None:
        """Test that status='completed' but is_success=False generates warning.
        
        This is an inconsistent state that should be flagged.
        """
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "completed"
        record.is_success = False
        record.started_at = utc_now() - timedelta(hours=1)
        record.completed_at = utc_now()
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert len(result.warnings) > 0
        assert any("inconsistent" in w.lower() or "completed" in w.lower() for w in result.warnings)

    def test_failed_but_success_true_warns(self) -> None:
        """Test that status='failed' but is_success=True generates warning.
        
        This is an inconsistent state that should be flagged.
        """
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "failed"
        record.is_success = True
        record.started_at = None
        record.completed_at = None
        record.retry_count = 3
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert len(result.warnings) > 0
        assert any("inconsistent" in w.lower() or "failed" in w.lower() for w in result.warnings)

    def test_completed_before_started_warns(self) -> None:
        """Test that completed_at < started_at generates warning.
        
        Abnormal timestamps should be flagged.
        """
        engine = URLRuleEngine()
        
        now = utc_now()
        started_at = now
        completed_at = now - timedelta(hours=1)
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "completed"
        record.is_success = True
        record.started_at = started_at
        record.completed_at = completed_at
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert len(result.warnings) > 0
        assert any("abnormal" in w.lower() or "timestamp" in w.lower() for w in result.warnings)

    def test_negative_retry_count_warns(self) -> None:
        """Test that negative retry_count generates warning."""
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "pending"
        record.is_success = False
        record.started_at = None
        record.completed_at = None
        record.retry_count = -5
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert len(result.warnings) > 0
        assert any("negative" in w.lower() and "retry" in w.lower() for w in result.warnings)

    def test_negative_max_retries_warns(self) -> None:
        """Test that negative max_retries generates warning."""
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "pending"
        record.is_success = False
        record.started_at = None
        record.completed_at = None
        record.retry_count = 0
        record.max_retries = -3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert len(result.warnings) > 0
        assert any("negative" in w.lower() and "max_retries" in w.lower() for w in result.warnings)

    def test_in_progress_without_started_at_is_dirty_data(self) -> None:
        """Test that in_progress without started_at is DIRTY_DATA_WARNING.
        
        This is an inconsistent state that should be flagged as dirty data.
        """
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "in_progress"
        record.is_success = False
        record.started_at = None
        record.completed_at = None
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert result.scenario == URLScenario.DIRTY_DATA_WARNING
        assert result.action == URLAction.WARN
        assert result.is_success is False
        assert "inconsistent" in result.message.lower()


class TestMissingAttributeHandling:
    """Tests for handling records with missing attributes.

    These tests verify that the engine uses safe attribute access
    with default values when attributes are missing.
    """

    def test_record_with_missing_status(self) -> None:
        """Test that record without status attribute is handled safely."""
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        del record.status
        record.is_success = False
        record.started_at = None
        record.completed_at = None
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert result.action == URLAction.SKIP

    def test_record_with_missing_is_success(self) -> None:
        """Test that record without is_success attribute uses default=False."""
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "completed"
        del record.is_success
        record.started_at = None
        record.completed_at = utc_now()
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert result.scenario == URLScenario.DUPLICATE_DEPENDENCY

    def test_record_with_missing_timestamps(self) -> None:
        """Test that record without timestamp attributes is handled safely."""
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "in_progress"
        record.is_success = False
        del record.started_at
        del record.completed_at
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert result.scenario == URLScenario.DIRTY_DATA_WARNING


class TestRulePriorityConflicts:
    """Tests for rule priority when multiple conditions apply.

    These tests verify that when multiple scenario conditions are met,
    the highest priority scenario wins.

    Priority (highest to lowest):
        INVALID_INPUT > DIRTY_DATA_WARNING > CIRCULAR_DEPENDENCY > DUPLICATE_DEPENDENCY > NEW_OPTIONAL > NORMAL
    """

    def test_dirty_data_overrides_circular(self) -> None:
        """Test that DIRTY_DATA_WARNING takes priority over CIRCULAR_DEPENDENCY.
        
        A record can be both:
        - "in_progress" (circular condition)
        - Stuck beyond threshold (dirty data condition)
        
        Dirty data should win because it indicates a problem needing attention.
        """
        engine = URLRuleEngine()
        
        now = utc_now()
        two_hours_ago = now - timedelta(hours=2)
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "in_progress"
        record.is_success = False
        record.started_at = two_hours_ago
        record.completed_at = None
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert result.scenario == URLScenario.DIRTY_DATA_WARNING
        assert result.scenario != URLScenario.CIRCULAR_DEPENDENCY
        assert result.action == URLAction.WARN

    def test_circular_overrides_duplicate(self) -> None:
        """Test that CIRCULAR_DEPENDENCY takes priority over DUPLICATE_DEPENDENCY.
        
        A "completed successful" record could be seen as:
        - Already processed (circular condition)
        - Already exists (duplicate condition)
        
        Circular should win because it indicates successful completion,
        which is a stronger condition for skipping.
        """
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "completed"
        record.is_success = True
        record.started_at = utc_now() - timedelta(hours=1)
        record.completed_at = utc_now()
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert result.scenario == URLScenario.CIRCULAR_DEPENDENCY
        assert result.action == URLAction.SKIP

    def test_in_progress_is_circular_not_duplicate(self) -> None:
        """Test that in_progress is CIRCULAR_DEPENDENCY, not DUPLICATE_DEPENDENCY.
        
        "in_progress" indicates the URL is currently being processed,
        so it should be treated as circular (already in the system).
        """
        engine = URLRuleEngine()
        
        record = MagicMock()
        record.url = "https://example.com"
        record.status = "in_progress"
        record.is_success = False
        record.started_at = utc_now()
        record.completed_at = None
        record.retry_count = 0
        record.max_retries = 3
        
        result = engine.evaluate_add(
            url="https://example.com",
            existing_record=record,
        )
        
        assert result.scenario == URLScenario.CIRCULAR_DEPENDENCY
        assert result.scenario != URLScenario.DUPLICATE_DEPENDENCY


class TestBatchEvaluationEdgeCases:
    """Tests for batch evaluation with edge cases."""

    def test_batch_with_mixed_validity(self) -> None:
        """Test batch evaluation with mixed valid/invalid URLs."""
        engine = URLRuleEngine()
        
        urls = [
            "https://valid1.com",
            "",
            "https://valid2.com",
            "   ",
            "https://valid3.com",
        ]
        
        results = engine.evaluate_batch(
            urls=urls,
            existing_records={},
        )
        
        assert len(results) == 5
        
        valid_count = sum(1 for r in results if r.scenario == URLScenario.NORMAL)
        invalid_count = sum(1 for r in results if r.scenario == URLScenario.INVALID_INPUT)
        
        assert valid_count == 3
        assert invalid_count == 2

    def test_stats_summary_with_mixed_scenarios(self) -> None:
        """Test stats_summary correctly counts all scenarios including new ones."""
        engine = URLRuleEngine()
        
        results = [
            URLRuleResult(
                action=URLAction.CREATE,
                scenario=URLScenario.NORMAL,
                message="OK",
                url="https://a.com",
            ),
            URLRuleResult(
                action=URLAction.ERROR,
                scenario=URLScenario.INVALID_INPUT,
                message="Invalid",
                url="",
                is_success=False,
            ),
            URLRuleResult(
                action=URLAction.SKIP,
                scenario=URLScenario.CIRCULAR_DEPENDENCY,
                message="Circular",
                url="https://b.com",
            ),
        ]
        
        stats = engine.get_stats_summary(results)
        
        assert stats["total"] == 3
        assert stats["by_scenario"]["normal"] == 1
        assert stats["by_scenario"]["invalid_input"] == 1
        assert stats["by_scenario"]["circular_dependency"] == 1
        assert stats["by_action"]["create"] == 1
        assert stats["by_action"]["error"] == 1
        assert stats["by_action"]["skip"] == 1
        assert stats["success_count"] == 2
        assert stats["error_count"] == 1
