class AIMessagerError(Exception):
    """Base class for all ai-messager errors."""


class NotLoggedIn(AIMessagerError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            f"Provider {provider!r} is not logged in. Run: ai-messager login {provider}"
        )
        self.provider = provider


class CloudflareChallenge(AIMessagerError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            f"Cloudflare challenge for {provider!r}. Solve the checkbox once in "
            "a visible browser — the cf_clearance cookie then unlocks the next "
            "~30-60 minutes of automated calls. Quickest path: "
            f"`AI_MESSAGER_SERVE_HEADLESS=false` before starting the MCP host, "
            f"or run `ai-messager login {provider}` to open a visible window."
        )
        self.provider = provider


class ChatNotFound(AIMessagerError):
    def __init__(self, chat_url: str) -> None:
        super().__init__(f"Chat URL not reachable or deleted: {chat_url}")
        self.chat_url = chat_url


class LLMResponseTimeout(AIMessagerError):
    def __init__(
        self, provider: str, timeout_s: int, *, stage: str = "response"
    ) -> None:
        super().__init__(f"{provider!r} timed out after {timeout_s}s (stage={stage}).")
        self.provider = provider
        self.timeout_s = timeout_s
        self.stage = stage


class ProviderNotRegistered(AIMessagerError):
    def __init__(self, provider: str, known: list[str]) -> None:
        super().__init__(
            f"Unknown provider {provider!r}. Known providers: {', '.join(known) or '(none)'}."
        )
        self.provider = provider
