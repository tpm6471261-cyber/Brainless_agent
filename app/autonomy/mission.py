"""Persistent runtime-owned mission state; model context is never authoritative."""
from __future__ import annotations
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from uuid import uuid4
from typing import Any
from threading import RLock


class MissionStatus(str, Enum):
    CREATED="created"; PLANNING="planning"; RUNNING="running"; WAITING="waiting"; BLOCKED="blocked"
    PAUSED="paused"; AWAITING_USER="awaiting_user"; RECOVERING="recovering"; COMPLETED="completed"
    PARTIALLY_COMPLETED="partially_completed"; FAILED="failed"; CANCELLED="cancelled"


@dataclass(slots=True)
class Mission:
    goal: str
    owner: str
    constraints: tuple[str, ...] = ()
    priority: int = 0
    status: MissionStatus = MissionStatus.CREATED
    deadline: str | None = None
    task_graph: dict[str, Any] = field(default_factory=dict)
    current_state: dict[str, Any] = field(default_factory=dict)
    acceptance_criteria: tuple[str, ...] = ()
    risk_policy: str = "autonomous"
    resource_policy: str = "exclusive"
    checkpoint: dict[str, Any] = field(default_factory=dict)
    progress: dict[str, int | bool] = field(default_factory=dict)
    next_wakeup: str | None = None
    mission_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_activity: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def touch(self) -> None: self.last_activity = datetime.now(timezone.utc).isoformat()

    def refresh_progress(self) -> dict[str, int | bool]:
        nodes = list(self.task_graph.values())
        self.progress = {"tasks_completed": sum(node.get("status") == "completed" for node in nodes),
                         "tasks_remaining": sum(node.get("status") in {"pending", "running"} for node in nodes),
                         "blocked_tasks": sum(node.get("status") == "blocked" for node in nodes),
                         "verification_status": self.status is MissionStatus.COMPLETED}
        return self.progress


class MissionStore:
    """Atomic local mission persistence, independent from any reasoning provider."""
    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = RLock()

    def save(self, mission: Mission) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = asdict(mission); data["status"] = mission.status.value
            all_missions = self._read(); all_missions[mission.mission_id] = data
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(all_missions, sort_keys=True, default=str), encoding="utf-8")
            temporary.replace(self.path)

    def load(self, mission_id: str) -> Mission | None:
        data = self._read().get(mission_id)
        return _mission(data) if data else None

    def active(self) -> tuple[Mission, ...]:
        terminal = {MissionStatus.COMPLETED, MissionStatus.PARTIALLY_COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}
        return tuple(mission for data in self._read().values() if (mission := _mission(data)).status not in terminal)

    def all(self) -> tuple[Mission, ...]:
        """Return persisted history, including terminal missions, for observability."""
        return tuple(_mission(data) for data in self._read().values())

    def _read(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}


def _mission(data: dict[str, Any]) -> Mission:
    data = dict(data); data["status"] = MissionStatus(data["status"])
    data["constraints"] = tuple(data.get("constraints", ())); data["acceptance_criteria"] = tuple(data.get("acceptance_criteria", ()))
    return Mission(**data)
