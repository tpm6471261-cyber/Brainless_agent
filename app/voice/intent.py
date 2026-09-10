"""Deterministic high-priority voice controls and structured mission intents."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum


class VoiceIntentType(str, Enum):
    EXECUTE_TASK="execute_task"; CREATE_MISSION="create_mission"; QUERY_STATUS="query_status"
    CONTROL_AGENT="control_agent"; CONTROL_MISSION="control_mission"; SCHEDULE_TASK="schedule_task"
    CANCEL_TASK="cancel_task"; PAUSE="pause"; RESUME="resume"; TAKEOVER="takeover"
    APPROVAL="approval"; ASK_INFORMATION="ask_information"; STOP="stop"; EMERGENCY_STOP="emergency_stop"


@dataclass(frozen=True, slots=True)
class VoiceIntent:
    type: VoiceIntentType
    transcript: str
    goal: str | None
    constraints: tuple[str, ...] = ()
    urgency: str = "normal"
    requires_confirmation: bool = False
    confidence: float = 1.0


class VoiceIntentEngine:
    """Classifies controls locally; ordinary language becomes one mission goal."""
    sensitive = ("delete", "purchase", "buy", "transfer", "send email", "publish", "install", "password", "private data")

    def parse(self, transcript: str, confidence: float) -> VoiceIntent:
        text, normalized = transcript.strip(), transcript.casefold().strip().rstrip(".!?")
        exact = {
            "stop everything": VoiceIntentType.EMERGENCY_STOP, "emergency stop": VoiceIntentType.EMERGENCY_STOP,
            "stop": VoiceIntentType.STOP, "pause": VoiceIntentType.PAUSE, "wait": VoiceIntentType.PAUSE,
            "resume": VoiceIntentType.RESUME, "continue": VoiceIntentType.RESUME,
            "let me take over": VoiceIntentType.TAKEOVER, "give control back": VoiceIntentType.RESUME,
            "approve": VoiceIntentType.APPROVAL, "deny": VoiceIntentType.APPROVAL,
            "what is running": VoiceIntentType.QUERY_STATUS, "what's running": VoiceIntentType.QUERY_STATUS,
        }
        intent_type = exact.get(normalized, VoiceIntentType.CREATE_MISSION if normalized.startswith("create a mission") else VoiceIntentType.EXECUTE_TASK)
        sensitive = any(term in normalized for term in self.sensitive)
        return VoiceIntent(intent_type, text, text if intent_type in {VoiceIntentType.EXECUTE_TASK, VoiceIntentType.CREATE_MISSION} else None,
                           urgency="emergency" if intent_type is VoiceIntentType.EMERGENCY_STOP else "normal",
                           requires_confirmation=sensitive, confidence=confidence)
