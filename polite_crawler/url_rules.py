"""URL Management Rules Module.

This module provides unified rule-based URL management with clear:
1. Decision boundaries for each scenario
2. Consistent return semantics
3. Prioritized warning messages
4. Robust input validation and graceful degradation

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
from urllib.parse import urlparse

from polite_crawler.models import CrawledURL
from polite_crawler.utils import utc_now


class URLAction(Enum):
    """The action to take for a URL.

    Values:
        CREATE: Create a new record
        SKIP: Skip this URL (already exists/processed)
        UPDATE: Update existing record (for retry scenarios)
        WARN: Warning - data inconsistency detected
        ERROR: Error - invalid input
    """

    CREATE = auto()
    SKIP = auto()
    UPDATE = auto()
    WARN = auto()
    ERROR = auto()


class URLScenario(Enum):
    """The scenario that triggered the action.

    Priority order (highest to lowest):
        DIRTY_DATA_WARNING > CIRCULAR_DEPENDENCY > DUPLICATE_DEPENDENCY > NEW_OPTIONAL > NORMAL
    """

    NEW_OPTIONAL = auto()
    DUPLICATE_DEPENDENCY = auto()
    CIRCULAR_DEPENDENCY = auto()
    DIRTY_DATA_WARNING = auto()
    NORMAL = auto()
    INVALID_INPUT = auto()


@dataclass
class URLRuleResult:
    """Unified result from URL rule evaluation.

    This dataclass provides a consistent interface for all rule evaluations,
    ensuring that even abnormal inputs return predictable results.

    Attributes:
        action: The recommended action (URLAction)
        scenario: The scenario that triggered this result (URLScenario)
        message: Human-readable message (highest priority first)
        url: The URL being evaluated (normalized if possible)
        existing_record: Existing database record if found
        is_success: Whether the operation was successful
        metadata: Additional context-specific metadata
        warnings: List of warning messages (lower priority than main message)
        original_url: The original URL before normalization (for debugging)
    """

    action: URLAction
    scenario: URLScenario
    message: str
    url: str
    existing_record: Optional[CrawledURL] = None
    is_success: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)
    original_url: Optional[str] = None

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
        """Check if this result has warnings or indicates dirty data."""
        return (
            self.scenario == URLScenario.DIRTY_DATA_WARNING
            or self.scenario == URLScenario.INVALID_INPUT
            or bool(self.warnings)
        )

    @property
    def normalized_url(self) -> str:
        """Get the normalized URL, or original if normalization failed."""
        return self.url


class URLRuleConfig:
    """Configuration for URL management rules.

    Allows customization of rule thresholds and behaviors.
    """

    VALID_STATUSES = {"pending", "in_progress", "completed", "failed"}

    def __init__(
        self,
        dirty_data_threshold_minutes: int = 60,
        allow_duplicate_pending: bool = False,
        allow_retry_completed: bool = False,
        max_retries_default: int = 3,
        max_retries_min: int = 0,
        max_retries_max: int = 10,
        circular_check_states: tuple = ("completed", "in_progress"),
        normalize_urls: bool = True,
        reject_empty_urls: bool = True,
    ):
        """Initialize URL rule configuration.

        Args:
            dirty_data_threshold_minutes: Threshold for detecting stuck "in_progress" records
            allow_duplicate_pending: Whether to allow adding duplicate pending URLs
            allow_retry_completed: Whether to allow re-crawling completed URLs
            max_retries_default: Default max retries for new URLs
            max_retries_min: Minimum allowed max_retries value
            max_retries_max: Maximum allowed max_retries value
            circular_check_states: States that indicate a URL has been/can be processed
            normalize_urls: Whether to normalize URLs before evaluation
            reject_empty_urls: Whether to reject empty/whitespace-only URLs
        """
        self.dirty_data_threshold_minutes = dirty_data_threshold_minutes
        self.allow_duplicate_pending = allow_duplicate_pending
        self.allow_retry_completed = allow_retry_completed
        self.max_retries_default = max_retries_default
        self.max_retries_min = max_retries_min
        self.max_retries_max = max_retries_max
        self.circular_check_states = circular_check_states
        self.normalize_urls = normalize_urls
        self.reject_empty_urls = reject_empty_urls

    def validate_and_clamp_max_retries(self, value: Optional[int]) -> int:
        """Validate and clamp max_retries value to valid range.

        Args:
            value: The input value (may be None or invalid)

        Returns:
            Clamped value within [min, max] range, or default if None
        """
        if value is None:
            return self.max_retries_default
        
        try:
            int_value = int(value)
            return max(
                self.max_retries_min,
                min(int_value, self.max_retries_max)
            )
        except (TypeError, ValueError):
            return self.max_retries_default

    def is_valid_status(self, status: Optional[str]) -> bool:
        """Check if a status value is valid.

        Args:
            status: The status to check (may be None)

        Returns:
            True if status is valid
        """
        return status is not None and status in self.VALID_STATUSES


class URLNormalizer:
    """URL normalizer for consistent URL handling.

    Provides normalization functions to ensure equivalent URLs
    are treated identically by the rule engine.
    """

    @staticmethod
    def normalize_url(url: str) -> str:
        """Normalize a URL for consistent handling.

        Normalization steps:
        1. Strip leading/trailing whitespace
        2. Remove trailing slash from path (unless path is just "/")
        3. Convert scheme and hostname to lowercase (for equivalence)

        Note: This is for semantic equivalence detection, not for actual
        HTTP requests (which should use the original URL).

        Args:
            url: The URL to normalize

        Returns:
            Normalized URL string
        """
        if not url:
            return ""
        
        url = url.strip()
        
        try:
            parsed = urlparse(url)
            
            scheme = parsed.scheme.lower() if parsed.scheme else ""
            netloc = parsed.netloc.lower() if parsed.netloc else ""
            path = parsed.path
            query = parsed.query
            fragment = parsed.fragment
            
            if path and path != "/" and path.endswith("/"):
                path = path.rstrip("/")
            
            normalized_parts = []
            if scheme:
                normalized_parts.append(f"{scheme}://")
            if netloc:
                normalized_parts.append(netloc)
            if path:
                normalized_parts.append(path)
            elif netloc:
                normalized_parts.append("/")
            if query:
                normalized_parts.append(f"?{query}")
            if fragment:
                normalized_parts.append(f"#{fragment}")
            
            result = "".join(normalized_parts)
            return result if result else url
            
        except Exception:
            return url

    @staticmethod
    def are_urls_equivalent(url1: str, url2: str) -> bool:
        """Check if two URLs are semantically equivalent after normalization.

        Args:
            url1: First URL
            url2: Second URL

        Returns:
            True if URLs are equivalent after normalization
        """
        return URLNormalizer.normalize_url(url1) == URLNormalizer.normalize_url(url2)


class URLRuleEngine:
    """Unified rule engine for URL management.

    This engine provides consistent decision-making across all URL operations
    with clear boundaries, return semantics, and message prioritization.

    Rule Priority (highest to lowest):
    1. INVALID_INPUT - Empty/invalid URL (if reject_empty_urls is True)
    2. DIRTY_DATA_WARNING - Inconsistent state that needs attention
    3. CIRCULAR_DEPENDENCY - URL already processed (completed/in_progress)
    4. DUPLICATE_DEPENDENCY - URL already exists (pending/failed)
    5. NEW_OPTIONAL - New URL with optional parameters
    6. NORMAL - Standard new URL

    Graceful Degradation:
    - All methods handle abnormal inputs without raising exceptions
    - Missing attributes in records are handled with defaults
    - Invalid numeric values are clamped to valid ranges
    """

    MESSAGE_TEMPLATES = {
        URLScenario.NEW_OPTIONAL: "URL '{url}' added with optional parameters: {params}",
        URLScenario.DUPLICATE_DEPENDENCY: "Duplicate URL '{url}' detected - already exists with status '{status}'",
        URLScenario.CIRCULAR_DEPENDENCY: "Circular reference detected - URL '{url}' was already {status} at {time}",
        URLScenario.DIRTY_DATA_WARNING: "Dirty data warning for URL '{url}': {reason}",
        URLScenario.NORMAL: "URL '{url}' added successfully",
        URLScenario.INVALID_INPUT: "Invalid URL '{url}': {reason}",
    }

    def __init__(self, config: Optional[URLRuleConfig] = None):
        """Initialize the rule engine.

        Args:
            config: Optional custom configuration
        """
        self._config = config or URLRuleConfig()
        self._normalizer = URLNormalizer()

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
        except (KeyError, IndexError):
            return template

    def _safe_getattr(self, obj: Any, attr: str, default: Any = None) -> Any:
        """Safely get an attribute from an object, returning default if missing.

        Args:
            obj: The object to get attribute from
            attr: The attribute name
            default: Default value if attribute is missing or raises exception

        Returns:
            Attribute value or default
        """
        try:
            return getattr(obj, attr, default)
        except Exception:
            return default

    def _normalize_url(self, url: str) -> str:
        """Normalize URL if configured to do so.

        Args:
            url: The URL to normalize

        Returns:
            Normalized URL or original URL
        """
        if self._config.normalize_urls:
            return self._normalizer.normalize_url(url)
        return url

    def _create_invalid_input_result(
        self,
        url: str,
        reason: str,
        original_url: Optional[str] = None,
    ) -> URLRuleResult:
        """Create a result for invalid input.

        Args:
            url: The URL (may be empty)
            reason: Why the input is invalid
            original_url: Original URL before normalization

        Returns:
            URLRuleResult indicating invalid input
        """
        return URLRuleResult(
            action=URLAction.ERROR,
            scenario=URLScenario.INVALID_INPUT,
            message=self._get_message(
                URLScenario.INVALID_INPUT,
                url=url or "(empty)",
                reason=reason,
            ),
            url=url,
            is_success=False,
            metadata={
                "reason": reason,
                "validation_failed": True,
            },
            warnings=[reason],
            original_url=original_url,
        )

    def evaluate_add(
        self,
        url: str,
        existing_record: Optional[CrawledURL],
        max_retries: Optional[int] = None,
    ) -> URLRuleResult:
        """Evaluate rules for adding a URL.

        This method provides robust input validation and graceful degradation
        for all edge cases.

        Decision Boundary (highest priority first):
        1. INVALID_INPUT: URL is empty/whitespace (if reject_empty_urls is True)
        2. DIRTY_DATA_WARNING: existing record has inconsistent state
           - "in_progress" beyond threshold
           - contradictory status/is_success
           - abnormal timestamps
        3. CIRCULAR_DEPENDENCY: existing record is "completed" (success) or "in_progress"
        4. DUPLICATE_DEPENDENCY: existing record is "pending" or "failed"
        5. NEW_OPTIONAL: new URL with non-default parameters
        6. NORMAL: new URL with default parameters

        Args:
            url: The URL to add
            existing_record: Existing database record if any
            max_retries: Optional max retries override

        Returns:
            URLRuleResult with the recommended action (never raises exception)
        """
        original_url = url
        
        url = self._normalize_url(url)
        
        if self._config.reject_empty_urls:
            if not url or url.strip() == "":
                return self._create_invalid_input_result(
                    url=url,
                    reason="URL cannot be empty or whitespace-only",
                    original_url=original_url,
                )
        
        validated_max_retries = self._config.validate_and_clamp_max_retries(max_retries)
        
        if existing_record is None:
            return self._evaluate_new_url(
                url=url,
                original_url=original_url,
                max_retries=validated_max_retries,
                original_max_retries=max_retries,
            )
        
        return self._evaluate_existing_url(
            url=url,
            original_url=original_url,
            existing_record=existing_record,
        )

    def _evaluate_new_url(
        self,
        url: str,
        original_url: str,
        max_retries: int,
        original_max_retries: Optional[int],
    ) -> URLRuleResult:
        """Evaluate rules for a new URL (no existing record).

        Decision Boundary:
        - NEW_OPTIONAL: max_retries was provided and differs from default
        - NORMAL: max_retries is default or None

        Args:
            url: Normalized URL
            original_url: Original URL before normalization
            max_retries: Validated and clamped max_retries
            original_max_retries: Original input max_retries (for detection)

        Returns:
            URLRuleResult
        """
        params: Dict[str, Any] = {}
        warnings: List[str] = []
        
        if original_max_retries is not None:
            if original_max_retries != max_retries:
                warnings.append(
                    f"max_retries was clamped from {original_max_retries} to {max_retries}"
                )
            if max_retries != self._config.max_retries_default:
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
                original_url=original_url if original_url != url else None,
                is_success=True,
                metadata={
                    "max_retries": max_retries,
                    "has_optional_params": True,
                    "original_max_retries": original_max_retries,
                },
                warnings=warnings,
            )
        
        return URLRuleResult(
            action=URLAction.CREATE,
            scenario=URLScenario.NORMAL,
            message=self._get_message(URLScenario.NORMAL, url=url),
            url=url,
            original_url=original_url if original_url != url else None,
            is_success=True,
            metadata={
                "max_retries": max_retries,
                "has_optional_params": False,
            },
            warnings=warnings,
        )

    def _evaluate_existing_url(
        self,
        url: str,
        original_url: str,
        existing_record: CrawledURL,
    ) -> URLRuleResult:
        """Evaluate rules for an existing URL.

        Decision Boundary (highest priority first):
        
        1. DIRTY_DATA_WARNING:
           - Status is "in_progress" and beyond threshold
           - OR contradictory status/is_success
           - OR abnormal timestamps
        
        2. CIRCULAR_DEPENDENCY:
           - Status is "completed" AND is_success is True
           - OR status is "in_progress"
        
        3. DUPLICATE_DEPENDENCY:
           - Status is "pending"
           - OR status is "failed"

        Args:
            url: Normalized URL
            original_url: Original URL before normalization
            existing_record: The existing database record

        Returns:
            URLRuleResult
        """
        warnings: List[str] = []
        
        status = self._safe_getattr(existing_record, "status")
        is_success = self._safe_getattr(existing_record, "is_success", False)
        started_at = self._safe_getattr(existing_record, "started_at")
        completed_at = self._safe_getattr(existing_record, "completed_at")
        retry_count = self._safe_getattr(existing_record, "retry_count", 0)
        max_retries_val = self._safe_getattr(existing_record, "max_retries", 3)
        
        if status is not None and not self._config.is_valid_status(status):
            warnings.append(f"Unknown status value: {status!r}")
            status = "pending"
        
        if status == "completed" and not is_success:
            warnings.append("Inconsistent state: status='completed' but is_success=False")
        
        if status == "failed" and is_success:
            warnings.append("Inconsistent state: status='failed' but is_success=True")
        
        if completed_at is not None and started_at is not None:
            try:
                if completed_at < started_at:
                    warnings.append(
                        f"Abnormal timestamps: completed_at ({completed_at}) < started_at ({started_at})"
                    )
            except TypeError:
                warnings.append("Unable to compare timestamps (mixed types)")
        
        if retry_count < 0:
            warnings.append(f"Negative retry_count: {retry_count}")
            retry_count = 0
        
        if max_retries_val < 0:
            warnings.append(f"Negative max_retries: {max_retries_val}")
            max_retries_val = self._config.max_retries_default
        
        dirty_data_check = self._is_dirty_data_with_safe_access(
            status=status,
            started_at=started_at,
            completed_at=completed_at,
        )
        
        if dirty_data_check["is_dirty"]:
            reason = dirty_data_check["reason"]
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
                original_url=original_url if original_url != url else None,
                existing_record=existing_record,
                is_success=False,
                metadata={
                    "status": status,
                    "started_at": started_at.isoformat() if started_at else None,
                    "completed_at": completed_at.isoformat() if completed_at else None,
                    "threshold_minutes": self._config.dirty_data_threshold_minutes,
                    "retry_count": retry_count,
                    "max_retries": max_retries_val,
                    "inconsistencies": warnings,
                },
                warnings=warnings,
            )
        
        if self._is_circular_dependency_with_safe_access(
            status=status,
            is_success=is_success,
        ):
            return URLRuleResult(
                action=URLAction.SKIP,
                scenario=URLScenario.CIRCULAR_DEPENDENCY,
                message=self._get_message(
                    URLScenario.CIRCULAR_DEPENDENCY,
                    url=url,
                    status=status,
                    time=completed_at.isoformat() if completed_at else "in progress",
                ),
                url=url,
                original_url=original_url if original_url != url else None,
                existing_record=existing_record,
                is_success=True,
                metadata={
                    "status": status,
                    "is_success": is_success,
                    "completed_at": completed_at.isoformat() if completed_at else None,
                },
                warnings=warnings,
            )
        
        if self._is_duplicate_with_safe_access(status=status):
            return URLRuleResult(
                action=URLAction.SKIP,
                scenario=URLScenario.DUPLICATE_DEPENDENCY,
                message=self._get_message(
                    URLScenario.DUPLICATE_DEPENDENCY,
                    url=url,
                    status=status,
                ),
                url=url,
                original_url=original_url if original_url != url else None,
                existing_record=existing_record,
                is_success=True,
                metadata={
                    "status": status,
                    "retry_count": retry_count,
                    "max_retries": max_retries_val,
                },
                warnings=warnings,
            )
        
        return URLRuleResult(
            action=URLAction.SKIP,
            scenario=URLScenario.DUPLICATE_DEPENDENCY,
            message=self._get_message(
                URLScenario.DUPLICATE_DEPENDENCY,
                url=url,
                status=status or "unknown",
            ),
            url=url,
            original_url=original_url if original_url != url else None,
            existing_record=existing_record,
            is_success=True,
            metadata={"status": status},
            warnings=warnings,
        )

    def _is_dirty_data_with_safe_access(
        self,
        status: Optional[str],
        started_at: Optional[datetime],
        completed_at: Optional[datetime],
    ) -> Dict[str, Any]:
        """Check if a record represents dirty/inconsistent data.

        Args:
            status: The status string (safely accessed)
            started_at: Start timestamp (safely accessed)
            completed_at: Completed timestamp (safely accessed)

        Returns:
            Dict with 'is_dirty' (bool) and 'reason' (str)
        """
        if status != "in_progress":
            return {"is_dirty": False, "reason": ""}
        
        if completed_at is not None:
            return {"is_dirty": False, "reason": ""}
        
        if started_at is None:
            return {
                "is_dirty": True,
                "reason": "Inconsistent state: 'in_progress' but started_at is None"
            }
        
        try:
            threshold = timedelta(minutes=self._config.dirty_data_threshold_minutes)
            elapsed = utc_now() - started_at
            
            if elapsed > threshold:
                elapsed_mins = int(elapsed.total_seconds() / 60)
                return {
                    "is_dirty": True,
                    "reason": (
                        f"Stuck 'in_progress' for {elapsed_mins} minutes "
                        f"(threshold: {self._config.dirty_data_threshold_minutes} min)"
                    )
                }
        except Exception as e:
            return {
                "is_dirty": True,
                "reason": f"Unable to calculate elapsed time: {e}"
            }
        
        return {"is_dirty": False, "reason": ""}

    def _is_circular_dependency_with_safe_access(
        self,
        status: Optional[str],
        is_success: bool,
    ) -> bool:
        """Check if a record represents a circular dependency.

        Args:
            status: The status string (safely accessed)
            is_success: Whether the crawl was successful (safely accessed)

        Returns:
            True if this is a circular dependency
        """
        if status == "completed" and is_success:
            return True
        
        if status == "in_progress":
            return True
        
        return False

    def _is_duplicate_with_safe_access(self, status: Optional[str]) -> bool:
        """Check if a record represents a duplicate dependency.

        Args:
            status: The status string (safely accessed)

        Returns:
            True if this is a duplicate dependency
        """
        if status == "pending":
            return True
        
        if status == "failed":
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
            normalized_url = self._normalize_url(url)
            existing = existing_records.get(url) or existing_records.get(normalized_url)
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
                "invalid_input": 0,
            },
            "by_action": {
                "create": 0,
                "skip": 0,
                "update": 0,
                "warn": 0,
                "error": 0,
            },
            "success_count": 0,
            "warning_count": 0,
            "error_count": 0,
            "warnings": [],
        }

        scenario_map = {
            URLScenario.NEW_OPTIONAL: "new_optional",
            URLScenario.DUPLICATE_DEPENDENCY: "duplicate_dependency",
            URLScenario.CIRCULAR_DEPENDENCY: "circular_dependency",
            URLScenario.DIRTY_DATA_WARNING: "dirty_data_warning",
            URLScenario.NORMAL: "normal",
            URLScenario.INVALID_INPUT: "invalid_input",
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
            
            if result.is_success:
                stats["success_count"] += 1
            
            if result.needs_warning:
                stats["warning_count"] += 1
                stats["warnings"].append({
                    "url": result.url,
                    "message": result.message,
                    "scenario": scenario_map[result.scenario],
                    "warnings": result.warnings,
                })
            
            if result.action == URLAction.ERROR:
                stats["error_count"] += 1

        return stats
