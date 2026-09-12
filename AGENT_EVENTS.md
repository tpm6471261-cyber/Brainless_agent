# Agent events

Agents subscribe with an `EventSubscription` and `EventFilter`; they never receive all PC events by default.
Use event type/category plus process/window and condition constraints. The intended path is observation →
filtered subscription → agent reasoning → permission check → registered action → result event.

Use `create_event_agent(...)` as the functional building block for future agents. It accepts name, purpose,
tools, permissions, subscriptions, resource limits, maximum runtime, allowed applications/directories and a
risk policy, then delegates to the existing parent-authorized `AgentManager`. `EventChain` composes delay,
branch, bounded retry, repeat and parallel steps without giving the agent additional authority.

For a complete reusable runtime, call `create_event_platform(config)`, attach an `AgentEventDispatcher`, and
subscribe only the new agent's declared event types. The platform keeps keyboard, mouse-button, clipboard,
device, audio, session, and notification observation off unless configuration opts in.
