"""Durable, advisory experience and versioned skills.

This layer has no ToolRegistry or controller dependency: it can only return data for
planning. All execution remains subject to ActionRuntime permission/policy checks.
"""
from __future__ import annotations
import json
import re
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from app.autonomy.task_graph import GraphTask, TaskGraph


class ExperienceSource(str, Enum):
    RUNTIME = "runtime"
    EXTERNAL = "external"
    HUMAN = "human"

class SkillStatus(str, Enum):
    UNTRUSTED = "untrusted"
    CANDIDATE = "candidate"
    TESTED = "tested"
    VERIFIED = "verified"
    TRUSTED = "trusted"
    REJECTED = "rejected"
    DEPRECATED = "deprecated"

@dataclass(frozen=True, slots=True)
class Experience:
    goal: str
    task_type: str
    environment: dict[str, str]
    plan: dict[str, Any]
    success: bool
    verified: bool
    final_result: str
    initial_state: dict[str, Any] = field(default_factory=dict)
    agents_used: tuple[str, ...] = ()
    observations: tuple[dict[str, Any], ...] = ()
    verification_results: tuple[str, ...] = ()
    resource_usage: dict[str, float] = field(default_factory=dict)
    capabilities_used: tuple[str, ...] = ()
    tools_used: tuple[str, ...] = ()
    actions: tuple[dict[str, Any], ...] = ()
    failures: tuple[str, ...] = ()
    recovery_steps: tuple[str, ...] = ()
    causal_evidence: tuple[dict[str, Any], ...] = ()
    execution_time_ms: float = 0.0
    risk_level: str = "low"
    source: ExperienceSource = ExperienceSource.RUNTIME
    experience_id: str = field(default_factory=lambda: str(uuid4()))
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

@dataclass(frozen=True, slots=True)
class Skill:
    name: str
    description: str
    required_capabilities: frozenset[str]
    required_permissions: frozenset[str]
    workflow: tuple[dict[str, Any], ...]
    expected_outcomes: tuple[str, ...]
    version: int = 1
    status: SkillStatus = SkillStatus.CANDIDATE
    preconditions: dict[str, Any] = field(default_factory=dict)
    failure_modes: tuple[str, ...] = ()
    recovery_strategy: str = "reobserve"
    verification_strategy: str = "runtime_goal_verifier"
    risk_level: str = "low"
    success_metrics: dict[str, float] = field(default_factory=dict)
    source_experience_id: str | None = None
    evaluation: dict[str, float] = field(default_factory=dict)
    skill_id: str = field(default_factory=lambda: str(uuid4()))

class ExperienceMemory:
    """Structured execution memory; external content can never become trusted experience."""
    def __init__(self, path: Path, max_records: int = 1_000) -> None:
        self.max_records = max_records
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS experiences (id TEXT PRIMARY KEY, created_at TEXT NOT NULL,
          source TEXT NOT NULL, goal TEXT NOT NULL, task_type TEXT NOT NULL, environment_json TEXT NOT NULL,
          payload_json TEXT NOT NULL, success INTEGER NOT NULL, verified INTEGER NOT NULL)""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS experience_feedback (feedback_id INTEGER PRIMARY KEY, experience_id TEXT NOT NULL,
          kind TEXT NOT NULL, actor TEXT NOT NULL, detail TEXT NOT NULL, created_at TEXT NOT NULL)""")
        self.db.commit()

    def store(self, experience: Experience) -> None:
        if experience.source is ExperienceSource.EXTERNAL:
            raise ValueError("External content must be validated before entering experience memory")
        payload = asdict(experience); payload["source"] = experience.source.value
        self.db.execute("INSERT OR REPLACE INTO experiences VALUES (?,?,?,?,?,?,?,?,?)", (experience.experience_id,
            experience.created_at, experience.source.value, experience.goal, experience.task_type,
            json.dumps(experience.environment, sort_keys=True), json.dumps(payload, sort_keys=True), int(experience.success), int(experience.verified)))
        self.db.execute("DELETE FROM experiences WHERE id IN (SELECT id FROM experiences ORDER BY created_at DESC LIMIT -1 OFFSET ?)", (self.max_records,))
        self.db.commit()

    def retrieve(self, goal: str, *, task_type: str | None = None, environment: dict[str, str] | None = None,
                 limit: int = 5, max_age: timedelta | None = None) -> list[Experience]:
        rows = self.db.execute("SELECT * FROM experiences ORDER BY created_at DESC").fetchall()
        terms = set(_terms(goal)); now = datetime.now(timezone.utc)
        scored: list[tuple[float, Experience]] = []
        for row in rows:
            # A damaged row must never prevent safe retrieval of other records.
            try:
                experience = _experience(json.loads(row["payload_json"]))
                created = datetime.fromisoformat(experience.created_at)
            except (KeyError, TypeError, ValueError, json.JSONDecodeError):
                continue
            if max_age and now - created > max_age: continue
            score = len(terms & set(_terms(experience.goal)))
            score += 3 if task_type and task_type == experience.task_type else 0
            score += sum(1 for key, value in (environment or {}).items() if experience.environment.get(key) == value)
            if score: scored.append((score + (2 if experience.success and experience.verified else -2) + self.feedback_score(experience.experience_id), experience))
        return [item for _, item in sorted(scored, key=lambda pair: pair[0], reverse=True)[:limit]]

    def add_feedback(self, experience_id: str, kind: str, *, actor: str, detail: str = "") -> None:
        if kind not in {"approve", "reject", "correct", "prefer_strategy", "mark_result_wrong"}:
            raise ValueError("Unknown feedback kind")
        if self.db.execute("SELECT 1 FROM experiences WHERE id=?", (experience_id,)).fetchone() is None:
            raise KeyError(f"Unknown experience: {experience_id}")
        self.db.execute("INSERT INTO experience_feedback(experience_id,kind,actor,detail,created_at) VALUES (?,?,?,?,?)",
                        (experience_id, kind, actor, detail, datetime.now(timezone.utc).isoformat()))
        self.db.commit()

    def feedback_score(self, experience_id: str) -> int:
        rows = self.db.execute("SELECT kind FROM experience_feedback WHERE experience_id=?", (experience_id,))
        return sum({"approve": 1, "prefer_strategy": 1, "reject": -2, "mark_result_wrong": -2, "correct": -1}[row[0]] for row in rows)

    def purge_expired(self, max_age: timedelta) -> int:
        """Remove non-critical stale records and return the number removed."""
        cutoff = (datetime.now(timezone.utc) - max_age).isoformat()
        cursor = self.db.execute("DELETE FROM experiences WHERE created_at < ? AND success=0", (cutoff,))
        self.db.commit()
        return cursor.rowcount

    def close(self) -> None: self.db.close()

class SkillRegistry:
    def __init__(self, path: Path) -> None:
        self.db = sqlite3.connect(path); self.db.row_factory = sqlite3.Row
        self.db.execute("""CREATE TABLE IF NOT EXISTS skills (id TEXT PRIMARY KEY, name TEXT NOT NULL, version INTEGER NOT NULL,
          status TEXT NOT NULL, payload_json TEXT NOT NULL, UNIQUE(name, version))""")
        self.db.execute("""CREATE TABLE IF NOT EXISTS skill_audit (event_id INTEGER PRIMARY KEY, skill_id TEXT NOT NULL,
          event TEXT NOT NULL, actor TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL)""")
        self.db.commit()

    def _audit(self, skill_id: str, event: str, actor: str, reason: str) -> None:
        self.db.execute("INSERT INTO skill_audit(skill_id,event,actor,reason,created_at) VALUES (?,?,?,?,?)",
                        (skill_id, event, actor, reason, datetime.now(timezone.utc).isoformat()))

    def audit_trail(self, skill_id: str) -> tuple[dict[str, str], ...]:
        return tuple(dict(row) for row in self.db.execute("SELECT event,actor,reason,created_at FROM skill_audit WHERE skill_id=? ORDER BY event_id", (skill_id,)))

    def register(self, skill: Skill) -> None:
        if skill.status in {SkillStatus.TRUSTED, SkillStatus.VERIFIED}:
            raise ValueError("Learned skills must enter as candidates and be evaluated first")
        if not skill.workflow: raise ValueError("A skill needs an executable workflow")
        self.db.execute("INSERT INTO skills VALUES (?,?,?,?,?)", (skill.skill_id, skill.name, skill.version, skill.status.value, json.dumps(_skill_dict(skill), sort_keys=True)))
        self._audit(skill.skill_id, "created", "system", "registered candidate")
        self.db.commit()

    def versions(self, name: str) -> list[Skill]: return [_skill(json.loads(row["payload_json"])) for row in self.db.execute("SELECT * FROM skills WHERE name=? ORDER BY version", (name,))]
    def search(self, goal: str, *, statuses: tuple[SkillStatus, ...] = (SkillStatus.VERIFIED, SkillStatus.TRUSTED)) -> list[Skill]:
        wanted = set(_terms(goal)); return [skill for skill in self._all() if skill.status in statuses and wanted & set(_terms(skill.name + " " + skill.description))]
    def list_skills(self) -> tuple[Skill, ...]: return tuple(self._all())
    def get(self, skill_id: str) -> Skill: return _skill(json.loads(self.db.execute("SELECT payload_json FROM skills WHERE id=?", (skill_id,)).fetchone()[0]))
    def set_status(self, skill_id: str, status: SkillStatus, *, actor: str = "system", reason: str = "lifecycle transition") -> None:
        skill = self.get(skill_id)
        allowed = {
            SkillStatus.UNTRUSTED: {SkillStatus.CANDIDATE, SkillStatus.REJECTED},
            SkillStatus.CANDIDATE: {SkillStatus.TESTED, SkillStatus.VERIFIED, SkillStatus.REJECTED, SkillStatus.DEPRECATED},
            SkillStatus.TESTED: {SkillStatus.VERIFIED, SkillStatus.REJECTED, SkillStatus.DEPRECATED},
            SkillStatus.VERIFIED: {SkillStatus.TRUSTED, SkillStatus.DEPRECATED},
            SkillStatus.TRUSTED: {SkillStatus.DEPRECATED},
            SkillStatus.REJECTED: set(),
            SkillStatus.DEPRECATED: set(),
        }
        if status is not skill.status and status not in allowed[skill.status]:
            raise ValueError(f"Invalid skill lifecycle transition: {skill.status.value} -> {status.value}")
        data = _skill_dict(skill)
        data["status"] = status.value
        self.db.execute("UPDATE skills SET status=?,payload_json=? WHERE id=?", (status.value, json.dumps(data, sort_keys=True), skill_id))
        self._audit(skill_id, status.value, actor, reason)
        self.db.commit()
    def approve(self, skill_id: str, *, actor: str, reason: str) -> None:
        """Human approval is explicit and never grants runtime permissions."""
        skill = self.get(skill_id)
        if skill.status is not SkillStatus.TESTED:
            raise ValueError("Only sandbox-tested skills may be approved")
        self.set_status(skill_id, SkillStatus.VERIFIED, actor=actor, reason=reason)
    def reject(self, skill_id: str, *, actor: str, reason: str) -> None:
        self.set_status(skill_id, SkillStatus.REJECTED, actor=actor, reason=reason)
    def deprecate(self, skill_id: str, *, actor: str = "system", reason: str = "deprecated") -> None: self.set_status(skill_id, SkillStatus.DEPRECATED, actor=actor, reason=reason)
    def candidates(self) -> tuple[Skill, ...]: return tuple(skill for skill in self._all() if skill.status is SkillStatus.CANDIDATE)
    def _all(self) -> list[Skill]: return [_skill(json.loads(row["payload_json"])) for row in self.db.execute("SELECT payload_json FROM skills")]
    def close(self) -> None: self.db.close()

class WorkflowSynthesizer:
    """Composes discovered skills into a graph; returned graph is still advisory and must be validated."""
    def synthesize(self, goal: str, skills: list[Skill], experiences: list[Experience] = ()) -> TaskGraph:
        graph = TaskGraph(); previous: str | None = None
        for skill in skills:
            for index, step in enumerate(skill.workflow):
                node_id = f"{skill.skill_id}:{index}"
                graph.add(GraphTask(node_id, str(step.get("objective", skill.description)),
                    dependencies={previous} if previous else set(), capabilities=skill.required_capabilities,
                    permissions=skill.required_permissions, resources=frozenset(step.get("resources", ())), tool=step.get("tool"),
                    high_risk=skill.risk_level in {"high", "critical"}, requires_approval=skill.risk_level in {"high", "critical"}))
                previous = node_id
        graph.validate(); return graph

def _terms(text: str) -> list[str]: return re.findall(r"[a-z0-9_]+", text.casefold())
def _experience(data: dict[str, Any]) -> Experience:
    data["source"] = ExperienceSource(data["source"]); data["agents_used"] = tuple(data.get("agents_used", ())); data["observations"] = tuple(data.get("observations", ())); data["verification_results"] = tuple(data.get("verification_results", ())); data["capabilities_used"] = tuple(data.get("capabilities_used", ())); data["tools_used"] = tuple(data.get("tools_used", ())); data["actions"] = tuple(data.get("actions", ())); data["failures"] = tuple(data.get("failures", ())); data["recovery_steps"] = tuple(data.get("recovery_steps", ())); data["causal_evidence"] = tuple(data.get("causal_evidence", ())); return Experience(**data)
def _skill_dict(skill: Skill) -> dict[str, Any]:
    data = asdict(skill); data["required_capabilities"] = sorted(skill.required_capabilities); data["required_permissions"] = sorted(skill.required_permissions); data["status"] = skill.status.value; return data
def _skill(data: dict[str, Any]) -> Skill:
    data["required_capabilities"] = frozenset(data["required_capabilities"]); data["required_permissions"] = frozenset(data["required_permissions"]); data["workflow"] = tuple(data["workflow"]); data["expected_outcomes"] = tuple(data["expected_outcomes"]); data["failure_modes"] = tuple(data.get("failure_modes", ())); data["success_metrics"] = dict(data.get("success_metrics", {})); data["status"] = SkillStatus(data["status"]); return Skill(**data)
