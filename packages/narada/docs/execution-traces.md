# Workflow execution traces

`Agent.run(require_execution_trace=True)` asks the server to admit canonical
trace capture before executing a workflow. Any authenticated caller may opt in;
existing observability, HIPAA and zero-data-retention settings can prohibit capture.
The server rejects a required trace before execution when those settings exclude
the request. Ordinary calls keep their current behavior when the option is omitted.
It also applies to a critic call.

The SDK uses existing `NARADA_API_KEY`, explicit `api_key`, or `auth_headers`
authentication. It does not collect keys in chat or add an authorization flow.
The existing `NARADA_API_BASE_URL` selects a different Narada environment when
intentionally configured.

```python
import asyncio
import os
from pathlib import Path

from narada import Agent, RemoteBrowserEnvironment


async def main():
    # Borrow the browser prepared by the launcher. Its owner closes it explicitly.
    env = RemoteBrowserEnvironment(
        browser_window_id=os.environ["NARADA_BROWSER_WINDOW_ID"],
    )
    response = await Agent(environment=env).run(
        "Inspect the current page and summarize its visible headings.",
        require_execution_trace=True,
    )
    print(response.text)
    trace = await env.execution_traces.fetch(
        request_id=response.request_id,
        destination=Path("artifacts") / response.request_id / "execution-trace",
        expected_trace_id=(response.execution_trace_context or {}).get("traceId"),
    )
    print(trace.status)


asyncio.run(main())
```

`AgentResponse.execution_trace_context` preserves the server context. The critic
result also carries `request_id` and `execution_trace_context` when available.
Pyodide preserves these response fields; local downloading and runner integration
are CPython-only.

`fetch(...)` only retrieves existing evidence. The result has `status`
(`complete`, `pending`, or `unavailable`), `request_id`, and, on success,
`trace_id` and `path`. `ExecutionTraceError.reason` reports a bounded failure
such as `denied`, `timeout`, or `trace_identity_mismatch`. A failed download does
not imply that the action failed. Retry retrieval for the exact request after
diagnosing the evidence failure; never redispatch solely to recover its trace.

The authenticated request API returns a temporary archive URL. A separate HTTP
session downloads it without Narada auth headers or cookies. The signed URL is
not returned in the public result or written into SDK evidence receipts; archive
redirects are rejected. Limits are 64 MiB compressed, 256 MiB extracted, 10,000
entries, and a default 60-second retrieval deadline. Canonical context/index,
segments/events/scopes, timeline-index and timeline files are required, with
matching trace identity. Traversal, symlinks, duplicate/case-colliding paths and
Windows-special paths are rejected. Publication is atomic after validation and
existing destination directories are preserved. Capture admission cannot
guarantee that later uploads or downloads succeed.

## Automatic runner evidence

A local runner may inject `NARADA_RUN_DIR` into its workflow child. The SDK
validates it when constructing an `Environment`; no decorator, callback setup,
`sitecustomize`, or monkeypatch is needed. The runner uses the same
`NARADA_API_KEY` as ordinary SDK usage; no separate plugin credential is required.

The binding must be an absolute directory with a lowercase 32-hex-character
basename, regular `manifest.json` and `output.log` files, and an `artifacts/`
directory. These entries cannot be symlinks. The manifest includes:

```json
{
  "schemaVersion": 1,
  "runId": "0123456789abcdef0123456789abcdef",
  "status": "running"
}
```

The ID must match the directory basename; additional runner fields are allowed.
Malformed bindings fail before dispatch. An unset variable leaves normal SDK
behavior unchanged. A valid binding requires trace capture on every SDK dispatch.

After admission the SDK writes `artifacts/requests/<request-id>/evidence.json`.
It saves the completed API response in `response.json` **before** retrieving the
canonical archive into `execution-trace/`. The evidence receipt reports `pending`,
`complete`, `unavailable`, or `failed`, with request/trace IDs and primary/critic
linkage. Critic linkage is local evidence metadata; it does not turn a completed
primary request into an active server-side parent. Nested browser workflows are
represented by their canonical trace segments.

The SDK never edits the runner manifest or output log. Responses/traces are
sensitive business content intended for the customer's chosen coding agent;
setup must disclose that use. The integration does not additionally log request
prompts, auth headers, credentials or signed archive locations. Business responses
and page content can themselves contain sensitive customer data.

Retrieval has its own bound after the remote workflow completes. If it fails,
the response and original `AgentResponse` remain usable and evidence is marked
incomplete. An interrupted remote wait records `dispatch_not_completed`; it does
not claim that the remote action was canceled. The runner owns cancellation and
process cleanup.

`BrowserEnvironment.start()` already releases its Playwright connection after
initialization. Borrow its window through `RemoteBrowserEnvironment` and leave
closure to the browser owner: `RemoteBrowserEnvironment.close()` closes the
actual window, so it is not per-workflow resource cleanup.
