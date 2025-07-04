import asyncio
import time
from typing import Any

import aiohttp
from playwright.async_api import BrowserContext

from narada.config import BrowserConfig
from narada.errors import NaradaTimeoutError


def create_side_panel_url(config: BrowserConfig, browser_window_id: str) -> str:
    return f"chrome-extension://{config.extension_id}/sidepanel.html?browserWindowId={browser_window_id}"


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
        side_panel_url = create_side_panel_url(self._config, self._id)
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
        generate_gif: bool | None = None,
        timeout: int = 120,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout

        headers = {"x-api-key": self._api_key}

        body: dict[str, Any] = {
            "prompt": prompt,
            "browserWindowId": self.id,
        }
        if clear_chat is not None:
            body["clearChat"] = clear_chat
        if generate_gif is not None:
            body["saveScreenshots"] = generate_gif

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    "https://api.narada.ai/fast/v2/remote-dispatch",
                    headers=headers,
                    json=body,
                    timeout=aiohttp.ClientTimeout(total=timeout),
                ) as resp:
                    resp.raise_for_status()
                    request_id = (await resp.json())["requestId"]

                while (now := time.monotonic()) < deadline:
                    async with session.get(
                        f"https://api.narada.ai/fast/v2/remote-dispatch/responses/{request_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=deadline - now),
                    ) as resp:
                        resp.raise_for_status()
                        response = await resp.json()

                    if response.get("status") != "pending":
                        return response

                    # Poll every 3 seconds.
                    await asyncio.sleep(3)
                else:
                    raise NaradaTimeoutError

        except asyncio.TimeoutError:
            raise NaradaTimeoutError
