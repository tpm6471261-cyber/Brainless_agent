"""Playwright-backed persistent Chrome session manager."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path
from urllib.parse import urlsplit

from playwright.async_api import BrowserContext, Page, Playwright, async_playwright

from app.config.settings import BrowserSettings

LOGGER = logging.getLogger(__name__)


class BrowserManager:
    """Owns one persistent user-visible browser context; it never handles credentials."""

    def __init__(self, settings: BrowserSettings, repository_root: Path) -> None:
        self._settings = settings
        self._repository_root = repository_root
        self._playwright: Playwright | None = None
        self._context: BrowserContext | None = None
        self._conversation_pages: dict[str, Page] = {}
        self._conversation_file = repository_root / "data/conversation-urls.json"

    async def start(self) -> None:
        if self._context:
            return
        profile_dir = self._settings.profile_dir
        if not profile_dir.is_absolute():
            profile_dir = self._repository_root / profile_dir
        profile_dir.mkdir(parents=True, exist_ok=True)
        self._playwright = await async_playwright().start()
        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(profile_dir), channel=self._settings.channel,
                headless=self._settings.headless,
                viewport={"width": 1440, "height": 1000},
            )
        except Exception:
            await self._playwright.stop()
            self._playwright = None
            raise
        self._context.set_default_timeout(self._settings.navigation_timeout_seconds * 1000)
        LOGGER.info("Persistent Chrome session started: %s", profile_dir)

    async def page_for(self, url: str) -> Page:
        if not self._context:
            raise RuntimeError("BrowserManager.start() must be called first")
        page = next((page for page in self._context.pages if page.url.startswith(url)), None)
        if page is None:
            page = await self._context.new_page()
        await page.bring_to_front()
        if not page.url.startswith(url):
            await page.goto(url, wait_until="domcontentloaded")
        return page

    async def conversation_page(self, provider: str, prompt: str, base_url: str) -> Page:
        """Return the dedicated, persistent tab for one provider/prompt pair.

        A prompt digest avoids writing prompt content to disk.  Saved URLs let a
        later run reopen the same provider conversation, while the in-memory map
        prevents two prompts from accidentally sharing a tab during this run.
        """
        if not self._context:
            raise RuntimeError("BrowserManager.start() must be called first")
        key = self._conversation_key(provider, prompt)
        page = self._conversation_pages.get(key)
        if page is not None and not page.is_closed():
            await page.bring_to_front()
            return page

        saved_url = self._load_conversation_urls().get(key, base_url)
        if not self._same_origin(saved_url, base_url):
            LOGGER.warning("Ignoring invalid saved %s conversation URL", provider)
            saved_url = base_url
        # Persistent Chrome can restore tabs itself. Reattach to an exact saved
        # conversation rather than opening a duplicate; never share a generic
        # provider landing page because each new prompt needs its own tab.
        page = (next((candidate for candidate in self._context.pages
                      if saved_url != base_url and candidate.url == saved_url and not candidate.is_closed()), None)
                or await self._context.new_page())
        self._conversation_pages[key] = page
        await page.goto(saved_url, wait_until="domcontentloaded")
        await page.bring_to_front()
        return page

    def remember_conversation(self, provider: str, prompt: str, url: str, base_url: str) -> None:
        """Persist a provider-owned chat URL without retaining the prompt text."""
        if not self._same_origin(url, base_url):
            LOGGER.warning("Refusing to save off-origin %s conversation URL", provider)
            return
        conversations = self._load_conversation_urls()
        conversations[self._conversation_key(provider, prompt)] = url
        self._conversation_file.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._conversation_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(conversations, indent=2, sort_keys=True), encoding="utf-8")
        temporary.replace(self._conversation_file)

    @staticmethod
    def _conversation_key(provider: str, prompt: str) -> str:
        digest = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        return f"{provider}:{digest}"

    def _load_conversation_urls(self) -> dict[str, str]:
        try:
            value = json.loads(self._conversation_file.read_text(encoding="utf-8"))
            return {str(key): str(url) for key, url in value.items()} if isinstance(value, dict) else {}
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _same_origin(candidate: str, base_url: str) -> bool:
        candidate_parts, base_parts = urlsplit(candidate), urlsplit(base_url)
        return (candidate_parts.scheme, candidate_parts.netloc) == (base_parts.scheme, base_parts.netloc)

    async def close(self) -> None:
        if self._context:
            await self._context.close()
            self._context = None
            self._conversation_pages.clear()
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None
        LOGGER.info("Browser session closed")
