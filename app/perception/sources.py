"""Provider-independent perception sources; none can execute computer actions."""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Protocol
from hashlib import sha256
from itertools import islice

from app.perception.models import PerceptionObservation, UIElement


class PerceptionSource(Protocol):
    name: str
    capabilities: frozenset[str]

    async def observe(self) -> PerceptionObservation: ...


class ComputerControllerSource:
    """Adapts the existing controller observation API without granting execute access."""
    name = "computer_controller"
    capabilities = frozenset({"screen.read", "window.read", "browser.read", "process.read"})

    def __init__(self, controller) -> None:
        self._observe = controller.observe

    async def observe(self) -> PerceptionObservation:
        state = await self._observe()
        elements = tuple(UIElement(role="text", text=text, label=text, source="controller",
                                   confidence=.7, element_id=sha256(
                                       f"controller:text:{text}".encode()).hexdigest()[:24])
                         for text in state.visible_ui if text)
        browser = {key: value for key, value in {
            "url": state.browser_url, "title": state.browser_title,
        }.items() if value is not None}
        return PerceptionObservation(
            source=self.name, source_kind="controller", timestamp=state.timestamp,
            active_application=state.active_application, active_window=state.active_window,
            screen_dimensions=state.screen_size, screenshot_reference=state.screenshot_reference,
            elements=elements, browser_state=browser, recent_actions=state.recent_actions,
            metadata={"errors": list(state.errors)}, confidence=1.0,
        )


class BrowserDOMSource:
    """Reads semantic DOM controls from an already-authorized Playwright page."""
    name = "browser_dom"
    capabilities = frozenset({"browser.read", "browser.dom.read"})

    def __init__(self, page_provider: Callable[[], Awaitable[object]]) -> None:
        self._page_provider = page_provider

    async def observe(self) -> PerceptionObservation:
        page = await self._page_provider()
        records = await page.locator("a,button,input,textarea,select,[role],[aria-label]").evaluate_all(
            """nodes => nodes.slice(0, 500).map((node, index) => {
              const r=node.getBoundingClientRect(); return {index, tag:node.tagName.toLowerCase(),
              role:node.getAttribute('role'), label:node.getAttribute('aria-label'),
              text:(node.innerText||node.value||'').slice(0,300), disabled:!!node.disabled,
              bounds:[Math.round(r.x),Math.round(r.y),Math.round(r.width),Math.round(r.height)]}; })""")
        elements = tuple(UIElement(
            role=item.get("role") or {"a": "link", "input": "textbox", "textarea": "textbox"}.get(
                item["tag"], item["tag"]), label=item.get("label") or "", text=item.get("text") or "",
            bounds=tuple(item["bounds"]), enabled=not item["disabled"],
            visible=item["bounds"][2] > 0 and item["bounds"][3] > 0,
            clickable=item["tag"] in {"a", "button"} or bool(item.get("role") in {"button", "link", "tab"}),
            editable=item["tag"] in {"input", "textarea", "select"}, source="dom", confidence=.95,
            element_id=sha256(f"dom:{item['tag']}:{item['index']}:{item.get('label')}:{item.get('text')}".encode()).hexdigest()[:24]
        ) for item in records)
        return PerceptionObservation(self.name, "dom", active_application="browser",
                                     active_window=await page.title(), elements=elements,
                                     browser_state={"url": page.url, "title": await page.title()}, confidence=.95)


class FilesystemPerceptionSource:
    """Reports metadata-only changes under an explicitly scoped directory."""
    name = "filesystem"
    capabilities = frozenset({"filesystem.read"})

    def __init__(self, root: Path, *, limit: int = 500) -> None:
        self.root, self.limit, self._previous = root.resolve(), limit, {}

    async def observe(self) -> PerceptionObservation:
        paths = (path for path in islice(self.root.iterdir(), self.limit) if path.is_file())
        current = {str(path.relative_to(self.root)): (stat.st_mtime_ns, stat.st_size)
                   for path in paths for stat in (path.stat(),)}
        changes = tuple({"path": path, "change": "created" if path not in self._previous else "modified"}
                        for path, metadata in current.items()
                        if self._previous.get(path) != metadata)
        changes += tuple({"path": path, "change": "deleted"} for path in self._previous.keys() - current.keys())
        self._previous = current
        return PerceptionObservation(self.name, "filesystem", filesystem_changes=changes,
                                     confidence=1.0, metadata={"file_count": len(current)})
