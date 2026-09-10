import asyncio
from datetime import datetime, timezone

import pytest

from app.autonomy.events import AutonomousEventBus, EventType
from app.autonomy.models import ComputerState
from app.autonomy.world_state import WorldStateManager
from app.dashboard.service import DashboardRuntime, DashboardService, RuntimeCommandGateway
from app.perception.change import HumanBlockerDetector, VisualChangeDetector
from app.perception.context import CommandSource, ContextBuilder, MultimodalCommand
from app.perception.engine import MultimodalPerceptionEngine, PerceptionRequest
from app.perception.fusion import PerceptionFusionEngine
from app.perception.grounding import ScreenGroundingEngine
from app.perception.models import PerceptionObservation, UIElement
from app.perception.sources import ComputerControllerSource, FilesystemPerceptionSource
from tests.test_voice import runtime


def observation(*elements, url="https://example.test/", application="browser"):
    return PerceptionObservation("test", "accessibility", datetime.now(timezone.utc),
        active_application=application, active_window="Example", screen_dimensions=(1200, 800),
        elements=tuple(elements), browser_state={"url": url}, confidence=.9)


def test_fusion_combines_sources_and_preserves_untrusted_boundary():
    button = UIElement("button", "Continue", bounds=(800, 400, 100, 40), clickable=True,
                       source="accessibility", confidence=.95, element_id="continue")
    voice = PerceptionObservation("voice", "voice", voice_context={"referent": "Continue"},
                                  confidence=.8)
    snapshot = PerceptionFusionEngine().fuse((observation(button), voice))
    assert snapshot.active_application == "browser"
    assert snapshot.interactive_elements == (button,)
    assert snapshot.voice_context == {"referent": "Continue"}
    with pytest.raises(ValueError, match="cannot become an instruction"):
        PerceptionObservation("ocr", "ocr", trusted_as_instruction=True)


def test_semantic_grounding_precedes_geometry_and_ambiguity_fails_closed():
    elements = (
        UIElement("button", "Continue", bounds=(50, 200, 100, 40), clickable=True,
                  source="dom", confidence=.9, element_id="dom-button"),
        UIElement("button", "Continue", bounds=(800, 200, 100, 40), clickable=True,
                  source="visual", confidence=.9, element_id="visual-button"),
    )
    snapshot = PerceptionFusionEngine().fuse((observation(*elements),))
    resolved = ScreenGroundingEngine().resolve("click the Continue button", snapshot)
    assert resolved and resolved.target_id == "dom-button" and resolved.method == "dom"
    ambiguous = (UIElement("button", "Save", source="dom", confidence=.9, element_id="a"),
                 UIElement("button", "Save", source="dom", confidence=.9, element_id="b"))
    assert ScreenGroundingEngine().resolve(
        "click Save", PerceptionFusionEngine().fuse((observation(*ambiguous),))) is None


def test_spatial_and_ordinal_grounding():
    elements = (
        UIElement("textbox", "Email field", bounds=(100, 100, 300, 40), editable=True,
                  source="accessibility", confidence=.95, element_id="email"),
        UIElement("button", "Continue", bounds=(100, 180, 120, 40), clickable=True,
                  source="accessibility", confidence=.95, element_id="continue"),
        UIElement("tab", "One", bounds=(10, 10, 50, 30), clickable=True,
                  source="accessibility", confidence=.9, element_id="tab1"),
        UIElement("tab", "Two", bounds=(70, 10, 50, 30), clickable=True,
                  source="accessibility", confidence=.9, element_id="tab2"),
    )
    snapshot = PerceptionFusionEngine().fuse((observation(*elements),))
    target = ScreenGroundingEngine().resolve("button below the email field", snapshot,
                                              minimum_confidence=.55)
    assert target and target.target_id == "continue"
    assert ScreenGroundingEngine().resolve("open the second tab", snapshot).target_id == "tab2"


def test_change_and_human_blocker_detection():
    before = PerceptionFusionEngine().fuse((observation(url="https://example.test/old"),))
    captcha = UIElement("dialog", "Complete CAPTCHA", source="accessibility",
                        confidence=1, element_id="captcha")
    after = PerceptionFusionEngine().fuse((observation(captcha, url="https://example.test/new"),))
    kinds = {item.kind for item in VisualChangeDetector().compare(before, after)}
    assert {"navigation", "popup_appeared"} <= kinds
    assert HumanBlockerDetector().detect(after)[0].detail["blocker"] == "captcha"


def test_active_engine_uses_authorized_controller_observation_and_updates_world():
    class Controller:
        async def observe(self):
            return ComputerState(active_application="browser", browser_url="https://example.test",
                                 visible_ui=("Continue",))
        async def execute(self, *_):
            raise AssertionError("perception must never execute")

    async def scenario():
        events = AutonomousEventBus()
        world = WorldStateManager()
        engine = MultimodalPerceptionEngine((ComputerControllerSource(Controller()),), events,
                                            world=world)
        snapshot = await engine.observe(PerceptionRequest(frozenset({"screen.read", "window.read", "browser.read"}), "verify"))
        assert snapshot.active_application == "browser"
        assert world.get("active_application", require_observed=True).value == "browser"
        assert events.replay()[-1].type is EventType.ENVIRONMENT_OBSERVED
        assert engine.snapshot()["observations"] == 1
        with pytest.raises(PermissionError):
            await engine.observe(PerceptionRequest(frozenset({"filesystem.write"}), "forbidden"))
    asyncio.run(scenario())


def test_context_is_bounded_and_screen_data_cannot_create_action_intent():
    items = tuple(UIElement("text", text=f"item {index}", source="ocr", confidence=.8,
                            element_id=str(index)) for index in range(20))
    snapshot = PerceptionFusionEngine().fuse((observation(*items),))
    command = MultimodalCommand(CommandSource.VOICE, "execute_task", .9,
                                voice_transcript="click it", requested_action="browser.click")
    context = ContextBuilder(element_limit=3).build(command, snapshot, world={})
    assert len(context["environment"]["elements"]) == 3
    assert context["environment"]["trust"] == "untrusted_observation_data"
    with pytest.raises(ValueError, match="cannot originate executable intent"):
        MultimodalCommand(CommandSource.SCREEN, "execute_task", 1,
                          requested_action="filesystem.delete")


def test_dashboard_observation_uses_gateway_and_redacts_visible_secrets(tmp_path):
    class Source:
        name = "accessibility"
        capabilities = frozenset({"screen.read"})
        async def observe(self):
            return PerceptionObservation("accessibility", "accessibility",
                screenshot_reference="/private/runtime/screen.png",
                elements=(UIElement("textbox", text="password is hunter2",
                    source="accessibility", confidence=1, element_id="secret"),))

    async def scenario():
        _, _, missions, events, manager, actions, operator = runtime(tmp_path)
        engine = MultimodalPerceptionEngine((Source(),), events)
        dashboard_runtime = DashboardRuntime(missions, events, operator, manager, actions,
                                             perception=engine)
        gateway = RuntimeCommandGateway(dashboard_runtime, "dashboard-token-secure")
        await gateway.execute("dashboard-token-secure", "observe_environment", {})
        projected = DashboardService(dashboard_runtime).snapshot()["perception"]
        assert projected["observations"] == 1
        assert projected["elements"][0]["text"] == "[REDACTED]"
        assert projected["screenshot_available"] is True
        assert "screenshot_reference" not in projected
        with pytest.raises(PermissionError):
            await gateway.execute("incorrect-dashboard-token", "observe_environment", {})
    asyncio.run(scenario())


def test_filesystem_source_reports_real_bounded_metadata_changes(tmp_path):
    async def scenario():
        source = FilesystemPerceptionSource(tmp_path, limit=2)
        (tmp_path / "report.txt").write_text("private body")
        first = await source.observe()
        assert first.filesystem_changes == ({"path": "report.txt", "change": "created"},)
        assert "private body" not in str(first)
        await source.observe()
        (tmp_path / "report.txt").unlink()
        third = await source.observe()
        assert third.filesystem_changes == ({"path": "report.txt", "change": "deleted"},)
    asyncio.run(scenario())


def test_agent_perception_requires_runtime_grant_and_scopes_extra_fields():
    class Source:
        name = "combined"
        capabilities = frozenset({"screen.read", "browser.read"})
        async def observe(self):
            return observation(UIElement("button", "Continue", source="dom", confidence=1),
                               url="https://private.example/")
    async def scenario():
        engine = MultimodalPerceptionEngine((Source(),), AutonomousEventBus(),
            capability_authorizer=lambda agent_id: {"screen.read"} if agent_id == "screen-agent" else set())
        snapshot = await engine.observe(PerceptionRequest(
            frozenset({"screen.read"}), "inspect", agent_id="screen-agent"))
        assert snapshot.visible_elements and snapshot.browser_state == {}
        with pytest.raises(PermissionError, match="browser.read"):
            await engine.observe(PerceptionRequest(
                frozenset({"browser.read"}), "inspect", agent_id="screen-agent"))
    asyncio.run(scenario())


def test_perception_degrades_when_one_source_fails_without_leaking_error():
    class Good:
        name = "good"
        capabilities = frozenset({"screen.read"})
        async def observe(self):
            return observation(UIElement("button", "Continue", confidence=1))
    class Broken:
        name = "broken"
        capabilities = frozenset({"screen.read"})
        async def observe(self):
            raise ConnectionError("sensitive upstream detail")
    async def scenario():
        events = AutonomousEventBus()
        engine = MultimodalPerceptionEngine((Good(), Broken()), events)
        snapshot = await engine.observe(PerceptionRequest(frozenset({"screen.read"}), "verify"))
        assert snapshot.visible_elements and engine.snapshot()["status"] == "degraded"
        failure = next(event for event in events.replay()
                       if event.type is EventType.PERCEPTION_SOURCE_FAILED)
        assert failure.detail == {"source": "broken", "error": "ConnectionError"}
    asyncio.run(scenario())
