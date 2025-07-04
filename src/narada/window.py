import asyncio
from typing import Any

import aiohttp
from playwright.async_api import BrowserContext

from narada.config import BrowserConfig
from narada.errors import NaradaTimeoutError


class BrowserWindow:
    _api_key: str
    _config: BrowserConfig
    _context: BrowserContext
    _id: str

    def __init__(
        self, *, api_key: str, config: BrowserConfig, context: BrowserContext, id: str
    ) -> None:
        self._api_key = api_key
        self._config = config
        self._context = context
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    def __str__(self) -> str:
        return f"BrowserWindow(id={self.id})"

    async def reinitialize(self) -> None:
        side_panel_url = f"chrome-extension://{self._config.extension_id}/sidepanel.html?browserWindowId={self._id}"
        side_panel_page = next(
            p for p in self._context.pages if p.url == side_panel_url
        )

        # Refresh the extension side panel, which ensures any inflight Narada operations are
        # canceled.
        await side_panel_page.reload()

    async def dispatch_request(
        self,
        *,
        prompt: str,
        clear_chat: bool | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        headers = {"x-api-key": self._api_key}

        body: dict[str, Any] = {
            "prompt": prompt,
            "browserWindowId": self.id,
            # TODO: Make this poll on the frontend.
            "wait": True,
        }
        if clear_chat is not None:
            body["clearChat"] = clear_chat

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.narada.ai/fast/v2/remote-dispatch",
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    resp.raise_for_status()
                    return await resp.json()
        except asyncio.TimeoutError:
            raise NaradaTimeoutError
