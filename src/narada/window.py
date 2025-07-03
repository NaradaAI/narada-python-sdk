from typing import Any

import aiohttp


class BrowserWindow:
    _api_key: str
    _id: str

    def __init__(self, *, api_key: str, id: str) -> None:
        self._api_key = api_key
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    def __str__(self) -> str:
        return f"BrowserWindow(id={self.id})"

    async def dispatch_request(
        self,
        *,
        prompt: str,
        clear_chat: bool | None = None,
        timeout: int = 60,
    ) -> dict[str, Any]:
        headers = {"x-api-key": self._api_key}

        body: dict[str, Any] = {
            "prompt": prompt,
            # TODO: Use this once the server supports it.
            # "browserWindowId": self.id,
            "sessionId": self.id,
            # TODO: Make this poll on the frontend.
            "wait": True,
        }
        if clear_chat is not None:
            body["clearChat"] = clear_chat

        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.narada.ai/fast/v2/remote-dispatch",
                headers=headers,
                json=body,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
