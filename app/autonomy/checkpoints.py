"""Atomic durable checkpoints; resumption always starts with a fresh observation."""
from __future__ import annotations

import inspect
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable


@dataclass(frozen=True, slots=True)
class ExecutionCheckpoint:
    goal: str
    task_graph: dict[str, Any]
    world_state: dict[str, Any]
    agent_states: dict[str, str]
    pending_actions: tuple[str, ...] = ()
    retries: dict[str, int] | None = None
    permissions: dict[str, tuple[str, ...]] | None = None
    resource_owners: dict[str, str] | None = None
    errors: tuple[str, ...] = ()
    cognitive_state: dict[str, Any] | None = None
    created_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class CheckpointStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    def save(self, checkpoint: ExecutionCheckpoint) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(checkpoint.to_dict(), sort_keys=True, default=str), encoding="utf-8")
        temporary.replace(self.path)

    def load(self) -> ExecutionCheckpoint | None:
        if not self.path.exists():
            return None
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["pending_actions"] = tuple(data.get("pending_actions", ()))
        data["errors"] = tuple(data.get("errors", ()))
        if data.get("permissions"):
            data["permissions"] = {key: tuple(value) for key, value in data["permissions"].items()}
        return ExecutionCheckpoint(**data)

    async def resume(self, observe: Callable[[], Any]) -> tuple[ExecutionCheckpoint, Any] | None:
        """Load state and force a fresh observation before a caller resumes scheduling.

        Pending actions are intentionally returned as pending, never replayed here.
        """
        checkpoint = self.load()
        if checkpoint is None:
            return None
        observation = observe()
        if inspect.isawaitable(observation):
            observation = await observation
        return checkpoint, observation
