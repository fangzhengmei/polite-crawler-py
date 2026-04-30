"""URL Management Rules Module.

This module provides unified rule-based URL management with clear:
1. Decision boundaries for each scenario
2. Consistent return semantics
3. Prioritized warning messages

Scenarios covered:
- NEW_OPTIONAL: Adding URLs with optional parameters
- DUPLICATE_DEPENDENCY: Duplicate URL detection
- CIRCULAR_DEPENDENCY: Circular reference detection (already crawled URLs)
- DIRTY_DATA_WARNING: Inconsistent state detection
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set

from polite_crawler.models import CrawledURL
from polite_crawler.utils import utc_now


class URLAction(Enum):
    """The action to take for a URL."""

    CREATE = auto()
    SKIP = auto()
    UPDATE = auto()
    WARN = auto()
    ERROR = auto()


class URLScenario(Enum):
    """The scenario that triggered the action."""

    NEW_OPTIONAL = auto()
    DUPLICATE_DEPENDENCY = auto()
    CIRCULAR_DEPENDENCY = auto()
    DIRTY_DATA_WARNING = auto()
    NORMAL = auto()


@dataclass
class URLRuleResult:
    """Unified result from URL rule evaluation.

    Attributes:
        action: The recommended action
        scenario: The scenario that triggered this result
        message: Human-readable message (highest priority first)
        url: The URL being evaluated
        existing_record: Existing database record if found
        is_success: Whether the operation was successful
        metadata: Additional context-specific metadata
        warnings: List of warning messages (lower priority than main message)
    """

    action: URLAction
    scenario: URLScenario
    message: str
    url: str
    existing_record: Optional[CrawledURL] = None
    is_success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def is_duplicate(self) -> bool:
        """Check if this is a duplicate URL scenario."""
        return self.scenario == URLScenario.DUPLICATE_DEPENDENCY

    @property
    def is_circular(self) -> bool:
        """Check if this is a circular dependency scenario."""
        return self.scenario == URLScenario.CIRCULAR_DEPENDENCY

    @property
    def needs_warning(self) -> bool:
        """Check if this result has warnings."""
        return self.scenario == URLScenario.DIRTY_DATA_WARNING or bool(self.warnings)


class URLRuleConfig:
    """Configuration for URL management rules.

    Allows customization of rule thresholds and behaviors.
    """

    def __init__(
        self,
        dirty_data_threshold_minutes: int = 60,
        allow_duplicate_pending: bool = False,
        allow_retry_completed: bool = False,
        max_retries_default: int = 3,
        circular_check_states: tuple = ("completed", "in_progress"),
    ):
        """Initialize URL rule configuration.

        Args:
            dirty_data_threshold_minutes: Threshold for detecting stuck "in_progress" records
            allow_duplicate_pending: Whether to allow adding duplicate pending URLs
            allow_retry_completed: Whether to allow re-crawling completed URLs
            max_retries_default: Default max retries for new URLs
            circular_check_states: States that indicate a URL has been/can be processed
        """
        self.dirty_data_threshold_minutes = dirty_data_threshold_minutes
        self.allow_duplicate_pending = allow_duplicate_pending
        self.allow_retry_completed = allow_retry_completed
        self.max_retries_default = max_retries_default
        self.circular_check_states = circular_check_states


class URLRuleEngine:
    """Unified rule engine for URL management.

    This engine provides consistent decision-making across all URL operations
    with clear boundaries, return semantics, and message prioritization.

    Rule Priority (highest to lowest):
    1. DIRTY_DATA_WARNING - Inconsistent state that needs attention
    2. CIRCULAR_DEPENDENCY - URL already processed (completed/in_progress)
    3. DUPLICATE_DEPENDENCY - URL already exists (pending/failed)
    4. NEW_OPTIONAL - New URL with optional parameters
    5. NORMAL - Standard new URL
    """

    MESSAGE_TEMPLATES = {
        URLScenario.NEW_OPTIONAL: "URL '{url}' added with optional parameters: {params}",
        URLScenario.DUPLICATE_DEPENDENCY: "Duplicate URL '{url}' detected - already exists with status '{status}'",
        URLScenario.CIRCULAR_DEPENDENCY: "Circular reference detected - URL '{url}' was already {status} at {time}",
        URLScenario.DIRTY_DATA_WARNING: "Dirty data warning for URL '{url}': {reason}",
        URLScenario.NORMAL: "URL '{url}' added successfully",
    }

    def __init__(self, config: Optional[URLRuleConfig] = None):
        """Initialize the rule engine.

        Args:
            config: Optional custom configuration
        """
        self._config = config or URLRuleConfig()

    def _get_message(self, scenario: URLScenario, **kwargs: Any) -> str:
        """Generate a message from the template.

        Args:
            scenario: The scenario
            **kwargs: Template parameters

        Returns:
            Formatted message string
        """
        template = self.MESSAGE_TEMPLATES.get(scenario, "")
        try:
            return template.format(**kwargs)
        except KeyError:
            return template

    def evaluate_add(
        self,
        url: str,
        existing_record: Optional[CrawledURL],
        max_retries: Optional[int] = None,
    ) -> URLRuleResult:
        """Evaluate rules for adding a URL.

        Decision Boundary:
        1. DIRTY_DATA_WARNING: existing record is "in_progress" beyond threshold
        2. CIRCULAR_DEPENDENCY: existing record is "completed" (success)
        3. DUPLICATE_DEPENDENCY: existing record is "pending" or "failed"
        4. NEW_OPTIONAL: new URL with non-default parameters
        5. NORMAL: new URL with default parameters

        Args:
            url: The URL to add
            existing_record: Existing database record if any
            max_retries: Optional max retries override

        Returns:
            URLRuleResult with the recommended action
        """
        if existing_record is None:
            return self._evaluate_new_url(url, max_retries)
        
        return self._evaluate_existing_url(url, existing_record)

    def _evaluate_new_url(
        self,
        url: str,
        max_retries: Optional[int],
    ) -> URLRuleResult:
        """Evaluate rules for a new URL (no existing record).

        Decision Boundary:
        - NEW_OPTIONAL: max_retries is provided and != default
        - NORMAL: max_retries is None or == default
        """
        params: Dict[str, Any] = {}
        
        if max_retries is not None and max_retries != self._config.max_retries_default:
            params["max_retries"] = max_retries
        
        if params:
            return URLRuleResult(
                action=URLAction.CREATE,
                scenario=URLScenario.NEW_OPTIONAL,
                message=self._get_message(
                    URLScenario.NEW_OPTIONAL,
                    url=url,
                    params=params,
                ),
                url=url,
                is_success=True,
                metadata={
                    "max_retries": max_retries or self._config.max_retries_default,
                    "has_optional_params": True,
                },
            )
        
        return URLRuleResult(
            action=URLAction.CREATE,
            scenario=URLScenario.NORMAL,
            message=self._get_message(URLScenario.NORMAL, url=url),
            url=url,
            is_success=True,
            metadata={
                "max_retries": self._config.max_retries_default,
                "has_optional_params": False,
            },
        )

    def _evaluate_existing_url(
        self,
        url: str,
        existing_record: CrawledURL,
    ) -> URLRuleResult:
        """Evaluate rules for an existing URL.

        Decision Boundary (highest priority first):
        
        1. DIRTY_DATA_WARNING:
           - Status is "in_progress"
           - started_at is beyond threshold (e.g., 60 minutes ago)
           - No completed_at
        
        2. CIRCULAR_DEPENDENCY:
           - Status is "completed" AND is_success is True
           - OR status is "in_progress" (already being processed)
        
        3. DUPLICATE_DEPENDENCY:
           - Status is "pending" (waiting to be processed)
           - OR status is "failed" (exhausted retries)
        """
        warnings: List[str] = []
        
        if self._is_dirty_data(existing_record):
            reason = self._get_dirty_data_reason(existing_record)
            warnings.append(reason)
            
            return URLRuleResult(
                action=URLAction.WARN,
                scenario=URLScenario.DIRTY_DATA_WARNING,
                message=self._get_message(
                    URLScenario.DIRTY_DATA_WARNING,
                    url=url,
                    reason=reason,
                ),
                url=url,
                existing_record=existing_record,
                is_success=False,
                metadata={
                    "status": existing_record.status,
                    "started_at": existing_record.started_at.isoformat() if existing_record.started_at else None,
                    "threshold_minutes": self._config.dirty_data_threshold_minutes,
                },
                warnings=warnings,
            )
        
        if self._is_circular_dependency(existing_record):
            return URLRuleResult(
                action=URLAction.SKIP,
                scenario=URLScenario.CIRCULAR_DEPENDENCY,
                message=self._get_message(
                    URLScenario.CIRCULAR_DEPENDENCY,
                    url=url,
                    status=existing_record.status,
                    time=existing_record.completed_at.isoformat() if existing_record.completed_at else "in progress",
                ),
                url=url,
                existing_record=existing_record,
                is_success=True,
                metadata={
                    "status": existing_record.status,
                    "is_success": existing_record.is_success,
                    "completed_at": existing_record.completed_at.isoformat() if existing_record.completed_at else None,
                },
            )
        
        if self._is_duplicate(existing_record):
            return URLRuleResult(
                action=URLAction.SKIP,
                scenario=URLScenario.DUPLICATE_DEPENDENCY,
                message=self._get_message(
                    URLScenario.DUPLICATE_DEPENDENCY,
                    url=url,
                    status=existing_record.status,
                ),
                url=url,
                existing_record=existing_record,
                is_success=True,
                metadata={
                    "status": existing_record.status,
                    "retry_count": existing_record.retry_count,
                    "max_retries": existing_record.max_retries,
                },
            )
        
        return URLRuleResult(
            action=URLAction.SKIP,
            scenario=URLScenario.DUPLICATE_DEPENDENCY,
            message=self._get_message(
                URLScenario.DUPLICATE_DEPENDENCY,
                url=url,
                status=existing_record.status,
            ),
            url=url,
            existing_record=existing_record,
            is_success=True,
            metadata={"status": existing_record.status},
        )

    def _is_dirty_data(self, record: CrawledURL) -> bool:
        """Check if a record represents dirty/inconsistent data.

        Dirty data definition:
        - Status is "in_progress"
        - started_at exists and is beyond the threshold
        - No completed_at (never finished)

        Args:
            record: The database record

        Returns:
            True if this is dirty data
        """
        if record.status != "in_progress":
            return False
        
        if record.completed_at is not None:
            return False
        
        if record.started_at is None:
            return False
        
        threshold = timedelta(minutes=self._config.dirty_data_threshold_minutes)
        elapsed = utc_now() - record.started_at
        
        return elapsed > threshold

    def _get_dirty_data_reason(self, record: CrawledURL) -> str:
        """Generate a human-readable reason for dirty data.

        Args:
            record: The database record

        Returns:
            Reason string
        """
        if record.started_at:
            elapsed = utc_now() - record.started_at
            elapsed_mins = int(elapsed.total_seconds() / 60)
            return (
                f"Stuck 'in_progress' for {elapsed_mins} minutes "
                f"(threshold: {self._config.dirty_data_threshold_minutes} min)"
            )
        return "Inconsistent state detected"

    def _is_circular_dependency(self, record: CrawledURL) -> bool:
        """Check if a record represents a circular dependency.

        Circular dependency definition:
        - Status is "completed" with is_success=True (already successfully crawled)
        - OR status is "in_progress" (currently being processed)
        
        These URLs should be skipped to avoid:
        1. Re-crawling successful URLs
        2. Concurrent processing of the same URL

        Args:
            record: The database record

        Returns:
            True if this is a circular dependency
        """
        if record.status == "completed" and record.is_success:
            return True
        
        if record.status == "in_progress":
            return True
        
        return False

    def _is_duplicate(self, record: CrawledURL) -> bool:
        """Check if a record represents a duplicate dependency.

        Duplicate dependency definition:
        - Status is "pending" (waiting in queue)
        - OR status is "failed" (exhausted retries)
        
        These are duplicates but different from circular dependencies
        because they haven't been successfully processed yet.

        Args:
            record: The database record

        Returns:
            True if this is a duplicate dependency
        """
        if record.status == "pending":
            return True
        
        if record.status == "failed":
            return True
        
        return False

    def evaluate_batch(
        self,
        urls: List[str],
        existing_records: Dict[str, CrawledURL],
        max_retries: Optional[int] = None,
    ) -> List[URLRuleResult]:
        """Evaluate a batch of URLs.

        Args:
            urls: List of URLs to evaluate
            existing_records: Dict mapping URLs to existing records
            max_retries: Optional max retries for all URLs

        Returns:
            List of URLRuleResult objects
        """
        results: List[URLRuleResult] = []
        
        for url in urls:
            existing = existing_records.get(url)
            result = self.evaluate_add(url, existing, max_retries)
            results.append(result)
        
        return results

    def get_stats_summary(self, results: List[URLRuleResult]) -> Dict[str, Any]:
        """Generate a summary of rule evaluation results.

        Args:
            results: List of URLRuleResult objects

        Returns:
            Summary statistics
        """
        stats = {
            "total": len(results),
            "by_scenario": {
                "new_optional": 0,
                "duplicate_dependency": 0,
                "circular_dependency": 0,
                "dirty_data_warning": 0,
                "normal": 0,
            },
            "by_action": {
                "create": 0,
                "skip": 0,
                "update": 0,
                "warn": 0,
                "error": 0,
            },
            "warnings": [],
        }

        scenario_map = {
            URLScenario.NEW_OPTIONAL: "new_optional",
            URLScenario.DUPLICATE_DEPENDENCY: "duplicate_dependency",
            URLScenario.CIRCULAR_DEPENDENCY: "circular_dependency",
            URLScenario.DIRTY_DATA_WARNING: "dirty_data_warning",
            URLScenario.NORMAL: "normal",
        }

        action_map = {
            URLAction.CREATE: "create",
            URLAction.SKIP: "skip",
            URLAction.UPDATE: "update",
            URLAction.WARN: "warn",
            URLAction.ERROR: "error",
        }

        for result in results:
            stats["by_scenario"][scenario_map[result.scenario]] += 1
            stats["by_action"][action_map[result.action]] += 1
            
            if result.needs_warning:
                stats["warnings"].append({
                    "url": result.url,
                    "message": result.message,
                    "scenario": scenario_map[result.scenario],
                })

        return stats
