from __future__ import annotations

from typing import Any, Awaitable, Callable
from urllib.parse import urlencode

from narada_core.errors import NaradaError
from narada_core.models import ManagedVectorStore
from pyodide.http import pyfetch


class VectorStoreCatalog:
    """Read-only access to managed vector stores available in Agent Studio."""

    def __init__(
        self,
        *,
        base_url: str,
        get_auth_headers: Callable[[], Awaitable[dict[str, str]]],
    ) -> None:
        self._base_url = base_url
        self._get_auth_headers = get_auth_headers

    async def list(self) -> list[ManagedVectorStore]:
        data = await self._get("/agent-studio/vector-stores")
        return [ManagedVectorStore.model_validate(item) for item in data]

    async def get(
        self,
        *,
        id: str | None = None,
        path: str | None = None,
    ) -> ManagedVectorStore:
        if (id is None) == (path is None):
            raise ValueError("Provide exactly one of `id` or `path`")

        if id is not None:
            data = await self._get(f"/agent-studio/vector-stores/{id}")
        else:
            data = await self._get(
                "/agent-studio/vector-stores/by-path",
                params={"path": path},
            )
        return ManagedVectorStore.model_validate(data)

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str | None] | None = None,
    ) -> Any:
        query = ""
        if params is not None:
            query = f"?{urlencode({key: value for key, value in params.items() if value is not None})}"
        response = await pyfetch(
            f"{self._base_url}{path}{query}",
            headers=await self._get_auth_headers(),
        )
        if not response.ok:
            raise NaradaError(
                f"Vector store request failed: {response.status} {await response.text()}"
            )
        return await response.json()
