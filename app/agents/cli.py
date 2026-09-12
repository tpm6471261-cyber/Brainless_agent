"""Read-only debug commands for persisted hierarchical-agent audit data."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.agents.building_blocks import AgentDefinition

from app.memory.sqlite_memory import SQLiteMemory


def run_agent_cli(arguments: list[str], database: Path) -> None:
    parser = argparse.ArgumentParser(prog="python run.py agent")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    inspect = commands.add_parser("inspect"); inspect.add_argument("agent_id")
    permissions = commands.add_parser("permissions"); permissions.add_argument("agent_id")
    logs = commands.add_parser("logs"); logs.add_argument("agent_id")
    tree = commands.add_parser("tree"); tree.add_argument("agent_id", nargs="?")
    create = commands.add_parser("create", help="Create an agent in a running dashboard runtime")
    create.add_argument("--parent", required=True, help="Parent agent UUID")
    create.add_argument("--name"); create.add_argument("--role")
    create.add_argument("--objective"); create.add_argument("--task")
    create.add_argument("--permission", action="append", default=[])
    create.add_argument("--tool", action="append", default=[])
    create.add_argument("--risk-policy", choices=("low", "medium", "high", "critical"), default="medium")
    create.add_argument("--dashboard", default="http://127.0.0.1:8765")
    create.add_argument("--token", required=True, help="Dashboard bearer token")
    create.add_argument("--definition", type=Path, help="JSON definition; named flags provide defaults")
    parsed = parser.parse_args(arguments)
    if parsed.command == "create":
        raw = json.loads(parsed.definition.read_text(encoding="utf-8")) if parsed.definition else {
            "name": parsed.name, "role": parsed.role, "objective": parsed.objective, "task": parsed.task,
            "permissions": parsed.permission, "tools": parsed.tool, "risk_policy": parsed.risk_policy,
        }
        definition = AgentDefinition.from_mapping(raw)
        payload = {"command": "create_agent", "payload": {
            "parent_agent_id": parsed.parent,
            "agent": {"name": definition.name, "role": definition.role,
                      "objective": definition.objective, "task": definition.task,
                      "permissions": sorted(definition.permissions), "tools": sorted(definition.tools),
                      "subscriptions": sorted(definition.subscriptions), "context": dict(definition.context),
                      "resource_limits": dict(definition.resource_limits),
                      "allowed_applications": sorted(definition.allowed_applications),
                      "allowed_directories": sorted(definition.allowed_directories),
                      "risk_policy": definition.risk_policy}}}
        request = Request(parsed.dashboard.rstrip("/") + "/api/commands",
                          data=json.dumps(payload).encode(), method="POST",
                          headers={"Authorization": f"Bearer {parsed.token}", "Content-Type": "application/json"})
        try:
            with urlopen(request, timeout=10) as response:
                print(json.dumps(json.loads(response.read()), indent=2))
        except (HTTPError, URLError) as error:
            detail = error.read().decode() if isinstance(error, HTTPError) else str(error)
            raise SystemExit(f"Agent creation failed: {detail}") from error
        return
    storage = SQLiteMemory(database)
    try:
        records = storage.agent_records()
        if parsed.command == "list":
            print("\n".join(f"{item['agent_id']} {item['status']} {item['name']}" for item in records))
        elif parsed.command == "inspect":
            print(json.dumps(_record(records, parsed.agent_id), indent=2, default=str))
        elif parsed.command == "permissions":
            print("\n".join(_record(records, parsed.agent_id)["permissions"]))
        elif parsed.command == "logs":
            print(json.dumps(storage.agent_events(parsed.agent_id), indent=2, default=str))
        else:
            root_id = parsed.agent_id or next((item["agent_id"] for item in records if item["parent_agent_id"] is None), None)
            if root_id is None:
                raise SystemExit("No persisted agents found")
            print(json.dumps(_tree(records, root_id), indent=2, default=str))
    finally:
        storage.close()


def _record(records: list[dict[str, object]], agent_id: str) -> dict[str, object]:
    for record in records:
        if record["agent_id"] == agent_id:
            return record
    raise SystemExit(f"Unknown agent: {agent_id}")


def _tree(records: list[dict[str, object]], agent_id: str) -> dict[str, object]:
    record = _record(records, agent_id)
    return {"agent_id": agent_id, "name": record["name"],
            "children": [_tree(records, item["agent_id"]) for item in records if item["parent_agent_id"] == agent_id]}
