"""Runtime-enforced action contracts and retry safety metadata."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.autonomy.models import ComputerState


class Idempotency(str, Enum):
    SAFE_TO_RETRY = "safe_to_retry"
    CONDITIONALLY_RETRYABLE = "conditionally_retryable"
    NOT_SAFE_TO_RETRY = "not_safe_to_retry"


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    max_attempts: int = 1


@dataclass(frozen=True, slots=True)
class ActionContract:
    action_id: str
    tool: str
    required_permissions: frozenset[str]
    preconditions: dict[str, Any] = field(default_factory=dict)
    expected_effects: dict[str, Any] = field(default_factory=dict)
    timeout_seconds: float | None = None
    retry: RetryPolicy = field(default_factory=RetryPolicy)
    idempotency: Idempotency = Idempotency.SAFE_TO_RETRY
    risk: str = "low"
    rollback_tool: str | None = None

    def validate(self, state: ComputerState, permission: str) -> None:
        if permission not in self.required_permissions:
            raise ValueError("Action permission is not allowed by its contract")
        for key, expected in self.preconditions.items():
            if getattr(state, key, None) != expected:
                raise ValueError(f"Precondition failed: {key}")
