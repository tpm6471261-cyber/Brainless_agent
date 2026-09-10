"""Runtime autonomy-mode policy gate for sensitive registered tools."""
from __future__ import annotations
from app.agents.tools import RiskLevel, ToolSpec
from app.autonomy.operator import AutonomyMode
class ModePolicy:
    def __init__(self, mode:AutonomyMode=AutonomyMode.AUTONOMOUS): self.mode=mode
    def decision(self,tool:ToolSpec)->str:
        if self.mode in {AutonomyMode.TAKEOVER,AutonomyMode.PAUSED,AutonomyMode.OBSERVE_ONLY}: return "deny"
        if self.mode is AutonomyMode.ASSISTED: return "deny"
        if self.mode is AutonomyMode.WATCH and (tool.risk is not RiskLevel.LOW or tool.destructive): return "deny"
        if self.mode is AutonomyMode.SUPERVISED and (tool.risk is not RiskLevel.LOW or tool.destructive): return "approval"
        return "allow"
