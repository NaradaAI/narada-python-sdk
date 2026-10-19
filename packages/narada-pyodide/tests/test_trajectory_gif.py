from __future__ import annotations

from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "trajectory_gif",
    [
        None,
        {"status": "success", "frameCount": 3, "completionConfirmed": True},
        {"status": "success", "frameCount": 3, "completionConfirmed": False},
        {
            "status": "error",
            "frameCount": 3,
            "stage": "encoding",
            "code": "encoding_failed",
            "message": "GIF worker failed",
        },
        {
            "status": "error",
            "frameCount": 0,
            "stage": "capture",
            "code": "no_frames",
            "message": "No screenshots were captured",
        },
        {"status": "delegated", "ownerRequestId": "parent-request"},
    ],
)
@pytest.mark.parametrize("task_status", ["success", "error"])
async def test_pyodide_agent_preserves_trajectory_outcome_and_task_result(
    pyodide_narada: ModuleType,
    trajectory_gif: dict[str, Any] | None,
    task_status: str,
) -> None:
    env = pyodide_narada.Environment(api_key="test-key")
    response_content = {
        "text": "Task output",
        "output": {"type": "structured", "content": {"answer": 42}},
        "structuredOutput": {"answer": 42},
    }
    if trajectory_gif is not None:
        response_content["trajectoryGif"] = trajectory_gif
    env._dispatch_request = AsyncMock(
        return_value={
            "requestId": "request-1",
            "status": task_status,
            "response": response_content,
            "usage": {"actions": 1, "credits": 2},
        }
    )

    response = await pyodide_narada.Agent(environment=env).run(
        "Run a task", generate_gif=True
    )

    assert response.request_id == "request-1"
    assert response.status == task_status
    assert response.text == "Task output"
    assert response.output.content == {"answer": 42}
    assert response.structured_output == {"answer": 42}
    assert response.usage.actions == 1
    assert response.usage.credits == 2
    assert env._dispatch_request.await_args.kwargs["generate_gif"] is True
    if trajectory_gif is None:
        assert response.trajectory_gif is None
        assert "trajectoryGif" not in response.model_dump(
            by_alias=True, exclude_none=True
        )
    else:
        assert isinstance(
            response.trajectory_gif,
            (
                pyodide_narada.TrajectoryGifSuccess,
                pyodide_narada.TrajectoryGifError,
                pyodide_narada.TrajectoryGifDelegated,
            ),
        )
        assert response.trajectory_gif.model_dump(by_alias=True) == trajectory_gif
        assert response.model_dump(by_alias=True)["trajectoryGif"] == trajectory_gif
