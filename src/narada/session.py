class NaradaSession:
    id: str

    def __init__(self, *, id: str) -> None:
        self.id = id

    def __str__(self) -> str:
        return f"NaradaSession(id={self.id})"


_EXTENSION_MISSING_INDICATOR_SELECTOR = "#narada-extension-missing"
_SESSION_ID_SELECTOR = "#narada-session-id"
_INITIAL_URL = "https://app.narada.ai/initialize"
