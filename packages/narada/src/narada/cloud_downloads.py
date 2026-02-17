"""CDP-based download handling and file transfer for cloud browser sessions.

Uses a browser-level CDP session to capture downloads from all tabs via
Browser.downloadWillBegin / Browser.downloadProgress events, and CDP Fetch + IO.read
to stream remote files to local without loading the entire file into memory.

Ported from agentcore-download-solutions/custom_agentcore_playwright_cdp_streaming.py.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from playwright.async_api import Browser

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

DEFAULT_REMOTE_DOWNLOAD_DIR = "/tmp/remote_downloads"
CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB

# CDP Browser.downloadProgress state values
_STATE_IN_PROGRESS = "inProgress"
_STATE_COMPLETED = "completed"
_STATE_CANCELED = "canceled"
_STATE_INTERRUPTED = "interrupted"


@dataclass
class DownloadInfo:
    """Metadata about a completed download on the remote browser."""

    guid: str
    filename: str
    remote_path: str
    size: int


def local_path_for_session_download(
    base_dir: str | Path,
    session_id: str,
    filename: str,
) -> Path:
    """Build the local path for a session download so concurrent sessions do not overwrite.

    Files are placed under ``base_dir / session_id / filename``.
    """
    return Path(base_dir) / session_id / filename


def make_default_on_download_complete_callback(
    browser: "Browser",
    loop: asyncio.AbstractEventLoop,
    base_dir: str | Path,
    pending_futures: list[Any],
) -> Callable[[str, str, str], None]:
    """Return a sync callback (session_id, guid, filename) -> None that transfers each
    completed download to ``base_dir / session_id / filename`` and appends the
    transfer future to *pending_futures* so the caller can wait before closing the browser.
    """
    base_dir = Path(base_dir)

    def on_download_complete(session_id: str, guid: str, filename: str) -> None:
        local_path = local_path_for_session_download(base_dir, session_id, filename)
        local_path.parent.mkdir(parents=True, exist_ok=True)
        remote_path = f"{DEFAULT_REMOTE_DOWNLOAD_DIR}/{guid}"
        future = asyncio.run_coroutine_threadsafe(
            download_remote_file_to_local(browser, remote_path, local_path),
            loop,
        )
        pending_futures.append(future)

    return on_download_complete


class CDPDownloadHandler:
    """Tracks downloads on a remote cloud browser via a browser-level CDP session.

    Using a *browser-level* CDP session (``browser.new_browser_cdp_session()``)
    ensures that downloads triggered by **any** tab are captured, which is critical
    for cloud browser sessions where the agent may open new tabs.

    If *on_download_complete* is set, each completed download triggers that sync
    callable in a thread (run_in_executor), so the CDP event loop is not blocked.
    Signature: (session_id: str, guid: str, filename: str) -> None.
    """

    def __init__(
        self,
        remote_download_dir: str = DEFAULT_REMOTE_DOWNLOAD_DIR,
        session_id: str | None = None,
        on_download_complete: Callable[[str, str, str], None] | None = None,
    ) -> None:
        self._remote_download_dir = remote_download_dir
        self._session_id = session_id
        self._on_download_complete = on_download_complete
        # guid -> dict with keys "filename", "state", "received"
        self._downloads: dict[str, dict[str, Any]] = {}
        # guid -> Event set when that download reaches a terminal state
        self._done_events: dict[str, asyncio.Event] = {}
        self._cdp_session: Any | None = None
        self._browser: Browser | None = None

    async def setup(self, browser: Browser) -> None:
        """Attach to the browser and start listening for download events."""
        print(f"\n\nCDPDownloadHandler.setup called")
        self._browser = browser
        self._cdp_session = await browser.new_browser_cdp_session()

        await self._cdp_session.send(
            "Browser.setDownloadBehavior",
            {
                "behavior": "allowAndName",
                "downloadPath": self._remote_download_dir,
                "eventsEnabled": True,
            },
        )
        self._cdp_session.on(
            "Browser.downloadWillBegin",
            lambda event: asyncio.create_task(self._on_download_begin(event)),
        )
        self._cdp_session.on(
            "Browser.downloadProgress",
            lambda event: asyncio.create_task(self._on_download_progress(event)),
        )

    async def _on_download_begin(self, event: dict[str, Any]) -> None:
        print(f"\n\nCDPDownloadHandler._on_download_begin called")
        guid: str = event.get("guid", "")
        filename: str = event.get("suggestedFilename", "download")
        self._downloads[guid] = {
            "filename": filename,
            "state": _STATE_IN_PROGRESS,
            "received": 0,
        }
        self._done_events[guid] = asyncio.Event()

    async def _on_download_progress(self, event: dict[str, Any]) -> None:
        guid: str = event.get("guid", "")
        state: str = event.get("state", "")
        received: int = event.get("receivedBytes", 0)
        print(f"\n\nCDPDownloadHandler._on_download_progress called: {guid} {state} {received}")

        if guid in self._downloads:
            self._downloads[guid]["state"] = state
            self._downloads[guid]["received"] = received

        if state in (_STATE_COMPLETED, _STATE_CANCELED, _STATE_INTERRUPTED):
            if guid in self._done_events:
                self._done_events[guid].set()

        if state == _STATE_COMPLETED:
            print(f"\n\nCDPDownloadHandler._on_download_progress completed: {guid}. _on_download_complete={self._on_download_complete}")
            filename = self._downloads.get(guid, {}).get("filename", guid)
            if self._on_download_complete and self._session_id:
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None,
                    lambda: self._on_download_complete(
                        self._session_id, guid, filename
                    ),
                )
        elif state in (_STATE_CANCELED, _STATE_INTERRUPTED):
            pass

    async def wait_for_download(
        self, *, timeout: float | None = None
    ) -> DownloadInfo | None:
        print(f"\n\nCDPDownloadHandler.wait_for_download called")
        """Wait for the next download to complete and return its info.

        If no download events have been received yet, this will block until one
        arrives and finishes (or the *timeout* expires).

        Returns ``None`` on timeout or if the download was canceled/interrupted.
        """
        # Find first download that hasn't finished yet, or the most recent completed one
        # that hasn't been consumed.
        target_guid: str | None = None
        for guid, info in self._downloads.items():
            if info["state"] == _STATE_IN_PROGRESS:
                target_guid = guid
                break

        if target_guid is None:
            # All existing downloads are already done; wait for a new one by polling.
            # We do a simple poll loop so we can detect newly arriving downloads.
            loop = asyncio.get_running_loop()
            deadline = (loop.time() + timeout) if timeout is not None else None
            while True:
                for guid, info in self._downloads.items():
                    if guid not in self._done_events or not self._done_events[guid].is_set():
                        if info["state"] == _STATE_IN_PROGRESS:
                            target_guid = guid
                            break
                if target_guid is not None:
                    break
                if deadline is not None and loop.time() >= deadline:
                    return None
                await asyncio.sleep(0.5)

        assert target_guid is not None
        done_event = self._done_events[target_guid]

        try:
            if timeout is not None:
                await asyncio.wait_for(done_event.wait(), timeout=timeout)
            else:
                await done_event.wait()
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for download %s", target_guid)
            return None

        info = self._downloads[target_guid]
        if info["state"] != _STATE_COMPLETED:
            return None

        return DownloadInfo(
            guid=target_guid,
            filename=info["filename"],
            remote_path=f"{self._remote_download_dir}/{target_guid}",
            size=info["received"],
        )

    async def wait_for_all(
        self, *, timeout: float | None = None
    ) -> list[DownloadInfo]:
        """Wait for **all** tracked downloads to reach a terminal state.

        Returns a list of :class:`DownloadInfo` for every download that completed
        successfully.  Downloads that were canceled or interrupted are skipped.
        """
        print(f"\n\nCDPDownloadHandler.wait_for_all called")
        if not self._downloads:
            return []

        # Gather all done-events with an optional timeout.
        waiter = asyncio.gather(*(ev.wait() for ev in self._done_events.values()))
        try:
            if timeout is not None:
                await asyncio.wait_for(waiter, timeout=timeout)
            else:
                await waiter
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for all downloads")

        results: list[DownloadInfo] = []
        for guid, info in self._downloads.items():
            if info["state"] == _STATE_COMPLETED:
                results.append(
                    DownloadInfo(
                        guid=guid,
                        filename=info["filename"],
                        remote_path=f"{self._remote_download_dir}/{guid}",
                        size=info["received"],
                    )
                )

        return results


async def download_remote_file_to_local(
    browser: Browser,
    remote_file_path: str,
    local_path: str | Path,
) -> Path | None:
    """Stream a file from the remote browser filesystem to a local path.

    Strategy:
        1. Create a **fresh** browser context (safe even if existing contexts are
           corrupted by tab open/close activity that Playwright didn't track).
        2. Use the CDP *Fetch* domain to intercept the ``file://`` response.
        3. ``Fetch.takeResponseBodyAsStream`` + ``IO.read`` to stream large files
           in 4 MB chunks over the CDP WebSocket.

    Args:
        browser: Playwright browser connected via CDP.
        remote_file_path: Absolute path on the remote browser container
            (e.g. ``/tmp/remote_downloads/{guid}``).
        local_path: Local destination.  Parent directories are created
            automatically.

    Returns:
        The resolved local :class:`~pathlib.Path`, or ``None`` on failure.
    """
    print(f"\n\ndownload_remote_file_to_local called")
    local_path = Path(local_path)
    local_path.parent.mkdir(parents=True, exist_ok=True)

    # Always create a fresh context -- the original one may be corrupted by manual
    # tab open/close activity that Playwright didn't track.
    transfer_ctx = await browser.new_context()
    transfer_page = await transfer_ctx.new_page()
    cdp = await transfer_page.context.new_cdp_session(transfer_page)

    try:
        read_start_ts = time.strftime("%H:%M:%S", time.localtime())

        # Enable Fetch domain to intercept file:// responses
        await cdp.send(
            "Fetch.enable",
            {"patterns": [{"urlPattern": "file://*", "requestStage": "Response"}]},
        )

        stream_handle_holder: dict[str, str | None] = {}
        fetch_done = asyncio.Event()

        async def _on_request_paused(event: dict[str, Any]) -> None:
            request_id = event["requestId"]
            try:
                stream_result = await cdp.send(
                    "Fetch.takeResponseBodyAsStream", {"requestId": request_id}
                )
                stream_handle_holder["handle"] = stream_result.get("stream")
            except Exception:
                pass
            finally:
                fetch_done.set()

        cdp.on(
            "Fetch.requestPaused",
            lambda ev: asyncio.create_task(_on_request_paused(ev)),
        )

        # Navigate to the file -- this triggers the Fetch intercept.
        try:
            await transfer_page.goto(
                f"file://{remote_file_path}", wait_until="commit", timeout=30_000
            )
        except Exception:
            pass  # Navigation may abort for binary files, but Fetch still fires.

        # Wait for the Fetch intercept to fire.
        try:
            await asyncio.wait_for(fetch_done.wait(), timeout=30)
        except asyncio.TimeoutError:
            logger.warning("Timeout waiting for Fetch intercept")
            return None

        await cdp.send("Fetch.disable")

        stream_handle = stream_handle_holder.get("handle")
        if not stream_handle:
            logger.warning("No stream handle obtained")
            return None

        # Stream the file contents to local disk in chunks.
        stream_start = time.perf_counter()
        start_ts = time.strftime("%H:%M:%S", time.localtime())
        logger.warning(
            "Streaming file from remote to local: %s -> %s (started at %s)",
            remote_file_path,
            local_path,
            start_ts,
        )
        downloaded = 0

        with open(local_path, "wb") as f:
            while True:
                read_result = await cdp.send(
                    "IO.read", {"handle": stream_handle, "size": CHUNK_SIZE}
                )
                data: str = read_result.get("data", "")
                is_b64: bool = read_result.get("base64Encoded", False)
                eof: bool = read_result.get("eof", False)

                if data:
                    chunk = (
                        base64.b64decode(data) if is_b64 else data.encode("utf-8")
                    )
                    f.write(chunk)
                    downloaded += len(chunk)

                if eof:
                    break

        await cdp.send("IO.close", {"handle": stream_handle})
        stream_elapsed = time.perf_counter() - stream_start
        logger.warning(
            "Transfer complete: %s (%s bytes) in %.2fs",
            local_path,
            f"{downloaded:,}",
            stream_elapsed,
        )
        return local_path

    except Exception as exc:
        logger.exception("Transfer failed: %s", exc)
        return None

    finally:
        await transfer_ctx.close()
