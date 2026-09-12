import pytest

from app.agents import AgentDefinition, AgentManager, create_agent
from app.agents.tools import RiskLevel, ToolRegistry, ToolSpec


def manager_with_tool():
    tools = ToolRegistry()
    tools.register(ToolSpec("docs.read", "Read docs", "Read documentation",
                            frozenset({"filesystem.read"}), RiskLevel.LOW, lambda arguments: "ok"))
    manager = AgentManager(tools)
    root = manager.create_root("Root", "operator", "Delegate", {"filesystem.read"})
    root.allowed_directories = {"/workspace"}
    return manager, root


def test_definition_creates_a_bounded_auditable_agent():
    manager, root = manager_with_tool()
    definition = AgentDefinition.from_mapping({
        "name": "Docs", "role": "researcher", "objective": "Review docs",
        "permissions": ["filesystem.read"], "tools": ["docs.read"],
        "subscriptions": ["task_assigned"], "resource_limits": {"max_runtime": 60},
        "allowed_directories": ["/workspace/Brainless_agent"], "risk_policy": "low",
    })
    child = definition.create(manager, root.agent_id)
    assert child.available_tools == {"docs.read"}
    assert child.event_subscriptions == {"task_assigned"}
    assert child.resource_limits == {"max_runtime": 60.0}
    assert child.allowed_directories == {"/workspace/Brainless_agent"}
    assert child.risk_policy == "low"


def test_function_and_schema_fail_closed():
    manager, root = manager_with_tool()
    child = create_agent(manager, root.agent_id, name="Observer", role="reader",
                         objective="Observe only")
    assert child.permissions == set()
    with pytest.raises(ValueError, match="Unknown agent fields"):
        AgentDefinition.from_mapping({"name": "x", "role": "x", "objective": "x", "execute": "code"})
    with pytest.raises(ValueError, match="finite positive"):
        AgentDefinition.from_mapping({"name": "x", "role": "x", "objective": "x",
                                      "resource_limits": {"max_runtime": float("inf")}})
