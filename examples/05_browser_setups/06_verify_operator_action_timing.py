import asyncio
import os

from narada import Agent, AgentKind, CloudBrowserEnvironment
from narada_core.tracing.model import OperatorActionTraceItem


def walk_action_trace(
    items: list[OperatorActionTraceItem],
) -> list[OperatorActionTraceItem]:
    flattened: list[OperatorActionTraceItem] = []
    for item in items:
        flattened.append(item)
        if item.children is not None:
            flattened.extend(walk_action_trace(item.children))
    return flattened


def assert_timing(trace: list[OperatorActionTraceItem]) -> None:
    items = walk_action_trace(trace)
    assert items, "Expected at least one timed Operator browser action."

    for item in items:
        assert item.end_ts >= item.start_ts
        assert item.duration_ms == item.end_ts - item.start_ts

    done_items = [item for item in trace if item.action.startswith("Done:")]
    assert done_items, "Expected the Operator trace to end with a Done action."


async def main() -> None:
    if not os.environ.get("NARADA_API_KEY"):
        raise RuntimeError(
            "Set NARADA_API_KEY to a production API key before running this example."
        )

    env = CloudBrowserEnvironment(
        session_name="operator-action-timing-smoke-test",
        session_timeout=600,
    )
    agent = Agent(environment=env, kind=AgentKind.OPERATOR)

    try:
        response = await agent.run(
            "Open https://example.com, click the More information link, "
            "then report the destination page title."
        )
        assert response.action_trace is not None, (
            "Operator response did not include an action trace."
        )

        for item in response.action_trace:
            print(
                f"{item.action}: start={item.start_ts}, end={item.end_ts}, "
                f"duration={item.duration_ms}ms"
            )

        assert_timing(response.action_trace)
        print(f"Timing smoke test passed for request {response.request_id}.")
    finally:
        await env.close()


if __name__ == "__main__":
    asyncio.run(main())
