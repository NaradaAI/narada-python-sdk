from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote, urlsplit

import aiohttp
from narada_core.errors import NaradaError, NaradaTimeoutError


@dataclass(frozen=True)
class _RequestStopResult:
    """Internal terminal observation for the pinned local-runner integration.

    A request that completed before Stop keeps its original success/error result.
    This record confirms that it is terminal, not that every result is an abort
    or that the caller's Python workflow and any later requests have stopped.
    """

    request_id: str
    browser_window_id: str
    status: Literal["success", "error"]
    completed_at: str


class _BrowserControl:
    def __init__(self, socket: aiohttp.ClientWebSocketResponse) -> None:
        self.socket = socket
        self.sequence = 0

    async def command(
        self, method: str, params: dict[str, Any], session_id: str | None = None
    ) -> dict[str, Any]:
        self.sequence += 1
        command_id = self.sequence
        message: dict[str, Any] = {"id": command_id, "method": method, "params": params}
        if session_id is not None:
            message["sessionId"] = session_id
        await self.socket.send_json(message)
        async for incoming in self.socket:
            if incoming.type != aiohttp.WSMsgType.TEXT:
                raise NaradaError("Browser disconnected before Stop was acknowledged")
            response = json.loads(incoming.data)
            if response.get("id") != command_id:
                continue
            if "error" in response:
                raise NaradaError("Browser rejected the SDK Stop control command")
            return response.get("result", {})
        raise NaradaError("Browser disconnected before Stop was acknowledged")

    async def evaluate(self, session_id: str, expression: str) -> Any:
        result = await self.command(
            "Runtime.evaluate",
            {"expression": expression, "returnByValue": True, "awaitPromise": True},
            session_id,
        )
        if result.get("exceptionDetails"):
            raise NaradaError("Narada side panel could not acknowledge Stop")
        return result.get("result", {}).get("value")


async def _stop_in_panel(
    session: aiohttp.ClientSession,
    *,
    cdp_url: str,
    initialization_url: str,
    browser_window_id: str,
    request_id: str,
) -> None:
    async with session.get(cdp_url.rstrip("/") + "/json/version") as response:
        response.raise_for_status()
        endpoint = (await response.json())["webSocketDebuggerUrl"]
    origin = urlsplit(initialization_url)
    async with session.ws_connect(endpoint) as socket:
        control = _BrowserControl(socket)
        targets = (await control.command("Target.getTargets", {}))["targetInfos"]
        matches: list[str] = []
        for target in targets:
            url = urlsplit(target.get("url", ""))
            if (
                target.get("type") not in {"page", "iframe"}
                or (url.scheme, url.netloc) != (origin.scheme, origin.netloc)
                or url.path != "/app"
            ):
                continue
            attached = await control.command(
                "Target.attachToTarget",
                {"targetId": target["targetId"], "flatten": True},
            )
            session_id = attached["sessionId"]
            identity = await control.evaluate(
                session_id,
                "(()=>{const c=window.__naradaSdkStopV1;return c&&"
                "{version:c.version,browserWindowId:c.browserWindowId}})()",
            )
            if identity == {"version": 1, "browserWindowId": browser_window_id}:
                matches.append(session_id)
        if len(matches) != 1:
            raise NaradaError("No unique compatible Narada side panel for this request")
        payload = json.dumps(
            {"browserWindowId": browser_window_id, "requestId": request_id}
        )
        acknowledgment = await control.evaluate(
            matches[0], f"window.__naradaSdkStopV1.stop({payload})"
        )
        if (
            not isinstance(acknowledgment, dict)
            or acknowledgment.get("version") != 1
            or acknowledgment.get("browserWindowId") != browser_window_id
            or acknowledgment.get("requestId") != request_id
            or acknowledgment.get("status") not in {"stopped", "not_active"}
        ):
            raise NaradaError("Narada returned a mismatched Stop acknowledgment")


async def _stop_browser_request(
    *,
    base_url: str,
    auth_headers: dict[str, str],
    cdp_url: str,
    initialization_url: str,
    request_id: str,
    expected_browser_window_id: str,
    timeout: float,
) -> _RequestStopResult:
    if not request_id or len(request_id) > 256 or not expected_browser_window_id:
        raise ValueError("Stop requires the exact request and browser window IDs")
    if timeout <= 0:
        raise ValueError("Stop timeout must be positive")
    try:
        async with asyncio.timeout(timeout), aiohttp.ClientSession() as session:
            while True:
                async with session.get(
                    f"{base_url.rstrip('/')}/remote-dispatch/responses/{quote(request_id, safe='')}",
                    headers=auth_headers,
                    allow_redirects=False,
                ) as response:
                    response.raise_for_status()
                    value = await response.json()
                if value.get("browserWindowId") != expected_browser_window_id:
                    raise NaradaError(
                        "Request does not belong to the expected browser window"
                    )
                if value.get("completedAt") is not None:
                    if (
                        value.get("status") not in {"success", "error"}
                        or not isinstance(value["completedAt"], str)
                        or not value["completedAt"]
                    ):
                        raise NaradaError(
                            "Request has an inconsistent terminal response"
                        )
                    return _RequestStopResult(
                        request_id,
                        expected_browser_window_id,
                        value["status"],
                        value["completedAt"],
                    )
                await _stop_in_panel(
                    session,
                    cdp_url=cdp_url,
                    initialization_url=initialization_url,
                    browser_window_id=expected_browser_window_id,
                    request_id=request_id,
                )
                # Dispatch can still be entering the panel, or its terminal save
                # may be in flight. Retry Stop, never the original business action.
                await asyncio.sleep(0.25)
    except TimeoutError as error:
        raise NaradaTimeoutError(
            "Remote Stop was not confirmed before the deadline"
        ) from error
