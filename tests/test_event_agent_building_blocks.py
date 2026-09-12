import asyncio
import json

from app.agents.manager import AgentManager
from app.event_system import (ActionRegistry,ActionSpec,AgentActionExecutor,AgentBlueprint,
    EventChain,EventSystemConfig,MockEventGenerator,RiskLevel,StructuredEventLogger,sanitize)


def test_blueprint_creates_bounded_child_and_discovers_only_allowed_actions():
    manager=AgentManager();parent=manager.create_root("root","supervisor","test",{"filesystem.read"})
    blueprint=AgentBlueprint("reader","Read documents",permissions=frozenset({"filesystem.read"}),
        subscriptions=frozenset({"ON_FILE_CREATED"}),resource_limits={"max_event_rate":2},
        allowed_directories=frozenset({"C:/Documents"}))
    child=blueprint.create(manager,parent.agent_id)
    assert child.permissions=={"filesystem.read"} and child.event_subscriptions=={"ON_FILE_CREATED"}
    assert child.resource_limits["max_event_rate"]==2 and child.allowed_directories=={"C:/Documents"}


def test_agent_action_and_chain_are_reusable_building_blocks():
    async def scenario():
        registry=ActionRegistry();registry.register(ActionSpec("ADD","Add","test",frozenset({"math.use"}),
            RiskLevel.LOW,frozenset({"value"}),"number",lambda args:args["value"]+1))
        manager=AgentManager();parent=manager.create_root("root","root","test",{"math.use"})
        agent=AgentBlueprint("worker","math",permissions=frozenset({"math.use"})).create(manager,parent.agent_id)
        executor=AgentActionExecutor(registry);chain=EventChain().action(executor,agent,"ADD",{"value":"$number"})
        chain.then(lambda context:context.update(done=True))
        context=await chain.run({"number":4})
        assert context["step_0"].data==5 and context["done"] is True
    asyncio.run(scenario())


def test_config_is_private_by_default_and_honors_dry_run(monkeypatch):
    monkeypatch.setenv("DRY_RUN","true")
    config=EventSystemConfig.from_mapping({"keyboard":{"observation":True}})
    assert config.dry_run and config.keyboard_observation and not config.clipboard_observation


def test_structured_logs_redact_sensitive_values(tmp_path):
    logger=StructuredEventLogger(tmp_path)
    logger.write("security",{"token":"secret-token","nested":{"password":"hunter2"},"safe":"ok"})
    for handler in logger._logs["security"].handlers: handler.flush()
    record=json.loads((tmp_path/"security.log").read_text().strip())
    assert record["token"]=="[REDACTED]" and record["nested"]["password"]=="[REDACTED]"
    assert record["safe"]=="ok" and sanitize({"clipboard_content":"private"})["clipboard_content"]=="[REDACTED]"


def test_mock_event_generator_is_explicit_and_deterministic():
    async def scenario():
        generator=MockEventGenerator();event=generator.emit("ON_USB_CONNECTED","device",device_class="storage")
        assert await generator.poll()==(event,) and await generator.poll()==()
    asyncio.run(scenario())
