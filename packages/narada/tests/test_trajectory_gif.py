from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest
from narada import (
    Agent,
    Environment,
    TrajectoryGifDelegated,
    TrajectoryGifError,
    TrajectoryGifSuccess,
)
from narada_core.actions.models import AgentResponse
from pydantic import ValidationError

GIF_OUTCOMES = [
    None,
    {"status": "success", "frameCount": 3, "completionConfirmed": True},
    {"status": "success", "frameCount": 3, "completionConfirmed": False},
    {
        "status": "error",
        "frameCount": 3,
        "stage": "download",
        "code": "timeout",
        "message": "Trajectory finalization timed out",
    },
    {
        "status": "error",
        "frameCount": 0,
        "stage": "capture",
        "code": "no_frames",
        "message": "No screenshots were captured",
    },
    {"status": "delegated", "ownerRequestId": "parent-request"},
]


@pytest.mark.asyncio
@pytest.mark.parametrize("trajectory_gif", GIF_OUTCOMES)
@pytest.mark.parametrize("task_status", ["success", "error"])
async def test_agent_preserves_trajectory_outcome_and_task_result(
    trajectory_gif: dict[str, Any] | None,
    task_status: str,
) -> None:
    env = Environment(auth_headers={})
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

    response = await Agent(environment=env).run("Run a task", generate_gif=True)

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
        assert response.trajectory_gif is not None
        assert response.trajectory_gif.model_dump(by_alias=True) == trajectory_gif
        assert response.model_dump(by_alias=True)["trajectoryGif"] == trajectory_gif


def test_trajectory_models_accept_wire_aliases_and_expose_python_attributes() -> None:
    success = TrajectoryGifSuccess.model_validate(GIF_OUTCOMES[1])
    assert success.frame_count == 3
    assert success.completion_confirmed is True
    error = TrajectoryGifError.model_validate(GIF_OUTCOMES[3])
    assert error.stage == "download"
    assert error.code == "timeout"
    delegated = TrajectoryGifDelegated.model_validate(GIF_OUTCOMES[5])
    assert delegated.owner_request_id == "parent-request"

    assert (
        TrajectoryGifSuccess(
            status="success", frame_count=3, completion_confirmed=False
        ).model_dump(by_alias=True)
        == GIF_OUTCOMES[2]
    )


@pytest.mark.parametrize(
    "trajectory_gif",
    [
        {"status": "success", "frameCount": 1},
        {"status": "success", "frameCount": -1, "completionConfirmed": True},
        {"status": "success", "frameCount": "3", "completionConfirmed": True},
        {"status": "success", "frameCount": 3, "completionConfirmed": "false"},
        {"status": "delegated"},
        {
            "status": "error",
            "frameCount": 3,
            "stage": "encoding",
            "code": "unknown_code",
            "message": "Failed",
        },
    ],
)
def test_agent_response_rejects_invalid_trajectory_metadata(
    trajectory_gif: dict[str, Any],
) -> None:
    with pytest.raises(ValidationError):
        AgentResponse.model_validate(
            {
                "request_id": "request-1",
                "status": "success",
                "text": "Task output",
                "output": {"type": "text", "content": "Task output"},
                "structured_output": None,
                "usage": {"actions": 1, "credits": 2},
                "trajectoryGif": trajectory_gif,
            }
        )
