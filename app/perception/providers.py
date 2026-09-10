"""Replaceable interpretation providers; providers return data and never receive tools."""
from __future__ import annotations

from typing import Protocol

from app.perception.models import PerceptionObservation


class VisualUnderstandingProvider(Protocol):
    """Converts an authorized screenshot reference into structured observation data."""
    async def understand(self, screenshot_reference: str) -> PerceptionObservation: ...


class SpeechRecognitionProvider(Protocol):
    """Lifecycle boundary implemented by AssemblyAI transport or future providers."""
    async def connect(self, on_turn, on_error) -> str: ...
    async def stream_microphone(self) -> None: ...
    async def disconnect(self) -> None: ...
    def health_check(self) -> bool: ...


class SpeechOutputProvider(Protocol):
    """Optional output-only boundary; not coupled to mission execution."""
    async def speak(self, text: str) -> None: ...
