from __future__ import annotations

from typing import Any


class Narada:
    def __init__(self, *, api_key: str | None = None) -> None:
        pass

    async def __aenter__(self) -> Narada:
        return self

    async def __aexit__(self, *_args: Any) -> None:
        pass
