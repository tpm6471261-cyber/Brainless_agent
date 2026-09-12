"""Composable building blocks for creating permission-bounded event agents."""
from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from time import monotonic
from typing import Any

from app.event_system.actions import ActionRegistry
from app.event_system.models import ActionResult, ActionStatus, Event


@dataclass(frozen=True, slots=True)
class AgentBlueprint:
    """Declarative child-agent boundary; authority must still come from its parent."""

    name: str
    purpose: str
    permissions: frozenset[str] = frozenset()
    tools: frozenset[str] = frozenset()
    subscriptions: frozenset[str] = frozenset()
    resource_limits: Mapping[str, float] = field(default_factory=dict)
    maximum_runtime: float | None = None
    allowed_applications: frozenset[str] = frozenset()
    allowed_directories: frozenset[str] = frozenset()
    risk_policy: str = "medium"

    def create(self, manager, parent_agent_id: str, *, task: str | None = None):
        agent = manager.create_agent(parent_agent_id, self.name, self.purpose, self.purpose,
            task=task, permissions=set(self.permissions), tools=set(self.tools))
        manager.set_event_subscriptions(parent_agent_id, agent.agent_id, set(self.subscriptions))
        agent.resource_limits = dict(self.resource_limits)
        if self.maximum_runtime is not None: agent.resource_limits["max_runtime"] = self.maximum_runtime
        agent.allowed_applications = set(self.allowed_applications)
        agent.allowed_directories = set(self.allowed_directories)
        agent.risk_policy = self.risk_policy
        return agent

def create_event_agent(manager, parent_agent_id: str, *, name: str, purpose: str,
                       permissions=(), tools=(), subscriptions=(), resource_limits=None,
                       maximum_runtime=None, allowed_applications=(), allowed_directories=(),
                       risk_policy="medium", task=None):
    """Functional agent factory for callers that do not need to retain a blueprint."""
    return AgentBlueprint(name=name,purpose=purpose,permissions=frozenset(permissions),
        tools=frozenset(tools),subscriptions=frozenset(subscriptions),
        resource_limits=dict(resource_limits or {}),maximum_runtime=maximum_runtime,
        allowed_applications=frozenset(allowed_applications),allowed_directories=frozenset(allowed_directories),
        risk_policy=risk_policy).create(manager,parent_agent_id,task=task)

def discover_agent_actions(registry: ActionRegistry, agent) -> tuple[dict[str, Any], ...]:
    """Return serializable action metadata filtered to an agent's current authority."""
    return tuple({"action_name":spec.action_name,"description":spec.description,"category":spec.category,
        "required_permissions":sorted(spec.required_permissions),"risk_level":spec.risk_level.value,
        "input_schema":sorted(spec.input_schema),"output_schema":spec.output_schema}
        for spec in registry.available(agent.permissions))


class AgentResourceLimiter:
    """Enforce event/action rate and concurrency limits without granting authority."""

    def __init__(self) -> None:
        self._events: dict[str, deque[float]] = defaultdict(deque)
        self._actions: dict[str, deque[float]] = defaultdict(deque)
        self._active: dict[str, int] = defaultdict(int)

    @staticmethod
    def _within(bucket: deque[float], limit: float) -> bool:
        now = monotonic()
        while bucket and now - bucket[0] >= 60: bucket.popleft()
        if len(bucket) >= limit: return False
        bucket.append(now)
        return True

    def allow_event(self, agent) -> bool:
        limit = agent.resource_limits.get("max_event_rate")
        return True if limit is None else self._within(self._events[agent.agent_id], limit)

    def begin_action(self, agent) -> bool:
        runtime = agent.resource_limits.get("max_runtime")
        if runtime is not None and (datetime.now(timezone.utc)-agent.created_at).total_seconds() >= runtime:return False
        concurrent = agent.resource_limits.get("max_concurrent_actions")
        per_minute = agent.resource_limits.get("max_actions_per_minute")
        if concurrent is not None and self._active[agent.agent_id] >= concurrent: return False
        if per_minute is not None and not self._within(self._actions[agent.agent_id], per_minute): return False
        self._active[agent.agent_id] += 1
        return True

    def end_action(self, agent) -> None:
        self._active[agent.agent_id] = max(0, self._active[agent.agent_id] - 1)


class AgentActionExecutor:
    """One-call bridge from an agent to the action registry with scope enforcement."""

    def __init__(self, registry: ActionRegistry, limiter: AgentResourceLimiter | None = None) -> None:
        self.registry, self.limiter = registry, limiter or AgentResourceLimiter()

    async def execute(self, agent, action_name: str, **arguments: Any) -> ActionResult:
        spec = self.registry.get(action_name)
        if spec is not None and spec.category == "filesystem" and agent.allowed_directories:
            roots = tuple(Path(root).expanduser().resolve() for root in agent.allowed_directories)
            for key in ("path", "source", "destination"):
                if key in arguments and not any(Path(arguments[key]).expanduser().resolve().is_relative_to(root) for root in roots):
                    return ActionResult(ActionStatus.DENIED, "Path is outside the agent directory boundary")
        if spec is not None and spec.category == "process" and agent.allowed_applications and "command" in arguments:
            executable = Path(str(arguments["command"][0])).name.casefold()
            if executable not in {Path(item).name.casefold() for item in agent.allowed_applications}:
                return ActionResult(ActionStatus.DENIED, "Application is outside the agent boundary")
        if not self.limiter.begin_action(agent):
            return ActionResult(ActionStatus.DENIED, "Agent resource limit reached")
        try:
            return await self.registry.execute(action_name, arguments, agent.permissions)
        finally:
            self.limiter.end_action(agent)


class EventAgentRuntime:
    """Connect EventBus delivery to permission-scoped agents and their handler."""

    def __init__(self, bus, dispatcher, *, limiter: AgentResourceLimiter | None = None) -> None:
        self.bus, self.dispatcher = bus, dispatcher
        self.limiter = limiter or AgentResourceLimiter()
        self.dispatcher.limiter = self.limiter

    async def handle(self, event: Event) -> tuple[str, ...]:
        return await self.dispatcher.dispatch(event)


Step = Callable[[dict[str, Any]], Awaitable[Any] | Any]


class EventChain:
    """Execute reusable workflow steps with timeout, retry, branching, loops and parallelism."""

    def __init__(self, *, timeout: float = 60) -> None:
        self.steps: list[Step] = []; self.timeout = timeout

    def then(self, step: Step) -> "EventChain": self.steps.append(step); return self

    def delay(self, seconds: float) -> "EventChain":
        async def pause(_): await asyncio.sleep(seconds)
        return self.then(pause)

    def action(self, executor: AgentActionExecutor, agent, name: str, arguments: Mapping[str, Any]) -> "EventChain":
        return self.then(lambda context: executor.execute(agent, name,
            **{key: (context[value[1:]] if isinstance(value, str) and value.startswith("$") else value)
               for key, value in arguments.items()}))

    def branch(self, predicate: Callable[[dict[str, Any]], bool], yes: Step, no: Step | None = None) -> "EventChain":
        return self.then(lambda context: yes(context) if predicate(context) else no(context) if no else None)

    def parallel(self, *steps: Step) -> "EventChain":
        async def run(context): return await asyncio.gather(*(self._invoke(step, context) for step in steps))
        return self.then(run)

    def repeat(self, step: Step, count: int) -> "EventChain":
        async def run(context): return [await self._invoke(step, context) for _ in range(max(0, count))]
        return self.then(run)

    def retry(self, step: Step, attempts: int = 3, backoff: float = .1) -> "EventChain":
        async def run(context):
            for attempt in range(max(1, attempts)):
                try: return await self._invoke(step, context)
                except Exception:
                    if attempt + 1 == attempts: raise
                    await asyncio.sleep(backoff * 2 ** attempt)
        return self.then(run)

    @staticmethod
    async def _invoke(step: Step, context: dict[str, Any]) -> Any:
        result = step(context)
        return await result if isinstance(result, Awaitable) else result

    async def run(self, event: Event | Mapping[str, Any] | None = None,
                  variables: Mapping[str, Any] | None = None) -> dict[str, Any]:
        context = dict(event) if isinstance(event, Mapping) else {"event": event}
        context.update(variables or {})
        async def execute():
            for index, step in enumerate(self.steps): context[f"step_{index}"] = await self._invoke(step, context)
            return context
        return await asyncio.wait_for(execute(), self.timeout)
