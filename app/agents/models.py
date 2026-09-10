"""Typed models for the runtime-owned agent hierarchy."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class AgentStatus(str, Enum):
    CREATED = "created"
    READY = "ready"
    RUNNING = "running"
    WAITING = "waiting"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"
    TERMINATED = "terminated"


class EventType(str, Enum):
    TASK = "task"
    STATUS = "status"
    RESULT = "result"
    ERROR = "error"
    PROGRESS = "progress"
    PERMISSION_DENIED = "permission_denied"
    TOOL = "tool"


@dataclass(frozen=True, slots=True)
class AgentEvent:
    type: EventType
    agent_id: str
    parent_agent_id: str | None
    task_id: str | None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    detail: str = ""
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolExecution:
    tool_id: str
    timestamp: datetime
    success: bool
    detail: str = ""


@dataclass(slots=True)
class Agent:
    name: str
    role: str
    objective: str
    current_task: str | None = None
    current_task_id: str | None = None
    parent_agent_id: str | None = None
    permissions: set[str] = field(default_factory=set)
    available_tools: set[str] = field(default_factory=set)
    context: dict[str, str] = field(default_factory=dict)
    agent_id: str = field(default_factory=lambda: str(uuid4()))
    status: AgentStatus = AgentStatus.CREATED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    child_agents: list[str] = field(default_factory=list)
    execution_history: list[ToolExecution] = field(default_factory=list)
    result: str | None = None
    error: str | None = None
    retries: int = 0
