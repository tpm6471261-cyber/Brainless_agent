"""Validated environment configuration for bounded voice sessions."""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from math import isfinite
import os


class VoiceMode(str, Enum):
    OFF = "voice_off"
    PUSH_TO_TALK = "push_to_talk"
    ACTIVE = "voice_active"
    SESSION = "voice_session"


@dataclass(frozen=True, slots=True)
class VoiceConfig:
    api_key: str
    model: str = "universal-3-5-pro"
    sample_rate: int = 16_000
    mode: VoiceMode = VoiceMode.PUSH_TO_TALK
    language: str | None = None
    idle_timeout: float = 30
    max_session_duration: float = 900
    min_confidence: float = 0.75
    sensitive_confidence: float = 0.92
    reconnect_limit: int = 3
    store_transcripts: bool = False
    store_audio: bool = False
    context_limit: int = 12

    @classmethod
    def from_env(cls) -> "VoiceConfig":
        def value(key: str, default: str) -> str:
            return os.environ.get(key, default)

        config = cls(
            api_key=value("ASSEMBLYAI_API_KEY", ""),
            model=value("ASSEMBLYAI_MODEL", "universal-3-5-pro"),
            sample_rate=int(value("VOICE_SAMPLE_RATE", "16000")),
            mode=VoiceMode(value("VOICE_MODE", "push_to_talk")),
            language=value("VOICE_LANGUAGE", "") or None,
            idle_timeout=float(value("VOICE_IDLE_TIMEOUT", "30")),
            max_session_duration=float(value("VOICE_MAX_SESSION_DURATION", "900")),
            min_confidence=float(value("VOICE_MIN_CONFIDENCE", ".75")),
            sensitive_confidence=float(value("VOICE_SENSITIVE_CONFIDENCE", ".92")),
            reconnect_limit=int(value("VOICE_RECONNECT_LIMIT", "3")),
            store_transcripts=value("VOICE_STORE_TRANSCRIPTS", "false").lower()
            == "true",
            store_audio=value("VOICE_STORE_AUDIO", "false").lower() == "true",
        )
        config.validate()
        return config

    def validate(self) -> None:
        if self.mode is not VoiceMode.OFF and not self.api_key:
            raise ValueError("ASSEMBLYAI_API_KEY is required when voice is enabled")
        if (
            not self.model
            or len(self.model) > 100
            or self.language
            and len(self.language) > 40
        ):
            raise ValueError("Voice model or language is invalid")
        if self.sample_rate != 16_000:
            raise ValueError("Voice input must be 16 kHz PCM16 mono")
        if (
            not all(
                isfinite(item)
                for item in (self.min_confidence, self.sensitive_confidence)
            )
            or not 0 <= self.min_confidence <= self.sensitive_confidence <= 1
        ):
            raise ValueError("Voice confidence thresholds are invalid")
        if (
            not 0 < self.idle_timeout <= 3_600
            or not 0 < self.max_session_duration <= 86_400
            or not 0 <= self.reconnect_limit <= 20
            or not 1 <= self.context_limit <= 200
        ):
            raise ValueError("Voice session limits are invalid")
        if self.store_audio:
            raise ValueError(
                "Raw audio persistence is not supported by the secure default implementation"
            )
