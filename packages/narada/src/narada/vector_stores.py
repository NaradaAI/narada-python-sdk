from __future__ import annotations

from typing import Any
from urllib.parse import quote

import aiohttp
from narada_core.errors import NaradaError
from narada_core.models import ManagedVectorStore


class VectorStoreCatalog:
    """Read-only access to managed vector stores available in Agent Studio.

    Managed vector-store paths use the canonical ``/owner@email.com/path/to/store``
    format.
    """

    def __init__(self, *, base_url: str, auth_headers: dict[str, str]) -> None:
        self._base_url = base_url
        self._auth_headers = auth_headers

    async def list(self) -> list[ManagedVectorStore]:
        data = await self._get("/agent-studio/vector-stores")
        return [ManagedVectorStore.model_validate(item) for item in data]

    async def get(
        self,
        *,
        id: str | None = None,
        path: str | None = None,
    ) -> ManagedVectorStore | None:
        """Get a managed vector store by ID or canonical owner-qualified path."""
        if (id is None) == (path is None):
            raise ValueError("Provide exactly one of `id` or `path`")

        if id is not None:
            encoded_id = quote(id, safe="")
            data = await self._get(
                f"/agent-studio/vector-stores/{encoded_id}",
                allow_not_found=True,
            )
        else:
            data = await self._get(
                "/agent-studio/vector-stores/by-path",
                params={"path": path},
                allow_not_found=True,
            )

        return ManagedVectorStore.model_validate(data) if data is not None else None

    async def _get(
        self,
        path: str,
        *,
        params: dict[str, str | None] | None = None,
        allow_not_found: bool = False,
    ) -> Any:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{self._base_url}{path}",
                headers=self._auth_headers,
                params=params,
            ) as response:
                if allow_not_found and response.status == 404:
                    return None
                if not response.ok:
                    raise NaradaError(
                        f"Vector store request failed: {response.status} {await response.text()}"
                    )
                return await response.json()
