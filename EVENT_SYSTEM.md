# Event system

`app.event_system` provides normalized immutable events, bounded replay history, priority delivery,
wildcard/type/category/process/window subscriptions, nested conditions, debounce, throttle and deduplication.
Detectors publish observations only; routers deliver only matching events. Sensitive detectors are disabled
unless configured. `FilesystemDetector` and `ResourceDetector` are implemented with real OS data.

Example: subscribe with `EventFilter(event_types={"ON_FILE_CREATED"}, conditions={"field":"extension","operator":"equals","value":".pdf"})`.

## Status

Implemented: normalized bus, history/replay, conditions, filesystem create/modify/size/delete, disk threshold,
mouse-position changes, privacy-safe clipboard changes, resolution changes, and Windows process start/stop.
Partial/platform adapter required: browser, network, power. Windows hooks for mouse buttons/wheels, keyboard,
window, UI Automation, devices, audio, sessions, notifications and security are unavailable until their
optional native adapters are installed; the capability report states this rather than fabricating events.

Reusable agent construction and workflow primitives live in `app.event_system.building_blocks`. Structured
rotating audit streams are provided by `StructuredEventLogger`; safe defaults are represented by
`EventSystemConfig` and honor `DRY_RUN` from the environment.
