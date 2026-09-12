# Actions

`ActionRegistry` records an action name, category, permission set, risk, exact input schema, output schema,
executor, timeout, retry count and optional rollback. It returns structured success, failed, denied,
timeout, not-found, not-supported or cancelled results. Medium/high/critical actions are blocked in dry-run;
high/critical actions require confirmation. Emergency stop cancels pending asynchronous actions and blocks
new executions. Three terminal integration failures open a circuit until the operator resumes the registry.

Registered desktop actions include mouse movement/click/button/scroll/drag, keyboard key down/up/press/text/
hotkey/sequence, clipboard read/write/clear, file create/copy/move/rename/delete/open and folder create/delete,
process start/safe terminate/application focus, screenshot/region capture/screen size/monitor inventory,
window minimize/maximize/restore/close/move/resize/focus/activate, opening a browser/URL, and explicitly
confirmed Windows sleep/hibernate/shutdown/restart requests. `discover_agent_actions()` exposes only registrations whose
permissions the requesting agent currently holds.

`AgentActionExecutor` additionally enforces each agent's allowed directories, allowed applications, action
rate/concurrency/runtime limits, and maximum risk policy before entering the registry.
