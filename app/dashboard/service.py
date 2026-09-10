"""Read-only dashboard projections and authorized runtime command gateway."""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
import hmac
from typing import Any
from uuid import uuid4

from app.agents.models import AgentStatus
from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.mission import Mission, MissionStatus, MissionStore
from app.autonomy.operator import AutonomousOperator
from app.autonomy.triggers import TriggerStore
from app.autonomy.approvals import ApprovalStatus, ApprovalSystem
from app.perception.engine import PerceptionRequest
from app.safety.redaction import redact


class DashboardAuthorizationError(PermissionError):
    pass


class DashboardCommand(str, Enum):
    CREATE_MISSION = "create_mission"
    PAUSE_MISSION = "pause_mission"
    RESUME_MISSION = "resume_mission"
    CANCEL_MISSION = "cancel_mission"
    TAKE_OVER = "take_over"
    RELEASE_TAKEOVER = "release_takeover"
    APPROVE = "approve"
    DENY = "deny"
    CONFIGURE_VOICE = "configure_voice"
    START_VOICE = "start_voice"
    STOP_VOICE = "stop_voice"
    OBSERVE_ENVIRONMENT = "observe_environment"


@dataclass(frozen=True, slots=True)
class DashboardRuntime:
    missions: MissionStore
    events: AutonomousEventBus
    operator: AutonomousOperator
    agents: Any
    actions: Any
    triggers: TriggerStore | None = None
    memory: Any = None
    skills: Any = None
    provider_names: tuple[str, ...] = ()
    mission_execution_status: str = "healthy"
    approval_system: ApprovalSystem | None = None
    voice: Any = None
    perception: Any = None


class RuntimeCommandGateway:
    """The only dashboard mutation path; commands are authenticated and allow-listed."""
    def __init__(self, runtime: DashboardRuntime, token: str) -> None:
        if len(token) < 16:
            raise ValueError("Dashboard token must contain at least 16 characters")
        self.runtime, self._token = runtime, token

    def authorized(self, token: str) -> bool:
        return hmac.compare_digest(token, self._token)

    async def execute(self, token: str, command: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.authorized(token):
            raise DashboardAuthorizationError("Dashboard command is not authorized")
        try:
            requested = DashboardCommand(command)
        except ValueError as error:
            raise ValueError("Unsupported dashboard command") from error
        mission_id = str(payload.get("mission_id", ""))
        if requested is DashboardCommand.CREATE_MISSION:
            goal = str(payload.get("goal", "")).strip()
            owner = str(payload.get("owner", "user")).strip()
            if not goal or len(goal) > 4_000 or not owner or len(owner) > 200:
                raise ValueError("Mission goal and owner are required and bounded")
            priority = int(payload.get("priority", 0))
            if not -100 <= priority <= 100:
                raise ValueError("Mission priority must be between -100 and 100")
            mission = Mission(goal, owner, priority=priority)
            await self.runtime.operator.create(mission)
            mission_id = mission.mission_id
        elif requested in {DashboardCommand.PAUSE_MISSION, DashboardCommand.RESUME_MISSION,
                         DashboardCommand.CANCEL_MISSION}:
            mission = self.runtime.missions.load(mission_id)
            if mission is None:
                raise KeyError(f"Unknown mission: {mission_id}")
            terminal = {MissionStatus.COMPLETED, MissionStatus.FAILED, MissionStatus.CANCELLED}
            if mission.status in terminal:
                raise ValueError("Terminal missions cannot be changed by dashboard commands")
            if requested is DashboardCommand.RESUME_MISSION and mission.status not in {
                    MissionStatus.PAUSED, MissionStatus.WAITING, MissionStatus.BLOCKED,
                    MissionStatus.AWAITING_USER, MissionStatus.RECOVERING}:
                raise ValueError("Mission is not in a resumable state")
            transitions = {
                DashboardCommand.PAUSE_MISSION: MissionStatus.PAUSED,
                DashboardCommand.RESUME_MISSION: MissionStatus.WAITING,
                DashboardCommand.CANCEL_MISSION: MissionStatus.CANCELLED,
            }
            mission.status = transitions[requested]
            mission.touch()
            self.runtime.missions.save(mission)
        elif requested is DashboardCommand.TAKE_OVER:
            self.runtime.operator.takeover.begin()
        elif requested is DashboardCommand.RELEASE_TAKEOVER:
            self.runtime.operator.takeover.resume()
        elif requested in {DashboardCommand.APPROVE, DashboardCommand.DENY}:
            if self.runtime.approval_system is None:
                raise ValueError("Approval system is not configured")
            approval_id = str(payload.get("approval_id", ""))
            status = ApprovalStatus.APPROVED if requested is DashboardCommand.APPROVE else ApprovalStatus.DENIED
            approval = self.runtime.approval_system.decide(approval_id, status, "dashboard_user")
            mission_id = approval.mission_id
        elif requested is DashboardCommand.CONFIGURE_VOICE:
            if self.runtime.voice is None: raise ValueError("Voice control is unavailable")
            api_key = str(payload.get("api_key", ""))
            settings = {key: payload[key] for key in ("model", "language", "idle_timeout",
                "max_session_duration", "min_confidence", "sensitive_confidence") if key in payload}
            self.runtime.voice.configure(api_key, settings)
        elif requested is DashboardCommand.START_VOICE:
            if self.runtime.voice is None: raise ValueError("Voice control is unavailable")
            await self.runtime.voice.start()
        elif requested is DashboardCommand.STOP_VOICE:
            if self.runtime.voice is None: raise ValueError("Voice control is unavailable")
            await self.runtime.voice.stop()
        elif requested is DashboardCommand.OBSERVE_ENVIRONMENT:
            if self.runtime.perception is None: raise ValueError("Multimodal perception is unavailable")
            await self.runtime.perception.observe(PerceptionRequest(
                frozenset({"screen.read", "window.read", "browser.read", "process.read"}),
                "Authenticated dashboard observation", mission_id or None))
        correlation_id = str(uuid4())
        event_type = EventType.APPROVAL_RECEIVED if requested in {
            DashboardCommand.APPROVE, DashboardCommand.DENY} else EventType.USER_MESSAGE
        await self.runtime.events.publish(AutonomousEvent(
            event_type, mission_id or None,
            {"command": requested.value, "status": "accepted", "correlation_id": correlation_id},
            correlation_id=correlation_id,
        ))
        return {"accepted": True, "command": requested.value, "correlation_id": correlation_id}


class DashboardService:
    """Creates secret-redacted DTOs from authoritative runtime components."""
    def __init__(self, runtime: DashboardRuntime) -> None:
        self.runtime = runtime

    def snapshot(self) -> dict[str, Any]:
        missions = [self._mission(item) for item in self.runtime.missions.all()]
        schedules = [self._trigger(item) for item in self.runtime.triggers.all()] if self.runtime.triggers else []
        tasks = [task for mission in missions for task in mission["tasks"]]
        task_missions = {task["task_id"]: task["mission_id"] for task in tasks}
        agents = [self._agent(item, task_missions) for item in self.runtime.agents.list_agents()]
        actions = [self._action(item, task_missions) for item in self.runtime.actions.audit]
        events = self.events(task_missions=task_missions)
        statuses = [mission["status"] for mission in missions]
        pending_approvals = self._approvals()
        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "takeover_mode": self.runtime.operator.takeover.mode.value,
            "overview": {
                "active_missions": sum(status not in {"completed", "failed", "cancelled"} for status in statuses),
                "active_tasks": sum(task["status"] == "running" for task in tasks),
                "active_agents": sum(agent["status"] == AgentStatus.RUNNING.value for agent in agents),
                "scheduled_tasks": sum(item["enabled"] for item in schedules),
                "completed_tasks": sum(task["status"] == "completed" for task in tasks),
                "failed_tasks": sum(task["status"] == "failed" for task in tasks),
                "waiting_blocked": sum(status in {"waiting", "blocked", "awaiting_user"} for status in statuses),
                "pending_approvals": len(pending_approvals),
            },
            "health": self.health(), "missions": missions, "tasks": tasks, "agents": agents,
            "schedules": schedules, "events": events, "actions": actions,
            "approvals": pending_approvals, "resources": {"locks": self.runtime.actions.locks.owners,
                "queue_depth": self.runtime.events.queue_depth, "agent_count": len(agents), "task_count": len(tasks)},
            "world": self._world(), "inventory": self.inventory(),
            "recovery": [event for event in events if event["event_type"] in {"agent_failed", "task_failed"}],
            "security": [action for action in actions if action["error"] or action["policy_decision"] != "auto_approve"],
            "logs": events,
            "notifications": self.notifications(), "analytics": self.analytics(missions, tasks, agents, actions),
            "memory": self.memory(), "skills": self.skills(),
            "governance": self.runtime.actions.governor.snapshot(),
            "leases": [{"lease_id": item.lease_id, "agent_id": item.agent_id,
                        "permission": item.permission, "task_id": item.task_id,
                        "mission_id": task_missions.get(item.task_id), "status": "active",
                        "granted_at": item.granted_at.isoformat(), "expires_at": item.expires_at.isoformat()}
                       for item in self.runtime.agents.leases.active()],
            "voice": redact(self.runtime.voice.snapshot()) if self.runtime.voice else {
                "status": "not_configured", "connection": "disconnected", "history": [],
                "current_transcript": "", "final_transcript": "", "error": None},
            "perception": self._perception() if self.runtime.perception else {
                "status": "not_configured", "observations": 0, "average_latency_ms": None,
                "elements": [], "sources": [], "screenshot_available": False},
        }

    def health(self) -> list[dict[str, str]]:
        now = datetime.now(timezone.utc).isoformat()
        checks = {
            "runtime": "healthy", "event_bus": "healthy", "mission_store": "healthy",
            "mission_execution": self.runtime.mission_execution_status,
            "agent_manager": "healthy", "tool_registry": "healthy", "permission_policy": "healthy",
            "world_model": "healthy", "persistence": "healthy",
            "llm_provider": "healthy" if self.runtime.provider_names else "not_configured",
            "browser": "unknown", "computer_control": "healthy", "dashboard_api": "healthy",
            "knowledge_graph": "not_configured",
            "voice": self._voice_health(),
            "multimodal_perception": self._perception_health(),
        }
        return [{"component": key, "status": value, "last_seen": now} for key, value in checks.items()]

    def events(self, *, since: int = 0, limit: int = 200,
               task_missions: dict[str, str] | None = None) -> list[dict[str, Any]]:
        task_missions = task_missions or self._task_mission_index()
        return [self._event(item, task_missions) for item in self.runtime.events.replay(since, limit)]

    def search(self, query: str) -> list[dict[str, Any]]:
        needle = query.casefold().strip()
        if not needle:
            return []
        snapshot = self.snapshot()
        results = []
        for category in ("missions", "tasks", "agents", "events", "actions", "schedules"):
            for item in snapshot[category]:
                if needle in str(item).casefold():
                    results.append({"category": category, "item": item})
        return results[:200]

    def inventory(self) -> dict[str, Any]:
        return {"tools": list(self.runtime.agents.tools.tool_ids),
                "agents": len(self.runtime.agents.list_agents()),
                "missions": len(self.runtime.missions.all()),
                "triggers": len(self.runtime.triggers.all()) if self.runtime.triggers else 0,
                "skills": len(self.skills()),
                "permissions": sorted({permission for agent in self.runtime.agents.list_agents() for permission in agent.permissions}),
                "providers": list(self.runtime.provider_names)}

    def memory(self) -> list[dict[str, Any]]:
        if self.runtime.memory is None or not hasattr(self.runtime.memory, "recent_metadata"): return []
        return [_redact(item) for item in self.runtime.memory.recent_metadata()]

    def skills(self) -> list[dict[str, Any]]:
        if self.runtime.skills is None or not hasattr(self.runtime.skills, "list_skills"): return []
        return [{"skill_id": item.skill_id, "name": item.name, "description": _redact(item.description),
                 "status": item.status.value, "required_capabilities": sorted(item.required_capabilities),
                 "required_permissions": sorted(item.required_permissions),
                 "verification_method": item.verification_strategy,
                 "success_rate": item.evaluation.get("success_rate"), "trust": "controlled_artifact"}
                for item in self.runtime.skills.list_skills()]

    def notifications(self) -> list[dict[str, Any]]:
        important = {"task_completed", "task_failed", "agent_failed", "approval_received", "user_takeover"}
        return [event for event in self.events() if event["event_type"] in important or event["severity"] in {"error", "critical"}]

    def analytics(self, missions=None, tasks=None, agents=None, actions=None) -> dict[str, float | int | None]:
        missions = missions if missions is not None else [self._mission(item) for item in self.runtime.missions.all()]
        tasks = tasks if tasks is not None else [task for mission in missions for task in mission["tasks"]]
        agents = agents if agents is not None else [self._agent(item) for item in self.runtime.agents.list_agents()]
        actions = actions if actions is not None else [self._action(item) for item in self.runtime.actions.audit]
        terminal_missions = [item for item in missions if item["status"] in {"completed", "failed", "cancelled", "partially_completed"}]
        terminal_tasks = [item for item in tasks if item["status"] in {"completed", "failed", "cancelled"}]
        successful_actions = [item for item in actions if not item["error"]]
        recovery_events = [item for item in self.events() if item["event_type"] in {"agent_failed", "task_failed"}]
        interventions = [item for item in self.events() if item["payload"].get("command") == "take_over"]
        return {
            "mission_success_rate": _ratio(sum(item["status"] == "completed" for item in terminal_missions), len(terminal_missions)),
            "task_success_rate": _ratio(sum(item["status"] == "completed" for item in terminal_tasks), len(terminal_tasks)),
            "verification_score": _ratio(len(successful_actions), len(actions)),
            "recovery_score": None if not recovery_events else _ratio(sum(item["status"] == "completed" for item in recovery_events), len(recovery_events)),
            "autonomy_score": _ratio(max(0, sum(item["status"] == "completed" for item in terminal_missions) - len(interventions)), len(terminal_missions)),
            "average_action_duration_ms": (sum(item["duration_ms"] for item in actions) / len(actions)) if actions else None,
            "retry_rate": _ratio(sum(int(item.get("retries", 0)) for item in tasks), len(tasks)),
            "user_intervention_rate": _ratio(len(interventions), len(terminal_missions)),
            "agent_failure_rate": _ratio(sum(item["status"] == "failed" for item in agents), len(agents)),
            "approval_rate": _ratio(sum(item["approval_status"] == "approved" for item in actions),
                                    sum(item["approval_status"] in {"approved", "denied"} for item in actions)),
            "blocked_task_rate": _ratio(sum(item["status"] == "blocked" for item in tasks), len(tasks)),
        }

    def _mission(self, mission: Mission) -> dict[str, Any]:
        tasks = [{"task_id": task_id, "mission_id": mission.mission_id,
                  "description": data.get("objective", task_id), **data}
                 for task_id, data in mission.task_graph.items()]
        return {"mission_id": mission.mission_id, "objective": mission.goal, "owner": mission.owner,
                "status": mission.status.value, "priority": mission.priority, "deadline": mission.deadline,
                "progress": dict(mission.progress), "constraints": list(mission.constraints),
                "acceptance_criteria": list(mission.acceptance_criteria), "current_state": _redact(mission.current_state),
                "checkpoint": _redact(mission.checkpoint), "created_at": mission.created_at,
                "updated_at": mission.last_activity, "next_wakeup": mission.next_wakeup, "tasks": tasks}

    @staticmethod
    def _agent(agent, task_missions: dict[str, str] | None = None) -> dict[str, Any]:
        task_missions = task_missions or {}
        return {"agent_id": agent.agent_id, "name": agent.name, "role": agent.role,
                "parent_agent_id": agent.parent_agent_id, "children": list(agent.child_agents),
                "status": agent.status.value, "current_task": agent.current_task,
                "task_id": agent.current_task_id, "mission_id": task_missions.get(agent.current_task_id),
                "permissions": sorted(agent.permissions),
                "tools": sorted(agent.available_tools), "created_at": agent.created_at.isoformat(),
                "last_action": agent.execution_history[-1].tool_id if agent.execution_history else None,
                "health": "failed" if agent.status in {AgentStatus.FAILED, AgentStatus.TERMINATED} else "healthy"}

    @staticmethod
    def _action(record, task_missions: dict[str, str] | None = None) -> dict[str, Any]:
        data = asdict(record); data["timestamp"] = record.timestamp.isoformat()
        data["mission_id"] = (task_missions or {}).get(record.task_id)
        data["arguments"] = _redact(data["arguments"]); return data

    @staticmethod
    def _event(event: AutonomousEvent, task_missions: dict[str, str] | None = None) -> dict[str, Any]:
        task_id = event.detail.get("task_id")
        return {"sequence": event.sequence, "timestamp": event.timestamp.isoformat(), "event_type": event.type.value,
                "mission_id": event.mission_id or (task_missions or {}).get(task_id), "task_id": task_id,
                "agent_id": event.detail.get("agent_id"), "status": event.detail.get("status"),
                "severity": event.detail.get("severity", "info"), "correlation_id": event.correlation_id,
                "payload": _redact(event.detail)}

    @staticmethod
    def _trigger(trigger) -> dict[str, Any]:
        return {"schedule_id": trigger.trigger_id, "mission_id": trigger.mission_id,
                "trigger": trigger.kind.value, "next_execution": trigger.value if trigger.kind.value == "time" else None,
                "previous_execution": trigger.last_fired, "enabled": trigger.enabled}

    def _world(self) -> list[dict[str, Any]]:
        return [{"key": key, "value": _redact(fact.value), "kind": fact.kind.value,
                 "confidence": fact.confidence, "source": fact.source, "timestamp": fact.timestamp.isoformat()}
                for key, fact in self.runtime.actions.world_state.snapshot().facts.items()]

    def _approvals(self) -> list[dict[str, Any]]:
        if self.runtime.approval_system is None: return []
        return [{"approval_id": item.approval_id, "mission_id": item.mission_id,
                 "task_id": item.task_id, "agent_id": item.agent_id, "tool": item.tool,
                 "reason": item.reason, "risk_level": item.risk_level, "permission": item.permission,
                 "status": item.status.value, "requested_at": item.requested_at,
                 "decided_at": item.decided_at, "decided_by": item.decided_by}
                for item in self.runtime.approval_system.store.all() if item.status is ApprovalStatus.PENDING]

    def _perception(self) -> dict[str, Any]:
        projection = redact(self.runtime.perception.snapshot())
        projection["screenshot_available"] = bool(projection.pop("screenshot_reference", None))
        return projection

    def _voice_health(self) -> str:
        if self.runtime.voice is None: return "not_configured"
        if self.runtime.voice.health_check(): return "healthy"
        return "offline" if self.runtime.voice.snapshot().get("configured") else "not_configured"

    def _perception_health(self) -> str:
        if self.runtime.perception is None: return "not_configured"
        status = self.runtime.perception.snapshot().get("status")
        return {"available": "healthy", "waiting": "offline"}.get(status, status)

    def _task_mission_index(self) -> dict[str, str]:
        return {task_id: mission.mission_id for mission in self.runtime.missions.all()
                for task_id in mission.task_graph}


def _redact(value: Any) -> Any:
    return redact(value)


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None
