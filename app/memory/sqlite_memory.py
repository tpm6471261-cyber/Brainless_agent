"""SQLite-backed, local-only task result storage."""
from __future__ import annotations

import sqlite3
import json
from pathlib import Path

from app.memory.models import MemoryRecord


class SQLiteMemory:
    def __init__(self, database_path: Path) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = sqlite3.connect(database_path)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("""CREATE TABLE IF NOT EXISTS task_results (
            id INTEGER PRIMARY KEY, task_id TEXT NOT NULL, timestamp TEXT NOT NULL,
            provider TEXT NOT NULL, prompt TEXT NOT NULL, response TEXT NOT NULL,
            status TEXT NOT NULL, duration_seconds REAL NOT NULL, workflow TEXT NOT NULL,
            final_result INTEGER NOT NULL, error TEXT, screenshot_path TEXT)""")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS agent_records (
            agent_id TEXT PRIMARY KEY, parent_agent_id TEXT, name TEXT NOT NULL, role TEXT NOT NULL,
            objective TEXT NOT NULL, current_task TEXT, status TEXT NOT NULL, created_at TEXT NOT NULL,
            permissions_json TEXT NOT NULL, tools_json TEXT NOT NULL, result TEXT, error TEXT)""")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS agent_events (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, agent_id TEXT NOT NULL, parent_agent_id TEXT,
            task_id TEXT, event_type TEXT NOT NULL, detail TEXT NOT NULL, metadata_json TEXT NOT NULL)""")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS computer_action_audit (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, agent_id TEXT NOT NULL, parent_agent_id TEXT, task_id TEXT NOT NULL,
            action_id TEXT NOT NULL, tool TEXT NOT NULL, permission TEXT NOT NULL, arguments_json TEXT NOT NULL,
            result TEXT, error TEXT, duration_ms REAL NOT NULL, policy_decision TEXT NOT NULL,
            approval_status TEXT NOT NULL)""")
        self._connection.execute("""CREATE TABLE IF NOT EXISTS task_journal (
            id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL, task_id TEXT NOT NULL,
            event_type TEXT NOT NULL, detail_json TEXT NOT NULL)""")
        columns = {row[1] for row in self._connection.execute("PRAGMA table_info(task_results)")}
        if "screenshot_path" not in columns:
            self._connection.execute("ALTER TABLE task_results ADD COLUMN screenshot_path TEXT")
        audit_columns = {row[1] for row in self._connection.execute("PRAGMA table_info(computer_action_audit)")}
        if "parent_agent_id" not in audit_columns:
            self._connection.execute("ALTER TABLE computer_action_audit ADD COLUMN parent_agent_id TEXT")
        self._connection.commit()

    def store(self, record: MemoryRecord) -> None:
        self._connection.execute("""INSERT INTO task_results
            (task_id,timestamp,provider,prompt,response,status,duration_seconds,workflow,final_result,error,screenshot_path)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)""", (record.task_id, record.timestamp.isoformat(), record.provider,
            record.prompt, record.response, record.status, record.duration_seconds, record.workflow,
            int(record.final_result), record.error, record.screenshot_path))
        self._connection.commit()

    def search(self, query: str, limit: int = 5) -> list[MemoryRecord]:
        terms = [term for term in query.split() if len(term) >= 3] or [query]
        conditions = " OR ".join("response LIKE ? OR prompt LIKE ?" for _ in terms)
        values = [value for term in terms for value in (f"%{term}%", f"%{term}%")]
        rows = self._connection.execute(f"SELECT * FROM task_results WHERE {conditions} "
            "ORDER BY timestamp DESC LIMIT ?", (*values, limit)).fetchall()
        from datetime import datetime
        return [MemoryRecord(row["task_id"], datetime.fromisoformat(row["timestamp"]), row["provider"],
                row["prompt"], row["response"], row["status"], row["duration_seconds"], row["workflow"],
                bool(row["final_result"]), row["error"], row["screenshot_path"]) for row in rows]

    def recent_metadata(self, limit: int = 100) -> list[dict[str, object]]:
        """Dashboard-safe task history without prompt, response, or screenshot content."""
        rows = self._connection.execute("SELECT task_id,timestamp,provider,status,duration_seconds,"
            "final_result,error FROM task_results ORDER BY timestamp DESC LIMIT ?", (max(0, min(limit, 500)),)).fetchall()
        return [dict(row) for row in rows]

    def close(self) -> None:
        self._connection.close()

    def store_agent(self, agent) -> None:
        """Persist an agent snapshot without coupling memory to the orchestration package."""
        self._connection.execute("""INSERT INTO agent_records
            (agent_id,parent_agent_id,name,role,objective,current_task,status,created_at,permissions_json,tools_json,result,error)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(agent_id) DO UPDATE SET parent_agent_id=excluded.parent_agent_id,name=excluded.name,
            role=excluded.role,objective=excluded.objective,current_task=excluded.current_task,status=excluded.status,
            permissions_json=excluded.permissions_json,tools_json=excluded.tools_json,result=excluded.result,error=excluded.error""",
            (agent.agent_id, agent.parent_agent_id, agent.name, agent.role, agent.objective, agent.current_task,
             agent.status.value, agent.created_at.isoformat(), json.dumps(sorted(agent.permissions)),
             json.dumps(sorted(agent.available_tools)), agent.result, agent.error))
        self._connection.commit()

    def store_agent_event(self, event) -> None:
        self._connection.execute("""INSERT INTO agent_events
            (timestamp,agent_id,parent_agent_id,task_id,event_type,detail,metadata_json) VALUES (?,?,?,?,?,?,?)""",
            (event.timestamp.isoformat(), event.agent_id, event.parent_agent_id, event.task_id, event.type.value,
             event.detail, json.dumps(event.metadata, sort_keys=True)))
        self._connection.commit()

    def agent_events(self, agent_id: str | None = None, limit: int = 100) -> list[dict[str, object]]:
        query = "SELECT * FROM agent_events" + (" WHERE agent_id=?" if agent_id else "") + " ORDER BY id DESC LIMIT ?"
        values = (agent_id, limit) if agent_id else (limit,)
        return [dict(row) | {"metadata": json.loads(row["metadata_json"])}
                for row in self._connection.execute(query, values).fetchall()]

    def agent_records(self) -> list[dict[str, object]]:
        return [dict(row) | {"permissions": json.loads(row["permissions_json"]),
                              "tools": json.loads(row["tools_json"])}
                for row in self._connection.execute("SELECT * FROM agent_records ORDER BY created_at").fetchall()]

    def store_action_audit(self, record) -> None:
        """Persist runtime-owned computer action audit records without an autonomy import."""
        self._connection.execute("""INSERT INTO computer_action_audit
            (timestamp,agent_id,parent_agent_id,task_id,action_id,tool,permission,arguments_json,result,error,duration_ms,policy_decision,approval_status)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""", (record.timestamp.isoformat(), record.agent_id, record.parent_agent_id, record.task_id,
            record.action_id, record.tool, record.permission, json.dumps(record.arguments, sort_keys=True), record.result,
            record.error, record.duration_ms, record.policy_decision, record.approval_status))
        self._connection.commit()

    def computer_action_audit(self, task_id: str | None = None) -> list[dict[str, object]]:
        query = "SELECT * FROM computer_action_audit" + (" WHERE task_id=?" if task_id else "") + " ORDER BY id"
        values = (task_id,) if task_id else ()
        return [dict(row) | {"arguments": json.loads(row["arguments_json"])}
                for row in self._connection.execute(query, values).fetchall()]

    def store_task_journal(self, task_id: str, event_type: str, detail: dict[str, object]) -> None:
        from datetime import datetime, timezone
        self._connection.execute("INSERT INTO task_journal (timestamp,task_id,event_type,detail_json) VALUES (?,?,?,?)",
            (datetime.now(timezone.utc).isoformat(), task_id, event_type, json.dumps(detail, sort_keys=True)))
        self._connection.commit()

    def task_journal(self, task_id: str) -> list[dict[str, object]]:
        return [dict(row) | {"detail": json.loads(row["detail_json"])} for row in self._connection.execute(
            "SELECT * FROM task_journal WHERE task_id=? ORDER BY id", (task_id,)).fetchall()]
