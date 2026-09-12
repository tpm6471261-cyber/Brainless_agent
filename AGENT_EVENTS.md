# Agent events

Agents subscribe with an `EventSubscription` and `EventFilter`; they never receive all PC events by default.
Use event type/category plus process/window and condition constraints. The intended path is observation →
filtered subscription → agent reasoning → permission check → registered action → result event.

Use `AgentBlueprint` to define a reusable child-agent boundary, `EventAgentRuntime` to dispatch normalized
events, `AgentActionExecutor` for permission/resource-checked actions, and `EventChain` for multi-step flows.
