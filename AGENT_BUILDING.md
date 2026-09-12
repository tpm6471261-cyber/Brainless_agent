# Agent building and lifecycle handbook

This handbook is the complete operator and developer guide for creating, validating, inspecting, changing, running, and retiring Brainless agents.

> Scope: the instructions describe the repository as implemented. They do not imply that the dashboard can grant authority, execute an agent, or edit every field after creation.

> Security rule: an agent is configuration under a parent-owned authority boundary. It is not an arbitrary Python plug-in and it cannot create permissions for itself.

## Table of contents

1. [Mental model](#mental-model)
2. [Five-minute quick start](#five-minute-quick-start)
3. [Prerequisites](#prerequisites)
4. [Definition schema](#definition-schema)
5. [Python building blocks](#python-building-blocks)
6. [Dashboard creation](#dashboard-creation)
7. [CLI creation](#cli-creation)
8. [JSON definitions](#json-definitions)
9. [Updating an agent](#updating-an-agent)
10. [Task and lifecycle operations](#task-and-lifecycle-operations)
11. [Permissions, tools, and leases](#permissions-tools-and-leases)
12. [Scopes, resources, and risk](#scopes-resources-and-risk)
13. [Patterns and recipes](#patterns-and-recipes)
14. [Validation and testing](#validation-and-testing)
15. [Troubleshooting](#troubleshooting)
16. [Security runbooks](#security-runbooks)
17. [API reference](#api-reference)
18. [Operational checklists](#operational-checklists)
19. [Glossary](#glossary)

## Mental model

Every runtime agent has an identity, a purpose, a lifecycle state, and an explicit authority envelope. The root is created by the application. Child creation is always attributed to one direct parent.

1. Identify the outcome and decide whether a reusable child already exists.
2. Select the direct parent that owns the minimum required permissions.
3. Select registered tools; do not substitute generic computer control for a missing specialist tool.
4. Add every permission required by the selected tools, but no unrelated permission.
5. Narrow application and directory boundaries where the parent already has boundaries.
6. Set a risk ceiling and positive finite resource limits.
7. Create the child through `AgentDefinition`, the authenticated dashboard, or the live-runtime CLI.
8. Inspect the resulting record before assigning or starting work.
9. Run tools only through `AgentManager.execute_tool` while the agent is running.
10. Collect verified results, revoke temporary authority, and terminate agents that are no longer needed.

### Authority flow

```text
operator -> root agent -> direct child -> allow-listed tool
                         |               |
                         |               +-> tool-required permissions
                         +-> parent-owned permissions only
```

Creation does not execute a tool. A subscription does not execute a tool. Context does not execute a tool. A tool identifier does not grant its permissions. Each boundary is checked separately.

### Important distinctions

| Concept | What it does | What it does not do |
|---|---|---|
| Definition | Describes a requested child | Register tools or callbacks |
| Parent | Delegates authority it owns | Invent new authority |
| Permission | Names an allowed capability | Select a tool automatically |
| Tool allow-list | Selects callable registered tools | Bypass required permissions |
| Risk policy | Caps acceptable action risk | Approve sensitive actions |
| Resource limit | Bounds consumption | Grant any capability |
| Subscription | Records event interests | Authorize event-driven actions |
| Context | Supplies bounded string metadata | Carry secrets or executable code |
| Lease | Temporarily supplies one capability | Survive restart or task reassignment |
| Dashboard token | Authenticates a command-center caller | Expand a parent's permission set |

## Five-minute quick start

Use this path for a first read-only child in a running dashboard.

1. Install project dependencies and configure the runtime as described in `README.md` and `run_project.md`.
2. Set `BRAINLESS_DASHBOARD_TOKEN` to a random value containing at least 16 characters.
3. Start `python run_dashboard.py` and retain the root agent ID shown in the Agents page.
4. Open Agents, choose Create agent, and select Root Operator as the parent.
5. Enter a name, role, objective, and optional initial task.
6. Leave permissions and tools empty for a metadata-only child, or enter an exact registered read capability and tool.
7. Choose `low` risk for observation-only work.
8. Submit, then verify the child under Agents and Hierarchy.
9. Use the CLI `list`, `inspect`, `permissions`, `logs`, and `tree` commands to inspect persisted audit records.

### Minimal Python example

```python
from app.agents import AgentDefinition

child = AgentDefinition.from_mapping({
    "name": "Observer",
    "role": "reader",
    "objective": "Inspect assigned metadata without external side effects",
    "risk_policy": "low",
}).create(manager, root.agent_id)
```

The child is ready but not running. It has no permissions and no tools.

### Minimal CLI example

```bash
python run.py agent create \
  --token "$BRAINLESS_DASHBOARD_TOKEN" \
  --parent "$ROOT_AGENT_ID" \
  --name Observer \
  --role reader \
  --objective "Inspect assigned metadata without external side effects" \
  --risk-policy low
```

## Prerequisites

Complete these checks before creating an agent.

1. Use Python 3.11 or newer.
2. Create and activate a virtual environment.
3. Install `requirements.txt`; browser-backed runtime imports require Playwright.
4. Start the authoritative runtime before using `agent create` from the CLI.
5. Use a dashboard token of at least 16 characters.
6. Ensure a root agent exists; the normal configured dashboard creates Root Operator.
7. Inventory registered tools and their required permissions.
8. Determine the exact parent agent ID.
9. Do not use a terminal snapshot ID from an unrelated runtime process.
10. Prepare only non-secret context values.

### Environment setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
export BRAINLESS_DASHBOARD_TOKEN="replace-with-a-long-random-token"
python run_dashboard.py
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` and set environment variables using `$env:BRAINLESS_DASHBOARD_TOKEN = '...'`.

### Find the parent ID

Dashboard method:

1. Open Agents.
2. Locate the intended parent.
3. Copy the full UUID from the authoritative API or inspect output; the table visually abbreviates IDs.

CLI inspection method:

```bash
python run.py agent list
python run.py agent tree
python run.py agent inspect ROOT_AGENT_UUID
```

The inspection commands read persisted audit data. Creation posts to the live dashboard runtime.

## Definition schema

`AgentDefinition.from_mapping` is the canonical validation boundary shared by Python, dashboard commands, JSON definitions, and the CLI.

| Field | Required | Type | Bound | Meaning |
|---|---:|---|---|---|
| `name` | yes | string | 1..100 | Human-readable identity; unique names are recommended but not enforced. |
| `role` | yes | string | 1..100 | Functional role used by operators and projections. |
| `objective` | yes | string | 1..2000 | Stable outcome or responsibility, not a hidden prompt. |
| `task` | no | string or null | 1..4000 | Initial task; creation generates a task ID when supplied. |
| `permissions` | no | list of strings | 0..100 entries | Permanent capabilities requested from the direct parent. |
| `tools` | no | list of strings | 0..100 entries | Registered tool IDs allowed for this child. |
| `subscriptions` | no | list of strings | 0..100 entries | Event interests; these confer no execution authority. |
| `context` | no | object | 0..100 entries | Keys and values become strings; never store secrets here. |
| `resource_limits` | no | number object | 0..20 entries | Every value must be finite and greater than zero. |
| `allowed_applications` | no | list of strings | 0..100 entries | Application scope; cannot exceed a bounded parent. |
| `allowed_directories` | no | list of strings | 0..100 entries | Resolved paths; each child path must be under a parent root. |
| `risk_policy` | no | enum | low/medium/high/critical | Maximum risk accepted by compatible action execution; default medium. |

### Validation order

1. Confirm the input is a mapping/object.
2. Reject every unknown top-level field.
3. Trim and bound `name`, `role`, and `objective`.
4. Convert empty or null `task` to no task; otherwise trim and bound it.
5. Normalize the risk policy to lowercase and validate the enum.
6. Validate context and resource-limit container sizes.
7. Convert each resource number to `float` and reject zero, negatives, infinity, and NaN.
8. Validate list fields and reject plain strings used in place of lists.
9. Convert context keys and values to strings.
10. Ask the manager to validate the parent, permissions, tools, and required tool permissions.
11. Apply inherited or narrowed scopes.
12. Record subscriptions through the manager so the authoritative snapshot is persisted.

### Complete JSON example

```json
{
  "name": "Documentation reviewer",
  "role": "researcher",
  "objective": "Review local documentation and return a concise report",
  "task": "Inspect architecture documents",
  "permissions": ["browser.read", "browser.navigate"],
  "tools": ["browser.read_title"],
  "subscriptions": ["task_assigned"],
  "context": {"format": "markdown", "audience": "maintainers"},
  "resource_limits": {"max_runtime": 300, "max_actions_per_minute": 10},
  "allowed_applications": [],
  "allowed_directories": ["/workspace/project/docs"],
  "risk_policy": "low"
}
```

## Python building blocks

Use Python creation when composing agents inside the runtime or in controlled integration code.

### Import surface

```python
from app.agents import AgentDefinition, AgentManager, create_agent
```

### Step-by-step declarative creation

1. Obtain the active `AgentManager`.
2. Obtain the direct parent ID.
3. Build a plain mapping.
4. Pass the mapping to `AgentDefinition.from_mapping`.
5. Handle `ValueError`, `KeyError`, `PermissionError`, or `PermissionDenied` at the caller boundary.
6. Call `definition.create(manager, parent_id)`.
7. Retain the returned `Agent` object or its `agent_id`.
8. Inspect the created status; it should be `ready`.
9. Assign/start work separately.

```python
definition = AgentDefinition.from_mapping({
    "name": "Release note reader",
    "role": "reviewer",
    "objective": "Summarize release notes",
    "permissions": ["browser.read", "browser.navigate"],
    "tools": ["browser.read_title"],
    "allowed_directories": ["/workspace/project/docs"],
    "risk_policy": "low",
})
try:
    child = definition.create(manager, root.agent_id)
except (ValueError, KeyError, PermissionError) as error:
    raise RuntimeError(f"Agent definition was rejected: {error}") from error
```

### Functional helper

```python
child = create_agent(
    manager,
    root.agent_id,
    name="Metadata worker",
    role="worker",
    objective="Transform bounded in-memory metadata",
    risk_policy="low",
)
```

The helper performs the same mapping validation and calls the same creation path. It is convenience, not a privileged API.

### Create a root

Only application composition code should create a root:

```python
root = manager.create_root(
    "Root Operator",
    "orchestrator",
    "Supervise autonomous missions",
    {permission.value for permission in Permission},
)
```

A manager permits only one root. Dashboard and CLI child creation do not expose root creation.

### Creation exceptions

| Exception | Typical cause | Operator response |
|---|---|---|
| `ValueError` | Invalid schema, risk, limit, unknown tool, or missing tool permission | Correct the definition; never suppress validation |
| `KeyError` | Parent ID or tool ID is unknown | Refresh runtime state and use an active ID |
| `PermissionError` | Child application/directory scope exceeds parent | Narrow the child scope |
| `PermissionDenied` | Parent lacks a requested permission | Remove it or choose a legitimately authorized parent |

## Dashboard creation

The dashboard uses the authenticated command gateway. It does not write directly to SQLite and does not construct arbitrary objects.

1. Start the dashboard and authenticate with its bearer token.
2. Open the Agents page from the Runtime navigation group.
3. Select Create agent.
4. Choose a non-terminated parent from the live list.
5. Enter a descriptive name and role.
6. Write a stable objective.
7. Optionally enter the initial task.
8. Enter exact permission IDs separated by commas.
9. Enter exact registered tool IDs separated by commas.
10. Select the lowest workable risk ceiling.
11. Review that no credentials appear in any field.
12. Submit the form.
13. Wait for the accepted notification and refreshed snapshot.
14. Locate the new UUID in Agents.
15. Open Hierarchy and verify the direct parent relationship.
16. Inspect Security if the request was rejected.

### Dashboard field guidance

#### Parent agent

Select the closest owner of the needed authority. Choosing the root for every child weakens hierarchy even though subset checks still apply.

#### Name

Use a short operational identity such as `Docs Reader`, not a task-sized paragraph.

#### Role

Use a stable function such as `researcher`, `reviewer`, `browser_operator`, or `tester`.

#### Objective

Describe the long-lived responsibility. Do not paste webpage content or provider instructions.

#### Initial task

Describe the first bounded unit of work. Leave blank if assignment happens later.

#### Permissions and tools

Use comma-separated exact identifiers. Whitespace is trimmed. Empty segments are ignored by the browser client.

#### Risk ceiling

Choose `low` for reads, `medium` only when the intended action specifications require it, and higher values only under an explicit governance plan.

### What happens after Submit

1. The browser serializes the form to JSON.
2. The browser sends `POST /api/commands` with the bearer token.
3. The gateway compares the token in constant time.
4. The gateway allow-lists `create_agent`.
5. `AgentDefinition.from_mapping` validates the nested agent object.
6. The definition resolves the selected parent.
7. Application and directory scopes are checked.
8. `AgentManager.create_agent` verifies parent permissions and registered tools.
9. Runtime metadata and subscriptions are recorded.
10. The response returns `agent_id`, `parent_agent_id`, command, and correlation ID.
11. The UI refreshes from the authoritative system snapshot.

### Dashboard limitations

- The current form creates children; it does not create roots.
- The current form exposes core identity, task, permissions, tools, and risk fields.
- Advanced context, subscriptions, scopes, and resource limits should be supplied by JSON through the CLI or Python API.
- The current form does not start the child.
- The current form does not register missing tools.
- The current form does not grant permission to the parent.
- The dashboard cannot bypass approvals, governor contracts, mode policy, or tool validation.
- Existing agent field updates use manager lifecycle methods, not a general dashboard patch endpoint.

## CLI creation

The CLI creation command validates locally, then posts to the running dashboard. This avoids unaudited direct database mutation.

### Basic command

```bash
python run.py agent create \
  --dashboard http://127.0.0.1:8765 \
  --token "$BRAINLESS_DASHBOARD_TOKEN" \
  --parent "$ROOT_AGENT_ID" \
  --name "Read-only researcher" \
  --role researcher \
  --objective "Review project documentation" \
  --task "Summarize architecture" \
  --permission browser.read \
  --permission browser.navigate \
  --tool browser.read_title \
  --risk-policy low
```

### CLI options

| Option | Required | Repeatable | Purpose |
|---|---:|---:|---|
| `--parent` | yes | no | Direct parent UUID |
| `--name` | without definition | no | Agent name |
| `--role` | without definition | no | Agent role |
| `--objective` | without definition | no | Agent objective |
| `--task` | no | no | Initial task |
| `--permission` | no | yes | One permission per occurrence |
| `--tool` | no | yes | One registered tool per occurrence |
| `--risk-policy` | no | no | Risk ceiling; default medium |
| `--dashboard` | no | no | Base URL; default loopback port 8765 |
| `--token` | yes | no | Dashboard bearer token |
| `--definition` | no | no | Complete JSON definition file |

### Multiple permissions and tools

```bash
python run.py agent create \
  --token "$BRAINLESS_DASHBOARD_TOKEN" \
  --parent "$ROOT_AGENT_ID" \
  --name "Browser observer" \
  --role browser_researcher \
  --objective "Read and navigate public documentation" \
  --permission browser.read \
  --permission browser.navigate \
  --tool browser.read_title \
  --risk-policy low
```

Repeat flags; do not comma-join values on the CLI.

### Interpret output

```json
{
  "accepted": true,
  "command": "create_agent",
  "correlation_id": "...",
  "agent_id": "...",
  "parent_agent_id": "..."
}
```

Save the full `agent_id`. A successful HTTP response means creation was accepted, not that work ran.

### Inspect after creation

```bash
python run.py agent list
python run.py agent inspect AGENT_UUID
python run.py agent permissions AGENT_UUID
python run.py agent logs AGENT_UUID
python run.py agent tree ROOT_AGENT_UUID
```

Inspection reads persisted audit data. If the live child is not yet visible, allow the runtime bridge/store to flush and retry.

## JSON definitions

Use JSON for advanced definition fields and reproducible review.

### Create the file

```bash
cat > docs-reader.agent.json <<'JSON'
{
  "name": "Docs reader",
  "role": "researcher",
  "objective": "Read approved documentation roots",
  "task": "Summarize the agent handbook",
  "permissions": ["browser.read", "browser.navigate"],
  "tools": ["browser.read_title"],
  "subscriptions": ["task_assigned", "task_cancelled"],
  "context": {"format": "bullets", "language": "en"},
  "resource_limits": {
    "max_runtime": 300,
    "max_actions_per_minute": 12,
    "max_concurrent_actions": 1
  },
  "allowed_directories": ["/workspace/project/docs"],
  "allowed_applications": [],
  "risk_policy": "low"
}
JSON
```

### Validate and submit

```bash
python -m json.tool docs-reader.agent.json >/dev/null
python run.py agent create \
  --dashboard http://127.0.0.1:8765 \
  --token "$BRAINLESS_DASHBOARD_TOKEN" \
  --parent "$ROOT_AGENT_ID" \
  --definition docs-reader.agent.json
```

### Review checklist

1. Confirm every top-level key is in the schema.
2. Confirm the objective contains no secret or copied credential.
3. Confirm every tool exists in inventory.
4. Confirm each tool-required permission appears in permissions.
5. Confirm the parent owns every requested permission.
6. Resolve directory paths and confirm they are nested under parent roots.
7. Confirm application names match the parent's allowed set when bounded.
8. Confirm all limits are positive and finite.
9. Confirm risk is lowercase or normalizable to a valid value.
10. Commit reusable non-secret definitions only if project policy permits.

## Updating an agent

There is intentionally no unrestricted `PATCH agent` operation. Update through explicit `AgentManager` lifecycle methods so ownership and audit behavior remain visible.

| Update | Method | Authority rule | Result |
|---|---|---|---|
| Assign or replace a task | `assign_task(parent_id, agent_id, task, context=None, task_id=None)` | Direct parent only; terminated children are rejected. | Sets status to ready, clears result/error, and creates or accepts a task ID. |
| Grant a permanent permission | `grant_permission(parent_id, agent_id, permission)` | Direct parent must own the permission. | Adds permission and records a status event. |
| Revoke a permission | `revoke_permission(parent_id, agent_id, permission)` | Direct parent only. | Removes permission; also review tools that now lack requirements. |
| Grant a tool | `grant_tool(parent_id, agent_id, tool_id)` | Tool must be registered and child must already hold requirements. | Adds the tool to the allow-list and records an event. |
| Update subscriptions | `set_event_subscriptions(parent_id, agent_id, subscriptions)` | Direct parent only. | Replaces the subscription set and records an event. |
| Lease authority | `lease_permission(parent_id, agent_id, permission, task_id, seconds)` | Parent-owned permission, exact current task, maximum registry duration. | Creates temporary task-scoped authority. |
| Revoke a lease | `manager.leases.revoke(lease_id)` | Use the authoritative lease registry. | Immediately invalidates temporary authority. |
| Pause | `pause_agent(parent_id, agent_id)` | Direct child; effective for running status. | Marks paused and records a status event. |
| Resume | `resume_agent(parent_id, agent_id)` | Direct child in paused status. | Returns the child to ready. |
| Terminate | `terminate_agent(parent_id, agent_id)` | Direct child only. | Cancels tracked work and marks terminated. |

### Step-by-step task update

```python
manager.assign_task(
    parent.agent_id,
    child.agent_id,
    "Review the revised architecture document",
    {"document": "architecture.md", "format": "summary"},
)
```

1. Verify the caller is the direct parent.
2. Verify the child is not terminated.
3. Choose a bounded, non-secret context.
4. Supply a stable task ID only when correlating to an existing mission task.
5. Call `assign_task`.
6. Confirm `current_task`, `current_task_id`, and `status`.
7. Confirm prior result and error fields were cleared.
8. Review the task event in logs.

### Step-by-step permission update

```python
manager.grant_permission(parent.agent_id, child.agent_id, "browser.read")
manager.grant_permission(parent.agent_id, child.agent_id, "browser.navigate")
manager.grant_tool(parent.agent_id, child.agent_id, "browser.read_title")
```

1. Inspect the tool specification.
2. List its required permissions.
3. Confirm the parent owns them.
4. Grant only the required permission to the direct child.
5. Grant the tool after the permission exists.
6. Inspect `available_tools(child.agent_id)`.
7. Execute only while the child is running.
8. Revoke authority when no longer required.

### Replace immutable-style configuration

For name, role, objective, directory scope, application scope, resource limits, or risk policy, prefer creating a reviewed replacement child and terminating the old child. This avoids partially mutating an authority boundary without a dedicated audit operation.

1. Inspect and export the old non-secret configuration.
2. Remove stale permissions and tools from the proposed definition.
3. Apply the new scope or risk ceiling.
4. Create the replacement under the same authorized parent.
5. Assign a fresh task or explicitly correlate the intended task.
6. Verify the replacement in the hierarchy.
7. Pause the old child.
8. Confirm no tracked operation is active.
9. Terminate the old child.
10. Record the replacement relationship in external operational notes, not secret context.

### Dashboard and CLI update status

The current dashboard and CLI expose child creation and read-only inspection, not a generic update command. Do not edit SQLite records to simulate an update. Use in-process manager methods or create a replacement definition until a narrowly authorized update command is implemented.

## Task and lifecycle operations

Creation, assignment, execution, result collection, retry, pause, resume, and termination are separate operations.

### Status reference

| Status | Meaning |
|---|---|
| `created` | Object default before manager readiness is applied. |
| `ready` | Created or assigned and eligible to start. |
| `running` | Executor active; tools may be invoked. |
| `waiting` | Waiting on runtime work or dependency. |
| `blocked` | Unable to progress under current conditions. |
| `completed` | Executor returned successfully; result is available. |
| `failed` | Executor raised; error is recorded. |
| `paused` | Parent paused a running child. |
| `terminated` | Final manual/cancellation state; cannot be reassigned or started. |

### Full execution example

```python
async def work(agent, supervisor):
    supervisor.report_progress(agent.agent_id, "Reading approved document")
    result = await supervisor.execute_tool(
        agent.agent_id,
        "browser.read_title",
        {"url": "https://example.com/documentation"},
    )
    return str(result)

result = await manager.start_agent(parent.agent_id, child.agent_id, work)
assert manager.collect_result(parent.agent_id, child.agent_id) == result
```

### Lifecycle runbook

1. Create a ready child.
2. Confirm task and tool requirements.
3. Start through the direct parent.
4. During execution, report progress through the manager.
5. Invoke only allow-listed tools through the manager.
6. Let exceptions propagate so failure is recorded accurately.
7. Collect results only after completed status.
8. Retry only a failed child and within the manager retry limit.
9. Pause or terminate from the direct parent when intervention is required.
10. Never modify status fields merely to make a failed operation appear successful.

## Permissions, tools, and leases

Authority requires agreement between parent ownership, child permissions, tool allow-list, tool requirements, policy, and any applicable lease.

### Permission algorithm

1. Resolve the child and direct parent.
2. For creation or permanent grants, confirm the requested permission belongs to the parent.
3. Resolve every requested tool in `ToolRegistry`.
4. Confirm each tool's required permissions are present in the requested child set.
5. At execution time, confirm the agent is running.
6. Confirm the tool is allow-listed for the child.
7. For each requirement, accept a permanent permission or active matching lease.
8. Ask global permission policy for its decision.
9. Execute the registered handler only after every gate passes.
10. Record success or failure in execution history and events.

### Discover usable tools

```python
for item in manager.available_tools(child.agent_id):
    print(item["tool_id"], item["permissions"], item["risk"])
```

This method filters the child's allow-list to tools whose required permissions are currently permanent. Lease-aware execution can still authorize a missing permanent permission for the exact task while the lease is active.

### Capability lease example

```python
lease = manager.lease_permission(
    parent.agent_id,
    child.agent_id,
    "filesystem.read",
    child.current_task_id,
    seconds=300,
)
# Later:
manager.leases.revoke(lease.lease_id)
```

A lease is scoped to one agent, permission, and current task. Expiry, revocation, task reassignment, or restart fails closed.

## Scopes, resources, and risk

Scopes and limits narrow operation but never add authority.

### Directory boundaries

Child paths are expanded and resolved. If the parent has directory roots, every requested child path must be located at or beneath at least one root.

Accepted example:

```text
parent: /workspace/project
child:  /workspace/project/docs
```

Rejected example:

```text
parent: /workspace/project/docs
child:  /workspace/project
```

Use real intended roots. Do not rely on `..`, symlink tricks, or string-prefix similarity.

### Application boundaries

When the parent is bounded, the child's requested application set must be a subset. An empty child set inherits the parent's set during creation.

### Resource limits

| Common key | Unit | Purpose |
|---|---|---|
| `max_runtime` | seconds | Maximum lifetime window checked by the event action limiter |
| `max_actions_per_minute` | count | Sliding per-minute action rate |
| `max_concurrent_actions` | count | Simultaneous active action count |
| `max_event_rate` | count/minute | Sliding event-delivery rate |

All values must be positive finite numbers. A resource limit is not a scheduler guarantee; it is a denial boundary.

### Risk ceiling

| Policy | Intended use |
|---|---|
| `low` | Read-only observation and low-risk transformations |
| `medium` | Moderate operations under ordinary policy |
| `high` | Sensitive operations requiring explicit governance |
| `critical` | Exceptional operations; never a substitute for approval |

The event action executor denies an action whose registered risk exceeds the child's risk policy. Other runtime policy and approval gates continue to apply even when the ceiling is high.

## Patterns and recipes

The following recipes are starting points. Replace identifiers with tools and permissions that are actually registered in your runtime.

Some recipes intentionally show domain-specific adapters such as `filesystem.read`; the production registry currently exposes `browser.read_title`, `browser.type`, `keyboard.write`, `mouse.click`, `filesystem.write`, `process.execute`, and `screen.capture`. A domain-specific example is not callable until its real adapter is registered.

### Recipe 1: Metadata-only coordinator

**Objective:** Coordinate child results without calling tools.

**Risk ceiling:** `low`.

**Permissions:** none.

**Tools:** none.

**Directory scope:** inherited or none.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Coordinate child results without calling tools`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 2: Documentation reader

**Objective:** Read approved local documentation.

**Risk ceiling:** `low`.

**Permissions:** `filesystem.read`.

**Tools:** `filesystem.read`.

**Directory scope:** `/workspace/project/docs`.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Read approved local documentation`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 3: Browser observer

**Objective:** Observe browser state without navigation.

**Risk ceiling:** `low`.

**Permissions:** `screen.read`.

**Tools:** none.

**Directory scope:** inherited or none.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Observe browser state without navigation`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 4: Browser navigator

**Objective:** Navigate approved web resources.

**Risk ceiling:** `medium`.

**Permissions:** `screen.read`, `browser.navigate`.

**Tools:** `browser.navigate`.

**Directory scope:** inherited or none.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Navigate approved web resources`.
7. Set `risk_policy` to `medium` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 5: Text entry worker

**Objective:** Enter reviewed text into an active application.

**Risk ceiling:** `high`.

**Permissions:** `keyboard.write`.

**Tools:** `keyboard.write`.

**Directory scope:** inherited or none.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Enter reviewed text into an active application`.
7. Set `risk_policy` to `high` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 6: Filesystem writer

**Objective:** Write bounded generated artifacts.

**Risk ceiling:** `high`.

**Permissions:** `filesystem.write`.

**Tools:** `filesystem.write`.

**Directory scope:** `/workspace/project/output`.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Write bounded generated artifacts`.
7. Set `risk_policy` to `high` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 7: Test runner

**Objective:** Run approved test commands.

**Risk ceiling:** `medium`.

**Permissions:** `process.execute`.

**Tools:** `process.execute`.

**Directory scope:** `/workspace/project`.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Run approved test commands`.
7. Set `risk_policy` to `medium` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 8: Screenshot observer

**Objective:** Capture authorized visual evidence.

**Risk ceiling:** `low`.

**Permissions:** `screen.read`.

**Tools:** `screen.capture`.

**Directory scope:** inherited or none.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Capture authorized visual evidence`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 9: Event monitor

**Objective:** Receive bounded structural event notifications.

**Risk ceiling:** `low`.

**Permissions:** none.

**Tools:** none.

**Directory scope:** inherited or none.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Receive bounded structural event notifications`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 10: Result reviewer

**Objective:** Review structured child results.

**Risk ceiling:** `low`.

**Permissions:** none.

**Tools:** none.

**Directory scope:** inherited or none.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Review structured child results`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 11: Release reviewer

**Objective:** Review release documentation.

**Risk ceiling:** `low`.

**Permissions:** `filesystem.read`.

**Tools:** `filesystem.read`.

**Directory scope:** `/workspace/project/docs`.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Review release documentation`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

### Recipe 12: Temporary migration reader

**Objective:** Use a task-scoped read lease.

**Risk ceiling:** `low`.

**Permissions:** none.

**Tools:** `filesystem.read`.

**Directory scope:** `/workspace/project/migrations`.

Procedure:

1. Verify the named tools exist in the active inventory.
2. Inspect each tool specification for exact required permissions.
3. Choose a direct parent that already owns the requirements.
4. Remove placeholder permissions that are not registered locally.
5. Narrow paths and applications for the real task.
6. Set the definition objective to: `Use a task-scoped read lease`.
7. Set `risk_policy` to `low` unless a lower registered action risk permits further reduction.
8. Add positive runtime and rate limits.
9. Create without starting execution.
10. Inspect the resulting child and audit events.
11. Assign one bounded task.
12. Revoke or terminate after verified completion.

## Validation and testing

Test definitions and gateway behavior without weakening production checks.

### Unit-test a definition

```python
def test_reader_definition():
    definition = AgentDefinition.from_mapping({
        "name": "Reader",
        "role": "researcher",
        "objective": "Read docs",
        "permissions": ["filesystem.read"],
        "tools": ["docs.read"],
        "risk_policy": "low",
    })
    child = definition.create(manager, root.agent_id)
    assert child.permissions == {"filesystem.read"}
    assert child.available_tools == {"docs.read"}
    assert child.risk_policy == "low"
```

### Required negative tests

1. Reject a plain string for `permissions`.
2. Reject an unknown top-level key.
3. Reject blank required text.
4. Reject overlong required text.
5. Reject NaN, infinity, zero, and negative limits.
6. Reject an invalid risk policy.
7. Reject an unknown parent.
8. Reject a child permission not owned by its parent.
9. Reject an unknown tool.
10. Reject a tool when required permission is absent.
11. Reject an application outside a bounded parent.
12. Reject a directory outside a bounded parent.
13. Reject dashboard creation with an invalid token.
14. Confirm creation does not start execution.
15. Confirm the hierarchy contains the child exactly once.

### Repository checks

```bash
python -m pytest tests/test_agent_building_blocks.py -q
python -m pytest tests/test_agent_manager.py -q
python -m pytest tests/test_dashboard.py -q
python -m compileall -q app run.py run_dashboard.py
node --check app/dashboard/static/app.js
git diff --check
```

Browser-backed imports require installed project dependencies. Report missing dependencies as environment limitations; do not call a skipped integration check successful.

## Troubleshooting

Start with the exact error, then inspect parent, tool, permission, scope, and runtime identity in that order.

| Symptom | Likely cause | Resolution |
|---|---|---|
| Agent name is required | Missing/blank `name` | Provide 1 to 100 non-whitespace characters. |
| Unknown agent fields | Misspelled or unsupported JSON key | Remove the key or map it to the documented schema. |
| permissions must be a list | A JSON string was supplied | Use `["filesystem.read"]`, not `"filesystem.read"`. |
| resource limits must be finite positive numbers | Zero, negative, NaN, or infinity | Choose a positive finite numeric value. |
| Unknown agent | Stale or incorrect parent ID | Refresh the live snapshot and copy the full UUID. |
| Only one root agent may be created | Composition code attempted another root | Create a child under the existing root. |
| Parent does not possess this permission | Requested authority exceeds parent | Remove it or select a legitimately authorized parent. |
| Child lacks required tool permission | Tool requirement missing from child set | Add only the exact requirement if the parent owns it. |
| Unknown tool | Identifier is not registered | Inspect inventory or register a real adapter in application composition. |
| Child application boundary exceeds its parent | Application scope is wider | Use a subset or inherit the parent scope. |
| Child directory boundary exceeds its parent | Resolved path is outside roots | Choose a descendant of an allowed root. |
| Dashboard command is not authorized | Token mismatch | Use the current runtime token; do not log it. |
| Connection refused | Dashboard is not running or URL is wrong | Start the authoritative runtime and verify loopback port. |
| Agent creation failed with HTTP error | Gateway rejected payload | Read the bounded error and correct the definition. |
| Only running agents may execute tools | Tool called before start or after completion | Invoke tools only inside the active executor. |
| Tool was not granted | Tool absent from child allow-list | Grant it through the direct parent after permissions exist. |
| Agent has not completed successfully | Result collected too early or after failure | Wait for completed state or inspect error. |
| Cannot assign a task to a terminated agent | Attempted reuse of terminal child | Create a replacement child. |
| Agent retry limit reached | Failure budget exhausted | Diagnose cause; do not increase retries blindly. |
| No persisted agents found | Audit database has no root snapshot | Run configured runtime work or inspect the correct data directory. |

### Troubleshooting procedure 1: Agent name is required

Likely cause: Missing/blank `name`.

Primary resolution: Provide 1 to 100 non-whitespace characters.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 2: Unknown agent fields

Likely cause: Misspelled or unsupported JSON key.

Primary resolution: Remove the key or map it to the documented schema.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 3: permissions must be a list

Likely cause: A JSON string was supplied.

Primary resolution: Use `["filesystem.read"]`, not `"filesystem.read"`.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 4: resource limits must be finite positive numbers

Likely cause: Zero, negative, NaN, or infinity.

Primary resolution: Choose a positive finite numeric value.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 5: Unknown agent

Likely cause: Stale or incorrect parent ID.

Primary resolution: Refresh the live snapshot and copy the full UUID.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 6: Only one root agent may be created

Likely cause: Composition code attempted another root.

Primary resolution: Create a child under the existing root.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 7: Parent does not possess this permission

Likely cause: Requested authority exceeds parent.

Primary resolution: Remove it or select a legitimately authorized parent.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 8: Child lacks required tool permission

Likely cause: Tool requirement missing from child set.

Primary resolution: Add only the exact requirement if the parent owns it.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 9: Unknown tool

Likely cause: Identifier is not registered.

Primary resolution: Inspect inventory or register a real adapter in application composition.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 10: Child application boundary exceeds its parent

Likely cause: Application scope is wider.

Primary resolution: Use a subset or inherit the parent scope.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 11: Child directory boundary exceeds its parent

Likely cause: Resolved path is outside roots.

Primary resolution: Choose a descendant of an allowed root.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 12: Dashboard command is not authorized

Likely cause: Token mismatch.

Primary resolution: Use the current runtime token; do not log it.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 13: Connection refused

Likely cause: Dashboard is not running or URL is wrong.

Primary resolution: Start the authoritative runtime and verify loopback port.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 14: Agent creation failed with HTTP error

Likely cause: Gateway rejected payload.

Primary resolution: Read the bounded error and correct the definition.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 15: Only running agents may execute tools

Likely cause: Tool called before start or after completion.

Primary resolution: Invoke tools only inside the active executor.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 16: Tool was not granted

Likely cause: Tool absent from child allow-list.

Primary resolution: Grant it through the direct parent after permissions exist.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 17: Agent has not completed successfully

Likely cause: Result collected too early or after failure.

Primary resolution: Wait for completed state or inspect error.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 18: Cannot assign a task to a terminated agent

Likely cause: Attempted reuse of terminal child.

Primary resolution: Create a replacement child.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 19: Agent retry limit reached

Likely cause: Failure budget exhausted.

Primary resolution: Diagnose cause; do not increase retries blindly.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

### Troubleshooting procedure 20: No persisted agents found

Likely cause: Audit database has no root snapshot.

Primary resolution: Run configured runtime work or inspect the correct data directory.

1. Capture the error class and safe message.
2. Do not copy tokens, arguments, or secret context into an issue.
3. Refresh the authoritative agent and tool inventory.
4. Confirm the full parent and child UUIDs.
5. Revalidate the definition locally.
6. Compare requested permissions with the parent set.
7. Compare selected tools with registered requirements.
8. Recheck directory and application boundaries.
9. Retry only after correcting the cause.
10. Confirm the resulting event and hierarchy state.

## Security runbooks

These procedures preserve least privilege during common operational events.

### Security runbook 1: Suspected credential in context

1. Pause the child.
2. Do not display or copy the value.
3. Terminate if exposure may continue.
4. Rotate the credential outside Brainless.
5. Create a clean replacement without the value.
6. Review redacted audit records.
7. Preserve only non-sensitive evidence.
8. Confirm policy, approval, and governor gates remain active.

### Security runbook 2: Unexpected permission denial

1. Treat denial as a safety result.
2. Identify the exact required permission.
3. Confirm whether the task truly needs it.
4. Confirm the parent owns it.
5. Prefer a short lease for temporary work.
6. Record the authorization decision.
7. Preserve only non-sensitive evidence.
8. Confirm policy, approval, and governor gates remain active.

### Security runbook 3: Compromised dashboard token

1. Stop remote access.
2. Terminate the dashboard process.
3. Rotate the environment token.
4. Restart on loopback.
5. Review correlated command events.
6. Investigate unexpected children.
7. Preserve only non-sensitive evidence.
8. Confirm policy, approval, and governor gates remain active.

### Security runbook 4: Stale child

1. Inspect current status.
2. Confirm no running task.
3. Revoke active leases.
4. Revoke unnecessary permissions.
5. Terminate through the direct parent.
6. Confirm termination event.
7. Preserve only non-sensitive evidence.
8. Confirm policy, approval, and governor gates remain active.

### Security runbook 5: Tool mismatch

1. Stop the attempted workflow.
2. Inspect the registered tool spec.
3. Do not replace it with broad mouse/keyboard access.
4. Register a purpose-built adapter if required.
5. Rebuild the child definition.
6. Retest verification behavior.
7. Preserve only non-sensitive evidence.
8. Confirm policy, approval, and governor gates remain active.

### Security runbook 6: Scope expansion request

1. Document why expansion is needed.
2. Inspect the parent boundary.
3. Prefer a separate narrowly scoped child.
4. Require review for broader roots.
5. Create a replacement definition.
6. Terminate the superseded child.
7. Preserve only non-sensitive evidence.
8. Confirm policy, approval, and governor gates remain active.

## API reference

This section summarizes the exact public building and manager operations used by the workflows.

| API | Purpose | Inputs | Returns | Errors |
|---|---|---|---|---|
| `AgentDefinition.from_mapping(value)` | Validate an untrusted object and return an immutable definition. | Mapping with documented fields | AgentDefinition | ValueError |
| `AgentDefinition.create(manager, parent_agent_id)` | Create one bounded direct child. | Manager and parent UUID | Agent | KeyError, PermissionError, PermissionDenied, ValueError |
| `create_agent(manager, parent_agent_id, **configuration)` | Functional validation and creation helper. | Keyword schema | Agent | Same as definition creation |
| `AgentManager.create_root(name, role, objective, permissions)` | Create the sole root. | Identity plus permission set | Agent | ValueError |
| `AgentManager.create_agent(...)` | Low-level checked child creation. | Parent, identity, task, permissions, tools, context | Agent | KeyError, PermissionDenied |
| `AgentManager.assign_task(...)` | Replace current task and reset outcome. | Parent, child, task, optional context/ID | None | PermissionDenied, RuntimeError |
| `AgentManager.grant_permission(...)` | Delegate parent-owned permanent capability. | Parent, child, permission | None | PermissionDenied |
| `AgentManager.revoke_permission(...)` | Remove permanent capability. | Parent, child, permission | None | PermissionDenied |
| `AgentManager.grant_tool(...)` | Allow a registered tool after requirements exist. | Parent, child, tool ID | None | KeyError, PermissionDenied |
| `AgentManager.lease_permission(...)` | Temporarily delegate one task-scoped capability. | Parent, child, permission, task, seconds | CapabilityLease | PermissionDenied, ValueError |
| `AgentManager.set_event_subscriptions(...)` | Replace subscriptions. | Parent, child, string set | None | PermissionDenied |
| `AgentManager.available_tools(agent_id)` | Return usable permanent-permission tool metadata. | Agent UUID | Tuple of mappings | KeyError |
| `AgentManager.start_agent(...)` | Run one child executor. | Parent, child, async executor | Result string | PermissionDenied, RuntimeError, executor error |
| `AgentManager.start_parallel(...)` | Run independent direct children concurrently. | Parent, child IDs, executor | Result list | Child/executor errors |
| `AgentManager.retry_agent(...)` | Retry one failed child within budget. | Parent, child, executor | Result string | RuntimeError |
| `AgentManager.pause_agent(...)` | Pause a running direct child. | Parent and child IDs | None | PermissionDenied |
| `AgentManager.resume_agent(...)` | Move a paused child to ready. | Parent and child IDs | None | PermissionDenied |
| `AgentManager.terminate_agent(...)` | Cancel tracked work and terminate child. | Parent and child IDs | None | PermissionDenied |
| `AgentManager.monitor_agent(...)` | Return a direct child snapshot object. | Parent and child IDs | Agent | PermissionDenied |
| `AgentManager.collect_result(...)` | Read completed successful result. | Parent and child IDs | String | RuntimeError, PermissionDenied |
| `AgentManager.execute_tool(...)` | Invoke through status, allow-list, lease, and policy gates. | Agent, tool, arguments | Tool result | RuntimeError, PermissionDenied, ApprovalRequired, handler errors |

### Dashboard wire request

```http
POST /api/commands HTTP/1.1
Authorization: Bearer DASHBOARD_TOKEN
Content-Type: application/json

{
  "command": "create_agent",
  "payload": {
    "parent_agent_id": "PARENT_UUID",
    "agent": {
      "name": "Observer",
      "role": "reader",
      "objective": "Inspect bounded state",
      "permissions": [],
      "tools": [],
      "risk_policy": "low"
    }
  }
}
```

Use the provided dashboard or CLI client instead of scripting tokens into source control.

## Operational checklists

Copy these checklists into a change record when agent authority is material.

### Design review checklist

- [ ] Outcome is explicit.
- [ ] Existing compatible agent considered.
- [ ] Direct parent selected.
- [ ] Registered tools identified.
- [ ] Tool permissions mapped.
- [ ] Risk classified.
- [ ] Directories narrowed.
- [ ] Applications narrowed.
- [ ] Resource limits selected.
- [ ] Secrets excluded.

### Pre-creation checklist

- [ ] Runtime active.
- [ ] Token current.
- [ ] Parent UUID current.
- [ ] JSON syntax valid.
- [ ] Unknown fields absent.
- [ ] Required fields bounded.
- [ ] Lists encoded as arrays.
- [ ] Limits positive and finite.
- [ ] Tool IDs exact.
- [ ] Parent owns permissions.

### Post-creation checklist

- [ ] Response accepted.
- [ ] Agent UUID retained.
- [ ] Parent relationship correct.
- [ ] Status ready.
- [ ] Task ID expected.
- [ ] Permissions minimal.
- [ ] Tools minimal.
- [ ] Scopes correct.
- [ ] Risk ceiling correct.
- [ ] Audit event present.

### Pre-execution checklist

- [ ] Task bounded.
- [ ] Context non-secret.
- [ ] Agent ready.
- [ ] Tool registered.
- [ ] Tool allow-listed.
- [ ] Permissions active.
- [ ] Lease valid if used.
- [ ] Policy understood.
- [ ] Approval path available.
- [ ] Verification defined.

### Post-execution checklist

- [ ] Status accurate.
- [ ] Result verified.
- [ ] Errors preserved.
- [ ] Tool history reviewed.
- [ ] Denials investigated.
- [ ] Temporary lease revoked.
- [ ] Permissions reduced.
- [ ] Artifacts inspected.
- [ ] Audit correlation retained.
- [ ] Stale child terminated.

### Replacement update checklist

- [ ] Old child inspected.
- [ ] New definition reviewed.
- [ ] Unneeded authority removed.
- [ ] New child created.
- [ ] Hierarchy verified.
- [ ] New task assigned.
- [ ] Old child paused.
- [ ] Active work drained.
- [ ] Old child terminated.
- [ ] Replacement recorded.

### Incident review checklist

- [ ] Agent isolated.
- [ ] Leases revoked.
- [ ] Token rotated if needed.
- [ ] Events exported safely.
- [ ] Secrets redacted.
- [ ] Parent authority reviewed.
- [ ] Tool handlers reviewed.
- [ ] Scopes tightened.
- [ ] Tests added.
- [ ] Corrective action documented.

### Review worksheet 1: identity

Use this worksheet to review the agent's **identity** before production use.

- [ ] What concrete requirement does the identity decision satisfy?
- [ ] Which authoritative runtime record proves the identity value?
- [ ] Can the identity choice be narrowed without blocking the task?
- [ ] Who owns review of the identity decision?
- [ ] What failure occurs when the identity assumption is false?
- [ ] How will the identity boundary be tested before execution?
- [ ] Which event or audit record captures the identity outcome?
- [ ] When should the identity choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 2: objective

Use this worksheet to review the agent's **objective** before production use.

- [ ] What concrete requirement does the objective decision satisfy?
- [ ] Which authoritative runtime record proves the objective value?
- [ ] Can the objective choice be narrowed without blocking the task?
- [ ] Who owns review of the objective decision?
- [ ] What failure occurs when the objective assumption is false?
- [ ] How will the objective boundary be tested before execution?
- [ ] Which event or audit record captures the objective outcome?
- [ ] When should the objective choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 3: task

Use this worksheet to review the agent's **task** before production use.

- [ ] What concrete requirement does the task decision satisfy?
- [ ] Which authoritative runtime record proves the task value?
- [ ] Can the task choice be narrowed without blocking the task?
- [ ] Who owns review of the task decision?
- [ ] What failure occurs when the task assumption is false?
- [ ] How will the task boundary be tested before execution?
- [ ] Which event or audit record captures the task outcome?
- [ ] When should the task choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 4: parent selection

Use this worksheet to review the agent's **parent selection** before production use.

- [ ] What concrete requirement does the parent selection decision satisfy?
- [ ] Which authoritative runtime record proves the parent selection value?
- [ ] Can the parent selection choice be narrowed without blocking the task?
- [ ] Who owns review of the parent selection decision?
- [ ] What failure occurs when the parent selection assumption is false?
- [ ] How will the parent selection boundary be tested before execution?
- [ ] Which event or audit record captures the parent selection outcome?
- [ ] When should the parent selection choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 5: permissions

Use this worksheet to review the agent's **permissions** before production use.

- [ ] What concrete requirement does the permissions decision satisfy?
- [ ] Which authoritative runtime record proves the permissions value?
- [ ] Can the permissions choice be narrowed without blocking the task?
- [ ] Who owns review of the permissions decision?
- [ ] What failure occurs when the permissions assumption is false?
- [ ] How will the permissions boundary be tested before execution?
- [ ] Which event or audit record captures the permissions outcome?
- [ ] When should the permissions choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 6: tool registry

Use this worksheet to review the agent's **tool registry** before production use.

- [ ] What concrete requirement does the tool registry decision satisfy?
- [ ] Which authoritative runtime record proves the tool registry value?
- [ ] Can the tool registry choice be narrowed without blocking the task?
- [ ] Who owns review of the tool registry decision?
- [ ] What failure occurs when the tool registry assumption is false?
- [ ] How will the tool registry boundary be tested before execution?
- [ ] Which event or audit record captures the tool registry outcome?
- [ ] When should the tool registry choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 7: tool requirements

Use this worksheet to review the agent's **tool requirements** before production use.

- [ ] What concrete requirement does the tool requirements decision satisfy?
- [ ] Which authoritative runtime record proves the tool requirements value?
- [ ] Can the tool requirements choice be narrowed without blocking the task?
- [ ] Who owns review of the tool requirements decision?
- [ ] What failure occurs when the tool requirements assumption is false?
- [ ] How will the tool requirements boundary be tested before execution?
- [ ] Which event or audit record captures the tool requirements outcome?
- [ ] When should the tool requirements choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 8: subscriptions

Use this worksheet to review the agent's **subscriptions** before production use.

- [ ] What concrete requirement does the subscriptions decision satisfy?
- [ ] Which authoritative runtime record proves the subscriptions value?
- [ ] Can the subscriptions choice be narrowed without blocking the task?
- [ ] Who owns review of the subscriptions decision?
- [ ] What failure occurs when the subscriptions assumption is false?
- [ ] How will the subscriptions boundary be tested before execution?
- [ ] Which event or audit record captures the subscriptions outcome?
- [ ] When should the subscriptions choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 9: context

Use this worksheet to review the agent's **context** before production use.

- [ ] What concrete requirement does the context decision satisfy?
- [ ] Which authoritative runtime record proves the context value?
- [ ] Can the context choice be narrowed without blocking the task?
- [ ] Who owns review of the context decision?
- [ ] What failure occurs when the context assumption is false?
- [ ] How will the context boundary be tested before execution?
- [ ] Which event or audit record captures the context outcome?
- [ ] When should the context choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 10: resource limits

Use this worksheet to review the agent's **resource limits** before production use.

- [ ] What concrete requirement does the resource limits decision satisfy?
- [ ] Which authoritative runtime record proves the resource limits value?
- [ ] Can the resource limits choice be narrowed without blocking the task?
- [ ] Who owns review of the resource limits decision?
- [ ] What failure occurs when the resource limits assumption is false?
- [ ] How will the resource limits boundary be tested before execution?
- [ ] Which event or audit record captures the resource limits outcome?
- [ ] When should the resource limits choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 11: directory scope

Use this worksheet to review the agent's **directory scope** before production use.

- [ ] What concrete requirement does the directory scope decision satisfy?
- [ ] Which authoritative runtime record proves the directory scope value?
- [ ] Can the directory scope choice be narrowed without blocking the task?
- [ ] Who owns review of the directory scope decision?
- [ ] What failure occurs when the directory scope assumption is false?
- [ ] How will the directory scope boundary be tested before execution?
- [ ] Which event or audit record captures the directory scope outcome?
- [ ] When should the directory scope choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 12: application scope

Use this worksheet to review the agent's **application scope** before production use.

- [ ] What concrete requirement does the application scope decision satisfy?
- [ ] Which authoritative runtime record proves the application scope value?
- [ ] Can the application scope choice be narrowed without blocking the task?
- [ ] Who owns review of the application scope decision?
- [ ] What failure occurs when the application scope assumption is false?
- [ ] How will the application scope boundary be tested before execution?
- [ ] Which event or audit record captures the application scope outcome?
- [ ] When should the application scope choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 13: risk ceiling

Use this worksheet to review the agent's **risk ceiling** before production use.

- [ ] What concrete requirement does the risk ceiling decision satisfy?
- [ ] Which authoritative runtime record proves the risk ceiling value?
- [ ] Can the risk ceiling choice be narrowed without blocking the task?
- [ ] Who owns review of the risk ceiling decision?
- [ ] What failure occurs when the risk ceiling assumption is false?
- [ ] How will the risk ceiling boundary be tested before execution?
- [ ] Which event or audit record captures the risk ceiling outcome?
- [ ] When should the risk ceiling choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 14: auditability

Use this worksheet to review the agent's **auditability** before production use.

- [ ] What concrete requirement does the auditability decision satisfy?
- [ ] Which authoritative runtime record proves the auditability value?
- [ ] Can the auditability choice be narrowed without blocking the task?
- [ ] Who owns review of the auditability decision?
- [ ] What failure occurs when the auditability assumption is false?
- [ ] How will the auditability boundary be tested before execution?
- [ ] Which event or audit record captures the auditability outcome?
- [ ] When should the auditability choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 15: correlation

Use this worksheet to review the agent's **correlation** before production use.

- [ ] What concrete requirement does the correlation decision satisfy?
- [ ] Which authoritative runtime record proves the correlation value?
- [ ] Can the correlation choice be narrowed without blocking the task?
- [ ] Who owns review of the correlation decision?
- [ ] What failure occurs when the correlation assumption is false?
- [ ] How will the correlation boundary be tested before execution?
- [ ] Which event or audit record captures the correlation outcome?
- [ ] When should the correlation choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 16: status

Use this worksheet to review the agent's **status** before production use.

- [ ] What concrete requirement does the status decision satisfy?
- [ ] Which authoritative runtime record proves the status value?
- [ ] Can the status choice be narrowed without blocking the task?
- [ ] Who owns review of the status decision?
- [ ] What failure occurs when the status assumption is false?
- [ ] How will the status boundary be tested before execution?
- [ ] Which event or audit record captures the status outcome?
- [ ] When should the status choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

### Review worksheet 17: execution

Use this worksheet to review the agent's **execution** before production use.

- [ ] What concrete requirement does the execution decision satisfy?
- [ ] Which authoritative runtime record proves the execution value?
- [ ] Can the execution choice be narrowed without blocking the task?
- [ ] Who owns review of the execution decision?
- [ ] What failure occurs when the execution assumption is false?
- [ ] How will the execution boundary be tested before execution?
- [ ] Which event or audit record captures the execution outcome?
- [ ] When should the execution choice be reviewed again?

Evidence to retain:

- Non-secret definition fragment.
- Relevant parent/tool inventory identifiers.
- Validation or test result.
- Approval reference when applicable.
- Retirement or next-review condition.

## Glossary

Terms used consistently throughout this handbook.

### Agent

Runtime-owned configuration and mutable lifecycle record.

### Agent definition

Immutable validated request used to create a child.

### Agent manager

Authoritative hierarchy, lifecycle, permission, tool, and audit supervisor.

### Agent ID

UUID identifying one runtime agent.

### Root agent

Sole top-level authority owner created by application composition.

### Parent agent

Direct owner allowed to manage one child.

### Child agent

Agent whose `parent_agent_id` points to its direct owner.

### Objective

Stable purpose of an agent.

### Task

Current bounded work assignment.

### Task ID

Correlation identifier for a task and temporary leases.

### Permission

Named capability checked before tool execution.

### Tool

Registered callable adapter with metadata and requirements.

### Tool allow-list

Set of registered tool IDs assigned to an agent.

### Risk policy

Maximum risk level accepted by applicable action execution.

### Application boundary

Set restricting processes/applications.

### Directory boundary

Resolved filesystem roots restricting path actions.

### Resource limit

Positive finite consumption boundary.

### Subscription

Event interest label without authority.

### Context

Bounded string metadata associated with a task or definition.

### Lease

Temporary permission scoped to an agent and task.

### Policy

Global permission decision layer.

### Approval

Independent human decision required for selected sensitive work.

### Governor

Mission contract and budget gate.

### Audit event

Structured record of status, task, tool, result, error, or denial.

### Dashboard gateway

Authenticated allow-listed mutation boundary.

### Correlation ID

Identifier connecting a dashboard command and emitted event.

### Replacement update

Create reviewed replacement and retire old agent instead of arbitrary mutation.

### Fail closed

Deny or stop when authority or state cannot be proven.

### Least privilege

Grant only the minimum authority for the shortest necessary time.

### Authoritative runtime

Live process owning manager state and validated execution paths.

## Final operator summary

1. Build a plain, non-secret definition.
2. Validate it through `AgentDefinition.from_mapping`.
3. Delegate only from a direct parent that owns the capability.
4. Pair each tool with its exact required permissions.
5. Narrow scope, risk, and resource use.
6. Create through Python, dashboard, or live-runtime CLI.
7. Inspect before execution.
8. Update through explicit manager methods or a reviewed replacement.
9. Execute only through validated manager/tool boundaries.
10. Verify results and retire stale authority.
