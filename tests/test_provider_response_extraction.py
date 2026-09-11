import asyncio

from app.providers.base_provider import ChatbotProvider, ProviderSelectors


class FakeResponseLocator:
    def __init__(self, responses: list[str], index: int | None = None) -> None:
        self.responses = responses
        self.index = index

    async def count(self) -> int:
        return len(self.responses)

    def nth(self, index: int) -> "FakeResponseLocator":
        return FakeResponseLocator(self.responses, index)

    async def is_visible(self) -> bool:
        return self.index is not None and bool(self.responses[self.index])

    async def is_enabled(self) -> bool:
        return True

    async def inner_text(self) -> str:
        assert self.index is not None
        return self.responses[self.index]


class FakeResponsePage:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses

    def locator(self, selector: str) -> FakeResponseLocator:
        assert selector == "assistant"
        return FakeResponseLocator(self.responses)


class FakeStopLocator:
    def __init__(self, visible: bool) -> None:
        self.first = self
        self.visible = visible

    async def count(self) -> int:
        return 1

    async def is_visible(self) -> bool:
        return self.visible


class FakeStopPage:
    def __init__(self, visible: dict[str, bool]) -> None:
        self.visible = visible

    def locator(self, selector: str) -> FakeStopLocator:
        return FakeStopLocator(self.visible[selector])


def test_provider_extracts_the_response_added_after_submission() -> None:
    async def scenario() -> None:
        page = FakeResponsePage(["Earlier assistant answer"])
        provider = ChatbotProvider(None, "https://example.invalid", ProviderSelectors((), ("assistant",), ()))
        provider.page = page
        provider._response_counts_before_submit = await provider._response_counts()
        page.responses.append("Newest assistant answer")

        assert await provider.extract_response() == "Newest assistant answer"

    asyncio.run(scenario())


def test_provider_checks_async_stop_controls_without_using_async_generator_any() -> None:
    async def scenario() -> None:
        provider = ChatbotProvider(
            None, "https://example.invalid", ProviderSelectors((), (), ("hidden", "visible"))
        )
        provider.page = FakeStopPage({"hidden": False, "visible": True})
        assert await provider.is_response_complete() is False

        provider.page = FakeStopPage({"hidden": False, "visible": False})
        assert await provider.is_response_complete() is True

    asyncio.run(scenario())
