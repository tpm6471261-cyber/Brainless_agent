"""Declarative, reusable building blocks for safely creating runtime agents."""
from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Iterable, Mapping


_RISK_POLICIES = frozenset({"low", "medium", "high", "critical"})


def _bounded_text(value: object, label: str, maximum: int = 500) -> str:
    text = str(value).strip()
    if not text or len(text) > maximum:
        raise ValueError(f"{label} is required and must contain at most {maximum} characters")
    return text


def _string_set(values: Iterable[object], label: str, maximum: int = 100) -> frozenset[str]:
    if isinstance(values, (str, bytes)):
        raise ValueError(f"{label} must be a list of strings")
    result = frozenset(str(value).strip() for value in values)
    if "" in result or len(result) > maximum:
        raise ValueError(f"{label} contains an empty value or exceeds {maximum} entries")
    return result


@dataclass(frozen=True, slots=True)
class AgentDefinition:
    """Portable agent configuration; it contains no executable code or new authority."""

    name: str
    role: str
    objective: str
    task: str | None = None
    permissions: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()
    subscriptions: frozenset[str] = frozenset()
    context: Mapping[str, str] = field(default_factory=dict)
    resource_limits: Mapping[str, float] = field(default_factory=dict)
    allowed_applications: frozenset[str] = frozenset()
    allowed_directories: frozenset[str] = frozenset()
    risk_policy: str = "medium"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "AgentDefinition":
        """Validate an untrusted dashboard/CLI mapping into a definition."""
        if not isinstance(value, Mapping):
            raise ValueError("Agent definition must be an object")
        allowed = {item.name for item in fields(cls)}
        unknown = set(value) - allowed
        if unknown:
            raise ValueError(f"Unknown agent fields: {', '.join(sorted(unknown))}")
        name = _bounded_text(value.get("name", ""), "Agent name", 100)
        role = _bounded_text(value.get("role", ""), "Agent role", 100)
        objective = _bounded_text(value.get("objective", ""), "Agent objective", 2_000)
        task_value = value.get("task")
        task = None if task_value in (None, "") else _bounded_text(task_value, "Agent task", 4_000)
        risk = str(value.get("risk_policy", "medium")).strip().casefold()
        if risk not in _RISK_POLICIES:
            raise ValueError("risk_policy must be low, medium, high, or critical")
        context = value.get("context", {})
        limits = value.get("resource_limits", {})
        if not isinstance(context, Mapping) or len(context) > 100:
            raise ValueError("context must be an object with at most 100 entries")
        if not isinstance(limits, Mapping) or len(limits) > 20:
            raise ValueError("resource_limits must be an object with at most 20 entries")
        parsed_limits = {str(key): float(number) for key, number in limits.items()}
        if any(number <= 0 or number != number or number == float("inf") for number in parsed_limits.values()):
            raise ValueError("resource limits must be finite positive numbers")
        return cls(name, role, objective, task,
                   _string_set(value.get("permissions", ()), "permissions"),
                   _string_set(value.get("tools", ()), "tools"),
                   _string_set(value.get("subscriptions", ()), "subscriptions"),
                   {str(key): str(item) for key, item in context.items()}, parsed_limits,
                   _string_set(value.get("allowed_applications", ()), "allowed_applications"),
                   _string_set(value.get("allowed_directories", ()), "allowed_directories"), risk)

    def create(self, manager, parent_agent_id: str):
        """Create a child while preserving the manager's parent/tool authority checks."""
        parent = manager.get_agent(parent_agent_id)
        if parent.allowed_applications and not self.allowed_applications.issubset(parent.allowed_applications):
            raise PermissionError("Child application boundary exceeds its parent")
        if parent.allowed_directories:
            roots = tuple(Path(item).expanduser().resolve() for item in parent.allowed_directories)
            if any(not any(Path(item).expanduser().resolve().is_relative_to(root) for root in roots)
                   for item in self.allowed_directories):
                raise PermissionError("Child directory boundary exceeds its parent")
        child = manager.create_agent(parent_agent_id, self.name, self.role, self.objective,
                                     self.task, set(self.permissions), set(self.tools), dict(self.context))
        child.resource_limits = dict(self.resource_limits)
        child.allowed_applications = set(self.allowed_applications or parent.allowed_applications)
        child.allowed_directories = set(self.allowed_directories or parent.allowed_directories)
        child.risk_policy = self.risk_policy
        manager.set_event_subscriptions(parent_agent_id, child.agent_id, set(self.subscriptions))
        return child


def create_agent(manager, parent_agent_id: str, **configuration: Any):
    """Functional building block for Python callers."""
    return AgentDefinition.from_mapping(configuration).create(manager, parent_agent_id)
