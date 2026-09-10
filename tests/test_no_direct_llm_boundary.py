import asyncio

import pytest

from app.agents.manager import AgentManager
from app.autonomy.cognitive import (CounterfactualPlanner, Decision, DecisionEngine, ObservationOption,
                                    PerceptionPlanner, Strategy)
from app.autonomy.executor import ActionRuntime
from app.autonomy.models import ActionProposal, ComputerState, DecisionContext
from app.autonomy.proposals import (ProposalRejected, ProposalType, ProposalValidator, ReasoningContext,
                                    ReasoningProposal)
from app.autonomy.world_model import WorldModel
from app.safety.permissions import Permission


class Controller:
    def __init__(self): self.calls = 0
    async def observe(self): return ComputerState(active_application="test", browser_url="before")
    async def execute(self, *_): self.calls += 1; return "executed"


def setup():
    manager = AgentManager()
    root = manager.create_root("root", "root", "goal", {Permission.SCREEN_READ.value, Permission.MOUSE_CLICK.value})
    runtime = ActionRuntime(manager, Controller())
    child = manager.create_agent(root.agent_id, "child", "child", "goal", permissions={Permission.SCREEN_READ.value, Permission.MOUSE_CLICK.value}, tools={"mouse.click"}, context={"task_id": "task-1"})
    return manager, root, child, runtime


def test_malicious_proposals_are_rejected_before_tool_or_resource_access():
    manager, _, child, runtime = setup()
    validator = ProposalValidator(manager)
    bad = ActionProposal("process.execute", {"command": "cat /secret"}, "steal secret")
    with pytest.raises(ProposalRejected): validator.validate_action(child.agent_id, "task-1", bad)
    assert runtime.locks.owners == {}

    async def run():
        result = await runtime.perform_proposal(child.agent_id, "other-task", ActionProposal("mouse.click", {"x": 1, "y": 2}, "cross task"))
        assert not result.success and "own" in (result.error or "")
    asyncio.run(run())


def test_structured_reasoning_proposal_cannot_grant_permissions_or_use_extra_arguments():
    manager, _, child, _ = setup()
    validator = ProposalValidator(manager)
    proposal = ReasoningProposal("p", "goal", "task-1", ProposalType.ACTION, "click", (
        ActionProposal("mouse.click", {"x": 1, "y": 2, "permission": "filesystem.write"}, "bad"),),
        required_permissions=frozenset({Permission.FILESYSTEM_WRITE.value}), confidence=.8)
    with pytest.raises(ProposalRejected): validator.validate(child.agent_id, proposal)


def test_world_model_comparison_and_simulation_do_not_execute_actions():
    model = WorldModel()
    model.state.capture(ComputerState(browser_url="before"))
    simulated = model.simulate({"browser_url": "after"})
    assert simulated["browser_url"] == "after"
    assert model.state.get("browser_url").value == "before"
    model.predict("click", {"browser_url": "after"})
    observed = model.state.capture(ComputerState(browser_url="error"))
    comparison = model.compare("click", observed)
    assert comparison.invalidated and comparison.differences["browser_url"] == ("after", "error")


def test_runtime_decisions_prefer_information_and_counterfactuals_are_inert():
    from app.autonomy.world_state import WorldStateManager
    world = WorldStateManager()
    assert DecisionEngine().choose(world, ["browser_url"]) is Decision.OBSERVE
    choice = PerceptionPlanner().choose({"active_window"}, [
        ObservationOption("screen", 4, .8, frozenset({"active_window"})),
        ObservationOption("window.query", 1, .9, frozenset({"active_window"})),
    ])
    assert choice.tool_id == "window.query"
    assert CounterfactualPlanner().choose([Strategy("unsafe", 1, 0, 1, 0, True, False, True)]) is None
