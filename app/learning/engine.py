"""Bridge advisory experience/skills into the existing validated task-engine path."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from collections.abc import Callable

from app.autonomy.planning import PlanValidator
from app.autonomy.task_graph import TaskGraph
from app.learning.core import Experience, ExperienceMemory, ExperienceSource, Skill, SkillRegistry, SkillStatus, WorkflowSynthesizer
from app.learning.evaluator import ExecutionEvaluator
from app.learning.policy import PolicyEngine

@dataclass(frozen=True, slots=True)
class LearningConfig:
    learning_enabled: bool = True
    experience_retrieval_enabled: bool = True
    skill_learning_enabled: bool = True
    skill_auto_activation: bool = False
    minimum_skill_success_rate: float = .8
    max_candidate_skills: int = 20
    require_human_approval_for_skill_activation: bool = True
    minimum_evaluation_runs: int = 2

@dataclass(frozen=True, slots=True)
class WorkflowAdvice:
    experiences: tuple[Experience, ...]
    skills: tuple[Skill, ...]
    graph: TaskGraph

class SkillSandbox:
    """Restricted candidate test gate; callers supply no ambient runtime authority."""
    def validate(self, skill: Skill, *, capabilities: frozenset[str], permissions: frozenset[str],
                 known_tools: frozenset[str], contracted_tools: frozenset[str]) -> None:
        if skill.status is not SkillStatus.CANDIDATE:
            raise ValueError("Only candidate skills may enter the sandbox")
        graph = WorkflowSynthesizer().synthesize(skill.description, [skill])
        PlanValidator().validate(graph, available_capabilities=capabilities, available_permissions=permissions,
                                 known_tools=known_tools, contracted_tools=contracted_tools)

    async def execute_restricted(self, skill: Skill, runner: Callable[[TaskGraph], "Any"], *, capabilities: frozenset[str],
                                 permissions: frozenset[str], known_tools: frozenset[str], contracted_tools: frozenset[str]) -> Experience:
        """Execute only a pre-built candidate graph through a caller-owned disposable runtime.

        The sandbox owns neither controller nor permissions: the runner must provide
        an isolated runtime and return a structured, runtime-produced experience.
        """
        self.validate(skill, capabilities=capabilities, permissions=permissions, known_tools=known_tools, contracted_tools=contracted_tools)
        result = runner(WorkflowSynthesizer().synthesize(skill.description, [skill]))
        if hasattr(result, "__await__"): result = await result
        if not isinstance(result, Experience): raise TypeError("sandbox runner must return Experience")
        if result.source is not ExperienceSource.RUNTIME: raise ValueError("sandbox accepts runtime evidence only")
        return result

    def test(self, skill: Skill, experiences: list[Experience], *, capabilities: frozenset[str],
             permissions: frozenset[str], known_tools: frozenset[str], contracted_tools: frozenset[str]) -> tuple[SkillStatus, dict[str, float]]:
        """Sandbox evaluation accepts recorded controlled runs, never arbitrary external code."""
        self.validate(skill, capabilities=capabilities, permissions=permissions, known_tools=known_tools, contracted_tools=contracted_tools)
        evaluator = ExecutionEvaluator()
        return evaluator.evaluate(skill, experiences), evaluator.metrics(experiences)

class LearningCoordinator:
    """Retrieves advisory knowledge and persists evaluated runtime outcomes.

    It never invokes a controller or changes permissions/statuses: callers still send
    the graph through the existing plan validator and AutonomousTaskEngine.
    """
    def __init__(self, experiences: ExperienceMemory, skills: SkillRegistry,
                 config: LearningConfig | None = None, policy: PolicyEngine | None = None) -> None:
        self.experiences, self.skills, self.config = experiences, skills, config or LearningConfig()
        self.policy = policy or PolicyEngine()

    def advise(self, goal: str, task_type: str, environment: dict[str, str], *,
               agent_permissions: frozenset[str] | None = None,
               available_capabilities: frozenset[str] | None = None) -> WorkflowAdvice:
        """Return only advisory skills that independently satisfy runtime policy.

        The caller must still validate the resulting graph against the real tool
        contract immediately before execution.
        """
        experiences = self.experiences.retrieve(goal, task_type=task_type, environment=environment) if self.config.experience_retrieval_enabled else []
        skills = self.skills.search(goal) if self.config.learning_enabled else []
        if agent_permissions is not None and available_capabilities is not None:
            skills = [skill for skill in skills if self.policy.evaluate(
                skill, agent_permissions=agent_permissions,
                available_capabilities=available_capabilities, environment=environment, goal=goal).allowed]
        ordered = self.select_strategy(tuple(skills), tuple(experiences))
        return WorkflowAdvice(tuple(experiences), ordered, WorkflowSynthesizer().synthesize(goal, list(ordered), experiences))

    def strategy_notes(self, goal: str, task_type: str, environment: dict[str, str]) -> tuple[str, ...]:
        """Return contextual failure warnings as data for a planner, never commands."""
        failures = self.experiences.retrieve(goal, task_type=task_type, environment=environment, limit=20)
        return tuple(f"Avoid prior failure: {failure}" for item in failures if not item.success
                     for failure in item.failures)

    def select_strategy(self, skills: tuple[Skill, ...], experiences: tuple[Experience, ...]) -> tuple[Skill, ...]:
        """Reliability-first ordering; speed only breaks otherwise equal candidates."""
        failure_penalty = sum(not item.success for item in experiences)
        return tuple(sorted(skills, key=lambda skill: (-skill.evaluation.get("success_rate", 0.0),
            skill.evaluation.get("resource_cost", 0.0), skill.evaluation.get("execution_time_ms", 0.0),
            _risk_value(skill.risk_level), failure_penalty, skill.name)))

    def record(self, experience: Experience, *, candidate_name: str | None = None,
               candidate_description: str | None = None) -> Skill | None:
        self.experiences.store(experience)
        if not self.config.skill_learning_enabled or not candidate_name or not candidate_description:
            return None
        versions = self.skills.versions(candidate_name)
        candidate = next((item for item in reversed(versions)
                          if item.status in {SkillStatus.CANDIDATE, SkillStatus.TESTED,
                                             SkillStatus.VERIFIED, SkillStatus.TRUSTED}), None)
        if candidate is None:
            candidate = ExecutionEvaluator().candidate(experience, candidate_name, candidate_description)
            if candidate is None or len(self.skills.candidates()) >= self.config.max_candidate_skills:
                return None
            self.skills.register(candidate)

        evidence = self.experiences.for_task_type(experience.task_type)
        evaluator = ExecutionEvaluator()
        metrics = evaluator.metrics(evidence)
        candidate = self.skills.update_evaluation(candidate.skill_id, metrics)
        if len(evidence) < self.config.minimum_evaluation_runs:
            return candidate

        reliable = (metrics.get("success_rate", 0.0) >= self.config.minimum_skill_success_rate
                    and metrics.get("verification_rate", 0.0) >= self.config.minimum_skill_success_rate)
        if candidate.status is SkillStatus.CANDIDATE:
            self.skills.set_status(candidate.skill_id,
                SkillStatus.TESTED if reliable else SkillStatus.REJECTED,
                actor="learning_loop", reason="evaluated repeated runtime outcomes")
        elif candidate.status in {SkillStatus.VERIFIED, SkillStatus.TRUSTED} and not reliable:
            self.skills.set_status(candidate.skill_id, SkillStatus.DEPRECATED,
                actor="learning_loop", reason="runtime outcome regression")
        return self.skills.get(candidate.skill_id)


def _risk_value(value: str) -> int:
    return {"low": 0, "medium": 1, "high": 2, "critical": 3}.get(value, 99)
