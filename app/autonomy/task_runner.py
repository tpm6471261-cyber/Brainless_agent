"""Trusted bridge from persistent Mission state to the existing verified TaskEngine."""
from __future__ import annotations
from collections.abc import Callable
from typing import Any
from app.autonomy.mission import Mission, MissionStatus
from app.autonomy.task_engine import AutonomousTask, AutonomousTaskEngine, GoalCriterion, TaskOutcome
from app.autonomy.task_graph import GraphTask, GraphTaskStatus, TaskGraph

class TaskEngineMissionRunner:
    """Runs mission graphs exclusively through AutonomousTaskEngine/ActionRuntime."""
    def __init__(self, engine: AutonomousTaskEngine, root_agent_id: str,
                 graph_for: Callable[[Mission], TaskGraph], decider_for: Callable[[GraphTask], Any],
                 criteria_for: Callable[[Mission], tuple[GoalCriterion, ...]]) -> None:
        self.engine, self.root_agent_id, self.graph_for, self.decider_for, self.criteria_for = engine, root_agent_id, graph_for, decider_for, criteria_for

    async def __call__(self, mission: Mission) -> MissionStatus:
        graph = self.graph_for(mission)
        self._restore(graph, mission.checkpoint.get("task_graph", mission.task_graph))
        result = await self.engine.run_graph(self.root_agent_id,
            AutonomousTask(mission.goal, self.criteria_for(mission), task_id=mission.mission_id), graph, self.decider_for)
        mission.task_graph = self._serialize(graph)
        mission.checkpoint["task_graph"] = mission.task_graph
        mission.checkpoint["verified"] = result.verified
        return {TaskOutcome.COMPLETED: MissionStatus.COMPLETED, TaskOutcome.PARTIALLY_COMPLETED: MissionStatus.PARTIALLY_COMPLETED,
                TaskOutcome.BLOCKED: MissionStatus.BLOCKED, TaskOutcome.CANCELLED: MissionStatus.CANCELLED}.get(result.outcome, MissionStatus.FAILED)

    @staticmethod
    def _restore(graph: TaskGraph, saved: dict[str, Any]) -> None:
        for task_id, data in saved.items():
            if task_id in graph.tasks and data.get("status") in {status.value for status in GraphTaskStatus}:
                graph.tasks[task_id].status = GraphTaskStatus(data["status"])
                graph.tasks[task_id].retries = int(data.get("retries", 0))
                graph.tasks[task_id].error = data.get("error")

    @staticmethod
    def _serialize(graph: TaskGraph) -> dict[str, Any]:
        return {node.task_id: {"objective": node.objective, "status": node.status.value,
                 "dependencies": sorted(node.dependencies), "retries": node.retries, "error": node.error}
                for node in graph.tasks.values()}
