import asyncio

from app.providers.base_provider import ChatbotProvider, ProviderSelectors
from app.providers.chatgpt import ChatGPTProvider
from app.providers.claude import ClaudeProvider
from app.providers.gemini import GeminiProvider


class FakeCandidate:
    def __init__(self, visible: bool, enabled: bool = True) -> None:
        self.visible = visible
        self.enabled = enabled

    async def is_visible(self) -> bool:
        return self.visible

    async def is_enabled(self) -> bool:
        return self.enabled


class FakeCollection:
    def __init__(self, candidates: list[FakeCandidate]) -> None:
        self.candidates = candidates

    async def count(self) -> int:
        return len(self.candidates)

    def nth(self, index: int) -> FakeCandidate:
        return self.candidates[index]


class FakePage:
    def __init__(self, candidates: list[FakeCandidate]) -> None:
        self.candidates = candidates

    def locator(self, selector: str) -> FakeCollection:
        assert selector == "composer"
        return FakeCollection(self.candidates)


def test_input_discovery_skips_hidden_and_disabled_duplicate_composers() -> None:
    async def scenario() -> None:
        hidden = FakeCandidate(False)
        disabled = FakeCandidate(True, False)
        active = FakeCandidate(True, True)
        provider = ChatbotProvider(None, "https://example.invalid", ProviderSelectors(("composer",), (), ()))
        provider.page = FakePage([hidden, disabled, active])

        assert await provider._first_visible(provider.selectors.input) is active

    asyncio.run(scenario())


def test_provider_selector_catalogs_cover_current_rich_text_composers() -> None:
    chatgpt = ChatGPTProvider(None, "https://chatgpt.com/")
    gemini = GeminiProvider(None, "https://gemini.google.com/")
    claude = ClaudeProvider(None, "https://claude.ai/")

    assert "[data-testid='composer-text-input']" in chatgpt.selectors.input
    assert "rich-textarea .ql-editor[contenteditable='true']" in gemini.selectors.input
    assert "[data-testid='chat-input']" in claude.selectors.input
