from __future__ import annotations

import os
from typing import Any


class Narada:
    def __init__(self, *, api_key: str | None = None) -> None:
        self._api_key = api_key or os.environ["NARADA_API_KEY"]

    async def __aenter__(self) -> Narada:
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass
