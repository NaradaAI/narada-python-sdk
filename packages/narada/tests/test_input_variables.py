from io import BytesIO

import pytest
from narada.window import BaseBrowserWindow


@pytest.mark.asyncio
async def test_input_variable_files_normalize_to_current_file_variable_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    window = BaseBrowserWindow(
        auth_headers={},
        base_url="https://api.example.test",
        browser_window_id="browser-window-123",
    )
    upload_calls = []

    async def fake_upload_file_impl(*, file):
        upload_calls.append(file)
        return {"key": "user-user-123/20260426000000000000-report.txt"}

    monkeypatch.setattr(window, "_upload_file_impl", fake_upload_file_impl)

    file_obj = BytesIO(b"hello")
    file_obj.name = "/tmp/report.txt"

    normalized = await window._normalize_input_variables(
        input_variables={"doc": file_obj}
    )

    assert upload_calls == [file_obj]
    assert normalized == {
        "doc": {
            "source": "remoteDispatchUpload",
            "id": "user-user-123/20260426000000000000-report.txt",
            "filename": "report.txt",
            "mimeType": "text/plain",
        }
    }
