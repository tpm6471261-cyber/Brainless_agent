"""AssemblyAI Streaming v3 input service; finalized turns alone reach runtime routing."""
from __future__ import annotations
import asyncio
from datetime import datetime, timezone
from time import monotonic
from typing import Awaitable, Callable, Protocol
from uuid import uuid4

from app.autonomy.events import AutonomousEvent, AutonomousEventBus, EventType
from app.autonomy.mission import Mission, MissionStatus
from app.voice.config import VoiceConfig
from app.voice.intent import VoiceIntent, VoiceIntentEngine, VoiceIntentType
from app.voice.models import VoiceSession, VoiceSessionStatus, VoiceTurn
from app.voice.store import VoiceMetadataStore


TurnHandler = Callable[[VoiceTurn], None]


class StreamingTransport(Protocol):
    async def connect(self, on_turn: TurnHandler, on_error: Callable[[str], None]) -> str | None: ...
    async def stream_microphone(self) -> None: ...
    async def disconnect(self) -> None: ...
    def health_check(self) -> bool: ...


class AssemblyAIStreamingTransport:
    """Thin SDK adapter for wss://streaming.assemblyai.com/v3/ws."""
    def __init__(self, config: VoiceConfig) -> None:
        self.config, self.client, self._connected = config, None, False

    async def connect(self, on_turn: TurnHandler, on_error: Callable[[str], None]) -> str | None:
        from assemblyai.streaming.v3 import (StreamingClient, StreamingClientOptions,
                                              StreamingEvents, StreamingParameters)
        self.client = StreamingClient(StreamingClientOptions(api_key=self.config.api_key))
        def receive_turn(*args) -> None:
            turn = args[-1]
            on_turn(VoiceTurn(str(getattr(turn, "turn_order", uuid4())),
                getattr(turn, "transcript", ""),
                float(getattr(turn, "end_of_turn_confidence", 1.0) or 1.0),
                bool(getattr(turn, "end_of_turn", False))))
        self.client.on(StreamingEvents.Turn, receive_turn)
        self.client.on(StreamingEvents.Error, lambda *args: on_error(str(args[-1])))
        options = {"sample_rate": self.config.sample_rate, "speech_model": self.config.model,
                   "language_detection": not bool(self.config.language)}
        if self.config.language: options["language_code"] = self.config.language
        parameters = StreamingParameters(**options)
        connected = await asyncio.to_thread(self.client.connect, parameters)
        self._connected = True
        return str(getattr(connected, "id", "") or getattr(self.client, "session_id", "")) or None

    async def stream_microphone(self) -> None:
        from assemblyai.extras import MicrophoneStream
        if self.client is None: raise RuntimeError("AssemblyAI stream is not connected")
        microphone = MicrophoneStream(sample_rate=self.config.sample_rate)
        await asyncio.to_thread(self.client.stream, microphone)

    async def disconnect(self) -> None:
        try:
            if self.client is not None:
                await asyncio.to_thread(self.client.disconnect, terminate=True)
        finally:
            self._connected = False
            self.client = None

    def health_check(self) -> bool: return self._connected


class AssemblyAISpeechProvider(AssemblyAIStreamingTransport):
    """Named provider implementation; the legacy transport name remains compatible."""


class VoiceRuntimeRouter:
    """Maps structured voice intent only into existing runtime-owned services."""
    def __init__(self, operator, missions, approvals=None,
                 emergency_stop: Callable[[], Awaitable[None] | None] | None = None,
                 approval_authorizer: Callable[[VoiceIntent], Awaitable[bool] | bool] | None = None) -> None:
        self.operator, self.missions, self.approvals, self.emergency_stop = operator, missions, approvals, emergency_stop
        self.approval_authorizer = approval_authorizer

    async def route(self, intent: VoiceIntent) -> dict[str, str | None]:
        if intent.type in {VoiceIntentType.EXECUTE_TASK, VoiceIntentType.CREATE_MISSION}:
            mission = Mission(intent.goal or intent.transcript, "voice")
            await self.operator.create(mission)
            return {"status": "accepted", "mission_id": mission.mission_id, "result": "Mission created"}
        if intent.type in {VoiceIntentType.EMERGENCY_STOP, VoiceIntentType.STOP, VoiceIntentType.PAUSE}:
            self.operator.takeover.begin()
            if self.emergency_stop:
                result = self.emergency_stop()
                if hasattr(result, "__await__"): await result
            else:
                for mission in self.missions.active():
                    mission.status = MissionStatus.PAUSED; mission.touch(); self.missions.save(mission)
            return {"status": "completed", "mission_id": None, "result": "Autonomous work paused"}
        if intent.type is VoiceIntentType.TAKEOVER:
            self.operator.takeover.begin()
            return {"status": "completed", "mission_id": None, "result": "User takeover enabled"}
        if intent.type is VoiceIntentType.RESUME:
            self.operator.takeover.resume()
            for mission in self.missions.active():
                if mission.status in {MissionStatus.PAUSED, MissionStatus.AWAITING_USER}:
                    mission.status = MissionStatus.WAITING
                    mission.touch()
                    self.missions.save(mission)
                    await self.operator.events.publish(AutonomousEvent(
                        EventType.MISSION_TRIGGERED, mission.mission_id,
                        {"source": "authorized_voice_resume"}))
            return {"status": "completed", "mission_id": None, "result": "Control returned to runtime"}
        if intent.type is VoiceIntentType.QUERY_STATUS:
            return {"status": "completed", "mission_id": None,
                    "result": f"{len(self.missions.active())} active missions"}
        if intent.type is VoiceIntentType.APPROVAL:
            if self.approval_authorizer is None:
                return {"status": "waiting", "mission_id": None,
                        "result": "Voice approval is disabled; use the authenticated dashboard"}
            authorized = self.approval_authorizer(intent)
            if hasattr(authorized, "__await__"): authorized = await authorized
            if not authorized:
                return {"status": "waiting", "mission_id": None,
                        "result": "Voice approval authorization failed"}
            pending = self.approvals.store.all() if self.approvals else ()
            pending = [item for item in pending if item.status.value == "pending"]
            if len(pending) != 1: return {"status": "waiting", "mission_id": None,
                                        "result": "Approval is ambiguous; use the dashboard"}
            from app.autonomy.approvals import ApprovalStatus
            decision = ApprovalStatus.APPROVED if intent.transcript.casefold().strip(" .!") == "approve" else ApprovalStatus.DENIED
            item = self.approvals.decide(pending[0].approval_id, decision, "voice_user")
            return {"status": "completed", "mission_id": item.mission_id, "result": decision.value}
        return {"status": "waiting", "mission_id": None, "result": "Command requires clarification"}


class VoiceService:
    def __init__(self, config: VoiceConfig, transport: StreamingTransport, router: VoiceRuntimeRouter,
                 events: AutonomousEventBus, store: VoiceMetadataStore, intent_engine: VoiceIntentEngine | None = None) -> None:
        config.validate()
        self.config, self.transport, self.router, self.events, self.store = config, transport, router, events, store
        self.intent_engine = intent_engine or VoiceIntentEngine()
        self.session: VoiceSession | None = None
        self.history: list[dict[str, object]] = list(store.all())[-config.context_limit:]
        self.reconnects = 0
        self._seen: set[str] = set(); self._pending: VoiceIntent | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._last_activity = monotonic()

    async def start(self, user_id: str = "local_user") -> VoiceSession:
        if self.session and self.session.status not in {VoiceSessionStatus.STOPPED, VoiceSessionStatus.ERROR} and self.transport.health_check():
            return self.session
        self.session = VoiceSession(user_id); self.session.status = VoiceSessionStatus.LISTENING
        self._loop = asyncio.get_running_loop()
        try:
            self.session.assemblyai_session_id = await self._connect_with_backoff()
        except Exception:
            self.session.status = VoiceSessionStatus.ERROR
            self.session.connection_status = "disconnected"
            self.session.error_state = "AssemblyAI connection failed"
            raise
        self.session.connection_status = "connected"
        await self.events.publish(AutonomousEvent(EventType.VOICE_SESSION, detail={"session_id": self.session.session_id, "status": "listening"}))
        return self.session

    async def listen(self) -> None:
        if not self.session: raise RuntimeError("Voice session is not started")
        stream = asyncio.create_task(self.transport.stream_microphone())
        started = monotonic()
        try:
            while not stream.done():
                await asyncio.sleep(min(1, self.config.idle_timeout))
                if monotonic() - started >= self.config.max_session_duration or monotonic() - self._last_activity >= self.config.idle_timeout:
                    await self.pause(); stream.cancel(); break
            results = await asyncio.gather(stream, return_exceptions=True)
            failure = next((item for item in results if isinstance(item, Exception)
                            and not isinstance(item, asyncio.CancelledError)), None)
            if failure and self.session:
                self.session.status = VoiceSessionStatus.ERROR
                self.session.error_state = "Microphone streaming error"
                await self.events.publish(AutonomousEvent(EventType.VOICE_SESSION,
                    detail={"session_id": self.session.session_id, "status": "error",
                            "error": type(failure).__name__}))
        finally:
            if not stream.done(): stream.cancel()

    async def stop(self) -> None:
        disconnect_error = None
        try:
            await self.transport.disconnect()
        except Exception as error:
            disconnect_error = error
        if self.session:
            self.session.status = VoiceSessionStatus.STOPPED; self.session.connection_status = "disconnected"
            self.session.ended_at = datetime.now(timezone.utc)
            self.store.append({"session_id": self.session.session_id, "status": "stopped",
                               "started_at": self.session.started_at.isoformat(), "ended_at": self.session.ended_at.isoformat()})
            await self.events.publish(AutonomousEvent(EventType.VOICE_SESSION, detail={"session_id": self.session.session_id,
                "status": "stopped", "disconnect_error": type(disconnect_error).__name__ if disconnect_error else None}))

    async def pause(self) -> None:
        await self.transport.disconnect()
        if self.session: self.session.status = VoiceSessionStatus.WAITING; self.session.connection_status = "paused"

    async def resume(self) -> None:
        if not self.session: await self.start(); return
        self.session.assemblyai_session_id = await self._connect_with_backoff()
        self.session.status = VoiceSessionStatus.LISTENING; self.session.connection_status = "connected"

    def health_check(self) -> bool:
        return bool(self.session and self.session.status not in {
            VoiceSessionStatus.STOPPED, VoiceSessionStatus.ERROR} and self.transport.health_check())

    def _on_turn(self, turn: VoiceTurn) -> None:
        if self._loop: asyncio.run_coroutine_threadsafe(self.process_turn(turn), self._loop)

    def _on_error(self, error: str) -> None:
        if self.session: self.session.status = VoiceSessionStatus.ERROR; self.session.error_state = "AssemblyAI streaming error"

    async def process_turn(self, turn: VoiceTurn) -> None:
        if not self.session or turn.transcript_id in self._seen: return
        self._last_activity = monotonic()
        self.session.current_transcript = turn.transcript
        if not turn.finalized:
            self.session.status = VoiceSessionStatus.TRANSCRIBING
            await self.events.publish(AutonomousEvent(EventType.VOICE_PARTIAL, detail={"session_id": self.session.session_id, "status": "transcribing"}))
            return
        self._seen.add(turn.transcript_id); self.session.last_final_transcript = turn.transcript
        self.session.status = VoiceSessionStatus.PROCESSING
        intent = self.intent_engine.parse(turn.transcript, turn.confidence)
        if turn.confidence < self.config.min_confidence or (intent.requires_confirmation and turn.confidence < self.config.sensitive_confidence):
            result = {"status": "waiting", "mission_id": None, "result": "Please repeat or confirm the command"}
        elif intent.requires_confirmation:
            self._pending = intent
            result = {"status": "waiting", "mission_id": None, "result": f"Confirm sensitive command: {intent.transcript}"}
        elif self._pending and turn.transcript.casefold().strip(" .!") in {"yes", "confirm"}:
            pending, self._pending = self._pending, None
            result = await self.router.route(VoiceIntent(pending.type, pending.transcript, pending.goal,
                pending.constraints, pending.urgency, False, pending.confidence))
        else:
            result = await self.router.route(intent)
        self.session.active_mission = result.get("mission_id"); self.session.status = VoiceSessionStatus.WAITING if result["status"] == "waiting" else VoiceSessionStatus.LISTENING
        record = {"session_id": self.session.session_id, "transcript_id": turn.transcript_id,
                  "timestamp": turn.timestamp.isoformat(), "transcript": turn.transcript,
                  "intent": intent.type.value, "confidence": turn.confidence, **result}
        self.history.append(record); self.history[:] = self.history[-self.config.context_limit:]
        self.store.append(record, include_transcript=self.config.store_transcripts)
        event_record = dict(record)
        if not self.config.store_transcripts: event_record["transcript"] = "[NOT STORED]"
        await self.events.publish(AutonomousEvent(EventType.VOICE_COMMAND, result.get("mission_id"), event_record))

    async def _connect_with_backoff(self) -> str | None:
        error = None
        for attempt in range(self.config.reconnect_limit + 1):
            try: return await self.transport.connect(self._on_turn, self._on_error)
            except Exception as caught:
                error = caught
                if attempt < self.config.reconnect_limit:
                    self.reconnects += 1
                    await asyncio.sleep(min(2 ** attempt, 8))
        raise ConnectionError("AssemblyAI connection failed") from error

    def snapshot(self) -> dict[str, object]:
        session = self.session
        finalized = [item for item in self.history if "confidence" in item]
        successful = sum(item.get("status") in {"accepted", "completed"} for item in finalized)
        return {"status": session.status.value if session else "idle", "connection": session.connection_status if session else "disconnected",
                "session_id": session.session_id if session else None, "assemblyai_session_id": session.assemblyai_session_id if session else None,
                "microphone": session.microphone if session else "default", "current_transcript": session.current_transcript if session else "",
                "final_transcript": session.last_final_transcript if session else "", "active_mission": session.active_mission if session else None,
                "error": session.error_state if session else None, "history": list(self.history), "model": self.config.model,
                "sample_rate": self.config.sample_rate, "mode": self.config.mode.value,
                "analytics": {"sessions": 1 if session else 0, "commands": len(finalized),
                              "successful_commands": successful, "failed_commands": len(finalized) - successful,
                              "average_confidence": (sum(float(item["confidence"]) for item in finalized) / len(finalized)) if finalized else None,
                              "reconnects": self.reconnects}}
