from __future__ import annotations

import json
from typing import Any, Awaitable, Callable

from narada_core.errors import NaradaError
from narada_core.models import GoogleDriveAuth, GoogleDriveFile, InMemoryFileVariable
from pydantic import TypeAdapter
from pyodide.http import pyfetch

_FILES_ADAPTER = TypeAdapter(list[GoogleDriveFile])
_FILE_VARIABLE_ADAPTER = TypeAdapter(InMemoryFileVariable)


class GoogleDriveClient:
    """List and download public Drive files through authenticated Narada endpoints.

    The optional ``auth`` selects Google Drive access independently of Narada
    authentication. Omitting it uses public sharing; OAuth is not yet supported.
    """

    def __init__(
        self,
        *,
        base_url: str,
        get_auth_headers: Callable[[], Awaitable[dict[str, str]]],
    ) -> None:
        self._base_url = base_url
        self._get_auth_headers = get_auth_headers

    async def list_files(
        self, *, folder: str, auth: GoogleDriveAuth | None = None
    ) -> list[GoogleDriveFile]:
        """List all immediate files in a public folder URL or ID, without recursion."""
        body: dict[str, object] = {"folder": folder}
        if auth is not None:
            body["auth"] = auth
        data = await self._post("/google/drive/list-files", body)
        return _FILES_ADAPTER.validate_python(data["files"])

    async def download_file(
        self, *, file: str | GoogleDriveFile, auth: GoogleDriveAuth | None = None
    ) -> InMemoryFileVariable:
        """Download a listing entry, file URL, or ID into a file-variable dictionary.

        Pass the entire listing entry to retain resource keys. Google Docs,
        Sheets, and Slides export to DOCX, XLSX, and PPTX respectively.
        """
        body: dict[str, object] = {"file": file}
        if auth is not None:
            body["auth"] = auth
        data = await self._post("/google/drive/download-file", body)
        return _FILE_VARIABLE_ADAPTER.validate_python(data)

    async def _post(self, path: str, body: dict[str, object]) -> Any:
        response = await pyfetch(
            f"{self._base_url}{path}",
            method="POST",
            headers={
                **await self._get_auth_headers(),
                "Content-Type": "application/json",
            },
            body=json.dumps(body),
        )
        if not response.ok:
            raise NaradaError(
                f"Google Drive request failed: {response.status} {await response.text()}"
            )
        return await response.json()
