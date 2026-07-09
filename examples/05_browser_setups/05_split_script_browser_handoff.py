import argparse
import asyncio
import json
import tempfile
from pathlib import Path
from typing import Any

from narada import Agent, BrowserEnvironment, RemoteBrowserEnvironment


STATE_PATH = Path(tempfile.gettempdir()) / "narada_split_script_browser_handoff.json"
DEFAULT_PROMPT = (
    'Search for "LLM Compiler" on Google and open the first arXiv paper on the '
    "results page, then tell me who the authors are."
)


def load_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        raise SystemExit(
            f"No saved browser state found at {STATE_PATH}. Run this example with "
            "`start` first."
        )

    state = json.loads(STATE_PATH.read_text())
    browser_window_id = state.get("browser_window_id")
    if not isinstance(browser_window_id, str) or not browser_window_id:
        raise SystemExit(
            f"Saved browser state at {STATE_PATH} is missing `browser_window_id`."
        )

    return state


async def start_browser() -> None:
    env = BrowserEnvironment()
    await env.start()

    state = {
        "browser_window_id": env.browser_window_id,
        "browser_process_id": env.browser_process_id,
    }
    STATE_PATH.write_text(json.dumps(state, indent=2) + "\n")

    print(f"Started browser window: {env.browser_window_id}")
    if env.browser_process_id is not None:
        print(f"Browser process ID: {env.browser_process_id}")
    print(f"Saved handoff state: {STATE_PATH}")


async def run_task(prompt: str) -> None:
    state = load_state()
    env = RemoteBrowserEnvironment(browser_window_id=state["browser_window_id"])
    agent = Agent(environment=env)

    response = await agent.run(prompt=prompt)
    print("Response:", response.model_dump_json(indent=2))


async def close_browser() -> None:
    state = load_state()
    env = RemoteBrowserEnvironment(browser_window_id=state["browser_window_id"])

    await env.close()
    STATE_PATH.unlink(missing_ok=True)
    print(f"Closed browser window: {state['browser_window_id']}")
    print(f"Removed handoff state: {STATE_PATH}")


async def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Demonstrate starting a Narada browser in one process and reusing it "
            "from later processes."
        )
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("start", help="Start a browser and save its handoff IDs.")

    run_parser = subparsers.add_parser(
        "run", help="Run a task in the previously started browser window."
    )
    run_parser.add_argument(
        "prompt",
        nargs="?",
        default=DEFAULT_PROMPT,
        help="Prompt to run in the existing browser window.",
    )

    subparsers.add_parser(
        "close", help="Close the previously started browser window and clear state."
    )

    args = parser.parse_args()
    if args.command == "start":
        await start_browser()
    elif args.command == "run":
        await run_task(args.prompt)
    elif args.command == "close":
        await close_browser()


if __name__ == "__main__":
    asyncio.run(main())
