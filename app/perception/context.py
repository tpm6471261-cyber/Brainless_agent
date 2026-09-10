"""Bounded multimodal commands and minimum-useful-context construction."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from uuid import uuid4

from app.perception.models import EnvironmentSnapshot


class CommandSource(str, Enum):
    VOICE = "voice"
    TEXT = "text"
    SCREEN = "screen"
    SYSTEM_EVENT = "system_event"
    SCHEDULE = "schedule"
    AGENT = "agent"
    MISSION = "mission"


@dataclass(frozen=True, slots=True)
class MultimodalCommand:
    source: CommandSource
    intent: str
    confidence: float
    voice_transcript: str | None = None
    visual_reference: str | None = None
    text_input: str | None = None
    current_environment_id: str | None = None
    user_context: dict[str, Any] = field(default_factory=dict)
    mission_context: dict[str, Any] = field(default_factory=dict)
    constraints: tuple[str, ...] = ()
    requested_action: str | None = None
    risk_level: str = "low"
    command_id: str = field(default_factory=lambda: str(uuid4()))

    def __post_init__(self) -> None:
        if not 0 <= self.confidence <= 1:
            raise ValueError("Command confidence must be between zero and one")
        if self.source is CommandSource.SCREEN and self.requested_action:
            raise ValueError("Observed screen data cannot originate executable intent")


class ContextBuilder:
    """Builds bounded structured context; observed content remains labelled untrusted."""
    def __init__(self, *, element_limit: int = 40, history_limit: int = 10) -> None:
        self.element_limit, self.history_limit = element_limit, history_limit

    def build(self, command: MultimodalCommand, environment: EnvironmentSnapshot,
              *, world: dict[str, Any], agents: tuple[dict[str, Any], ...] = (),
              recent_events: tuple[dict[str, Any], ...] = ()) -> dict[str, Any]:
        elements = environment.visible_elements[:self.element_limit]
        return {"command": {"id": command.command_id, "source": command.source.value,
                            "intent": command.intent, "requested_action": command.requested_action,
                            "risk_level": command.risk_level, "constraints": command.constraints},
                "environment": {"snapshot_id": environment.snapshot_id,
                                "active_application": environment.active_application,
                                "active_window": environment.active_window,
                                "browser": environment.browser_state,
                                "elements": [{"role": item.role, "label": item.label,
                                              "text": item.text[:300], "source": item.source,
                                              "confidence": item.confidence} for item in elements],
                                "trust": "untrusted_observation_data"},
                "world": world, "agents": agents[:self.history_limit],
                "recent_events": recent_events[-self.history_limit:]}
