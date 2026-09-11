"""Chatbot-planned, user-confirmed browser workflows for the interactive CLI."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

from app.providers.base_provider import ChatbotProvider


class UserPrompt(Protocol):
    def ask(self, question: str) -> str | None: ...
    def confirm(self, message: str) -> bool: ...


class PopupUserPrompt:
    """Use native dialogs when available and fall back to the terminal."""
    def ask(self, question: str) -> str | None:
        import tkinter as tk
        from tkinter import simpledialog
        try:
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            answer = simpledialog.askstring("Brainless Agent needs information", question, parent=root)
            root.destroy()
            return answer
        except tk.TclError:
            answer = input(f"\n{question}\n> ").strip()
            return answer or None

    def confirm(self, message: str) -> bool:
        import tkinter as tk
        from tkinter import messagebox
        try:
            root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
            approved = messagebox.askyesno("Confirm external action", message, parent=root)
            root.destroy()
            return approved
        except tk.TclError:
            return input(f"\n{message} [y/N] ").strip().casefold() in {"y", "yes"}


@dataclass(frozen=True, slots=True)
class BrowserStep:
    action: str
    target: str = ""
    value: str = ""
    url: str = ""
    external_effect: bool = False


@dataclass(frozen=True, slots=True)
class GuidedPlan:
    summary: str
    questions: tuple[str, ...]
    steps: tuple[BrowserStep, ...]


class WorkflowStore:
    """Store successful structural steps without message bodies or other entered values."""
    def __init__(self, path: Path) -> None:
        self.path = path

    def recent(self, limit: int = 5) -> list[dict[str, object]]:
        if not self.path.exists(): return []
        try: records = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError): return []
        return records[-limit:] if isinstance(records, list) else []

    def save(self, objective: str, plan: GuidedPlan) -> None:
        records = self.recent(100)
        records.append({"objective_terms": sorted(set(re.findall(r"[a-z]+", objective.casefold()))),
            "summary": plan.summary[:200], "steps": [
                {"action": step.action, "target": step.target[:100],
                 "host": urlsplit(step.url).hostname or "", "external_effect": step.external_effect}
                for step in plan.steps]})
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(records[-100:], indent=2, sort_keys=True), encoding="utf-8")


class GuidedBrowserWorkflow:
    """Ask a chatbot for bounded semantic steps, clarify, then execute with approval."""
    ALLOWED_ACTIONS = {"navigate", "fill", "click"}

    def __init__(self, provider: ChatbotProvider, browser, store: WorkflowStore,
                 user_prompt: UserPrompt | None = None) -> None:
        self.provider, self.browser, self.store = provider, browser, store
        self.user_prompt = user_prompt or PopupUserPrompt()

    @staticmethod
    def supports(objective: str) -> bool:
        text = objective.casefold()
        return any(phrase in text for phrase in ("send email", "send an email", "send mail", "gmail"))

    async def run(self, objective: str) -> str:
        answers: list[dict[str, str]] = []
        plan = await self._plan(objective, answers)
        for _ in range(3):
            if not plan.questions: break
            for question in plan.questions:
                answer = self.user_prompt.ask(question)
                if not answer: return "Cancelled: required information was not provided."
                answers.append({"question": question, "answer": answer})
            plan = await self._plan(objective, answers)
        if plan.questions: return "Cancelled: the task still has unresolved required information."
        await self.browser.start()
        page = None
        for step in plan.steps:
            if step.action == "navigate":
                self._validate_url(step.url)
                page = await self.browser.page_for(step.url)
                continue
            if page is None: raise ValueError("The plan must navigate before interacting with a page")
            if step.external_effect and not self.user_prompt.confirm(
                    f"Allow this external action?\n\n{plan.summary}\n\nAction: {step.action} {step.target}"):
                return "Cancelled: final external action was not approved."
            locator = page.get_by_label(step.target, exact=False).first
            if not await locator.count(): locator = page.get_by_role("button", name=step.target, exact=False).first
            if not await locator.count(): locator = page.get_by_text(step.target, exact=False).first
            if not await locator.count(): raise RuntimeError(f"Could not find the requested control: {step.target}")
            if step.action == "fill": await locator.fill(step.value)
            elif step.action == "click": await locator.click()
        self.store.save(objective, plan)
        return f"Completed guided browser workflow: {plan.summary}"

    async def _plan(self, objective: str, answers: list[dict[str, str]]) -> GuidedPlan:
        prompt = ("Create a browser automation plan for the user's task. Ask for every missing required value. "
            "Return ONLY JSON: {summary, questions:[string], steps:[{action,target,value,url,external_effect}]}. "
            "Allowed actions are navigate, fill, click. Use semantic visible labels, never CSS/XPath or coordinates. "
            "For Gmail navigate to https://mail.google.com/, fill To and Subject, fill Message Body, then click Send "
            "with external_effect=true. Never invent recipient, dates, reason, body, or signature.\n"
            f"USER_TASK={objective}\nUSER_ANSWERS={json.dumps(answers)}\n"
            f"PRIOR_VERIFIED_STRUCTURES={json.dumps(self.store.recent())}")
        await self.provider.open(); await self.provider.verify_page(); await self.provider.start_conversation()
        await self.provider.send_prompt(prompt); await self.provider.wait_for_response()
        return self.parse(await self.provider.extract_response())

    @classmethod
    def parse(cls, response: str) -> GuidedPlan:
        cleaned = response.strip()
        if cleaned.startswith("```"): cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", cleaned)
        data = json.loads(cleaned)
        questions = tuple(str(item).strip() for item in data.get("questions", ()) if str(item).strip())
        steps = tuple(BrowserStep(str(item.get("action", "")), str(item.get("target", "")),
            str(item.get("value", "")), str(item.get("url", "")), bool(item.get("external_effect", False)))
            for item in data.get("steps", ()))
        if any(step.action not in cls.ALLOWED_ACTIONS for step in steps):
            raise ValueError("Chatbot proposed an unsupported browser action")
        if not questions and (not steps or not any(step.action == "navigate" for step in steps)):
            raise ValueError("Chatbot did not provide an executable browser plan")
        return GuidedPlan(str(data.get("summary", "Guided browser task"))[:500], questions, steps)

    @staticmethod
    def _validate_url(url: str) -> None:
        parsed = urlsplit(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise ValueError("Guided navigation requires an absolute HTTPS URL")
