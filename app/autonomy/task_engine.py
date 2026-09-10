"""Goal engine that executes validated task graphs and verifies acceptance criteria."""
from __future__ import annotations

from collections.abc import Callable
import asyncio
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from uuid import uuid4

from app.autonomy.checkpoints import CheckpointStore, ExecutionCheckpoint
from app.autonomy.executor import ActionRuntime, DecisionProvider
from app.autonomy.orchestrator import AutonomousRuntime
from app.autonomy.models import TaskRequirements
from app.autonomy.task_graph import GraphTask, GraphTaskStatus, TaskGraph, TaskScheduler
from app.autonomy.planning import PlanValidator
from app.learning.core import Experience
from app.learning.engine import LearningCoordinator
from app.learning.performance import AgentPerformanceMemory
from app.autonomy.team import AgentTeamBuilder


class TaskOutcome(str, Enum):
    COMPLETED = "completed"
    PARTIALLY_COMPLETED = "partially_completed"
    FAILED = "failed"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AutonomousTask:
    objective: str
    acceptance_criteria: tuple["GoalCriterion", ...]
    task_id: str = field(default_factory=lambda: str(uuid4()))


class GoalCriterion(Protocol):
    async def verify(self, runtime: ActionRuntime) -> tuple[bool, str]: ...


class GoalCompletionVerifier:
    async def verify(self, criteria: tuple[GoalCriterion, ...], runtime: ActionRuntime) -> tuple[bool, tuple[str, ...]]:
        unmet: list[str] = []
        for criterion in criteria:
            passed, detail = await criterion.verify(runtime)
            if not passed:
                unmet.append(detail)
        return not unmet, tuple(unmet)


@dataclass(frozen=True, slots=True)
class TaskResult:
    task_id: str
    outcome: TaskOutcome
    result: str
    verified: bool
    unmet_criteria: tuple[str, ...] = ()
    completed_tasks: tuple[str, ...] = ()
    blocked_reason: str | None = None


class AutonomousTaskEngine:
    """Coordinates agents, graph scheduling, final verification, and append-only journaling."""
    def __init__(self, runtime: AutonomousRuntime, actions: ActionRuntime, journal=None,
                 scheduler: TaskScheduler | None = None, verifier: GoalCompletionVerifier | None = None,
                 checkpoints: CheckpointStore | None = None, learning: LearningCoordinator | None = None,
                 performance: AgentPerformanceMemory | None = None, team_builder: AgentTeamBuilder | None = None) -> None:
        self.runtime, self.actions, self.journal, self.checkpoints = runtime, actions, journal, checkpoints
        self.scheduler, self.verifier, self.learning = scheduler or TaskScheduler(), verifier or GoalCompletionVerifier(), learning
        self.performance, self.team_builder = performance, team_builder or AgentTeamBuilder()

    async def run(self, root_agent_id: str, task: AutonomousTask, decider: DecisionProvider) -> TaskResult:
        """Backward-compatible single-node goal execution and journal vocabulary."""
        self._journal(task.task_id, "TASK_CREATED", {"objective": task.objective})
        self._journal(task.task_id, "TASK_PLANNED", {"criteria": len(task.acceptance_criteria)})
        try:
            execution = await self.runtime.execute(root_agent_id, task.task_id, task.objective, decider)
        except Exception as error:
            self._journal(task.task_id, "TASK_FAILED", {"error": str(error)})
            return TaskResult(task.task_id, TaskOutcome.FAILED, str(error), False)
        self._journal(task.task_id, "CHECKPOINT_CREATED", {"agent_id": execution.agent_id, "result": execution.result})
        succeeded, unmet = await self.verifier.verify(task.acceptance_criteria, self.actions)
        if succeeded:
            self._journal(task.task_id, "TASK_COMPLETED", {"agent_id": execution.agent_id})
            return TaskResult(task.task_id, TaskOutcome.COMPLETED, execution.result, True)
        self._journal(task.task_id, "TASK_PARTIALLY_COMPLETED", {"unmet": list(unmet)})
        return TaskResult(task.task_id, TaskOutcome.PARTIALLY_COMPLETED, execution.result, False, unmet)

    async def run_graph(self, root_agent_id: str, task: AutonomousTask, graph: TaskGraph,
                        decider_for: Callable[[GraphTask], DecisionProvider], *, dry_run: bool = False) -> TaskResult:
        graph.validate()
        self._journal(task.task_id, "GOAL_CREATED", {"objective": task.objective})
        assignments = self.team_builder.build(graph, self.runtime.registry)
        self._journal(task.task_id, "PLAN_CREATED", {"tasks": sorted(graph.tasks), "team": [assignment.__dict__ if hasattr(assignment, "__dict__") else {"task_id": assignment.task_id, "agent_id": assignment.agent_id, "spawn": assignment.spawn} for assignment in assignments]})
        self._checkpoint(task, graph)
        if dry_run:
            return TaskResult(task.task_id, TaskOutcome.BLOCKED, "Dry run: no actions executed", False,
                              tuple(), tuple(), "dry_run")
        completed: list[str] = []
        # Only independent nodes with disjoint declared resources are scheduled together.
        parallel_limit = max(1, self.actions.limits.max_parallel_agents)
        while ready := self.scheduler.next_tasks(graph, set(self.actions.locks.owners), limit=parallel_limit):
            for node in ready:
                node.status = GraphTaskStatus.RUNNING
                self._journal(task.task_id, "TASK_CREATED", {"node": node.task_id, "objective": node.objective})

            async def execute_node(node: GraphTask):
                requirements = (TaskRequirements(node.capabilities, node.permissions,
                    frozenset({node.tool}) if node.tool else frozenset(), "WorkflowAgent")
                    if node.capabilities or node.permissions or node.tool else None)
                try:
                    return node, await self.runtime.execute(root_agent_id, f"{task.task_id}:{node.task_id}",
                        node.objective, decider_for(node), requirements), None
                except Exception as error:
                    return node, None, error

            outcomes = await asyncio.gather(*(execute_node(node) for node in ready))
            for node, execution, error in outcomes:
                if error:
                    graph.fail(node.task_id, str(error))
                    self._journal(task.task_id, "TASK_FAILED", {"node": node.task_id, "error": str(error)})
                    continue
                graph.complete(node.task_id); completed.append(node.task_id)
                self._journal(task.task_id, "TASK_COMPLETED", {"node": node.task_id, "agent_id": execution.agent_id})
            self._checkpoint(task, graph)
        succeeded, unmet = await self.verifier.verify(task.acceptance_criteria, self.actions)
        if succeeded and all(node.status is GraphTaskStatus.COMPLETED for node in graph.tasks.values()):
            self._journal(task.task_id, "GOAL_COMPLETED", {"completed": completed})
            return TaskResult(task.task_id, TaskOutcome.COMPLETED, "Goal acceptance criteria verified", True,
                              completed_tasks=tuple(completed))
        blocked = tuple(node for node in graph.tasks.values() if node.status is GraphTaskStatus.BLOCKED)
        failed = tuple(node for node in graph.tasks.values() if node.status is GraphTaskStatus.FAILED)
        outcome = TaskOutcome.BLOCKED if blocked else TaskOutcome.PARTIALLY_COMPLETED if completed else TaskOutcome.FAILED
        reason = (blocked[0].error if blocked else failed[0].error if failed else "Acceptance criteria were not met")
        self._journal(task.task_id, "GOAL_VERIFICATION_FAILED", {"unmet": list(unmet), "reason": reason})
        return TaskResult(task.task_id, outcome, "Goal was not fully verified", False, unmet, tuple(completed), reason)

    async def run_with_learning(self, root_agent_id: str, task: AutonomousTask, *, task_type: str,
                                environment: dict[str, str], decider_for: Callable[[GraphTask], DecisionProvider],
                                fallback_graph: TaskGraph, candidate_name: str | None = None,
                                candidate_description: str | None = None) -> TaskResult:
        """Run a policy-filtered reusable workflow, or the caller's validated fallback.

        Learned graphs are never executed directly from storage: this method applies
        the same graph, tool-contract, permission, scheduler, checkpoint, and final
        verification path used by all autonomous work.
        """
        if self.learning is None:
            return await self.run_graph(root_agent_id, task, fallback_graph, decider_for)
        requirements = self.runtime.analyzer.analyze(task.objective)
        advice = self.learning.advise(task.objective, task_type, environment,
            agent_permissions=requirements.permissions,
            available_capabilities=requirements.capabilities)
        chosen = advice.graph if advice.graph.tasks else fallback_graph
        PlanValidator().validate(chosen, available_capabilities=requirements.capabilities,
            available_permissions=requirements.permissions,
            known_tools=frozenset(self.actions.manager.tools.tool_ids),
            contracted_tools=frozenset(self.actions.contracts))
        result = await self.run_graph(root_agent_id, task, chosen, decider_for)
        experience = Experience(task.objective, task_type, environment,
            {"workflow": [{"objective": node.objective, "tool": node.tool,
                            "resources": sorted(node.resources)} for node in chosen.tasks.values()],
             "declared_permissions": sorted({permission for node in chosen.tasks.values() for permission in node.permissions}),
             "expected_outcomes": ["goal acceptance criteria verified"]},
            result.outcome is TaskOutcome.COMPLETED, result.verified, result.result,
            initial_state=self.actions.world_state.snapshot().values(),
            agents_used=tuple(sorted({record.agent_id for record in self.actions.audit if record.task_id.startswith(task.task_id)})),
            observations=tuple({"source": fact.source, "key": key, "value": str(fact.value)}
                               for key, fact in self.actions.world_state.snapshot().facts.items()),
            verification_results=("goal acceptance criteria passed" if result.verified else "goal acceptance criteria failed",),
            causal_evidence=tuple(item for item in self.actions.world_model.export_state()["causal_evidence"]
                                  if item["expected_effect"] == item["observed_effect"] and item["supporting"] > 0),
            resource_usage={"actions": float(len([record for record in self.actions.audit if record.task_id.startswith(task.task_id)]))},
            capabilities_used=tuple(sorted({capability for node in chosen.tasks.values() for capability in node.capabilities})),
            tools_used=tuple(sorted({node.tool for node in chosen.tasks.values() if node.tool})),
            failures=(result.blocked_reason,) if result.blocked_reason else ())
        self.learning.record(experience, candidate_name=candidate_name, candidate_description=candidate_description)
        if self.performance:
            for agent_id in experience.agents_used:
                self.performance.record(agent_id, task_type, environment.get("app", "unknown"), success=experience.success,
                    verified=experience.verified, duration_ms=experience.execution_time_ms,
                    resource_cost=sum(experience.resource_usage.values()))
        self._journal(task.task_id, "LEARNING_EXPERIENCE_STORED", {"reused_skills": [skill.skill_id for skill in advice.skills],
                                                                    "success": experience.success})
        return result

    def _checkpoint(self, task: AutonomousTask, graph: TaskGraph) -> None:
        if not self.checkpoints:
            return
        graph_data = {task_id: {"status": node.status.value, "dependencies": sorted(node.dependencies),
                                "retries": node.retries, "error": node.error} for task_id, node in graph.tasks.items()}
        agents = {agent.agent_id: agent.status.value for agent in self.runtime.manager.list_agents()}
        world = self.actions.world_state.snapshot().values()
        self.checkpoints.save(ExecutionCheckpoint(task.objective, graph_data, world, agents,
            tuple(task_id for task_id, node in graph.tasks.items() if node.status is GraphTaskStatus.PENDING),
            {task_id: node.retries for task_id, node in graph.tasks.items()},
            {agent.agent_id: tuple(sorted(agent.permissions)) for agent in self.runtime.manager.list_agents()},
            self.actions.locks.owners, cognitive_state=self.actions.world_model.export_state()))

    def _journal(self, task_id: str, event: str, detail: dict[str, object]) -> None:
        if self.journal:
            self.journal.store_task_journal(task_id, event, detail)
