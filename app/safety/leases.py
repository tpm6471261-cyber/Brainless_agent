"""Runtime-owned, task-scoped temporary capability leases."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import RLock
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class CapabilityLease:
    lease_id: str
    agent_id: str
    permission: str
    task_id: str
    granted_at: datetime
    expires_at: datetime

    @property
    def active(self) -> bool:
        return datetime.now(timezone.utc) < self.expires_at


class CapabilityLeaseRegistry:
    """Leases are deliberately process-local and expire on restart (fail closed)."""
    def __init__(self) -> None:
        self._leases: dict[str, CapabilityLease] = {}
        self._lock = RLock()

    def grant(self, agent_id: str, permission: str, task_id: str, seconds: int) -> CapabilityLease:
        if not task_id or not 1 <= seconds <= 86_400:
            raise ValueError("Capability lease scope and duration are required")
        now = datetime.now(timezone.utc)
        lease = CapabilityLease(str(uuid4()), agent_id, permission, task_id, now, now + timedelta(seconds=seconds))
        with self._lock:
            self._leases[lease.lease_id] = lease
        return lease

    def permits(self, agent_id: str, permission: str, task_id: str | None) -> bool:
        with self._lock:
            self._prune()
            return any(item.agent_id == agent_id and item.permission == permission and
                       item.task_id == task_id and item.active for item in self._leases.values())

    def active(self) -> tuple[CapabilityLease, ...]:
        with self._lock:
            self._prune()
            return tuple(self._leases.values())

    def revoke(self, lease_id: str) -> None:
        with self._lock:
            self._leases.pop(lease_id, None)

    def _prune(self) -> None:
        self._leases = {key: item for key, item in self._leases.items() if item.active}
