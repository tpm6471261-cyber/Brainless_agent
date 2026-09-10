"""Deterministic cognitive controls around the untrusted reasoning-provider boundary."""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

from app.autonomy.proposals import ReasoningContext, ReasoningProposal, ReasoningProvider
from app.autonomy.world_state import FactKind, WorldStateManager


class Decision(str, Enum):
    ACT = "act"; OBSERVE = "observe"; ASK_USER = "ask_user"; DELEGATE = "delegate"
    WAIT = "wait"; REPLAN = "replan"; VERIFY = "verify"; RETRY = "retry"; ROLLBACK = "rollback"; ABORT = "abort"


@dataclass(frozen=True, slots=True)
class Goal:
    objective: str
    constraints: tuple[str, ...] = ()
    priority: int = 0
    deadline: str | None = None
    acceptable_outcomes: tuple[str, ...] = ()
    prohibited_actions: tuple[str, ...] = ()
    ambiguity: tuple[str, ...] = ()


class IntentEngine:
    """Conservative parser: records ambiguity instead of inventing user constraints."""
    def interpret(self, request: str, *, constraints: Iterable[str] = (), priority: int = 0,
                  deadline: str | None = None, acceptable_outcomes: Iterable[str] = (),
                  prohibited_actions: Iterable[str] = ()) -> Goal:
        if not request.strip(): raise ValueError("A goal objective is required")
        ambiguity = ("deadline",) if "by " in request.casefold() and deadline is None else ()
        return Goal(request.strip(), tuple(constraints), priority, deadline, tuple(acceptable_outcomes),
                    tuple(prohibited_actions), ambiguity)


class DecisionEngine:
    """Runtime decisions favor observation when beliefs are unknown, stale, or contradicted."""
    def choose(self, world: WorldStateManager, required_facts: Iterable[str], *, failed: bool = False,
               approval_needed: bool = False) -> Decision:
        if approval_needed: return Decision.ASK_USER
        if failed: return Decision.REPLAN
        facts = [world.get(key) for key in required_facts]
        if any(fact is None or fact.kind is not FactKind.OBSERVED for fact in facts): return Decision.OBSERVE
        return Decision.ACT


@dataclass(frozen=True, slots=True)
class ObservationOption:
    tool_id: str
    cost: float
    reliability: float
    facts: frozenset[str]


class PerceptionPlanner:
    def choose(self, missing_facts: set[str], options: Iterable[ObservationOption]) -> ObservationOption | None:
        choices = [option for option in options if missing_facts & option.facts]
        return min(choices, key=lambda option: (option.cost / max(option.reliability, .01), option.cost), default=None)


@dataclass(frozen=True, slots=True)
class Strategy:
    name: str
    success: float
    risk: float
    reliability: float
    cost: float
    reversible: bool
    permitted: bool
    resources_available: bool


class CounterfactualPlanner:
    """Scores inert strategy descriptions; this planner has no execution dependency."""
    def choose(self, strategies: Iterable[Strategy]) -> Strategy | None:
        eligible = [s for s in strategies if s.permitted and s.resources_available]
        return max(eligible, key=lambda s: (s.success * s.reliability - s.risk - s.cost / 100,
                                            s.reversible), default=None)


class CognitiveEngine:
    """Reconstructs transient context and safely pauses when the provider fails."""
    def __init__(self, provider: ReasoningProvider) -> None: self.provider, self.paused = provider, False

    async def propose(self, context: ReasoningContext) -> ReasoningProposal | None:
        try:
            proposal = await self.provider.propose(context)
        except Exception:
            self.paused = True
            return None
        self.paused = proposal is None
        return proposal
