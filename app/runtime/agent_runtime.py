"""The central stateful orchestrator; chatbot websites provide all reasoning."""
from __future__ import annotations

import time
import asyncio
from contextlib import suppress
from pathlib import Path
from datetime import datetime, timezone

from app.browser.browser_manager import BrowserManager
from app.browser.page_observer import Observation, observe_page
from app.computer.screenshot import ScreenshotRecorder
from app.extraction.response_extractor import validate_response
from app.extraction.clipboard_extractor import ClipboardExtractor
from app.extraction.fallback_extractor import ResponseFallbackExtractor
from app.computer.ocr import OcrReader
from app.memory.models import MemoryRecord
from app.memory.memory_manager import MemoryManager
from app.memory.sqlite_memory import SQLiteMemory
from app.prompts.prompt_manager import PromptManager
from app.providers.registry import ProviderRegistry
from app.runtime.action_manager import ActionManager
from app.runtime.recovery_manager import RecoveryManager
from app.runtime.state_manager import RuntimeState, StateManager
from app.safety.emergency_stop import EmergencyStop
from app.safety.pause import PauseController
from app.safety.intervention import UserInterventionGate
from app.providers.base_provider import UserInterventionRequired
from app.tasks.task import Task


class TaskDurationExceeded(TimeoutError):
    """The configured task time budget elapsed."""


class AgentRuntime:
    def __init__(self, browser: BrowserManager, providers: ProviderRegistry, prompts: PromptManager,
                 memory: SQLiteMemory, max_retries: int, max_actions: int = 100,
                 max_task_minutes: int = 30, emergency_stop: EmergencyStop | None = None,
                 screenshots: ScreenshotRecorder | None = None, pause: PauseController | None = None,
                 fallback_extractor: ResponseFallbackExtractor | None = None,
                 intervention: UserInterventionGate | None = None) -> None:
        self.browser, self.providers, self.prompts, self.memory = browser, providers, prompts, memory
        self.state = StateManager()
        self.recovery = RecoveryManager(max_retries)
        self.actions = ActionManager(max_actions)
        self.max_task_seconds = max_task_minutes * 60
        self.emergency_stop = emergency_stop or EmergencyStop()
        self.screenshots = screenshots
        self.memory_context = MemoryManager(memory)
        self.pause = pause or PauseController()
        self.fallback_extractor = fallback_extractor or ResponseFallbackExtractor(ClipboardExtractor(), OcrReader())
        self.intervention = intervention or UserInterventionGate()

    async def run(self, task: Task) -> str:
        self.actions.count = 0
        self.emergency_stop.clear()
        self.pause.resume()
        started = time.monotonic()
        self.state.transition(RuntimeState.INITIALIZING)
        await self._act("start browser", self.browser.start, started)
        self.state.transition(RuntimeState.PLANNING)
        results: list[tuple[str, str]] = []
        try:
            for provider_name in task.providers:
                if results:
                    self.state.transition(RuntimeState.SWITCHING_PROVIDER)
                response = await self._run_provider(
                    task, provider_name, task.prompt_profile or task.category, results, started,
                    final_result=not task.synthesis and provider_name == task.providers[-1],
                )
                results.append((provider_name, response))
            if task.synthesis and len(results) > 1 and task.synthesis_provider:
                self.state.transition(RuntimeState.SYNTHESIZING)
                final = await self._run_provider(task, task.synthesis_provider, "synthesis", results, started,
                                                 final_result=True)
            else:
                final = "\n\n".join(f"## {name}\n\n{response}" for name, response in results)
        except Exception:
            if self.emergency_stop.triggered:
                self.state.transition(RuntimeState.STOPPED)
            elif self.state.state is not RuntimeState.FAILED:
                self.state.transition(RuntimeState.FAILED)
            raise
        self.state.transition(RuntimeState.COMPLETED)
        return final

    async def _run_provider(self, task: Task, provider_name: str, profile: str,
                            previous: list[tuple[str, str]], task_started: float,
                            final_result: bool = False) -> str:
        provider = self.providers.get(provider_name)
        previous_results = "\n\n".join(f"[{name}]\n{text}" for name, text in previous)
        local_context = self.memory_context.relevant_context(task.objective) if not previous else ""
        prompt = self.prompts.render(profile, task=task.objective, provider=provider_name,
                                     previous_results=previous_results, context=local_context, requirements="")
        started = time.monotonic()
        try:
            self.state.transition(RuntimeState.OPENING_BROWSER)
            await self._act(f"open {provider_name}", provider.open, task_started)
            self.state.transition(RuntimeState.VERIFYING_PAGE)
            await self._verify_provider(provider_name, provider, task_started)
            await self._observe(provider_name, provider)
            self.state.transition(RuntimeState.FOCUSING_INPUT)
            await self._act(f"focus {provider_name} prompt input", provider.start_conversation, task_started)
            self.state.transition(RuntimeState.SENDING_PROMPT)
            await self._act(f"send {provider_name} prompt", lambda: provider.send_prompt(prompt), task_started)
            self.state.transition(RuntimeState.WAITING_RESPONSE)
            await self._act(f"wait for {provider_name} response", provider.wait_for_response, task_started)
            self.state.transition(RuntimeState.EXTRACTING_RESPONSE)
            response = await self._extract_response(provider_name, provider, task_started)
            self.state.transition(RuntimeState.VALIDATING_RESPONSE)
            response = validate_response(response)
            screenshot_path = await self._capture(provider_name, provider, "response")
            self.state.transition(RuntimeState.STORING_RESULT)
            self.memory.store(MemoryRecord(task.id, datetime.now(timezone.utc), provider_name, prompt, response,
                "completed", time.monotonic() - started, task.strategy, final_result=final_result,
                screenshot_path=screenshot_path))
            return response
        except Exception as error:
            screenshot_path = await self._capture(provider_name, provider, "failure")
            self.memory.store(MemoryRecord(task.id, datetime.now(timezone.utc), provider_name, prompt, "", "failed",
                time.monotonic() - started, task.strategy, final_result=final_result, error=str(error),
                screenshot_path=screenshot_path))
            raise

    async def _act(self, description: str, operation, task_started: float) -> object:
        self.emergency_stop.raise_if_triggered()
        await self.pause.wait_until_resumed()
        deadline = task_started + self.max_task_seconds
        if time.monotonic() >= deadline:
            raise TaskDurationExceeded(f"Task exceeded {self.max_task_seconds / 60:g} minute limit")
        self.actions.record(description)
        active_operation = asyncio.create_task(operation())
        while not active_operation.done():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                await self._cancel_operation(active_operation)
                raise TaskDurationExceeded(f"Task exceeded {self.max_task_seconds / 60:g} minute limit")
            _, pending = await asyncio.wait({active_operation}, timeout=min(0.2, remaining))
            if not pending:
                break
            if self.emergency_stop.triggered:
                await self._cancel_operation(active_operation)
                self.emergency_stop.raise_if_triggered()
        return await active_operation

    async def _cancel_operation(self, operation: asyncio.Task[object]) -> None:
        operation.cancel()
        with suppress(asyncio.CancelledError):
            await operation

    async def _extract_response(self, provider_name: str, provider, task_started: float) -> str:
        try:
            return await self._act(f"extract {provider_name} response",
                lambda: self.recovery.run(provider.extract_response,
                                          lambda: self._recover_response(provider_name, provider)), task_started)
        except Exception:
            try:
                return await self._act(f"extract {provider_name} response from clipboard",
                    lambda: self.fallback_extractor.extract_from_clipboard(provider), task_started)
            except Exception as clipboard_error:
                screenshot = await self._capture(provider_name, provider, "ocr-fallback")
                if screenshot:
                    try:
                        return self.fallback_extractor.extract_from_ocr(Path(screenshot))
                    except Exception as ocr_error:
                        raise RuntimeError("DOM, clipboard, and OCR response extraction failed") from ocr_error
                raise RuntimeError("DOM and clipboard response extraction failed") from clipboard_error

    async def _recover_response(self, provider_name: str, provider) -> None:
        """Reload, observe, and return to extraction after a bounded DOM retry."""
        self.state.transition(RuntimeState.RECOVERING)
        self.actions.record(f"recover {provider_name} response")
        await provider.recover()
        await self._observe(provider_name, provider)
        self.state.transition(RuntimeState.EXTRACTING_RESPONSE)

    async def _verify_provider(self, provider_name: str, provider, task_started: float) -> None:
        while True:
            try:
                await self._act(f"verify {provider_name}", provider.verify_page, task_started)
                return
            except UserInterventionRequired as error:
                self.state.transition(RuntimeState.WAITING_USER_INTERVENTION)
                await self.intervention.wait(f"{provider_name.title()}: {error}", self.emergency_stop)
                self.state.transition(RuntimeState.VERIFYING_PAGE)

    async def _observe(self, provider_name: str, provider) -> Observation | None:
        """Refresh a page snapshot after navigation; observation failure never drives a blind action."""
        if provider.page is None:
            return None
        self.actions.record(f"observe {provider_name}")
        return await observe_page(provider.page)

    async def _capture(self, provider_name: str, provider, label: str) -> str | None:
        """Best-effort evidence capture that does not replace the original provider error."""
        if self.screenshots is None or provider.page is None:
            return None
        try:
            self.actions.record(f"capture {provider_name} {label}")
            return str(await self.screenshots.capture(provider.page, f"{provider_name}-{label}"))
        except Exception:
            return None
