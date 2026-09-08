"""Authorized canonical trace downloads, independent from workflow execution."""

from __future__ import annotations

import asyncio
import re
import shutil
import stat
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import aiohttp
from narada_core.errors import NaradaError
from pydantic import BaseModel, Field

_MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
_MAX_EXTRACTED_BYTES = 256 * 1024 * 1024
_MAX_FILES = 10_000
_CHUNK_BYTES = 64 * 1024
_REQUIRED_FILES = {
    "context.json",
    "index.json",
    "segments.jsonl",
    "events.jsonl",
    "scopes.jsonl",
    "timeline-index.json",
    "timeline.md",
}


class ExecutionTraceError(NaradaError):
    """Evidence retrieval failed; this says nothing about the workflow outcome.

    Messages contain a bounded reason, never a signed download URL or auth header.
    """

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"Execution trace retrieval failed: {reason}")


class ExecutionTraceDownloadResult(BaseModel):
    """A completed download or a server-reported nonterminal/unavailable state."""

    status: Literal["complete", "pending", "unavailable"]
    request_id: str
    trace_id: str | None = None
    path: Path | None = None


class _DownloadLocation(BaseModel):
    downloadUrl: str = Field(repr=False)
    expiresInSeconds: int


class _TraceDownloadResponse(BaseModel):
    status: Literal["ready", "pending", "unavailable"]
    download: _DownloadLocation | None = None


class _TraceIdentity(BaseModel):
    schemaVersion: Literal[1]
    traceId: str = Field(min_length=1)


def _validate_request_id(request_id: str) -> None:
    if re.fullmatch(r"[A-Za-z0-9_-]{1,200}", request_id) is None:
        raise ValueError("request_id must be a single Narada request identifier")


def _extract_archive(
    archive_path: Path, output: Path, *, expected_trace_id: str | None, deadline: float
) -> str:
    """Extract only a bounded, portable tree and verify its canonical identity."""
    seen: set[str] = set()
    total = 0
    with zipfile.ZipFile(archive_path) as archive:
        entries = archive.infolist()
        if len(entries) > _MAX_FILES:
            raise ExecutionTraceError("archive_too_large")
        for entry in entries:
            name = entry.filename.rstrip("/") if entry.is_dir() else entry.filename
            parts = name.split("/")
            # Apply Windows constraints on every OS, so an accepted archive remains
            # safe when a customer copies the resulting workflow to Windows.
            if not name or any(
                not part
                or part in (".", "..")
                or part[-1:] in (" ", ".")
                or any(ord(char) < 32 or char in '\\:<>"|?*' for char in part)
                or re.fullmatch(
                    r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?", part
                )
                for part in parts
            ):
                raise ExecutionTraceError("unsafe_archive_path")
            normalized = name.casefold()
            if normalized in seen:
                raise ExecutionTraceError("duplicate_archive_path")
            seen.add(normalized)
            mode = stat.S_IFMT(entry.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or entry.flag_bits & 1:
                raise ExecutionTraceError("unsupported_archive_entry")
            total += entry.file_size
            if total > _MAX_EXTRACTED_BYTES:
                raise ExecutionTraceError("archive_too_large")
            target = output.joinpath(*parts)
            if entry.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            written = 0
            with archive.open(entry) as source, target.open("xb") as sink:
                while chunk := source.read(_CHUNK_BYTES):
                    if time.monotonic() >= deadline:
                        raise ExecutionTraceError("timeout")
                    written += len(chunk)
                    if written > entry.file_size:
                        raise ExecutionTraceError("archive_too_large")
                    sink.write(chunk)
        if not _REQUIRED_FILES.issubset(seen):
            raise ExecutionTraceError("incomplete_archive")
        identities = [
            _TraceIdentity.model_validate_json((output / name).read_bytes())
            for name in ("context.json", "index.json")
        ]
        trace_id = identities[0].traceId
        if identities[1].traceId != trace_id or (
            expected_trace_id is not None and expected_trace_id != trace_id
        ):
            raise ExecutionTraceError("trace_identity_mismatch")
        return trace_id


class ExecutionTraceClient:
    """Public trace API bound to an Environment's existing Narada identity.

    Fetching only retrieves existing evidence; it never dispatches a workflow.
    Downloads are bounded to 64 MiB compressed, 256 MiB extracted, and 10,000
    entries. Archives publish as a directory only after full validation.
    """

    def __init__(self, *, base_url: str, auth_headers: dict[str, str]) -> None:
        self._base_url = base_url.rstrip("/")
        self._auth_headers = dict(auth_headers)

    @staticmethod
    def _check_status(status: int) -> None:
        if status in (401, 403):
            raise ExecutionTraceError("denied")
        if status < 200 or status >= 300:
            raise ExecutionTraceError("http_error")

    async def fetch(
        self,
        *,
        request_id: str,
        destination: Path | str,
        expected_trace_id: str | None = None,
        timeout: float = 60,
    ) -> ExecutionTraceDownloadResult:
        """Fetch a request's canonical trace into a new directory.

        Existing destinations are never intentionally replaced. Pending and
        unavailable results create no trace directory. Failures raise
        ExecutionTraceError; retry this method, never the business action.
        """
        _validate_request_id(request_id)
        destination = Path(destination).absolute()
        if destination.exists() or destination.is_symlink():
            raise ExecutionTraceError("destination_exists")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        staging: Path | None = None
        try:
            deadline = time.monotonic() + timeout
            async with asyncio.timeout(timeout), aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self._base_url}/remote-dispatch/runs/{request_id}/execution-trace",
                    headers=self._auth_headers,
                    allow_redirects=False,
                ) as response:
                    self._check_status(response.status)
                    descriptor = _TraceDownloadResponse.model_validate(
                        await response.json()
                    )
                if descriptor.status != "ready":
                    return ExecutionTraceDownloadResult(
                        status=descriptor.status, request_id=request_id
                    )
                if descriptor.download is None:
                    raise ExecutionTraceError("invalid_download_response")
                url = descriptor.download.downloadUrl
                parsed = urlsplit(url)
                # HTTP is accepted only for loopback fixture/development servers.
                if (
                    (
                        parsed.scheme != "https"
                        and not (
                            parsed.scheme == "http"
                            and parsed.hostname in ("127.0.0.1", "localhost", "::1")
                        )
                    )
                    or parsed.username is not None
                    or parsed.password is not None
                ):
                    raise ExecutionTraceError("invalid_download_url")
                destination.parent.mkdir(parents=True, exist_ok=True)
                staging = Path(
                    tempfile.mkdtemp(prefix=".narada-trace-", dir=destination.parent)
                )
                archive_path = staging / "archive.zip"
                # Separate session: neither API headers nor API cookies reach storage.
                async with aiohttp.ClientSession(
                    cookie_jar=aiohttp.DummyCookieJar()
                ) as storage:
                    async with storage.get(url, allow_redirects=False) as response:
                        self._check_status(response.status)
                        if (
                            response.content_length is not None
                            and response.content_length > _MAX_ARCHIVE_BYTES
                        ):
                            raise ExecutionTraceError("archive_too_large")
                        total = 0
                        with archive_path.open("xb") as sink:
                            async for chunk in response.content.iter_chunked(
                                _CHUNK_BYTES
                            ):
                                total += len(chunk)
                                if total > _MAX_ARCHIVE_BYTES:
                                    raise ExecutionTraceError("archive_too_large")
                                sink.write(chunk)
                extracted = staging / "extracted"
                extracted.mkdir()
                trace_id = _extract_archive(
                    archive_path,
                    extracted,
                    expected_trace_id=expected_trace_id,
                    deadline=deadline,
                )
                if destination.exists() or destination.is_symlink():
                    raise ExecutionTraceError("destination_exists")
                extracted.rename(destination)
                return ExecutionTraceDownloadResult(
                    status="complete",
                    request_id=request_id,
                    trace_id=trace_id,
                    path=destination,
                )
        except ExecutionTraceError:
            raise
        except TimeoutError:
            raise ExecutionTraceError("timeout") from None
        except (
            aiohttp.ClientError,
            OSError,
            ValueError,
            zipfile.BadZipFile,
            RuntimeError,
        ):
            raise ExecutionTraceError("invalid_or_unavailable_archive") from None
        finally:
            if staging is not None:
                shutil.rmtree(staging)
