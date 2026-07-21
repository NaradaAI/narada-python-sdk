"""Run Operator through the local frontend and validate action-trace timestamps.

Example:

    export NARADA_API_KEY="..."
    uv run python scripts/validate_operator_action_trace_timing.py

The script uses the locally running caddie API, frontend, and development
extension. It launches a local Chrome window and closes that window on exit.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import socket
import time
import urllib.request
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import NoReturn

from narada import Agent, BrowserConfig, BrowserEnvironment
from narada_core.tracing.model import OperatorActionTraceItem
from pydantic import ValidationError

PRODUCTION_API_BASE_URL = "https://api.narada.ai/fast/v2"
DEFAULT_LOCAL_API_BASE_URL = "http://127.0.0.1:8000/fast/v2"
DEFAULT_LOCAL_FRONTEND_URL = "http://localhost:3000"
DEFAULT_DEV_EXTENSION_ID = "ijdopnjleolkjakldkjplfhniiohnccf"
DEFAULT_CDP_PORT = 9223
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LOCAL_EXTENSION_PATH = (
    WORKSPACE_ROOT
    / "caddie"
    / "src"
    / "google"
    / "chrome-extension"
    / ".output"
    / "chrome-mv3-dev"
)
DEFAULT_LOCAL_USER_DATA_DIR = (
    Path.home() / ".config" / "narada" / "user-data-dirs" / "action-trace-local-cft"
)
DEFAULT_PROMPT = (
    "Go to https://example.com, read the page heading, and tell me the heading."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Operator action-trace timestamps through the local stack.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("NARADA_API_BASE_URL", DEFAULT_LOCAL_API_BASE_URL),
        help=(f"Local caddie API base URL (default: {DEFAULT_LOCAL_API_BASE_URL})."),
    )
    parser.add_argument(
        "--frontend-url",
        default=DEFAULT_LOCAL_FRONTEND_URL,
        help=f"Local frontend origin (default: {DEFAULT_LOCAL_FRONTEND_URL}).",
    )
    parser.add_argument(
        "--extension-id",
        default=DEFAULT_DEV_EXTENSION_ID,
        help=f"Installed local extension ID (default: {DEFAULT_DEV_EXTENSION_ID}).",
    )
    parser.add_argument(
        "--extension-path",
        type=Path,
        default=DEFAULT_LOCAL_EXTENSION_PATH,
        help=f"Built local extension directory (default: {DEFAULT_LOCAL_EXTENSION_PATH}).",
    )
    parser.add_argument(
        "--browser-executable",
        type=Path,
        help=(
            "Chromium or Chrome for Testing executable. By default, use the newest "
            "Playwright Chromium installation."
        ),
    )
    parser.add_argument(
        "--user-data-dir",
        type=Path,
        default=DEFAULT_LOCAL_USER_DATA_DIR,
        help=f"Chrome profile for this test (default: {DEFAULT_LOCAL_USER_DATA_DIR}).",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=DEFAULT_CDP_PORT,
        help=f"Dedicated Chrome CDP port (default: {DEFAULT_CDP_PORT}).",
    )
    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Operator task to run. It should require at least one browser action.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=600,
        help="Agent timeout in seconds (default: 600).",
    )
    args = parser.parse_args()

    if args.base_url.rstrip("/") == PRODUCTION_API_BASE_URL:
        parser.error("This local test refuses to run against the production API.")
    if not args.frontend_url:
        parser.error("--frontend-url must not be empty.")
    if not args.extension_id:
        parser.error("--extension-id must not be empty.")
    if args.cdp_port <= 0 or args.cdp_port > 65535:
        parser.error("--cdp-port must be between 1 and 65535.")
    if "NARADA_API_KEY" not in os.environ:
        parser.error("Set NARADA_API_KEY before running this script.")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero.")

    return args


def _format_timestamp(timestamp_ms: int) -> str:
    timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return timestamp.isoformat(timespec="milliseconds")


def _is_cdp_browser_running(cdp_port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", cdp_port), timeout=0.25):
            return True
    except OSError:
        return False


def _find_extension_capable_browser(requested_path: Path | None) -> Path:
    if requested_path is not None:
        executable = requested_path.expanduser().resolve()
        if not executable.is_file() or not os.access(executable, os.X_OK):
            raise RuntimeError(f"Browser executable is not executable: {executable}")
        return executable

    cache_roots = (
        Path.home() / "Library" / "Caches" / "ms-playwright",
        Path.home() / ".cache" / "ms-playwright",
    )
    executable_patterns = (
        "chromium-*/chrome-mac*/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing",
        "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
        "chromium-*/chrome-linux*/chrome",
        "chromium-*/chrome-win*/chrome.exe",
    )
    candidates = [
        executable
        for cache_root in cache_roots
        for pattern in executable_patterns
        for executable in cache_root.glob(pattern)
        if executable.is_file() and os.access(executable, os.X_OK)
    ]
    if not candidates:
        raise RuntimeError(
            "No extension-capable Playwright Chromium installation was found. "
            "Run `uv run playwright install chromium` or pass --browser-executable."
        )
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _get_cdp_extension_ids(cdp_port: int) -> set[str]:
    with urllib.request.urlopen(
        f"http://127.0.0.1:{cdp_port}/json/list",
        timeout=1,
    ) as response:
        targets = json.load(response)

    extension_prefix = "chrome-extension://"
    return {
        url.removeprefix(extension_prefix).partition("/")[0]
        for target in targets
        if isinstance(target, dict)
        and isinstance((url := target.get("url")), str)
        and url.startswith(extension_prefix)
    }


async def _wait_for_extension(cdp_port: int, extension_id: str) -> None:
    seen_extension_ids: set[str] = set()
    for _ in range(50):
        try:
            seen_extension_ids = await asyncio.to_thread(
                _get_cdp_extension_ids,
                cdp_port,
            )
        except OSError:
            pass
        if extension_id in seen_extension_ids:
            return
        await asyncio.sleep(0.1)

    seen = ", ".join(sorted(seen_extension_ids)) or "none"
    raise RuntimeError(
        f"Chrome on CDP port {cdp_port} did not load local extension "
        f"{extension_id}. Extension IDs seen: {seen}."
    )


async def _launch_local_extension_browser(
    *,
    config: BrowserConfig,
    extension_path: Path,
) -> asyncio.subprocess.Process:
    extension_path = extension_path.resolve()
    manifest_path = extension_path / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError(
            f"Local extension build not found at {manifest_path}. "
            "Start the extension dev server before running this script."
        )

    config.user_data_dir = str(Path(config.user_data_dir).expanduser().resolve())
    process = await asyncio.create_subprocess_exec(
        config.executable_path,
        f"--user-data-dir={config.user_data_dir}",
        f"--profile-directory={config.profile_directory}",
        f"--remote-debugging-port={config.cdp_port}",
        f"--disable-extensions-except={extension_path}",
        f"--load-extension={extension_path}",
        "--no-default-browser-check",
        "--no-first-run",
        "about:blank",
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
        start_new_session=True,
    )

    for _ in range(100):
        if _is_cdp_browser_running(config.cdp_port):
            try:
                await _wait_for_extension(config.cdp_port, config.extension_id)
            except Exception:
                process.terminate()
                await process.wait()
                raise
            return process
        if process.returncode is not None:
            raise RuntimeError(
                f"Local Chrome exited during startup with code {process.returncode}."
            )
        await asyncio.sleep(0.1)

    process.terminate()
    await process.wait()
    raise RuntimeError(
        f"Timed out waiting for local Chrome on CDP port {config.cdp_port}."
    )


def _raise_clear_timestamp_error(error: ValidationError) -> NoReturn:
    missing_timestamps = any(
        item["type"] == "missing"
        and item["loc"]
        and item["loc"][-1] in {"startTs", "endTs"}
        for item in error.errors()
    )
    if missing_timestamps:
        raise RuntimeError(
            "The local caddie process returned an action trace without timestamps. "
            "Restart the backend after switching to "
            "sp/operator-action-trace-timestamps, then run this script again."
        ) from error
    raise error


def _validate_trace(
    trace: Sequence[object] | None,
) -> list[OperatorActionTraceItem]:
    if not trace:
        raise AssertionError("Operator returned no action trace.")

    actions: list[OperatorActionTraceItem] = []
    for index, item in enumerate(trace):
        if not isinstance(item, OperatorActionTraceItem):
            raise AssertionError(
                f"Action {index} has unexpected trace type {type(item).__name__}."
            )
        actions.append(item)

    if len(actions) < 2:
        raise AssertionError(
            "Expected at least one browser action followed by the done action."
        )

    for index, action in enumerate(actions):
        if action.end_ts < action.start_ts:
            raise AssertionError(
                f"Action {index} ends before it starts: "
                f"{action.start_ts} > {action.end_ts}."
            )
        if index > 0 and action.start_ts != actions[index - 1].end_ts:
            raise AssertionError(
                f"Action {index} is not contiguous: startTs={action.start_ts}, "
                f"previous endTs={actions[index - 1].end_ts}."
            )

    if not actions[-1].action.startswith("Done:"):
        raise AssertionError("The final trace item is not the done action.")

    return actions


async def _run(args: argparse.Namespace) -> None:
    os.environ["NARADA_API_BASE_URL"] = args.base_url.rstrip("/")

    browser_executable = _find_extension_capable_browser(args.browser_executable)
    config = BrowserConfig(
        executable_path=str(browser_executable),
        user_data_dir=str(args.user_data_dir),
        cdp_port=args.cdp_port,
        initialization_url=f"{args.frontend_url.rstrip('/')}/initialize",
        extension_id=args.extension_id,
    )
    browser_process: asyncio.subprocess.Process | None = None
    if _is_cdp_browser_running(config.cdp_port):
        await _wait_for_extension(config.cdp_port, config.extension_id)
        print(f"Reusing the local dev Chrome process on CDP port {config.cdp_port}.")
    else:
        print(
            f"Launching the local extension from {args.extension_path} "
            f"in {browser_executable} on CDP port {config.cdp_port}."
        )
        browser_process = await _launch_local_extension_browser(
            config=config,
            extension_path=args.extension_path,
        )

    environment = BrowserEnvironment(config=config, attach_to_existing=True)
    agent = Agent(environment=environment)
    run_started_ms = int(time.time() * 1000)

    try:
        try:
            response = await agent.run(prompt=args.prompt, timeout=args.timeout)
        except ValidationError as error:
            _raise_clear_timestamp_error(error)
        run_finished_ms = int(time.time() * 1000)
        actions = _validate_trace(response.action_trace)

        print(f"Request: {response.request_id}")
        print(f"Response: {response.text}")
        print()
        print("Operator action timing:")
        for index, action in enumerate(actions, start=1):
            duration_ms = action.end_ts - action.start_ts
            print(
                f"{index:>2}. {action.action}\n"
                f"    start: {_format_timestamp(action.start_ts)} "
                f"({action.start_ts})\n"
                f"    end:   {_format_timestamp(action.end_ts)} "
                f"({action.end_ts})\n"
                f"    duration: {duration_ms} ms"
            )

        total_duration_ms = actions[-1].end_ts - actions[0].start_ts
        print()
        print(
            f"PASS: {len(actions)} contiguous actions; "
            f"trace duration={total_duration_ms} ms; "
            f"client elapsed={run_finished_ms - run_started_ms} ms."
        )
    finally:
        try:
            await environment.close(timeout=30)
        finally:
            if browser_process is not None and browser_process.returncode is None:
                browser_process.terminate()
                try:
                    await asyncio.wait_for(browser_process.wait(), timeout=10)
                except TimeoutError:
                    browser_process.kill()
                    await browser_process.wait()


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
