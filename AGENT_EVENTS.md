# Agent events

Agents subscribe with an `EventSubscription` and `EventFilter`; they never receive all PC events by default.
Use event type/category plus process/window and condition constraints. The intended path is observation →
filtered subscription → agent reasoning → permission check → registered action → result event.
