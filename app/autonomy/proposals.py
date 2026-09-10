"""Untrusted reasoning proposals and the runtime validation boundary.

Reasoning providers receive only a read-only context and return data.  This module has
no controller, lock, secret, policy-mutation, or tool-invocation API by design.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from uuid import uuid4

from app.agents.manager import AgentManager
from app.agents.tools import RiskLevel
from app.autonomy.models import ActionProposal, ComputerAction, DecisionContext


class ProposalType(str, Enum):
    ACTION = "action"
    PLAN = "plan"
    OBSERVE = "observe"
    REPLAN = "replan"


@dataclass(frozen=True, slots=True)
class ReasoningProposal:
    """Structured, untrusted output from a reasoning provider.

    Agent identity, permissions, action IDs, and the executable action are deliberately
    absent: they are issued by the runtime after validation.
    """
    proposal_id: str
    goal_id: str
    task_id: str
    proposal_type: ProposalType
    intent: str
    candidate_actions: tuple[ActionProposal, ...] = ()
    candidate_strategy: str = ""
    required_capabilities: frozenset[str] = frozenset()
    required_permissions: frozenset[str] = frozenset()
    expected_outcomes: tuple[str, ...] = ()
    verification_requirements: tuple[str, ...] = ()
    risk_assessment: RiskLevel = RiskLevel.LOW
    confidence: float = 0.0
    assumptions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ReasoningContext:
    """Read-only, reconstructed context; never a source of runtime authority."""
    decision: DecisionContext
    capabilities: frozenset[str]
    permissions: frozenset[str]
    world: dict[str, Any]
    previous_result: str | None = None


class ReasoningProvider(Protocol):
    """Replaceable proposal-only model boundary."""
    async def propose(self, context: ReasoningContext) -> ReasoningProposal | None: ...


@dataclass(frozen=True, slots=True)
class ActionRequest:
    """Runtime-issued action object; only this may cross into execution."""
    action_id: str
    task_id: str
    agent_id: str
    tool_id: str
    arguments: dict[str, Any]
    preconditions: dict[str, Any]
    expected_effects: dict[str, Any]
    verification: tuple[str, ...]
    risk_level: RiskLevel
    idempotency: str
    timeout: float | None
    permission: str

    def to_computer_action(self, reason: str) -> ComputerAction:
        return ComputerAction(self.tool_id, self.arguments, self.agent_id, self.task_id,
                              reason, self.permission, self.expected_effects,
                              action_id=self.action_id)


class ProposalRejected(ValueError):
    """A proposal failed deterministic runtime validation."""


class ProposalValidator:
    """Validates untrusted model output without granting it any authority."""
    def __init__(self, manager: AgentManager, resources_for_tool=None, contracts: dict | None = None) -> None:
        self.manager, self.resources_for_tool, self.contracts = manager, resources_for_tool or (lambda _: set()), contracts or {}

    def validate_action(self, agent_id: str, task_id: str, proposal: ActionProposal,
                        *, verification: tuple[str, ...] = ()) -> ActionRequest:
        if not isinstance(proposal, ActionProposal) or not isinstance(proposal.arguments, dict):
            raise ProposalRejected("Action proposal must be a structured object")
        if not proposal.reason.strip() or not isinstance(proposal.expected_state, dict):
            raise ProposalRejected("Action proposal requires reason and expected state")
        agent = self.manager.get_agent(agent_id)
        # Legacy agents stored task text rather than a task ID.  A runtime that has
        # an ID binding in context gets strict ownership validation; text is never
        # interpreted as an authority token.
        if agent.current_task_id is not None and agent.current_task_id != task_id:
            raise ProposalRejected("Agent does not own the proposed task")
        try:
            tool = self.manager.tools.get(proposal.action_type)
        except KeyError as error:
            raise ProposalRejected("Proposed tool is not registered") from error
        if proposal.action_type not in agent.available_tools:
            raise ProposalRejected("Proposed tool is not granted to agent")
        if set(proposal.arguments) - set(tool.input_schema):
            raise ProposalRejected("Proposal contains arguments outside the tool schema")
        if set(tool.input_schema) - set(proposal.arguments):
            raise ProposalRejected("Proposal omits required tool arguments")
        if not tool.required_permissions.issubset(agent.permissions):
            raise ProposalRejected("Agent lacks required tool permissions")
        if len(tool.required_permissions) != 1:
            raise ProposalRejected("Runtime computer action must have exactly one permission")
        contract = self.contracts.get(proposal.action_type)
        if contract and contract.tool != proposal.action_type:
            raise ProposalRejected("Action contract does not match tool")
        return ActionRequest(str(uuid4()), task_id, agent_id, proposal.action_type, dict(proposal.arguments),
                             dict(contract.preconditions) if contract else {}, dict(proposal.expected_state),
                             verification, tool.risk, contract.idempotency.value if contract else "unknown",
                             contract.timeout_seconds if contract else None, next(iter(tool.required_permissions)))

    def validate(self, agent_id: str, proposal: ReasoningProposal) -> tuple[ActionRequest, ...]:
        if not isinstance(proposal, ReasoningProposal) or not proposal.proposal_id or not proposal.goal_id:
            raise ProposalRejected("Malformed reasoning proposal")
        if not 0.0 <= proposal.confidence <= 1.0:
            raise ProposalRejected("Proposal confidence must be between zero and one")
        if proposal.proposal_type is ProposalType.ACTION and not proposal.candidate_actions:
            raise ProposalRejected("Action proposal has no candidate actions")
        if proposal.proposal_type is not ProposalType.ACTION and proposal.candidate_actions:
            raise ProposalRejected("Non-action proposal cannot contain executable candidates")
        agent = self.manager.get_agent(agent_id)
        if not proposal.required_permissions.issubset(agent.permissions):
            raise ProposalRejected("Proposal requests permissions the agent lacks")
        return tuple(self.validate_action(agent_id, proposal.task_id, action,
                                          verification=proposal.verification_requirements)
                     for action in proposal.candidate_actions)
