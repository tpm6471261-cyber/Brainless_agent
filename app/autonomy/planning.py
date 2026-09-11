"""Validated plan and context boundaries for autonomous goals.

Planners may propose plans, but this module never executes their text.  The runtime
validates a plan against the parent agent, registered tools, and contracts first.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Any

from app.autonomy.models import TaskRequirements
from app.autonomy.task_graph import TaskGraph
from app.autonomy.world_state import WorldSnapshot


class ContentTrust(str, Enum):
    SYSTEM_POLICY = "system_policy"
    USER_GOAL = "user_goal"
    AGENT_PLAN = "agent_plan"
    EXTERNAL = "external"


@dataclass(frozen=True, slots=True)
class TaskContext:
    objective: str
    world: dict[str, Any]
    constraints: dict[str, Any]
    permissions: frozenset[str]
    dependencies: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    expected_output: str = ""
    external_content: tuple[str, ...] = ()


class TaskContextManager:
    """Produces minimal child context and retains untrusted data as data only."""
    def build(self, objective: str, snapshot: WorldSnapshot, requirements: TaskRequirements,
              *, constraints: dict[str, Any] | None = None, dependencies: tuple[str, ...] = (),
              failures: tuple[str, ...] = (), external_content: tuple[str, ...] = ()) -> TaskContext:
        observed = {key: fact.value for key, fact in snapshot.facts.items() if fact.kind.value == "observed"}
        return TaskContext(objective, observed, dict(constraints or {}), requirements.permissions,
                           dependencies, failures, external_content=external_content)


class PlanValidator:
    def validate(self, graph: TaskGraph, *, available_capabilities: frozenset[str],
                 available_permissions: frozenset[str], known_tools: frozenset[str],
                 contracted_tools: frozenset[str]) -> None:
        graph.validate()
        for task in graph.tasks.values():
            if not task.capabilities.issubset(available_capabilities):
                raise ValueError(f"Task {task.task_id} requires unavailable capabilities")
            if not task.permissions.issubset(available_permissions):
                raise ValueError(f"Task {task.task_id} requests unavailable permissions")
            if task.tool and task.tool not in known_tools:
                raise ValueError(f"Task {task.task_id} references unknown tool")
            if task.tool and task.tool not in contracted_tools:
                raise ValueError(f"Task {task.task_id} has no action contract")
            if task.high_risk and not task.requires_approval:
                raise ValueError(f"High-risk task {task.task_id} must require approval")
