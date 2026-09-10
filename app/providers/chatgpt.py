from app.providers.base_provider import ChatbotProvider, ProviderSelectors


class ChatGPTProvider(ChatbotProvider):
    name = "chatgpt"

    def __init__(self, browser, url: str) -> None:
        super().__init__(browser, url, ProviderSelectors(
            input=("#prompt-textarea", "[data-testid='composer-text-input']",
                   "div.ProseMirror[contenteditable='true']", "textarea[placeholder*='message' i]",
                   "[contenteditable='true'][role='textbox']"),
            response=("[data-message-author-role='assistant']", "article[data-testid*='conversation-turn']"),
            stop=("button[aria-label*='Stop']", "button[data-testid='stop-button']"),
            copy=("button[aria-label='Copy']", "button[data-testid*='copy']"),
        ))
