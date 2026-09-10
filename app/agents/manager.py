"""Async supervisor for isolated child agents and permission-gated tools."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from app.agents.models import Agent, AgentEvent, AgentStatus, EventType, ToolExecution
from app.agents.tools import ToolRegistry
from app.safety.permissions import PermissionDenied, PermissionPolicy
from app.safety.leases import CapabilityLease, CapabilityLeaseRegistry

AgentExecutor = Callable[[Agent, "AgentManager"], Awaitable[str]]


class AgentManager:
    def __init__(self, tools: ToolRegistry | None = None, policy: PermissionPolicy | None = None,
                 max_retries: int = 1, audit_store=None) -> None:
        self.tools = tools or ToolRegistry()
        self.policy = policy or PermissionPolicy()
        self.max_retries = max_retries
        self._agents: dict[str, Agent] = {}
        self.events: list[AgentEvent] = []
        self._running: dict[str, asyncio.Task[str]] = {}
        self._audit_store = audit_store
        self.leases = CapabilityLeaseRegistry()

    def create_root(self, name: str, role: str, objective: str, permissions: set[str]) -> Agent:
        if any(agent.parent_agent_id is None for agent in self._agents.values()):
            raise ValueError("Only one root agent may be created per manager")
        root = Agent(name=name, role=role, objective=objective, permissions=set(permissions), status=AgentStatus.READY)
        self._agents[root.agent_id] = root
        self._event(root, EventType.STATUS, "Root agent created")
        return root

    def create_agent(self, parent_agent_id: str, name: str, role: str, objective: str,
                     task: str | None = None, permissions: set[str] | None = None,
                     tools: set[str] | None = None, context: dict[str, str] | None = None,
                     task_id: str | None = None) -> Agent:
        parent = self.get_agent(parent_agent_id)
        requested = set(permissions or ())
        missing = requested - parent.permissions
        if missing:
            permission = sorted(missing)[0]
            self._deny(parent_agent_id, parent.parent_agent_id, permission, "Parent does not possess this permission")
            raise PermissionDenied(parent_agent_id, permission, "Parent does not possess this permission")
        allowed_tools = set(tools or ())
        for tool_id in allowed_tools:
            required = self.tools.get(tool_id).required_permissions
            if not required.issubset(requested):
                permission = sorted(required - requested)[0]
                self._deny(parent_agent_id, parent.parent_agent_id, permission, "Child lacks required tool permission")
                raise PermissionDenied(parent_agent_id, permission, "Child lacks required tool permission")
        child_context = dict(context or {})
        resolved_task_id = task_id or child_context.get("task_id") or (str(uuid4()) if task is not None else None)
        if resolved_task_id is not None:
            child_context["task_id"] = resolved_task_id
        child = Agent(name=name, role=role, objective=objective, current_task=task, current_task_id=resolved_task_id, parent_agent_id=parent_agent_id,
                      permissions=requested, available_tools=allowed_tools, context=child_context,
                      status=AgentStatus.READY)
        self._agents[child.agent_id] = child
        parent.child_agents.append(child.agent_id)
        self._event(child, EventType.TASK, task or "Agent created")
        return child

    def get_agent(self, agent_id: str) -> Agent:
        try:
            return self._agents[agent_id]
        except KeyError as error:
            raise KeyError(f"Unknown agent: {agent_id}") from error

    def list_agents(self) -> tuple[Agent, ...]:
        return tuple(self._agents.values())

    def get_children(self, agent_id: str) -> tuple[Agent, ...]:
        return tuple(self.get_agent(child_id) for child_id in self.get_agent(agent_id).child_agents)

    def get_agent_tree(self, agent_id: str) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        return {"agent_id": agent.agent_id, "name": agent.name,
                "children": [self.get_agent_tree(child.agent_id) for child in self.get_children(agent_id)]}

    def assign_task(self, parent_agent_id: str, agent_id: str, task: str, context: dict[str, str] | None = None,
                    task_id: str | None = None) -> None:
        agent = self._owned_child(parent_agent_id, agent_id)
        if agent.status is AgentStatus.TERMINATED:
            raise RuntimeError("Cannot assign a task to a terminated agent")
        resolved_task_id = task_id or str(uuid4())
        agent.current_task, agent.current_task_id, agent.context, agent.result, agent.error = task, resolved_task_id, dict(context or {}), None, None
        agent.context["task_id"] = resolved_task_id
        agent.status = AgentStatus.READY
        self._event(agent, EventType.TASK, task)

    def grant_permission(self, parent_agent_id: str, agent_id: str, permission: str) -> None:
        """Grant a direct child a parent-owned capability; self-escalation is impossible."""
        parent, child = self.get_agent(parent_agent_id), self._owned_child(parent_agent_id, agent_id)
        if permission not in parent.permissions:
            self._deny(parent.agent_id, parent.parent_agent_id, permission, "Parent does not possess this permission")
            raise PermissionDenied(parent.agent_id, permission, "Parent does not possess this permission")
        child.permissions.add(permission)
        self._event(child, EventType.STATUS, "Permission granted", {"permission": permission})

    def revoke_permission(self, parent_agent_id: str, agent_id: str, permission: str) -> None:
        child = self._owned_child(parent_agent_id, agent_id)
        child.permissions.discard(permission)
        self._event(child, EventType.STATUS, "Permission revoked", {"permission": permission})

    def lease_permission(self, parent_agent_id: str, agent_id: str, permission: str,
                         task_id: str, seconds: int = 300) -> CapabilityLease:
        """Temporarily delegate parent-owned authority to one agent and task."""
        parent, child = self.get_agent(parent_agent_id), self._owned_child(parent_agent_id, agent_id)
        if permission not in parent.permissions or child.current_task_id != task_id:
            self._deny(child.agent_id, child.parent_agent_id, permission, "Lease authority or task scope is invalid")
            raise PermissionDenied(child.agent_id, permission, "Lease authority or task scope is invalid")
        lease = self.leases.grant(child.agent_id, permission, task_id, seconds)
        self._event(child, EventType.STATUS, "Capability leased", {"permission": permission,
                    "task_id": task_id, "lease_id": lease.lease_id, "expires_at": lease.expires_at.isoformat()})
        return lease

    def grant_tool(self, parent_agent_id: str, agent_id: str, tool_id: str) -> None:
        """Authorize a registered tool for a direct child after its permissions exist."""
        child = self._owned_child(parent_agent_id, agent_id)
        tool = self.tools.get(tool_id)
        missing = tool.required_permissions - child.permissions
        if missing:
            permission = sorted(missing)[0]
            self._deny(child.agent_id, child.parent_agent_id, permission, "Child lacks required tool permission")
            raise PermissionDenied(child.agent_id, permission, "Child lacks required tool permission")
        child.available_tools.add(tool_id)
        self._event(child, EventType.STATUS, "Tool granted", {"tool": tool_id})

    def report_progress(self, agent_id: str, detail: str) -> None:
        agent = self.get_agent(agent_id)
        self._event(agent, EventType.PROGRESS, detail)

    async def start_agent(self, parent_agent_id: str, agent_id: str, executor: AgentExecutor) -> str:
        agent = self._owned_child(parent_agent_id, agent_id)
        if agent.status is AgentStatus.TERMINATED:
            raise RuntimeError("Cannot start a terminated agent")
        if agent.status is AgentStatus.PAUSED:
            raise RuntimeError("Resume a paused agent before starting it")
        agent.status = AgentStatus.RUNNING
        self._event(agent, EventType.STATUS, "Agent started")
        task = asyncio.create_task(self._run(agent, executor))
        self._running[agent_id] = task
        try:
            return await task
        finally:
            self._running.pop(agent_id, None)

    async def start_parallel(self, parent_agent_id: str, agent_ids: list[str], executor: AgentExecutor) -> list[str]:
        return await asyncio.gather(*(self.start_agent(parent_agent_id, agent_id, executor) for agent_id in agent_ids))

    async def retry_agent(self, parent_agent_id: str, agent_id: str, executor: AgentExecutor) -> str:
        agent = self._owned_child(parent_agent_id, agent_id)
        if agent.status is not AgentStatus.FAILED:
            raise RuntimeError("Only failed agents may be retried")
        if agent.retries >= self.max_retries:
            raise RuntimeError("Agent retry limit reached")
        agent.retries += 1
        return await self.start_agent(parent_agent_id, agent_id, executor)

    def pause_agent(self, parent_agent_id: str, agent_id: str) -> None:
        agent = self._owned_child(parent_agent_id, agent_id)
        if agent.status is AgentStatus.RUNNING:
            agent.status = AgentStatus.PAUSED
            self._event(agent, EventType.STATUS, "Agent paused")

    def resume_agent(self, parent_agent_id: str, agent_id: str) -> None:
        agent = self._owned_child(parent_agent_id, agent_id)
        if agent.status is AgentStatus.PAUSED:
            agent.status = AgentStatus.READY
            self._event(agent, EventType.STATUS, "Agent resumed")

    def terminate_agent(self, parent_agent_id: str, agent_id: str) -> None:
        agent = self._owned_child(parent_agent_id, agent_id)
        running = self._running.get(agent_id)
        if running:
            running.cancel()
        agent.status = AgentStatus.TERMINATED
        self._event(agent, EventType.STATUS, "Agent terminated")

    def monitor_agent(self, parent_agent_id: str, agent_id: str) -> Agent:
        return self._owned_child(parent_agent_id, agent_id)

    def collect_result(self, parent_agent_id: str, agent_id: str) -> str:
        agent = self._owned_child(parent_agent_id, agent_id)
        if agent.status is not AgentStatus.COMPLETED or agent.result is None:
            raise RuntimeError("Agent has not completed successfully")
        return agent.result

    async def execute_tool(self, agent_id: str, tool_id: str, arguments: dict[str, Any]) -> Any:
        agent = self.get_agent(agent_id)
        if agent.status is not AgentStatus.RUNNING:
            raise RuntimeError("Only running agents may execute tools")
        if tool_id not in agent.available_tools:
            self._deny(agent.agent_id, agent.parent_agent_id, tool_id, "Tool was not granted to this agent")
            raise PermissionDenied(agent.agent_id, tool_id, "Tool was not granted to this agent")
        tool = self.tools.get(tool_id)
        for permission in tool.required_permissions:
            if permission not in agent.permissions and not self.leases.permits(
                    agent.agent_id, permission, agent.current_task_id):
                self._deny(agent.agent_id, agent.parent_agent_id, permission, "Agent does not possess this permission")
                raise PermissionDenied(agent.agent_id, permission, "Agent does not possess this permission")
            try:
                self.policy.check(agent.agent_id, permission)
            except PermissionDenied as error:
                self._deny(agent.agent_id, agent.parent_agent_id, permission, error.reason)
                raise
        try:
            result = await self.tools.invoke(tool_id, arguments)
        except Exception as error:
            agent.execution_history.append(ToolExecution(tool_id, datetime.now(timezone.utc), False, str(error)))
            self._event(agent, EventType.ERROR, str(error), {"tool": tool_id})
            raise
        agent.execution_history.append(ToolExecution(tool_id, datetime.now(timezone.utc), True))
        self._event(agent, EventType.TOOL, "Tool completed", {"tool": tool_id})
        return result

    async def _run(self, agent: Agent, executor: AgentExecutor) -> str:
        try:
            result = await executor(agent, self)
            if agent.status is AgentStatus.TERMINATED:
                raise asyncio.CancelledError
            agent.result, agent.status = result, AgentStatus.COMPLETED
            self._event(agent, EventType.RESULT, result)
            return result
        except asyncio.CancelledError:
            agent.status = AgentStatus.TERMINATED
            self._event(agent, EventType.STATUS, "Agent terminated")
            raise
        except Exception as error:
            agent.error, agent.status = str(error), AgentStatus.FAILED
            self._event(agent, EventType.ERROR, str(error))
            raise

    def _owned_child(self, parent_agent_id: str, agent_id: str) -> Agent:
        parent, child = self.get_agent(parent_agent_id), self.get_agent(agent_id)
        if child.parent_agent_id != parent.agent_id:
            raise PermissionDenied(parent.agent_id, agent_id, "Agent is not a direct child")
        return child

    def _event(self, agent: Agent, event_type: EventType, detail: str, metadata: dict[str, str] | None = None) -> None:
        event = AgentEvent(event_type, agent.agent_id, agent.parent_agent_id, agent.current_task,
                           detail=detail, metadata=metadata or {})
        self.events.append(event)
        if self._audit_store:
            self._audit_store.store_agent(agent)
            self._audit_store.store_agent_event(event)

    def _deny(self, agent_id: str, parent_agent_id: str | None, permission: str, reason: str) -> None:
        event = AgentEvent(EventType.PERMISSION_DENIED, agent_id, parent_agent_id, None,
                           detail=reason, metadata={"permission": permission})
        self.events.append(event)
        if self._audit_store:
            self._audit_store.store_agent_event(event)
