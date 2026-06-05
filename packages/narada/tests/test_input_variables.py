from io import BytesIO

import pytest
from narada import RemoteBrowserEnvironment


@pytest.mark.asyncio
async def test_input_variable_files_normalize_to_current_file_variable_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env = RemoteBrowserEnvironment(
        auth_headers={},
        browser_window_id="browser-window-123",
    )
    upload_calls = []

    async def fake_upload_file_impl(*, file):
        upload_calls.append(file)
        return {"key": "user-user-123/20260426000000000000-report.txt"}

    monkeypatch.setattr(env, "_upload_file_impl", fake_upload_file_impl)

    file_obj = BytesIO(b"hello")
    file_obj.name = "/tmp/report.txt"

    normalized = await env._normalize_input_variables(input_variables={"doc": file_obj})

    assert upload_calls == [file_obj]
    assert normalized == {
        "doc": {
            "source": "remoteDispatchUpload",
            "id": "user-user-123/20260426000000000000-report.txt",
            "filename": "report.txt",
            "mimeType": "text/plain",
        }
    }


def test_cloud_backed_remote_environment_exposes_session_id_for_remote_dispatch() -> (
    None
):
    remote_env = RemoteBrowserEnvironment(
        auth_headers={},
        browser_window_id="browser-window-456",
        cloud_browser_session_id="session-456",
    )

    assert remote_env.cloud_browser_session_id == "session-456"
