"""Write-only credential and lifecycle control plane for dashboard voice setup."""

from __future__ import annotations
import asyncio
from collections.abc import Callable

from app.voice.config import VoiceConfig
from app.voice.service import VoiceService


class VoiceControlPlane:
    """Owns VoiceService lifecycle; API keys are held in memory and never projected."""

    def __init__(self, factory: Callable[[VoiceConfig], VoiceService]) -> None:
        self._factory = factory
        self._service: VoiceService | None = None
        self._listener: asyncio.Task[None] | None = None
        self._running = False
        self._lifecycle_lock = asyncio.Lock()

    def configure(
        self, api_key: str, settings: dict[str, object] | None = None
    ) -> None:
        if self.health_check():
            raise ValueError("Stop voice before changing its configuration")
        if not 16 <= len(api_key.strip()) <= 512:
            raise ValueError("AssemblyAI API key length is invalid")
        settings = settings or {}
        allowed = {
            "model",
            "language",
            "idle_timeout",
            "max_session_duration",
            "min_confidence",
            "sensitive_confidence",
        }
        unknown = set(settings) - allowed
        if unknown:
            raise ValueError("Unsupported voice configuration field")
        try:
            idle_timeout = float(settings.get("idle_timeout", 30))
            max_session_duration = float(settings.get("max_session_duration", 900))
            min_confidence = float(settings.get("min_confidence", 0.75))
            sensitive_confidence = float(settings.get("sensitive_confidence", 0.92))
        except (TypeError, ValueError) as error:
            raise ValueError("Voice numeric configuration is invalid") from error
        config = VoiceConfig(
            api_key.strip(),
            model=str(settings.get("model", "universal-3-5-pro")),
            language=str(settings["language"]) if settings.get("language") else None,
            idle_timeout=idle_timeout,
            max_session_duration=max_session_duration,
            min_confidence=min_confidence,
            sensitive_confidence=sensitive_confidence,
        )
        config.validate()
        self._service = self._factory(config)

    def configure_config(self, config: VoiceConfig) -> None:
        """Install validated trusted startup configuration without exposing its key."""
        if self.health_check():
            raise ValueError("Stop voice before changing its configuration")
        config.validate()
        self._service = self._factory(config)

    async def start(self) -> None:
        async with self._lifecycle_lock:
            if self._service is None:
                raise ValueError("Configure AssemblyAI before starting voice")
            if self._running and self.health_check():
                return
            if self._listener and not self._listener.done():
                self._listener.cancel()
                await asyncio.gather(self._listener, return_exceptions=True)
            if self._running:
                await self._service.stop()
            await self._service.start()
            self._running = True
            self._listener = asyncio.create_task(
                self._service.listen(), name="voice-microphone"
            )
            self._listener.add_done_callback(self._listener_finished)

    async def stop(self) -> None:
        async with self._lifecycle_lock:
            if self._listener:
                self._listener.cancel()
                await asyncio.gather(self._listener, return_exceptions=True)
                self._listener = None
            if self._service and self._running:
                await self._service.stop()
            self._running = False

    def _listener_finished(self, task: asyncio.Task[None]) -> None:
        if task is self._listener and not self.health_check():
            self._running = False

    def health_check(self) -> bool:
        return bool(self._service and self._service.health_check())

    def snapshot(self) -> dict[str, object]:
        if self._service:
            return {**self._service.snapshot(), "configured": True}
        return {
            "status": "not_configured",
            "connection": "disconnected",
            "history": [],
            "current_transcript": "",
            "final_transcript": "",
            "error": None,
            "configured": False,
        }
