import asyncio
from pathlib import Path

import pytest

from app.agents.manager import AgentManager
from app.agents.models import AgentStatus
from app.autonomy.executor import ActionRuntime
from app.autonomy.models import ActionProposal, ComputerAction, ComputerState
from app.autonomy.orchestrator import AutonomousRuntime
from app.autonomy.controllers import FilesystemComputerController
from app.autonomy.task_engine import AutonomousTask, AutonomousTaskEngine, TaskOutcome
from app.safety.permissions import Permission, PermissionDenied
from app.safety.permissions import ApprovalMode, PermissionPolicy
from app.memory.sqlite_memory import SQLiteMemory


class LocalComputer:
    """Deterministic test controller exercising the real runtime boundary."""
    def __init__(self, root: Path) -> None:
        self.url = None; self.text = ""; self.root = root

    async def observe(self) -> ComputerState:
        return ComputerState(active_application="browser" if self.url else "editor", browser_url=self.url,
                             browser_title="Example" if self.url else None, visible_ui=(self.text,))

    async def execute(self, action_type, arguments):
        if action_type == "browser.navigate":
            self.url = arguments["url"]; return {"url": self.url}
        if action_type == "keyboard.write":
            self.text += arguments["text"]; return self.text
        if action_type == "filesystem.write":
            path = self.root / arguments["path"]; path.write_text(arguments["content"]); return str(path)
        if action_type == "mouse.click": return "clicked"
        raise RuntimeError(action_type)


class BrowserDecision:
    async def next_action(self, context):
        if context.state["browser_url"]:
            return None
        return ActionProposal("browser.navigate", {"url": "https://example.test"}, "Navigate to requested site",
                              {"browser_url": "https://example.test"})


def test_end_to_end_dynamic_creation_reuse_and_controlled_permission(tmp_path) -> None:
    async def scenario() -> None:
        manager = AgentManager()
        root = manager.create_root("Root", "orchestrator", "Coordinate", {
            Permission.SCREEN_READ.value, Permission.BROWSER_NAVIGATE.value, Permission.MOUSE_CLICK.value,
        })
        controller = LocalComputer(tmp_path)
        runtime = AutonomousRuntime(manager, ActionRuntime(manager, controller))
        decider = BrowserDecision()
        first = await runtime.execute(root.agent_id, "task-1", "Open browser and navigate to a website", decider)
        assert first.created and first.actions == 1
        agent = manager.get_agent(first.agent_id)
        assert agent.status is AgentStatus.COMPLETED
        assert controller.url == "https://example.test"

        # Discovery reuses the compatible READY agent after task assignment.
        controller.url = None
        second = await runtime.execute(root.agent_id, "task-2", "Navigate browser to website", decider)
        assert not second.created and second.agent_id == first.agent_id

        manager.assign_task(root.agent_id, agent.agent_id, "Attempt mouse click")
        async def forbidden(child, _):
            result = await runtime.actions.perform(ComputerAction("mouse.click", {"x": 1, "y": 2}, child.agent_id,
                "task-3", "test least privilege", Permission.MOUSE_CLICK.value))
            assert not result.success and "PERMISSION_DENIED" in result.error
            return "denied safely"
        assert await manager.start_agent(root.agent_id, agent.agent_id, forbidden) == "denied safely"

        manager.grant_permission(root.agent_id, agent.agent_id, Permission.MOUSE_CLICK.value)
        manager.grant_tool(root.agent_id, agent.agent_id, "mouse.click")
        async def allowed(child, _):
            result = await runtime.actions.perform(ComputerAction("mouse.click", {"x": 1, "y": 2}, child.agent_id,
                "task-4", "authorized click", Permission.MOUSE_CLICK.value))
            assert result.success and result.verified
            return "clicked"
        assert await manager.start_agent(root.agent_id, agent.agent_id, allowed) == "clicked"
    asyncio.run(scenario())


def test_document_requirements_are_minimal_and_factory_rejects_parent_escalation(tmp_path) -> None:
    manager = AgentManager()
    root = manager.create_root("Root", "orchestrator", "Coordinate", {Permission.SCREEN_READ.value})
    runtime = AutonomousRuntime(manager, ActionRuntime(manager, LocalComputer(tmp_path)))
    requirements = runtime.analyzer.analyze("Open a text editor, write and save a document")
    assert requirements.permissions == frozenset({Permission.SCREEN_READ.value, Permission.KEYBOARD_WRITE.value,
                                                   Permission.FILESYSTEM_WRITE.value})
    class Noop:
        async def next_action(self, context): return None
    with pytest.raises(ValueError, match="unavailable"):
        asyncio.run(runtime.execute(root.agent_id, "doc", "Open a text editor, write and save a document", Noop()))


def test_document_agent_writes_and_verifies_a_real_file(tmp_path) -> None:
    class DocumentDecision:
        def __init__(self) -> None: self.step = 0
        async def next_action(self, context):
            self.step += 1
            if self.step == 1:
                return ActionProposal("keyboard.write", {"text": "hello autonomous runtime"}, "Write requested document")
            if self.step == 2:
                return ActionProposal("filesystem.write", {"path": "note.txt", "content": "hello autonomous runtime"},
                                      "Save requested document")
            return None
    async def scenario() -> None:
        manager = AgentManager()
        root = manager.create_root("Root", "orchestrator", "Coordinate", {Permission.SCREEN_READ.value,
            Permission.KEYBOARD_WRITE.value, Permission.FILESYSTEM_WRITE.value})
        runtime = AutonomousRuntime(manager, ActionRuntime(manager, LocalComputer(tmp_path)))
        result = await runtime.execute(root.agent_id, "doc-write", "Open text editor, write and save document", DocumentDecision())
        assert result.created and result.actions == 2
        assert (tmp_path / "note.txt").read_text() == "hello autonomous runtime"
    asyncio.run(scenario())


def test_runtime_requires_registry_and_can_resume_after_explicit_approval(tmp_path) -> None:
    async def scenario() -> None:
        policy = PermissionPolicy({Permission.KEYBOARD_WRITE.value: ApprovalMode.REQUIRE_APPROVAL})
        manager = AgentManager(policy=policy)
        root = manager.create_root("Root", "orchestrator", "Coordinate", {Permission.SCREEN_READ.value,
            Permission.KEYBOARD_WRITE.value})
        controller = LocalComputer(tmp_path)
        runtime = ActionRuntime(manager, controller, approval_handler=lambda action: True)
        child = manager.create_agent(root.agent_id, "Writer", "writer", "Write", permissions={
            Permission.SCREEN_READ.value, Permission.KEYBOARD_WRITE.value}, tools={"keyboard.write"})
        async def work(agent, _):
            result = await runtime.perform_proposal(agent.agent_id, "approved", ActionProposal(
                "keyboard.write", {"text": "approved"}, "write after user approval"))
            assert result.success and result.verified
            unknown = await runtime.perform_proposal(agent.agent_id, "unknown", ActionProposal(
                "unregistered.shell", {}, "attempt a registry bypass"))
            assert not unknown.success and "TOOL_NOT_FOUND" in unknown.error
            return "done"
        assert await manager.start_agent(root.agent_id, child.agent_id, work) == "done"
        assert controller.text == "approved"
        assert runtime.audit[-1].tool == "unregistered.shell"
        assert runtime.audit[0].policy_decision == "require_approval"
        assert runtime.audit[0].approval_status == "approved"
    asyncio.run(scenario())


def test_action_audit_is_persisted_with_safe_runtime_metadata(tmp_path) -> None:
    async def scenario() -> None:
        storage = SQLiteMemory(tmp_path / "memory.db")
        manager = AgentManager(audit_store=storage)
        root = manager.create_root("Root", "orchestrator", "Coordinate", {Permission.SCREEN_READ.value,
            Permission.KEYBOARD_WRITE.value})
        runtime = ActionRuntime(manager, LocalComputer(tmp_path), audit_store=storage)
        child = manager.create_agent(root.agent_id, "Writer", "writer", "Write", permissions={
            Permission.SCREEN_READ.value, Permission.KEYBOARD_WRITE.value}, tools={"keyboard.write"})
        async def work(agent, _):
            result = await runtime.perform_proposal(agent.agent_id, "audit-task", ActionProposal(
                "keyboard.write", {"text": "audited"}, "record action"))
            assert result.success
            return "done"
        await manager.start_agent(root.agent_id, child.agent_id, work)
        record = storage.computer_action_audit("audit-task")[0]
        assert record["tool"] == "keyboard.write"
        assert record["permission"] == Permission.KEYBOARD_WRITE.value
        assert record["arguments"] == {"text": "audited"}
        assert record["parent_agent_id"] == root.agent_id
        assert record["policy_decision"] == "auto_approve"
        storage.close()
    asyncio.run(scenario())


def test_goal_engine_creates_agent_writes_real_file_checkpoints_and_verifies_outcome(tmp_path) -> None:
    class WriteDecision:
        def __init__(self) -> None: self.done = False
        async def next_action(self, context):
            if self.done:
                return None
            self.done = True
            return ActionProposal("filesystem.write", {"path": "reports/result.txt", "content": "verified content"},
                                  "Create the requested report")

    class FileCriterion:
        async def verify(self, runtime):
            path = tmp_path / "reports/result.txt"
            return (path.is_file() and path.read_text() == "verified content", "report file is missing or has wrong content")

    async def scenario() -> None:
        storage = SQLiteMemory(tmp_path / "journal.db")
        manager = AgentManager(audit_store=storage)
        root = manager.create_root("Root", "orchestrator", "Fulfil outcome", {Permission.SCREEN_READ.value,
            Permission.FILESYSTEM_WRITE.value, Permission.FILESYSTEM_READ.value})
        actions = ActionRuntime(manager, FilesystemComputerController(tmp_path), audit_store=storage)
        engine = AutonomousTaskEngine(AutonomousRuntime(manager, actions), actions, storage)
        task = AutonomousTask("Create a text file with requested content and save it", (FileCriterion(),), "file-goal")
        result = await engine.run(root.agent_id, task, WriteDecision())
        assert result.outcome is TaskOutcome.COMPLETED and result.verified
        assert (tmp_path / "reports/result.txt").read_text() == "verified content"
        assert [entry["event_type"] for entry in storage.task_journal("file-goal")] == [
            "TASK_CREATED", "TASK_PLANNED", "CHECKPOINT_CREATED", "TASK_COMPLETED"]
        storage.close()
    asyncio.run(scenario())


def test_closed_loop_recovery_replans_after_a_real_filesystem_failure(tmp_path) -> None:
    class RecoveringDecision:
        def __init__(self) -> None: self.calls = 0
        async def next_action(self, context):
            self.calls += 1
            if self.calls == 1:
                return ActionProposal("filesystem.write", {"path": "../escape.txt", "content": "unsafe"},
                                      "Try initial location")
            if self.calls == 2:
                assert context.previous is not None and not context.previous.success
                return ActionProposal("filesystem.write", {"path": "recovered.txt", "content": "safe"},
                                      "Replan to approved workspace", {"state_changed": True})
            return None
    async def scenario() -> None:
        manager = AgentManager()
        root = manager.create_root("Root", "orchestrator", "Recover", {Permission.SCREEN_READ.value,
            Permission.FILESYSTEM_WRITE.value})
        actions = ActionRuntime(manager, FilesystemComputerController(tmp_path))
        result = await AutonomousRuntime(manager, actions).execute(root.agent_id, "recover", "Create a file", RecoveringDecision())
        assert result.result == "Completed 1 verified action(s) after 1 recovered failure(s)"
        assert (tmp_path / "recovered.txt").read_text() == "safe"
        assert "INVALID_ARGUMENT" in actions.audit[0].error
    asyncio.run(scenario())


def test_task_engine_learns_then_reuses_a_verified_workflow_through_runtime_gates(tmp_path) -> None:
    """The second execution uses a persisted skill, not a task-name branch."""
    from app.autonomy.contracts import ActionContract
    from app.autonomy.task_graph import GraphTask, TaskGraph
    from app.learning import ExperienceMemory, LearningCoordinator, SkillRegistry, SkillStatus

    class FileCriterion:
        async def verify(self, _):
            report = tmp_path / "report.txt"
            return (report.is_file() and report.read_text() == "verified", "report missing")

    class WriteDecision:
        def __init__(self): self.done = False
        async def next_action(self, _):
            if self.done: return None
            self.done = True
            return ActionProposal("filesystem.write", {"path": "report.txt", "content": "verified"}, "write report")

    def graph() -> TaskGraph:
        result = TaskGraph()
        result.add(GraphTask("write", "write report file", capabilities=frozenset({"filesystem.write"}),
            permissions=frozenset({Permission.FILESYSTEM_WRITE.value}), tool="filesystem.write",
            resources=frozenset({"filesystem/report.txt"})))
        return result

    async def scenario() -> None:
        manager = AgentManager()
        root = manager.create_root("Root", "orchestrator", "Learn reports", {
            Permission.SCREEN_READ.value, Permission.FILESYSTEM_WRITE.value,
        })
        actions = ActionRuntime(manager, FilesystemComputerController(tmp_path), contracts={
            "filesystem.write": ActionContract("write-report", "filesystem.write", frozenset({Permission.FILESYSTEM_WRITE.value})),
        })
        memories = ExperienceMemory(tmp_path / "experiences.db")
        skills = SkillRegistry(tmp_path / "skills.db")
        engine = AutonomousTaskEngine(AutonomousRuntime(manager, actions), actions,
            learning=LearningCoordinator(memories, skills))
        first = await engine.run_with_learning(root.agent_id,
            AutonomousTask("Create report file", (FileCriterion(),), "first"), task_type="report",
            environment={"app": "filesystem"}, decider_for=lambda _: WriteDecision(), fallback_graph=graph(),
            candidate_name="create report file", candidate_description="write a verified report file")
        assert first.verified
        candidate = skills.candidates()[0]
        skills.set_status(candidate.skill_id, SkillStatus.VERIFIED)
        (tmp_path / "report.txt").unlink()
        reused_nodes: list[str] = []
        def reused_decider(node):
            reused_nodes.append(node.task_id)
            return WriteDecision()
        second = await engine.run_with_learning(root.agent_id,
            AutonomousTask("Create another report file", (FileCriterion(),), "second"), task_type="report",
            environment={"app": "filesystem"}, decider_for=reused_decider, fallback_graph=graph())
        assert second.verified
        assert memories.retrieve("another report", task_type="report")[0].success
        # The synthesized node id proves this was the persisted skill workflow, not fallback_graph.
        assert reused_nodes and reused_nodes[0].startswith(candidate.skill_id + ":")
        memories.close(); skills.close()

    asyncio.run(scenario())


def test_action_results_audit_and_events_redact_secret_values(tmp_path) -> None:
    async def scenario():
        manager = AgentManager()
        root = manager.create_root("Root", "orchestrator", "Coordinate", {
            Permission.KEYBOARD_WRITE.value})
        controller = LocalComputer(tmp_path)
        actions = ActionRuntime(manager, controller)
        child = manager.create_agent(root.agent_id, "Writer", "writer", "type",
            task="type secret", permissions={Permission.KEYBOARD_WRITE.value},
            tools={"keyboard.write"}, task_id="secret-task")
        child.status = AgentStatus.RUNNING
        result = await actions.perform(ComputerAction("keyboard.write",
            {"text": "password is hunter2"}, child.agent_id, "secret-task",
            "type supplied content", Permission.KEYBOARD_WRITE.value))
        assert result.output == "[REDACTED]"
        assert actions.audit[-1].arguments["text"] == "[REDACTED]"
        assert "hunter2" not in str(actions.audit[-1])
    asyncio.run(scenario())
