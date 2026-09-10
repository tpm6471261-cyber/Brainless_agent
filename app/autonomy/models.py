"""Structured, provider-independent contracts for autonomous execution."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4


class ErrorCode(str, Enum):
    PERMISSION_DENIED = "PERMISSION_DENIED"
    CAPABILITY_UNAVAILABLE = "CAPABILITY_UNAVAILABLE"
    TOOL_NOT_FOUND = "TOOL_NOT_FOUND"
    INVALID_ARGUMENT = "INVALID_ARGUMENT"
    RESOURCE_BUSY = "RESOURCE_BUSY"
    ACTION_FAILED = "ACTION_FAILED"
    ACTION_TIMEOUT = "ACTION_TIMEOUT"
    VERIFICATION_FAILED = "VERIFICATION_FAILED"
    POLICY_DENIED = "POLICY_DENIED"
    APPROVAL_REQUIRED = "APPROVAL_REQUIRED"


class RuntimeErrorDetail(RuntimeError):
    def __init__(self, code: ErrorCode, message: str) -> None:
        self.code = code
        super().__init__(f"{code.value}: {message}")


@dataclass(frozen=True, slots=True)
class ComputerState:
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    active_application: str | None = None
    active_window: str | None = None
    screen_size: tuple[int, int] | None = None
    screenshot_reference: str | None = None
    cursor_position: tuple[int, int] | None = None
    visible_ui: tuple[str, ...] = ()
    browser_url: str | None = None
    browser_title: str | None = None
    clipboard: str | None = None
    running_processes: tuple[str, ...] = ()
    recent_actions: tuple[str, ...] = ()
    last_action_result: str | None = None
    errors: tuple[str, ...] = ()
    progress: str | None = None

    def compact(self, fields: set[str]) -> dict[str, Any]:
        """Return only a decision provider's requested context fields."""
        return {field: getattr(self, field) for field in fields if hasattr(self, field)}

    def diff(self, later: "ComputerState") -> dict[str, tuple[Any, Any]]:
        """Return the observable fields changed by an action; timestamps are not state changes."""
        return {field: (getattr(self, field), getattr(later, field)) for field in self.__dataclass_fields__
                if field != "timestamp" and getattr(self, field) != getattr(later, field)}


@dataclass(frozen=True, slots=True)
class ComputerAction:
    action_type: str
    arguments: dict[str, Any]
    agent_id: str
    task_id: str
    reason: str
    permission: str
    expected_state: dict[str, Any] = field(default_factory=dict)
    action_id: str = field(default_factory=lambda: str(uuid4()))
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


@dataclass(frozen=True, slots=True)
class ActionProposal:
    """Untrusted reasoning output; the runtime supplies identity and permission."""
    action_type: str
    arguments: dict[str, Any]
    reason: str
    expected_state: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class DecisionContext:
    agent_id: str
    task_id: str
    task: str
    state: dict[str, Any]
    previous: "ActionResult | None" = None


@dataclass(frozen=True, slots=True)
class ActionResult:
    action_id: str
    success: bool
    output: Any = None
    error: str | None = None
    verified: bool = False
    duration_ms: float = 0.0


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    role: str
    objective: str
    task: str
    required_capabilities: frozenset[str]
    tools: frozenset[str]
    task_id: str | None = None
    constraints: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TaskRequirements:
    capabilities: frozenset[str]
    permissions: frozenset[str]
    tools: frozenset[str]
    role: str


@dataclass(frozen=True, slots=True)
class AuditRecord:
    timestamp: datetime
    agent_id: str
    parent_agent_id: str | None
    task_id: str
    action_id: str
    tool: str
    permission: str
    arguments: dict[str, Any]
    result: str | None
    error: str | None
    duration_ms: float
    policy_decision: str
    approval_status: str
