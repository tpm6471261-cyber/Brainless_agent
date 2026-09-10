"""Durable human approval authority for suspended runtime actions."""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import json
from pathlib import Path
from threading import RLock
from typing import Any

from app.autonomy.models import ComputerAction


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    mission_id: str
    task_id: str
    agent_id: str
    tool: str
    reason: str
    risk_level: str
    permission: str
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: str = ""
    decided_at: str | None = None
    decided_by: str | None = None


class ApprovalStore:
    """Atomic metadata-only persistence; action arguments are intentionally excluded."""
    def __init__(self, path: Path) -> None:
        self.path, self._lock = path, RLock()

    def put(self, request: ApprovalRequest) -> None:
        with self._lock:
            data = self._read(); payload = asdict(request); payload["status"] = request.status.value
            data[request.approval_id] = payload; self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, sort_keys=True), encoding="utf-8"); temporary.replace(self.path)

    def get(self, approval_id: str) -> ApprovalRequest | None:
        data = self._read().get(approval_id)
        return _request(data) if data else None

    def all(self) -> tuple[ApprovalRequest, ...]:
        return tuple(_request(item) for item in self._read().values())

    def _read(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}


class ApprovalSystem:
    """Runtime waits for a human decision; the dashboard can only submit that decision."""
    def __init__(self, store: ApprovalStore, manager, *, timeout_seconds: float = 300) -> None:
        self.store, self.manager, self.timeout_seconds = store, manager, timeout_seconds

    async def request(self, action: ComputerAction) -> bool:
        tool = self.manager.tools.get(action.action_type)
        existing = self.store.get(action.action_id)
        if existing is None:
            self.store.put(ApprovalRequest(action.action_id, "", action.task_id,
                action.agent_id, action.action_type, action.reason, tool.risk.value, action.permission,
                requested_at=datetime.now(timezone.utc).isoformat()))
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        while asyncio.get_running_loop().time() < deadline:
            request = self.store.get(action.action_id)
            if request and request.status is ApprovalStatus.APPROVED: return True
            if request and request.status in {ApprovalStatus.DENIED, ApprovalStatus.EXPIRED}: return False
            await asyncio.sleep(.2)
        self.decide(action.action_id, ApprovalStatus.EXPIRED, "runtime")
        return False

    def decide(self, approval_id: str, status: ApprovalStatus, actor: str) -> ApprovalRequest:
        if status not in {ApprovalStatus.APPROVED, ApprovalStatus.DENIED, ApprovalStatus.EXPIRED}:
            raise ValueError("Approval decision must be final")
        request = self.store.get(approval_id)
        if request is None: raise KeyError(f"Unknown approval: {approval_id}")
        if request.status is not ApprovalStatus.PENDING: raise ValueError("Approval was already decided")
        decided = ApprovalRequest(**(asdict(request) | {"status": status,
            "decided_at": datetime.now(timezone.utc).isoformat(), "decided_by": actor}))
        self.store.put(decided); return decided


def _request(data: dict[str, Any]) -> ApprovalRequest:
    payload = dict(data); payload["status"] = ApprovalStatus(payload["status"]); return ApprovalRequest(**payload)
