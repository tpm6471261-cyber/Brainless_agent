"""Validated factory: structured specifications, never arbitrary model objects."""
from __future__ import annotations

from app.agents.manager import AgentManager
from app.agents.models import Agent
from app.autonomy.models import AgentSpec
from app.safety.permissions import Permission


class AgentFactory:
    def __init__(self, manager: AgentManager) -> None:
        self.manager = manager

    def create(self, parent_agent_id: str, spec: AgentSpec) -> Agent:
        if not spec.name.strip() or not spec.role.strip() or not spec.required_capabilities:
            raise ValueError("Agent specification requires name, role, and capabilities")
        parent = self.manager.get_agent(parent_agent_id)
        unknown_tools = set(spec.tools) - set(self.manager.tools.tool_ids)
        if unknown_tools:
            raise ValueError(f"Unknown tools: {', '.join(sorted(unknown_tools))}")
        required_permissions = set().union(*(self.manager.tools.get(tool).required_permissions for tool in spec.tools)) if spec.tools else set()
        if "computer.observe" in spec.required_capabilities:
            required_permissions.add(Permission.SCREEN_READ.value)
        if not required_permissions.issubset(parent.permissions):
            raise ValueError("Specification requests permissions unavailable to its parent")
        return self.manager.create_agent(parent_agent_id, spec.name, spec.role, spec.objective, spec.task,
                                         required_permissions, set(spec.tools),
                                         {str(k): str(v) for k, v in spec.constraints.items()}, spec.task_id)
