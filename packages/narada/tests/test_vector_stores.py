from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from narada import (
    BedrockConnectionConfig,
    BedrockCredentials,
    ExternalVectorStore,
    ManagedVectorStore,
)
from narada.vector_stores import VectorStoreCatalog
from narada_core.actions.critic import run_critic
from pydantic import create_model


class _FakeResponse:
    def __init__(
        self,
        *,
        payload: Any = None,
        ok: bool = True,
        status: int = 200,
        text: str = "",
    ) -> None:
        self.ok = ok
        self.status = status
        self._payload = payload
        self._text = text

    async def __aenter__(self) -> "_FakeResponse":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    async def json(self) -> Any:
        return self._payload

    async def text(self) -> str:
        return self._text


class _FakeSession:
    def __init__(self, responses: list[_FakeResponse]) -> None:
        self._responses = responses
        self.get_calls: list[dict[str, Any]] = []

    async def __aenter__(self) -> "_FakeSession":
        return self

    async def __aexit__(self, *_args: object) -> None:
        return None

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.get_calls.append({"url": url, **kwargs})
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_managed_vector_store_catalog_lists_and_resolves_by_id_and_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.vector_stores as vector_stores_module

    responses = [
        _FakeResponse(
            payload=[
                {
                    "id": "store-1",
                    "name": "Policies",
                    "path": "/Knowledge/Policies",
                    "description": "Company policies",
                    "ownerEmail": "owner@example.com",
                    "fileCount": 2,
                    "updatedAt": "2026-08-25T12:00:00Z",
                }
            ]
        ),
        _FakeResponse(payload={"id": "store-1", "name": "Policies"}),
        _FakeResponse(
            payload={
                "id": "store-1",
                "name": "Policies",
                "path": "/Knowledge/Policies",
            }
        ),
    ]
    session = _FakeSession(responses)
    monkeypatch.setattr(
        vector_stores_module.aiohttp,
        "ClientSession",
        lambda: session,
    )
    catalog = VectorStoreCatalog(
        base_url="https://api.example.test/fast/v2",
        auth_headers={"x-api-key": "test-key"},
    )

    listed = await catalog.list()
    by_id = await catalog.get(id="store-1")
    by_path = await catalog.get(path="/Knowledge/Policies")

    assert listed == [
        ManagedVectorStore(
            id="store-1",
            name="Policies",
            path="/Knowledge/Policies",
            description="Company policies",
            ownerEmail="owner@example.com",
            fileCount=2,
            updatedAt="2026-08-25T12:00:00Z",
        )
    ]
    assert by_id.id == "store-1"
    assert by_path.path == "/Knowledge/Policies"
    assert session.get_calls == [
        {
            "url": "https://api.example.test/fast/v2/agent-studio/vector-stores",
            "headers": {"x-api-key": "test-key"},
            "params": None,
        },
        {
            "url": "https://api.example.test/fast/v2/agent-studio/vector-stores/store-1",
            "headers": {"x-api-key": "test-key"},
            "params": None,
        },
        {
            "url": "https://api.example.test/fast/v2/agent-studio/vector-stores/by-path",
            "headers": {"x-api-key": "test-key"},
            "params": {"path": "/Knowledge/Policies"},
        },
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("selector", [{}, {"id": "store-1", "path": "/Policies"}])
async def test_managed_vector_store_catalog_requires_exactly_one_selector(
    selector: dict[str, str],
) -> None:
    catalog = VectorStoreCatalog(base_url="https://api.example.test", auth_headers={})

    with pytest.raises(ValueError, match="exactly one"):
        await catalog.get(**selector)


@pytest.mark.asyncio
async def test_managed_vector_store_catalog_encodes_id_path_segment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import narada.vector_stores as vector_stores_module

    session = _FakeSession([_FakeResponse(payload={"id": "store/with?reserved#chars"})])
    monkeypatch.setattr(
        vector_stores_module.aiohttp,
        "ClientSession",
        lambda: session,
    )
    catalog = VectorStoreCatalog(
        base_url="https://api.example.test/fast/v2",
        auth_headers={"x-api-key": "test-key"},
    )

    vector_store = await catalog.get(id="store/with?reserved#chars")

    assert vector_store.id == "store/with?reserved#chars"
    assert session.get_calls[0]["url"].endswith(
        "/agent-studio/vector-stores/store%2Fwith%3Freserved%23chars"
    )


@pytest.mark.asyncio
async def test_critic_forwards_vector_stores() -> None:
    managed = ManagedVectorStore(id="store-1")
    external = ExternalVectorStore(
        id="bedrock-kb-1",
        name="External knowledge",
        description="Product documentation",
        connection=BedrockConnectionConfig(
            credentials=BedrockCredentials(
                accessKeyId="access-key",
                secretAccessKey="secret-key",
                region="us-east-1",
            ),
            knowledgeBaseId="kb-1",
        ),
    )
    CriticOutput = create_model("CriticOutput", narada_validation_passed=(bool, ...))
    dispatch_request = AsyncMock(
        return_value={
            "response": {
                "structuredOutput": CriticOutput(narada_validation_passed=True),
                "actionTrace": None,
                "workflowTrace": None,
            },
            "usage": {"actions": 0, "credits": 0},
        }
    )

    result = await run_critic(
        dispatch_request=dispatch_request,
        original_prompt="Summarize",
        response_content={"text": "Summary"},
        action_trace_raw=None,
        critic={"vector_stores": [managed, external]},
        time_zone="UTC",
        timeout=30,
    )

    assert result.validation_passed is True
    assert dispatch_request.await_args.kwargs["vector_stores"] == [managed, external]
