"""Deterministic final authority gate for mission-scoped autonomous actions."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from threading import RLock

from app.agents.tools import RiskLevel, ToolSpec
from app.autonomy.models import ComputerAction


class GovernorDecision(str, Enum):
    ALLOW = "allow"
    APPROVAL = "approval"
    DENY = "deny"


@dataclass(frozen=True, slots=True)
class MissionContract:
    mission_id: str
    allowed_tools: frozenset[str] = frozenset()
    allowed_permissions: frozenset[str] = frozenset()
    forbidden_actions: frozenset[str] = frozenset()
    max_actions: int = 1_000
    max_failures: int = 10
    minimum_confidence: float = 0.5


@dataclass(slots=True)
class BudgetUsage:
    actions: int = 0
    failures: int = 0


@dataclass(frozen=True, slots=True)
class GovernorOutcome:
    decision: GovernorDecision
    reason: str
    mission_id: str | None


class AutonomyGovernor:
    """Combines mission authority, risk, confidence, and budgets without model input."""
    def __init__(self) -> None:
        self._contracts: dict[str, MissionContract] = {}
        self._tasks: dict[str, str] = {}
        self._usage: dict[str, BudgetUsage] = {}
        self._lock = RLock()

    def register(self, contract: MissionContract, task_ids: set[str]) -> None:
        if contract.max_actions < 1 or contract.max_failures < 0:
            raise ValueError("Mission budgets are invalid")
        if not 0 <= contract.minimum_confidence <= 1:
            raise ValueError("Mission confidence threshold is invalid")
        with self._lock:
            self._contracts[contract.mission_id] = contract
            self._usage.setdefault(contract.mission_id, BudgetUsage())
            for task_id in task_ids:
                self._tasks[task_id] = contract.mission_id

    def evaluate(self, action: ComputerAction, tool: ToolSpec, confidence: float = 1.0) -> GovernorOutcome:
        with self._lock:
            mission_id = self._tasks.get(action.task_id)
            if mission_id is None:
                return GovernorOutcome(GovernorDecision.ALLOW, "no_mission_contract", None)
            contract, usage = self._contracts[mission_id], self._usage[mission_id]
            if action.action_type in contract.forbidden_actions:
                return GovernorOutcome(GovernorDecision.DENY, "forbidden_by_mission", mission_id)
            if contract.allowed_tools and action.action_type not in contract.allowed_tools:
                return GovernorOutcome(GovernorDecision.DENY, "tool_outside_mission", mission_id)
            if contract.allowed_permissions and action.permission not in contract.allowed_permissions:
                return GovernorOutcome(GovernorDecision.DENY, "permission_outside_mission", mission_id)
            if usage.actions >= contract.max_actions or usage.failures >= contract.max_failures:
                return GovernorOutcome(GovernorDecision.DENY, "mission_budget_exhausted", mission_id)
            if confidence < contract.minimum_confidence:
                return GovernorOutcome(GovernorDecision.APPROVAL, "confidence_below_contract", mission_id)
            if tool.risk is RiskLevel.HIGH or tool.destructive:
                return GovernorOutcome(GovernorDecision.APPROVAL, "mission_risk_gate", mission_id)
            return GovernorOutcome(GovernorDecision.ALLOW, "mission_contract_allows", mission_id)

    def record(self, task_id: str, success: bool) -> None:
        with self._lock:
            mission_id = self._tasks.get(task_id)
            if mission_id is None:
                return
            usage = self._usage[mission_id]
            usage.actions += 1
            if not success:
                usage.failures += 1

    def snapshot(self) -> list[dict[str, object]]:
        with self._lock:
            return [{"mission_id": mission_id, "allowed_tools": sorted(contract.allowed_tools),
                     "allowed_permissions": sorted(contract.allowed_permissions),
                     "forbidden_actions": sorted(contract.forbidden_actions),
                     "minimum_confidence": contract.minimum_confidence,
                     "actions_used": self._usage[mission_id].actions,
                     "actions_limit": contract.max_actions,
                     "failures_used": self._usage[mission_id].failures,
                     "failures_limit": contract.max_failures}
                    for mission_id, contract in self._contracts.items()]
