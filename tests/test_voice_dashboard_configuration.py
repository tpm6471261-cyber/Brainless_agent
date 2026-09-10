import asyncio
import json

import pytest

from app.dashboard.service import (
    DashboardRuntime,
    DashboardService,
    RuntimeCommandGateway,
)
from app.voice.controller import VoiceControlPlane

from tests.test_voice import runtime


def test_dashboard_configures_and_controls_voice_without_exposing_key(tmp_path):
    async def scenario():
        service_parts = runtime(tmp_path)
        original, transport, missions, events, manager, actions, operator = (
            service_parts
        )
        created = []

        def factory(config):
            created.append(config)
            original.config = config
            return original

        voice = VoiceControlPlane(factory)
        dashboard_runtime = DashboardRuntime(
            missions, events, operator, manager, actions, voice=voice
        )
        gateway = RuntimeCommandGateway(dashboard_runtime, "dashboard-token-secure")
        api_key = "assemblyai-secret-key-value"

        await gateway.execute(
            "dashboard-token-secure",
            "configure_voice",
            {
                "api_key": api_key,
                "model": "universal-3-5-pro",
                "language": "en",
                "min_confidence": 0.8,
            },
        )
        snapshot = DashboardService(dashboard_runtime).snapshot()
        serialized = json.dumps(
            {
                "snapshot": snapshot,
                "events": [event.detail for event in events.replay()],
            }
        )
        assert snapshot["voice"]["configured"] is True
        assert api_key not in serialized
        assert created[0].api_key == api_key

        await gateway.execute("dashboard-token-secure", "start_voice", {})
        assert transport.connected and voice.health_check()
        await gateway.execute("dashboard-token-secure", "stop_voice", {})
        assert not transport.connected

    asyncio.run(scenario())


def test_dashboard_voice_configuration_is_validated(tmp_path):
    service, _, missions, events, manager, actions, operator = runtime(tmp_path)
    voice = VoiceControlPlane(lambda config: service)
    gateway = RuntimeCommandGateway(
        DashboardRuntime(missions, events, operator, manager, actions, voice=voice),
        "dashboard-token-secure",
    )

    with pytest.raises(ValueError, match="length"):
        asyncio.run(
            gateway.execute(
                "dashboard-token-secure",
                "configure_voice",
                {
                    "api_key": "short",
                },
            )
        )
    assert events.replay() == ()


def test_dashboard_rejects_non_finite_voice_confidence(tmp_path):
    service, _, missions, events, manager, actions, operator = runtime(tmp_path)
    voice = VoiceControlPlane(lambda config: service)
    gateway = RuntimeCommandGateway(
        DashboardRuntime(missions, events, operator, manager, actions, voice=voice),
        "dashboard-token-secure",
    )
    with pytest.raises(ValueError, match="thresholds"):
        asyncio.run(
            gateway.execute(
                "dashboard-token-secure",
                "configure_voice",
                {"api_key": "assembly-key-long-enough", "min_confidence": float("nan")},
            )
        )
