"""Permission-, risk-, timeout-, retry-, dry-run-, and stop-aware action registry."""
from __future__ import annotations
import asyncio
import inspect
from dataclasses import dataclass
from enum import Enum
from time import monotonic
from app.event_system.models import ActionResult, ActionStatus

class RiskLevel(str, Enum): LOW="low"; MEDIUM="medium"; HIGH="high"; CRITICAL="critical"
@dataclass(frozen=True,slots=True)
class ActionSpec:
    action_name:str; description:str; category:str; required_permissions:frozenset[str]; risk_level:RiskLevel
    input_schema:frozenset[str]; output_schema:str; executor:object; timeout:float=30; retries:int=0; rollback:object|None=None

class ActionRegistry:
    def __init__(self,*,dry_run:bool=False,confirm=None) -> None:
        self._actions={}; self.dry_run=dry_run; self.confirm=confirm or (lambda _:False); self.stopped=False
    def register(self,spec:ActionSpec) -> None:
        if spec.action_name in self._actions: raise ValueError("Action already registered")
        self._actions[spec.action_name]=spec
    def available(self,permissions:set[str]) -> tuple[ActionSpec,...]:
        return tuple(x for x in self._actions.values() if x.required_permissions.issubset(permissions))
    def emergency_stop(self) -> None: self.stopped=True
    def resume(self) -> None: self.stopped=False
    async def execute(self,name:str,arguments:dict,permissions:set[str]) -> ActionResult:
        started=monotonic(); spec=self._actions.get(name)
        if not spec:return ActionResult(ActionStatus.NOT_FOUND,"Action is not registered")
        if self.stopped:return ActionResult(ActionStatus.CANCELLED,"Emergency stop is active")
        if not spec.required_permissions.issubset(permissions):return ActionResult(ActionStatus.DENIED,"Required permission is missing")
        if set(arguments)!=set(spec.input_schema):return ActionResult(ActionStatus.FAILED,"Action arguments do not match schema")
        if self.dry_run and spec.risk_level in {RiskLevel.MEDIUM,RiskLevel.HIGH,RiskLevel.CRITICAL}:
            return ActionResult(ActionStatus.DENIED,"Blocked by dry-run mode")
        if spec.risk_level in {RiskLevel.HIGH,RiskLevel.CRITICAL} and not self.confirm(spec):
            return ActionResult(ActionStatus.DENIED,"User confirmation was not granted")
        for attempt in range(spec.retries+1):
            try:
                value=spec.executor(arguments)
                value=await asyncio.wait_for(value,timeout=spec.timeout) if inspect.isawaitable(value) else value
                return ActionResult(ActionStatus.SUCCESS,"Action completed",value,duration_ms=(monotonic()-started)*1000)
            except asyncio.TimeoutError:return ActionResult(ActionStatus.TIMEOUT,"Action timed out",duration_ms=(monotonic()-started)*1000)
            except Exception as error:
                if attempt==spec.retries:return ActionResult(ActionStatus.FAILED,"Action failed",error=type(error).__name__,duration_ms=(monotonic()-started)*1000)
                await asyncio.sleep(min(.1*2**attempt,2))
