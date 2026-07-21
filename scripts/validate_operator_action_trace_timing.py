"""Run an Operator task against dev and validate action-trace timestamps.

Example:

    export NARADA_API_KEY="..."
    uv run python scripts/validate_operator_action_trace_timing.py \
        --base-url "https://<dev-api-host>/fast/v2"

The script refuses the production API endpoint, creates a temporary cloud
browser session, and always closes that session before exiting.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from collections.abc import Sequence
from datetime import UTC, datetime

from narada import Agent, CloudBrowserEnvironment
from narada_core.tracing.model import OperatorActionTraceItem

PRODUCTION_API_BASE_URL = "https://api.narada.ai/fast/v2"
DEFAULT_PROMPT = (
    "Go to https://example.com, read the page heading, and tell me the heading."
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate Operator action-trace timestamps against a dev API.",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("NARADA_API_BASE_URL"),
        help="Dev API base URL ending in /fast/v2. Defaults to NARADA_API_BASE_URL.",
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

    if not args.base_url:
        parser.error("Pass --base-url or set NARADA_API_BASE_URL.")
    if args.base_url.rstrip("/") == PRODUCTION_API_BASE_URL:
        parser.error("This dev test refuses to run against the production API.")
    if "NARADA_API_KEY" not in os.environ:
        parser.error("Set NARADA_API_KEY before running this script.")
    if args.timeout <= 0:
        parser.error("--timeout must be greater than zero.")

    return args


def _format_timestamp(timestamp_ms: int) -> str:
    timestamp = datetime.fromtimestamp(timestamp_ms / 1000, tz=UTC)
    return timestamp.isoformat(timespec="milliseconds")


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

    environment = CloudBrowserEnvironment(
        session_name="operator-action-trace-timing-dev-test",
        session_timeout=args.timeout + 120,
    )
    agent = Agent(environment=environment)
    run_started_ms = int(time.time() * 1000)

    try:
        response = await agent.run(prompt=args.prompt, timeout=args.timeout)
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
        await environment.close(timeout=30)


def main() -> None:
    args = _parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
