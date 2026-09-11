"""Provider contract and DOM-first base implementation."""
from __future__ import annotations

import asyncio
from abc import ABC
from dataclasses import dataclass
from urllib.parse import urlsplit

from playwright.async_api import Locator, Page

from app.browser.browser_manager import BrowserManager


class ProviderError(RuntimeError):
    """Raised when a provider's normal webpage cannot be used safely."""


class UserInterventionRequired(ProviderError):
    """Login, CAPTCHA, or similar security challenge requires the owner."""


@dataclass(frozen=True, slots=True)
class ProviderSelectors:
    input: tuple[str, ...]
    response: tuple[str, ...]
    stop: tuple[str, ...]
    copy: tuple[str, ...] = ()


class ChatbotProvider(ABC):
    name: str
    composer_wait_seconds = 15.0

    def __init__(self, browser: BrowserManager, url: str, selectors: ProviderSelectors) -> None:
        self.browser, self.url, self.selectors = browser, url, selectors
        self.page: Page | None = None
        self._response_count_before_submit = 0
        self._response_counts_before_submit: dict[str, int] = {}

    async def open(self) -> None:
        self.page = await self.browser.page_for(self.url)

    async def verify_page(self) -> None:
        page = self._require_page()
        body = (await page.locator("body").inner_text()).lower()
        if any(marker in body for marker in ("captcha", "verify you are human", "two-factor", "2fa")):
            raise UserInterventionRequired("Security challenge detected; complete it manually, then retry.")
        if not await self._wait_for_input():
            # Re-read after the bounded wait: login shells and client-rendered
            # composers frequently replace the initial DOM after navigation.
            body = (await page.locator("body").inner_text()).lower()
            if any(marker in body for marker in ("log in", "sign in", "login")):
                raise UserInterventionRequired("Login is required. Sign in manually in the persistent Chrome window.")
            raise ProviderError(await self._input_not_found_message())

    async def start_conversation(self) -> None:
        """Focus the verified composer before the runtime sends a prompt.

        Keeping this separate from :meth:`send_prompt` gives the runtime an
        observable action boundary: a page can be valid while its composer is
        covered by an onboarding dialog or otherwise not focusable.
        """
        field = await self._wait_for_input(timeout_seconds=3)
        if field is None:
            raise ProviderError(await self._input_not_found_message("disappeared before it could be focused"))
        await field.click()

    async def send_prompt(self, prompt: str) -> None:
        field = await self._wait_for_input(timeout_seconds=3)
        if field is None:
            raise ProviderError(await self._input_not_found_message("disappeared before submission"))
        self._response_counts_before_submit = await self._response_counts()
        self._response_count_before_submit = sum(self._response_counts_before_submit.values())
        await field.click()
        await field.fill(prompt)
        await field.press("Enter")

    async def wait_for_response(self, timeout_seconds: int = 180) -> None:
        response = await self._first_visible(self.selectors.response)
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while response is None or await self._response_count() <= self._response_count_before_submit:
            if asyncio.get_running_loop().time() >= deadline:
                raise ProviderError("No new response container appeared")
            await asyncio.sleep(0.5)
            response = await self._first_visible(self.selectors.response)
        while not await self.is_response_complete():
            if asyncio.get_running_loop().time() >= deadline:
                raise ProviderError(f"{self.name} response timed out")
            await asyncio.sleep(1)

    async def extract_response(self) -> str:
        response = await self._latest_response()
        text = (await response.inner_text()).strip() if response else ""
        if not text:
            raise ProviderError("Extracted response was empty")
        return text

    async def is_response_complete(self) -> bool:
        page = self._require_page()
        for selector in self.selectors.stop:
            locator = page.locator(selector)
            if await locator.count() and await locator.first.is_visible():
                return False
        return True

    async def recover(self) -> None:
        page = self._require_page()
        await page.reload(wait_until="domcontentloaded")
        await self.verify_page()

    async def copy_latest_response(self) -> None:
        """Click a provider-declared response Copy control for clipboard fallback."""
        control = await self._first_visible(self.selectors.copy)
        if control is None:
            raise ProviderError(f"{self.name} does not expose a visible response copy control")
        await control.click()

    def _require_page(self) -> Page:
        if self.page is None:
            raise ProviderError("Provider must be opened before use")
        return self.page

    async def _first_visible(self, selectors: tuple[str, ...]) -> Locator | None:
        page = self._require_page()
        for selector in selectors:
            locator = page.locator(selector)
            # Provider applications often retain a hidden mobile/old composer
            # before the active one. Checking only ``locator.first`` therefore
            # produces a false "input not found" even though another match is
            # visible. Prefer the first visible and enabled candidate.
            for index in range(await locator.count()):
                candidate = locator.nth(index)
                if await candidate.is_visible() and await candidate.is_enabled():
                    return candidate
        return None

    async def _wait_for_input(self, timeout_seconds: float | None = None) -> Locator | None:
        """Wait for a client-rendered prompt composer without waiting forever."""
        timeout = self.composer_wait_seconds if timeout_seconds is None else timeout_seconds
        deadline = asyncio.get_running_loop().time() + timeout
        while True:
            field = await self._first_visible(self.selectors.input)
            if field is not None:
                return field
            if asyncio.get_running_loop().time() >= deadline:
                return None
            await asyncio.sleep(0.2)

    async def _input_not_found_message(self, reason: str = "was not found") -> str:
        """Return actionable, credential-safe diagnostics for changed provider UIs."""
        page = self._require_page()
        host = urlsplit(page.url).hostname or "unknown host"
        title = (await page.title()).strip()[:120] or "untitled page"
        visible = await page.locator(
            "textarea, [contenteditable='true'], [role='textbox'], input[type='text']"
        ).count()
        return (f"{self.name} prompt input {reason} after a bounded wait "
                f"(page={host!r}, title={title!r}, editable_candidates={visible}). "
                "Complete any visible login/onboarding dialog, then retry; if the page is ready, "
                "the provider composer selectors may need updating.")

    async def _response_count(self) -> int:
        return sum((await self._response_counts()).values())

    async def _response_counts(self) -> dict[str, int]:
        """Return per-selector counts so extraction can identify a newly added response."""
        page = self._require_page()
        return {selector: await page.locator(selector).count() for selector in self.selectors.response}

    async def _latest_response(self) -> Locator | None:
        """Return the response added after the current prompt, not prior chat history.

        Provider selectors can match several historic assistant turns.  The
        count snapshot captured before submission lets us select the newest
        node for the first selector that gained a visible response.
        """
        page = self._require_page()
        counts = await self._response_counts()
        for selector in self.selectors.response:
            count = counts[selector]
            if count <= self._response_counts_before_submit.get(selector, 0):
                continue
            response = page.locator(selector).nth(count - 1)
            if await response.is_visible():
                return response
        # A DOM change can make a pre-submit snapshot unavailable (for example,
        # after a provider reload).  Fall back to the last visible response.
        for selector in self.selectors.response:
            locator = page.locator(selector)
            for index in range((await locator.count()) - 1, -1, -1):
                response = locator.nth(index)
                if await response.is_visible():
                    return response
        return None
