# Event system

`app.event_system` provides normalized immutable events, bounded replay history, priority delivery,
wildcard/type/category/process/window subscriptions, nested conditions, debounce, throttle and deduplication.
Detectors publish observations only; routers deliver only matching events. Sensitive detectors are disabled
unless configured. `EventManager` isolates an unavailable optional adapter and reports it through
`unavailable` instead of stopping healthy detectors. `run()` provides a cancellable polling loop.

Example: subscribe with `EventFilter(event_types={"ON_FILE_CREATED"}, conditions={"field":"extension","operator":"equals","value":".pdf"})`.

## Status

Implemented with real polling/API code: normalized bus, queued pause/resume, routed replay, conditions,
filesystem create/modify/size/delete/rename/move, disk threshold, mouse position/button/enter/leave/drag/
double-click changes, privacy-filtered key up/down/press/modifier/hotkey transitions, privacy-safe clipboard
changes, resolution changes, process start/stop, specific visible-window create/open/destroy/close/title/
move/resize/state transitions, host interface/IP connect/disconnect/change, Windows AC/battery transitions,
PnP device and AudioEndpoint connect/disconnect inventories, logon session inventories, safe dialog metadata,
and one-time/interval timers. Native collectors are polling based and enabled explicitly.

Partial: rename/move correlation depends on stable file IDs and copy/access events cannot be inferred
reliably by polling; wheel events require a native message hook; network adapter names, gateway, DNS and
SSID need a Windows-native adapter; AudioEndpoint polling does not expose volume/playback; dialog polling
does not expose notification contents. Browser lifecycle comes from the existing Playwright runtime rather
than the desktop event bus. UI Automation property events, toast history, security notifications, and
sleep/lock callbacks remain unavailable and are not synthesized.

`create_event_platform()` constructs the bus, manager, configured detectors, and action registry in one
call. `create_windows_detectors()` constructs optional native observers, and every detector accepts an
injected reader for specialized future agents and deterministic tests.

## Architecture assessment

The existing project already separates provider-driven reasoning (`app/providers`), hierarchical agents
(`app/agents`), policy (`app/safety`), autonomous execution (`app/autonomy`), computer adapters
(`app/computer`), and its authenticated dashboard (`app/dashboard`). The event system extends those
boundaries rather than replacing them: detectors only observe, the bus filters/routes, the dispatcher checks
observation authority, and `ActionRegistry` is the sole desktop-action boundary.
