# AutoWindow one-call API

```python
from app.event_system import AutoWindow
pc = AutoWindow(permissions={"mouse.control", "keyboard.control", "filesystem.write"})
pc.call_action_sync("MOVE_MOUSE", x=100, y=200)
pc.call_action_sync("TYPE_TEXT", text="hello")
pc.set_variable("project", "Brainless")
pc.get_variable("project")
pc.get_data("SCREEN_SIZE")
```

## Control functions

`call_action`, `call_action_sync`, `list_actions`, `emergency_stop`, `resume_agent_system`, `poll_events`.

Registered actions: `MOVE_MOUSE`, `LEFT_CLICK`, `RIGHT_CLICK`, `DOUBLE_CLICK`, `MIDDLE_CLICK`,
`SET_MOUSE_POSITION`, `MOUSE_DOWN`, `MOUSE_UP`, `SCROLL`, `DRAG`, `PRESS_KEY`, `RELEASE_KEY`, `TYPE_TEXT`, `HOTKEY`, `KEY_SEQUENCE`,
`READ_CLIPBOARD`, `WRITE_CLIPBOARD`, `CLEAR_CLIPBOARD`, `CREATE_FILE`, `COPY_FILE`, `MOVE_FILE`,
`RENAME_FILE`, `OPEN_FILE`, `DELETE_FILE`, `CREATE_FOLDER`, `DELETE_FOLDER`, `START_PROCESS`, `STOP_PROCESS`, `TAKE_SCREENSHOT`, `CAPTURE_REGION`, `CLOSE_WINDOW`, `MINIMIZE_WINDOW`, `MAXIMIZE_WINDOW`, `RESTORE_WINDOW`, `FOCUS_WINDOW`, `MOVE_WINDOW`, `RESIZE_WINDOW`, `REQUEST_SHUTDOWN`, `REQUEST_RESTART`, `REQUEST_HIBERNATE`.

## Data retrieval

`get_data("CAPABILITIES")`, `get_data("ENVIRONMENT")`, `get_data("DISK_USAGE", path=...)`,
`get_data("MOUSE_POSITION")`, `get_data("SCREEN_SIZE")`, `get_data("WINDOWS")`,
`get_data("PROCESSES")`, `get_data("CLIPBOARD")` (redacted).

## Variables

`set_variable(name, value)`, `get_variable(name, default=None)`, and `delete_variable(name)` are runtime-only and are not persisted.
All actions still require their declared permission. High-risk actions require confirmation; dry-run and
emergency stop remain independent of AI. Optional native facilities report unavailable instead of crashing startup.

## Detectors available for `EventManager`

`FilesystemDetector`, `ResourceDetector`, `MousePositionDetector`, `ClipboardDetector` (disabled by default),
`DisplayDetector`, and Windows `ProcessDetector`. Clipboard events store only type and length, never contents.

## Additional real detectors

`KeyboardStateDetector` (explicit opt-in), `WindowDetector`, `PowerDetector`, `NetworkDetector`, and
`SchedulerDetector` are available through the package API. Keyboard events contain key transitions,
never reconstructed text. Unsupported native integrations fail closed without stopping other detectors.

## Agent building blocks

`AgentBlueprint.create(manager, parent_agent_id)` creates a child while preserving the manager's existing
parent-authority checks. A blueprint carries permissions, tools, event subscriptions, resource limits,
maximum runtime, application/directory boundaries, and risk policy.

`AgentActionExecutor.execute(agent, action_name, **arguments)` is the one-call action boundary for an agent.
It applies the agent's current permissions and `max_actions_per_minute`/`max_concurrent_actions` limits before
calling the central registry. `EventAgentRuntime.handle(event)` applies subscription, observation-permission,
and `max_event_rate` checks. `EventChain` composes `then`, `delay`, `action`, `branch`, `parallel`, `repeat`,
`retry`, and `run` into reusable workflows; `$variable` action arguments resolve from chain context.

`EventSystemConfig.from_mapping(config)` supplies safe defaults: keyboard, mouse, and clipboard observation
are disabled unless explicitly enabled, while the `DRY_RUN` environment variable overrides execution mode.
`StructuredEventLogger` writes rotating `event.log`, `action.log`, and `security.log` JSON lines and recursively
redacts credential-, token-, clipboard-, password-, secret-, and text-labelled fields.
