"""Provider-independent voice session and turn records."""
from __future__ import annotations
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from uuid import uuid4


class VoiceSessionStatus(str, Enum):
    IDLE="idle"; LISTENING="listening"; TRANSCRIBING="transcribing"; PROCESSING="processing"
    EXECUTING="executing"; WAITING="waiting"; ERROR="error"; STOPPED="stopped"


@dataclass(frozen=True, slots=True)
class VoiceTurn:
    transcript_id: str
    transcript: str
    confidence: float
    finalized: bool
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    latency_ms: float | None = None


@dataclass(slots=True)
class VoiceSession:
    user_id: str
    microphone: str = "default"
    session_id: str = field(default_factory=lambda: str(uuid4()))
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ended_at: datetime | None = None
    status: VoiceSessionStatus = VoiceSessionStatus.IDLE
    assemblyai_session_id: str | None = None
    current_transcript: str = ""
    last_final_transcript: str = ""
    active_mission: str | None = None
    connection_status: str = "disconnected"
    error_state: str | None = None
    conversation_context: deque[dict[str, str]] = field(default_factory=deque)
