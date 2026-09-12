# Actions

`ActionRegistry` records an action name, category, permission set, risk, exact input schema, output schema,
executor, timeout, retry count and optional rollback. It returns structured success, failed, denied,
timeout, not-found, not-supported or cancelled results. Medium/high/critical actions are blocked in dry-run;
high/critical actions require confirmation. Emergency stop blocks all new executions.
