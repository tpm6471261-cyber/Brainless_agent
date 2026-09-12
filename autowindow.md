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

`call_action`, `call_action_sync`, `emergency_stop`, `resume_agent_system`, `poll_events`.

Registered actions: `MOVE_MOUSE`, `LEFT_CLICK`, `RIGHT_CLICK`, `DOUBLE_CLICK`, `MIDDLE_CLICK`,
`MOUSE_DOWN`, `MOUSE_UP`, `SCROLL`, `DRAG`, `PRESS_KEY`, `RELEASE_KEY`, `TYPE_TEXT`, `HOTKEY`,
`READ_CLIPBOARD`, `WRITE_CLIPBOARD`, `CLEAR_CLIPBOARD`, `CREATE_FILE`, `COPY_FILE`, `MOVE_FILE`,
`DELETE_FILE`, `CREATE_FOLDER`, `DELETE_FOLDER`, `START_PROCESS`, `STOP_PROCESS`, `TAKE_SCREENSHOT`.

## Data retrieval

`get_data("CAPABILITIES")`, `get_data("ENVIRONMENT")`, `get_data("DISK_USAGE", path=...)`,
`get_data("MOUSE_POSITION")`, `get_data("SCREEN_SIZE")`, `get_data("WINDOWS")`,
`get_data("PROCESSES")`, `get_data("CLIPBOARD")` (redacted).

## Variables

`set_variable(name, value)` and `get_variable(name, default=None)` are runtime-only and are not persisted.
All actions still require their declared permission. High-risk actions require confirmation; dry-run and
emergency stop remain independent of AI. Optional native facilities report unavailable instead of crashing startup.

## Detectors available for `EventManager`

`FilesystemDetector`, `ResourceDetector`, `MousePositionDetector`, `ClipboardDetector` (disabled by default),
`DisplayDetector`, and Windows `ProcessDetector`. Clipboard events store only type and length, never contents.
