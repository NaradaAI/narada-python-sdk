from __future__ import annotations

from typing import Any, Awaitable, Callable
from urllib.parse import quote, urlencode

from narada_core.errors import NaradaError
from narada_core.models import ManagedVectorStore
from pyodide.http import pyfetch


class VectorStoreCatalog:
    """Read-only access to managed vector stores available in Agent Studio.

    Managed vector-store paths use the canonical ``/owner@email.com/path/to/store``
    format.
    """

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
        query = ""
        if params is not None:
            query = f"?{urlencode({key: value for key, value in params.items() if value is not None})}"
        response = await pyfetch(
            f"{self._base_url}{path}{query}",
            headers=await self._get_auth_headers(),
        )
        if allow_not_found and response.status == 404:
            return None
        if not response.ok:
            raise NaradaError(
                f"Vector store request failed: {response.status} {await response.text()}"
            )
        return await response.json()
