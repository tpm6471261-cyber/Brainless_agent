"""Versioned, evidence-backed understanding of the external environment.

Facts are deliberately classified so callers cannot confuse an old inference with a
fresh observation.  Controllers feed this manager; action success never mutates facts.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any

from app.autonomy.models import ComputerState


class FactKind(str, Enum):
    OBSERVED = "observed"
    INFERRED = "inferred"
    ASSUMED = "assumed"
    STALE = "stale"


@dataclass(frozen=True, slots=True)
class WorldFact:
    value: Any
    kind: FactKind
    source: str
    timestamp: datetime
    confidence: float
    evidence: str | None
    version: int


@dataclass(frozen=True, slots=True)
class WorldSnapshot:
    version: int
    captured_at: datetime
    facts: dict[str, WorldFact]

    def values(self) -> dict[str, Any]:
        return {key: fact.value for key, fact in self.facts.items()}


class WorldStateManager:
    """Owns observation merges, freshness invalidation, snapshots, and diffs."""
    def __init__(self, stale_after: timedelta = timedelta(minutes=2)) -> None:
        self.stale_after, self._version = stale_after, 0
        self._facts: dict[str, WorldFact] = {}

    @property
    def version(self) -> int:
        return self._version

    def capture(self, state: ComputerState, *, source: str = "controller",
                evidence: str | None = None, confidence: float = 1.0) -> WorldSnapshot:
        """Merge direct controller observations and return an immutable snapshot."""
        self._version += 1
        timestamp = state.timestamp
        for name, value in asdict(state).items():
            if name == "timestamp" or value is None:
                continue
            self._facts[name] = WorldFact(value, FactKind.OBSERVED, source, timestamp,
                                          max(0.0, min(1.0, confidence)), evidence, self._version)
        return self.snapshot()

    def record(self, key: str, value: Any, *, kind: FactKind, source: str,
               confidence: float, evidence: str | None = None) -> WorldFact:
        self._version += 1
        fact = WorldFact(value, kind, source, datetime.now(timezone.utc), max(0.0, min(1.0, confidence)),
                         evidence, self._version)
        self._facts[key] = fact
        return fact

    def invalidate_stale(self, now: datetime | None = None) -> tuple[str, ...]:
        now = now or datetime.now(timezone.utc)
        stale: list[str] = []
        for key, fact in list(self._facts.items()):
            if fact.kind is not FactKind.STALE and now - fact.timestamp > self.stale_after:
                self._version += 1
                self._facts[key] = WorldFact(fact.value, FactKind.STALE, fact.source, fact.timestamp,
                                              fact.confidence, fact.evidence, self._version)
                stale.append(key)
        return tuple(stale)

    def get(self, key: str, *, require_observed: bool = False) -> WorldFact | None:
        self.invalidate_stale()
        fact = self._facts.get(key)
        return fact if fact and (not require_observed or fact.kind is FactKind.OBSERVED) else None

    def snapshot(self) -> WorldSnapshot:
        self.invalidate_stale()
        return WorldSnapshot(self._version, datetime.now(timezone.utc), dict(self._facts))

    @staticmethod
    def diff(before: WorldSnapshot, after: WorldSnapshot) -> dict[str, tuple[Any, Any]]:
        keys = set(before.facts) | set(after.facts)
        return {key: (before.facts.get(key).value if key in before.facts else None,
                      after.facts.get(key).value if key in after.facts else None)
                for key in keys if before.facts.get(key) != after.facts.get(key)}
