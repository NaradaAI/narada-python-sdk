from unittest.mock import AsyncMock

import pytest
from narada import Agent, BaseBrowserEnvironment
from narada_core.actions.models import (
    GetMatchingElementsRequest,
    GetMatchingElementsResponse,
)
from narada_core.tracing.model import ApaStepTrace
from pydantic import TypeAdapter, ValidationError


@pytest.mark.asyncio
async def test_get_matching_elements_dispatches_selector_and_returns_all_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = BaseBrowserEnvironment(auth_headers={}, browser_window_id="window-1")
    results = [
        {"text": "First", "url": "https://example.com/first"},
        {"text": "Second", "url": "https://example.com/second"},
    ]
    response = GetMatchingElementsResponse.model_validate({"results": results})
    run_extension_action = AsyncMock(return_value=response)
    monkeypatch.setattr(environment, "_run_extension_action", run_extension_action)

    actual = await Agent(environment=environment).get_matching_elements(
        selector="  a.result  ", timeout=30
    )

    request, response_model = run_extension_action.await_args.args
    assert isinstance(request, GetMatchingElementsRequest)
    assert request.model_dump() == {
        "name": "get_matching_elements",
        "selector": "a.result",
    }
    assert response_model is GetMatchingElementsResponse
    assert run_extension_action.await_args.kwargs == {"timeout": 30}
    assert actual == results


@pytest.mark.asyncio
async def test_get_matching_elements_rejects_empty_selector_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = BaseBrowserEnvironment(auth_headers={}, browser_window_id="window-1")
    run_extension_action = AsyncMock()
    monkeypatch.setattr(environment, "_run_extension_action", run_extension_action)

    with pytest.raises(ValueError, match="selector must not be empty"):
        await Agent(environment=environment).get_matching_elements(selector="  ")

    run_extension_action.assert_not_awaited()


def test_matching_elements_models_require_text_and_url_and_parse_step_trace() -> None:
    with pytest.raises(ValidationError):
        GetMatchingElementsResponse.model_validate({"results": [{"text": "Only text"}]})

    trace = TypeAdapter(ApaStepTrace).validate_python(
        {
            "step_type": "getMatchingElements",
            "description": "Stored 2 matching elements",
        }
    )
    assert trace.step_type == "getMatchingElements"
