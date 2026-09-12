"""Normalized event, subscription, condition, and action contracts."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

class EventSeverity(str, Enum):
    DEBUG="debug"; INFO="info"; WARNING="warning"; ERROR="error"; CRITICAL="critical"

@dataclass(frozen=True, slots=True)
class Event:
    event_type: str
    category: str
    source: str
    data: dict[str, Any] = field(default_factory=dict)
    process: str | None = None
    window: str | None = None
    user: str | None = None
    severity: EventSeverity = EventSeverity.INFO
    confidence: float = 1.0
    permissions_required: frozenset[str] = frozenset()
    parent_event_id: str | None = None
    priority: int = 0
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    event_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not self.event_type or not self.category or not self.source: raise ValueError("Event identity fields are required")
        if not 0 <= self.confidence <= 1: raise ValueError("Event confidence must be between zero and one")

@dataclass(frozen=True, slots=True)
class EventFilter:
    event_types: frozenset[str] = frozenset()
    categories: frozenset[str] = frozenset()
    processes: frozenset[str] = frozenset()
    windows: frozenset[str] = frozenset()
    minimum_severity: EventSeverity = EventSeverity.DEBUG
    conditions: dict[str, Any] = field(default_factory=dict)

    def matches(self, event: Event) -> bool:
        if self.event_types and "*" not in self.event_types and event.event_type not in self.event_types: return False
        if self.categories and event.category not in self.categories: return False
        if self.processes and (event.process or "").casefold() not in {x.casefold() for x in self.processes}: return False
        if self.windows and not any(x.casefold() in (event.window or "").casefold() for x in self.windows): return False
        order = list(EventSeverity)
        if order.index(event.severity) < order.index(self.minimum_severity): return False
        return ConditionEngine.matches(event.data, self.conditions)

class ConditionEngine:
    """Evaluate nested AND/OR/NOT and field comparison expressions."""
    @classmethod
    def matches(cls, data: dict[str, Any], expression: dict[str, Any]) -> bool:
        if not expression: return True
        if "AND" in expression: return all(cls.matches(data, item) for item in expression["AND"])
        if "OR" in expression: return any(cls.matches(data, item) for item in expression["OR"])
        if "NOT" in expression: return not cls.matches(data, expression["NOT"])
        field, operator, expected = expression.get("field"), expression.get("operator", "equals"), expression.get("value")
        actual = data.get(field); exists = field in data
        operations = {
            "equals": lambda: actual == expected, "not_equals": lambda: actual != expected,
            "contains": lambda: str(expected) in str(actual), "starts_with": lambda: str(actual).startswith(str(expected)),
            "ends_with": lambda: str(actual).endswith(str(expected)), "regex": lambda: __import__("re").search(str(expected), str(actual)) is not None,
            "greater_than": lambda: actual > expected, "less_than": lambda: actual < expected,
            "greater_or_equal": lambda: actual >= expected, "less_or_equal": lambda: actual <= expected,
            "exists": lambda: exists, "not_exists": lambda: not exists,
            "changed": lambda: actual != data.get(f"previous_{field}"),
            "changed_from": lambda: data.get(f"previous_{field}") == expected and actual != expected,
            "changed_to": lambda: actual == expected and data.get(f"previous_{field}") != expected,
        }
        try: return bool(operations[operator]())
        except (KeyError, TypeError, ValueError): return False

@dataclass(frozen=True, slots=True)
class EventSubscription:
    subscriber_id: str
    event_filter: EventFilter
    debounce_seconds: float = 0
    throttle_seconds: float = 0

class ActionStatus(str, Enum):
    SUCCESS="success"; FAILED="failed"; DENIED="denied"; TIMEOUT="timeout"; NOT_FOUND="not_found"; NOT_SUPPORTED="not_supported"; CANCELLED="cancelled"

@dataclass(frozen=True, slots=True)
class ActionResult:
    status: ActionStatus
    message: str
    data: Any = None
    error: str | None = None
    duration_ms: float = 0
    @property
    def success(self) -> bool: return self.status is ActionStatus.SUCCESS
