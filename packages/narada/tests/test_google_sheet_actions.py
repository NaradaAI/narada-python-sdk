from unittest.mock import AsyncMock

import pytest
from narada import Agent, BaseBrowserEnvironment
from narada_core.actions.models import (
    AppendGoogleSheetRowRequest,
    AppendGoogleSheetRowResponse,
)


@pytest.mark.asyncio
async def test_append_google_sheet_row_dispatches_object_and_returns_updated_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = BaseBrowserEnvironment(
        api_key="test-api-key",
        browser_window_id="browser-window-id",
    )
    response = AppendGoogleSheetRowResponse.model_validate(
        {"updatedRange": "People!A4:D4"}
    )
    run_extension_action = AsyncMock(return_value=response)
    monkeypatch.setattr(environment, "_run_extension_action", run_extension_action)

    result = await Agent(environment=environment).append_google_sheet_row(
        spreadsheet_id="spreadsheet-id",
        range="People!A1:D1",
        row={"Name": "Ada", "Age": 36, "Active": True, "Notes": None},
        timeout=30,
    )

    request, response_model = run_extension_action.await_args.args
    assert isinstance(request, AppendGoogleSheetRowRequest)
    assert request.model_dump() == {
        "name": "append_google_sheet_row",
        "spreadsheet_id": "spreadsheet-id",
        "range": "People!A1:D1",
        "row": {"Name": "Ada", "Age": 36, "Active": True, "Notes": None},
    }
    assert response_model is AppendGoogleSheetRowResponse
    assert run_extension_action.await_args.kwargs == {"timeout": 30}
    assert result.updated_range == "People!A4:D4"
