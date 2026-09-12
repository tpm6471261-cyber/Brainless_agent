"""Permission-scoped delivery from normalized events to subscribed agents."""
from __future__ import annotations
from app.event_system.models import Event

class AgentEventDispatcher:
    def __init__(self,manager,handler) -> None:self.manager,self.handler=manager,handler
    async def dispatch(self,event:Event) -> tuple[str,...]:
        delivered=[]
        for agent in self.manager.list_agents():
            if event.event_type not in agent.event_subscriptions and "*" not in agent.event_subscriptions:continue
            if not event.permissions_required.issubset(agent.permissions):continue
            result=self.handler(agent,event)
            if hasattr(result,"__await__"):await result
            delivered.append(agent.agent_id)
        return tuple(delivered)
