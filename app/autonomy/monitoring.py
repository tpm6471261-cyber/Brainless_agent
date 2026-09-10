"""Runtime-only presence, interruption classification, and autonomy metrics."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable
from app.autonomy.models import ComputerState

class InterruptionKind(str, Enum): LOGIN="login"; CAPTCHA="captcha"; POPUP="popup"; CRASH="crash"; NETWORK="network"; SCREEN_LOCK="screen_lock"; UNKNOWN="unknown"
@dataclass(frozen=True, slots=True)
class Interruption:
    kind: InterruptionKind; detail: str; requires_user: bool
class InterruptionManager:
    def classify(self, state: ComputerState) -> Interruption | None:
        text=" ".join(state.visible_ui + state.errors).casefold()
        if any(item in text for item in ("captcha", "verify you are human")): return Interruption(InterruptionKind.CAPTCHA,"CAPTCHA detected",True)
        if any(item in text for item in ("sign in", "log in", "login required")): return Interruption(InterruptionKind.LOGIN,"Authentication required",True)
        if "network" in text and "error" in text: return Interruption(InterruptionKind.NETWORK,"Network error detected",False)
        if "crash" in text or "unexpectedly quit" in text: return Interruption(InterruptionKind.CRASH,"Application crash detected",False)
        return None
class UserPresenceDetector:
    """Accepts a minimal boolean activity signal; it stores no user content."""
    def __init__(self, active: Callable[[], bool]): self.active,self.last_seen=active,None
    def present(self) -> bool:
        value=bool(self.active())
        if value: self.last_seen=datetime.now(timezone.utc)
        return value
@dataclass(slots=True)
class AutonomyMetrics:
    fully_autonomous:int=0; recovered:int=0; user_takeovers:int=0; failed:int=0
    planning_success:int=0; action_success:int=0; verification_success:int=0; recovery_success:int=0; mission_completion:int=0
    def autonomy_score(self)->float:
        total=self.fully_autonomous+self.recovered+self.user_takeovers+self.failed
        return (self.fully_autonomous+self.recovered)/total if total else 0.0
