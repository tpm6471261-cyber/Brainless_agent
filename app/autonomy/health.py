"""Runtime health monitoring and non-escalating agent cleanup/replacement hooks."""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone
from app.agents.manager import AgentManager
from app.agents.models import AgentStatus
from app.autonomy.resources import ResourceLockManager
@dataclass(frozen=True, slots=True)
class AgentHealth:
    agent_id:str; status:str; task_id:str|None; healthy:bool; released_resources:tuple[str,...]=()
class AgentHealthMonitor:
    def __init__(self, manager:AgentManager, locks:ResourceLockManager): self.manager,self.locks=manager,locks; self.heartbeats:dict[str,datetime]={}
    def heartbeat(self,agent_id:str)->None: self.manager.get_agent(agent_id); self.heartbeats[agent_id]=datetime.now(timezone.utc)
    def inspect(self)->tuple[AgentHealth,...]:
        report=[]
        for agent in self.manager.list_agents():
            unhealthy=agent.status in {AgentStatus.FAILED,AgentStatus.TERMINATED}; released=self.locks.release_agent(agent.agent_id) if unhealthy else ()
            report.append(AgentHealth(agent.agent_id,agent.status.value,agent.current_task_id,not unhealthy,released))
        return tuple(report)
    def replace(self,parent_agent_id:str,agent_id:str):
        """Replacement preserves only parent-approved permissions/tools; never escalates."""
        old=self.manager.get_agent(agent_id)
        if old.status not in {AgentStatus.FAILED,AgentStatus.TERMINATED}: raise ValueError("Only unhealthy agents can be replaced")
        self.locks.release_agent(agent_id)
        return self.manager.create_agent(parent_agent_id,old.name,old.role,old.objective,old.current_task,set(old.permissions),set(old.available_tools),task_id=old.current_task_id)
