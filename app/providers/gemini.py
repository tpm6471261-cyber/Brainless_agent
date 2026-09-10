from app.providers.base_provider import ChatbotProvider, ProviderSelectors


class GeminiProvider(ChatbotProvider):
    name = "gemini"

    def __init__(self, browser, url: str) -> None:
        super().__init__(browser, url, ProviderSelectors(
            input=("rich-textarea .ql-editor[contenteditable='true']", "rich-textarea textarea",
                   "textarea[aria-label*='prompt' i]", "[aria-label*='prompt' i][contenteditable='true']",
                   "div.ql-editor[contenteditable='true']", "[contenteditable='true'][role='textbox']"),
            response=("message-content", ".model-response-text"),
            stop=("button[aria-label*='Stop']",),
            copy=("button[aria-label*='Copy']",),
        ))
