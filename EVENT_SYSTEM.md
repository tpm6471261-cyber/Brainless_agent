# Event system

`app.event_system` provides normalized immutable events, bounded replay history, priority delivery,
wildcard/type/category/process/window subscriptions, nested conditions, debounce, throttle and deduplication.
Detectors publish observations only; routers deliver only matching events. Sensitive detectors are disabled
unless configured. `EventManager` isolates an unavailable optional adapter and reports it through
`unavailable` instead of stopping healthy detectors. `run()` provides a cancellable polling loop.

Example: subscribe with `EventFilter(event_types={"ON_FILE_CREATED"}, conditions={"field":"extension","operator":"equals","value":".pdf"})`.

## Status

Implemented with real polling/API code: normalized bus, routed replay, conditions, filesystem
create/modify/size/delete, disk threshold, mouse-position changes, privacy-safe clipboard changes,
resolution changes, process start/stop, visible-window create/destroy/change, host interface/IP connect,
disconnect/change, Windows AC/battery transitions and one-time/interval timers.

Partial: filesystem rename/move/copy cannot be distinguished reliably by portable polling; window changes
are normalized as `ON_WINDOW_CHANGED`; network adapter names, gateway, DNS and SSID need a Windows-native
adapter; browser lifecycle comes from the existing Playwright runtime rather than the desktop event bus.
Global mouse/keyboard hooks, UI Automation notifications, devices, audio, sessions, toasts and security
notifications remain unavailable. They are not advertised as implemented or synthesized.

## Architecture assessment

The existing project already separates provider-driven reasoning (`app/providers`), hierarchical agents
(`app/agents`), policy (`app/safety`), autonomous execution (`app/autonomy`), computer adapters
(`app/computer`), and its authenticated dashboard (`app/dashboard`). The event system extends those
boundaries rather than replacing them: detectors only observe, the bus filters/routes, the dispatcher checks
observation authority, and `ActionRegistry` is the sole desktop-action boundary.
