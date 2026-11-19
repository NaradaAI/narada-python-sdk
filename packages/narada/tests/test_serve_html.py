import base64
from unittest.mock import AsyncMock

import pytest
from narada import Agent, BaseBrowserEnvironment, UploadedFileVariable
from narada_core.actions.models import ServeHtmlRequest
from narada_core.tracing.model import ApaStepTrace
from pydantic import TypeAdapter


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "file",
    [
        {
            "source": "remoteDispatchUpload",
            "id": "upload-1",
            "filename": "page.html",
            "mimeType": "text/html",
        },
        {
            "source": "agentStudioAttachment",
            "id": "attachment-1",
            "filename": "page.html",
            "mimeType": "text/html",
            "itemId": "workflow-1",
        },
    ],
)
async def test_serve_html_dispatches_file_reference(
    monkeypatch: pytest.MonkeyPatch, file: UploadedFileVariable
) -> None:
    environment = BaseBrowserEnvironment(auth_headers={}, browser_window_id="window-1")
    dispatch = AsyncMock()
    monkeypatch.setattr(environment, "_run_extension_action", dispatch)
    await Agent(environment=environment).serve_html(file=file)

    request = dispatch.await_args.args[0]
    assert isinstance(request, ServeHtmlRequest)
    assert request.model_dump() == {"name": "serve_html", "file": file}
    assert dispatch.await_args.kwargs == {"timeout": 60}


@pytest.mark.asyncio
async def test_serve_html_uploads_inline_bytes_before_dispatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    environment = BaseBrowserEnvironment(auth_headers={}, browser_window_id="window-1")
    uploaded_reference = {
        "source": "remoteDispatchUpload",
        "id": "upload-1",
        "filename": "page.html",
        "mimeType": "text/html",
    }
    upload = AsyncMock(return_value=uploaded_reference)
    dispatch = AsyncMock()
    monkeypatch.setattr(environment, "_upload_input_variable_file", upload)
    monkeypatch.setattr(environment, "_run_extension_action", dispatch)

    await Agent(environment=environment).serve_html(
        file={
            "source": "inMemoryFile",
            "filename": "page.html",
            "mimeType": "text/html",
            "base64": base64.b64encode(b"<h1>Hello</h1>").decode(),
        }
    )

    uploaded_file = upload.await_args.kwargs["input_variable_value"]
    assert uploaded_file.name == "page.html"
    assert uploaded_file.getvalue() == b"<h1>Hello</h1>"
    assert dispatch.await_args.args[0].file == uploaded_reference


@pytest.mark.asyncio
async def test_serve_html_accepts_local_file_handle(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    environment = BaseBrowserEnvironment(auth_headers={}, browser_window_id="window-1")
    upload = AsyncMock(
        return_value={
            "source": "remoteDispatchUpload",
            "id": "upload-1",
            "filename": "page.html",
            "mimeType": "text/html",
        }
    )
    dispatch = AsyncMock()
    monkeypatch.setattr(environment, "_upload_input_variable_file", upload)
    monkeypatch.setattr(environment, "_run_extension_action", dispatch)
    path = tmp_path / "page.html"
    path.write_text("<h1>Hello</h1>")

    with path.open("rb") as file:
        await Agent(environment=environment).serve_html(file=file)

    assert upload.await_args.kwargs["input_variable_value"].name == str(path)
    assert dispatch.await_args.args[0].file["filename"] == "page.html"


def test_serve_html_step_trace_parses() -> None:
    trace = TypeAdapter(ApaStepTrace).validate_python(
        {"step_type": "serveHtml", "description": "Served page.html"}
    )
    assert trace.step_type == "serveHtml"
