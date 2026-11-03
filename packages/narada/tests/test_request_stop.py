"""Exercise Stop through real loopback HTTP/CDP transports; no model execution."""

import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from aiohttp import web
from narada import BrowserConfig, BrowserEnvironment
from narada._request_stop import stop_browser_request
from narada_core.errors import NaradaError, NaradaTimeoutError


@asynccontextmanager
async def server(*, behavior="normal", terminal=False):
    state = SimpleNamespace(
        stopped=False, gets=0, stops=0, methods=[], terminal=terminal
    )
    app = web.Application()

    async def response(request):
        assert request.headers.get("X-API-Key") == "synthetic-key"
        assert request.match_info["request_id"] == "request-a"
        state.gets += 1
        done = state.terminal or (state.stopped and behavior != "pending")
        return web.json_response(
            {
                "browserWindowId": "other" if behavior == "wrong-owner" else "owned",
                "status": "error" if done else "pending",
                "completedAt": (
                    123 if behavior == "bad-terminal" else "2026-11-03T00:00:00Z"
                )
                if done
                else None,
            }
        )

    async def version(request):
        assert "X-API-Key" not in request.headers
        return web.json_response(
            {"webSocketDebuggerUrl": state.url.replace("http:", "ws:") + "/cdp"}
        )

    async def cdp(request):
        assert "X-API-Key" not in request.headers
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            data = json.loads(msg.data)
            state.methods.append(data["method"])
            method = data["method"]
            if method == "Target.getTargets":
                result = {
                    "targetInfos": [
                        {
                            "targetId": "unrelated",
                            "type": "page",
                            "url": "https://other.example/app",
                        },
                        {
                            "targetId": "panel",
                            "type": "iframe",
                            "url": state.url + "/app",
                        },
                    ]
                }
                if behavior == "duplicate":
                    result["targetInfos"].append(
                        {
                            "targetId": "duplicate",
                            "type": "iframe",
                            "url": state.url + "/app",
                        }
                    )
            elif method == "Target.attachToTarget":
                assert data["params"]["targetId"] != "unrelated"
                result = {"sessionId": data["params"]["targetId"]}
            elif method == "Runtime.evaluate":
                expression = data["params"]["expression"]
                assert "reload" not in expression
                if ".stop(" in expression:
                    assert '"requestId": "request-a"' in expression
                    state.stops += 1
                    if behavior == "disconnect":
                        await ws.close()
                        break
                    if behavior == "blocked":
                        await asyncio.sleep(1)
                        break
                    state.stopped = True
                    value = {
                        "version": 1,
                        "browserWindowId": "owned",
                        "requestId": "wrong"
                        if behavior == "wrong-ack"
                        else "request-a",
                        "status": "stopped",
                    }
                else:
                    value = (
                        None
                        if behavior == "unsupported"
                        else {"version": 1, "browserWindowId": "owned"}
                    )
                result = {"result": {"value": value}}
            else:
                raise AssertionError(method)
            await ws.send_json(
                {"method": "Runtime.executionContextCreated", "params": {}}
            )
            await ws.send_json({"id": data["id"], "result": result})
        return ws

    app.router.add_get("/remote-dispatch/responses/{request_id}", response)
    app.router.add_get("/json/version", version)
    app.router.add_get("/cdp", cdp)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    state.url = f"http://127.0.0.1:{site._server.sockets[0].getsockname()[1]}"
    try:
        yield state
    finally:
        await runner.cleanup()


async def stop(state, *, timeout=2):
    return await stop_browser_request(
        base_url=state.url,
        auth_headers={"X-API-Key": "synthetic-key"},
        cdp_url=state.url,
        initialization_url=state.url + "/initialize",
        request_id="request-a",
        expected_browser_window_id="owned",
        timeout=timeout,
    )


@pytest.mark.asyncio
async def test_stop_requires_durable_terminal_response_after_panel_ack():
    async with server() as state:
        result = await stop(state)
        assert result.request_id == "request-a"
        assert result.browser_window_id == "owned"
        assert result.status == "error"
        assert result.completed_at
        assert state.stops == 1
        assert state.gets == 2


@pytest.mark.asyncio
async def test_already_terminal_does_not_touch_browser():
    async with server(terminal=True) as state:
        await stop(state)
        assert not state.methods
        assert state.gets == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "behavior", ["wrong-owner", "wrong-ack", "unsupported", "duplicate", "disconnect"]
)
async def test_unverified_stop_fails_closed(behavior):
    async with server(behavior=behavior) as state:
        with pytest.raises(NaradaError):
            await stop(state)
        if behavior in {"wrong-owner", "unsupported", "duplicate"}:
            assert state.stops == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("behavior", ["pending", "blocked"])
async def test_ack_or_browser_hang_cannot_bypass_deadline(behavior):
    async with server(behavior=behavior) as state:
        with pytest.raises(NaradaTimeoutError):
            await stop(state, timeout=0.4)
        assert state.stops >= 1


@pytest.mark.asyncio
async def test_malformed_terminal_evidence_is_not_confirmation():
    async with server(terminal=True, behavior="bad-terminal") as state:
        with pytest.raises(NaradaError):
            await stop(state)


@pytest.mark.asyncio
async def test_public_stop_does_not_initialize_or_launch_browser(monkeypatch):
    async with server(terminal=True) as state:
        config = BrowserConfig(
            cdp_host="http://127.0.0.1",
            cdp_port=int(state.url.rsplit(":", 1)[1]),
            initialization_url=state.url + "/initialize",
        )
        environment = BrowserEnvironment(config=config, api_key="synthetic-key")
        environment._base_url = state.url
        environment._auth_headers = {"X-API-Key": "synthetic-key"}

        async def forbidden():
            raise AssertionError("must not initialize")

        monkeypatch.setattr(environment, "_ensure_initialized", forbidden)
        result = await environment.stop_request("request-a", browser_window_id="owned")
        assert result.request_id == "request-a"
