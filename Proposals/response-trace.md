# Response Trace Shape

## Status and scope

This document defines the proposed public response-trace shape for the Narada Python SDK. The
models live in `narada_core.tracing.response_trace`.

The design covers:

- GUI Agent Studio workflow runs
- direct agent runs made through the local Python SDK
- a single `Trace` record followed by a flat list of `Span` records
- typed workflow, GUI-step, control-flow, agent, and agent-action span data

The design does not define how traces are collected, exported, or stored. It does not introduce
OpenTelemetry, a live tracing runtime, or Python Agent Studio workflow tracing. Existing
`action_trace` and `workflow_trace` fields are unaffected by the shape itself.

The trace and span envelopes and the span-data taxonomy are represented by the current Stage 1
models. The `input` and `output` fields described below are the proposed next schema additions and
are not yet present in those models.

## Design summary

A returned trace is represented as:

```python
list[Trace | Span[Any]]
```

The first record is the trace envelope. Every remaining record is a span associated with that
trace. Spans are flat in the returned list; `parent_id` reconstructs the execution tree.

```text
Trace
└── WorkflowSpanData
    ├── GuiStepSpanData
    ├── GuiStepSpanData (agent)
    │   └── AgentSpanData
    │       └── AgentActionSpanData
    ├── GuiStepSpanData (loop)
    │   ├── IterationSpanData
    │   └── IterationSpanData
    └── GuiStepSpanData (run custom agent)
        └── WorkflowSpanData
```

`Span` is generic so callers with a `Span[AgentSpanData]`, for example, retain typed access to the
fields on `AgentSpanData`. `SpanDataUnion` separately supports decoding JSON when the subtype is not
known in advance.

## Trace record

```json
{
  "object": "trace",
  "trace_id": "trace_123",
  "name": "Process renewals",
  "group_id": null,
  "metadata": null
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `object` | `"trace"` | Record discriminator. |
| `trace_id` | `str` | Unique trace identifier. |
| `name` | `str` | Human-readable name for the overall run. |
| `group_id` | `str \| None` | Optional correlation identifier for related traces. |
| `metadata` | `dict[str, Any] \| None` | Optional user-provided metadata. |

The Python model and its normal JSON serialization use the same field names. There are no aliases
such as `id` or `workflow_name` on the trace envelope.

## Span record

```json
{
  "object": "trace.span",
  "span_id": "span_123",
  "trace_id": "trace_123",
  "parent_id": null,
  "started_at": "2026-07-28T18:00:00Z",
  "ended_at": "2026-07-28T18:00:05Z",
  "span_data": {
    "type": "workflow"
  },
  "error": null
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `object` | `"trace.span"` | Record discriminator. |
| `span_id` | `str` | Unique span identifier. |
| `trace_id` | `str` | Identifier of the containing trace. |
| `parent_id` | `str \| None` | Parent span identifier; `None` identifies a root span. |
| `started_at` | `str \| None` | UTC ISO 8601 start timestamp. |
| `ended_at` | `str \| None` | UTC ISO 8601 end timestamp. |
| `span_data` | `SpanData` | Discriminated payload describing the operation. |
| `error` | `SpanError \| None` | Error associated with this span. |

`ended_at` cannot precede `started_at`. Both timestamps must be timezone-aware UTC values when
present.

Errors use:

```json
{
  "message": "Step failed",
  "data": {
    "error_type": "system"
  }
}
```

`data` is a required but nullable field for structured context.

## Span data

Every span-data model has a `type` discriminator. That discriminator selects the concrete payload
shape.

### Workflow spans

`WorkflowSpanData` represents one executed GUI workflow:

```json
{
  "type": "workflow",
  "workflow_name": "Process renewals",
  "workflow_id": "workflow_123",
  "status": "success",
  "request_id": "request_123",
  "output_variables": {
    "renewal_date": "2027-01-01"
  }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `workflow_name` | `str` | Display name of the workflow definition. |
| `workflow_id` | `str` | Stable workflow-definition identifier. |
| `status` | `WorkflowSpanStatus` | Remote workflow-dispatch status. |
| `request_id` | `str \| None` | Request identifier used to look up the workflow run. |
| `output_variables` | `dict[str, Any] \| None` | Actual output-variable names and runtime values. |

Workflow statuses are `pending`, `input-required`, `success`, `error`, and `expired`.

Every nested custom workflow receives its own `WorkflowSpanData`. A successful
`gui_step.run_custom_agent` span is its parent; the nested workflow is not summarized through a
separate link object.

### GUI-step spans

All GUI-step span data inherits these fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `type` | `gui_step.<step_type>` | Snake-case discriminator for the concrete GUI step. |
| `name` | `str \| None` | Optional user-facing step label. |
| `step_id` | `str` | Identifier of the step in the workflow definition. |
| `status` | `GuiStepSpanStatus` | Terminal status reported for this execution. |
| `description` | `str \| None` | User-facing description produced during execution. |
| `starting_url` | `str \| None` | Browser URL captured immediately before the step started. |
| `input` | `dict[str, Any] \| None` | Effective values supplied to the step at runtime. |
| `output` | `dict[str, Any] \| None` | Values actually returned or updated by the step. |

GUI-step statuses are `success`, `error`, `aborted`, and `end_tree`.

`starting_url` is execution context, not the input or output of the step. For example, a Go to URL
step starts on one page and receives a configured destination URL as input. The step does not
produce a `final_url` output unless a runtime producer actually returns one. The current shape
therefore does not define `final_url`.

#### Input and output rule

GUI-step span data should add two nullable dictionaries:

```python
input: dict[str, Any] | None = None
output: dict[str, Any] | None = None
```

The null and empty-object cases are different:

- `None` means the producer did not capture the input or output.
- `{}` means the producer captured it and the step legitimately has no input or output.

The dictionaries follow these rules:

- Input contains the values represented by user-visible controls in the GUI step editor: text
  fields, selectors, dropdowns, toggles, attachments, variable references, and similar configured
  values.
- Input contains the effective values used for this execution after runtime variable resolution.
  Secret values are redacted rather than returned.
- Output contains only values actually returned or updated during execution, such as an agent
  response body or `output_variables: dict[str, Any]`.
- Context observed around the execution, such as `starting_url`, remains a named context field.
- The trace must not infer or manufacture outputs. A Go to URL step, for example, may have a URL
  input and no output.
- Authored condition strings retain their variable references when they identify a selected branch
  or catch condition.

This keeps the schema useful for debugging without making the response look more precise than the
runtime data actually is.

#### Representative input and output shapes

A Go to URL step has a configured destination but no returned output:

```json
{
  "type": "gui_step.go_to_url",
  "step_id": "step_go_to_url",
  "status": "success",
  "starting_url": "https://example.test/orders",
  "input": {
    "url": "https://example.test/orders/481"
  },
  "output": {}
}
```

There is deliberately no `final_url`. If a caller needs the current page URL as a result, the
workflow can execute a Get URL step:

```json
{
  "type": "gui_step.get_url",
  "step_id": "step_get_url",
  "status": "success",
  "starting_url": "https://example.test/orders/481",
  "input": {
    "output_variable": "current_url"
  },
  "output": {
    "output_variables": {
      "current_url": "https://example.test/orders/481"
    }
  }
}
```

An HTTP Request step records the effective request, with credentials redacted, and only the
response values the runtime actually returns:

```json
{
  "type": "gui_step.http_request",
  "step_id": "step_http",
  "status": "success",
  "starting_url": null,
  "input": {
    "method": "POST",
    "url": "https://api.example.test/orders/481",
    "headers": {
      "Content-Type": "application/json"
    },
    "auth": {
      "type": "bearer",
      "token": "[REDACTED]"
    },
    "body_mode": "raw",
    "body": "{\"status\":\"approved\"}",
    "timeout_ms": 30000,
    "output_variable": "request_response"
  },
  "output": {
    "response_body": {
      "id": "481",
      "status": "approved"
    },
    "output_variables": {
      "request_response": {
        "id": "481",
        "status": "approved"
      }
    }
  }
}
```

The shape does not add a status code, response headers, or other HTTP information unless the
executor actually returns it.

Steps that update workflow variables use one standard output key:

```json
{
  "output_variables": {
    "variable_name": "runtime value"
  }
}
```

This applies to Get URL, HTML and screenshot steps, Set Variable, user-input steps, sheet reads,
file reads, agent structured outputs, and other steps that write workflow variables.

#### Agent-step ownership

The GUI agent step records what the user configured in Agent Studio:

```json
{
  "type": "gui_step.agent",
  "step_id": "step_agent",
  "status": "success",
  "starting_url": "https://example.test/orders/481",
  "input": {
    "agent_type": "operator",
    "query": "Update order 481 to approved",
    "attachments": [],
    "file_variable_attachments": [],
    "mcp_servers": [],
    "vector_stores": [],
    "tools": [],
    "output_variables": ["confirmation"],
    "clear_chat_history": false,
    "reasoning_mode": "none"
  },
  "output": {}
}
```

The child `AgentSpanData` owns the effective agent request and response. This avoids duplicating
the response on both the GUI-step span and the agent span, and keeps an agent invoked by a workflow
identical to a direct SDK agent call.

#### GUI-step taxonomy

Every GUI step carries the common fields above. The following table lists every discriminator and
its additional execution fields or hierarchy behavior.

| `type` | Additional fields or behavior |
| --- | --- |
| `gui_step.agent` | Parents the `AgentSpanData` for the invoked agent. |
| `gui_step.agentic_mouse_action` | `strategy: "direct" \| "operator_fallback"` and optional `verification_status: bool`. |
| `gui_step.agentic_selector` | `strategy: "selector" \| "operator_fallback"`. |
| `gui_step.break` | No additional fields. |
| `gui_step.close_tab` | No additional fields. |
| `gui_step.continue` | No additional fields. |
| `gui_step.critic_agent` | Parents the `AgentSpanData` for the invoked critic execution. |
| `gui_step.data_table_export_as_csv` | No additional fields. |
| `gui_step.data_table_insert_row` | No additional fields. |
| `gui_step.data_table_update_cell_value` | No additional fields. |
| `gui_step.desktop_agentic_selector` | No additional fields. |
| `gui_step.email_action` | Provider response and updated variables belong in `output`. |
| `gui_step.end` | Optional execution result `result_status: "success" \| "error"`; configured message belongs in `input`. |
| `gui_step.execute_javascript_on_page` | No additional fields. |
| `gui_step.for` | Required `total_iterations: int`; parents one `IterationSpanData` per started iteration. |
| `gui_step.get_full_html` | No additional fields. |
| `gui_step.get_screenshot` | No additional fields. |
| `gui_step.get_simplified_html` | No additional fields. |
| `gui_step.get_url` | Returned URL belongs in `output.output_variables`. |
| `gui_step.go_to_url` | No additional output fields. |
| `gui_step.http_request` | Response body and updated variable belong in `output`; no inferred HTTP fields. |
| `gui_step.if` | Optional authored `selected_condition: str`; `None` for else or no selected branch. |
| `gui_step.log_variables_to_file` | No additional fields. |
| `gui_step.narada_code_project_executable` | No additional fields. |
| `gui_step.object_export_as_json` | No additional fields. |
| `gui_step.object_set_properties` | No additional fields. |
| `gui_step.open_desktop_application` | No additional fields. |
| `gui_step.output` | Emitted runtime values belong in `output.output_variables`. |
| `gui_step.press_keys` | No additional fields. |
| `gui_step.print` | Effective rendered message belongs in `input`; the step has no returned output. |
| `gui_step.prompt_for_user_input` | No additional fields. |
| `gui_step.python` | No additional fields. |
| `gui_step.read_csv` | No additional fields. |
| `gui_step.read_excel_sheet` | No additional fields. |
| `gui_step.read_google_sheet` | No additional fields. |
| `gui_step.read_local_filesystem` | No additional fields. |
| `gui_step.run_bash_script` | No additional fields. |
| `gui_step.run_custom_agent` | On success, parents the invoked `WorkflowSpanData`. |
| `gui_step.save_pdf_file` | No additional fields. |
| `gui_step.set_variable` | No additional fields. |
| `gui_step.slack_action` | Provider response and updated variables belong in `output`. |
| `gui_step.start` | No additional fields. |
| `gui_step.throw` | No additional fields. |
| `gui_step.try_catch` | Optional authored `caught_condition: str`; `None` when no catch condition matched. |
| `gui_step.user_approval` | No additional fields. |
| `gui_step.wait` | No additional fields. |
| `gui_step.wait_for_element` | No additional fields. |
| `gui_step.while` | Required `total_iterations: int`; parents one `IterationSpanData` per started iteration. |
| `gui_step.write_excel_sheet` | No additional fields. |
| `gui_step.write_google_sheet` | No additional fields. |
| `gui_step.write_local_filesystem` | No additional fields. |

#### Input and output keys by GUI step

This table describes the proposed dictionary keys. Identifiers such as `output_variable` are
configured inputs; `output_variables` always contains actual names and runtime values.

| GUI-step types | `input` keys | `output` keys |
| --- | --- | --- |
| `agent`, `critic_agent` | Agent type, effective query or prompt, attachments, file-variable attachments, MCP servers, vector stores, tools, output-variable names, chat-history behavior, reasoning mode, and critic configuration shown in the editor. | `{}`; the child agent span owns the response and structured output. |
| `agentic_mouse_action` | Action, recorded click, resize behavior, fallback query, self-healing and verification controls. | `output_variables` when verification writes a variable. |
| `agentic_selector` | Selectors, selector-variable fields, action, fallback query, self-healing, match index, and output-variable name. CSS/XPath and other selectors are included because they are visible editor inputs. | `output_variables` for text, property, or other returned selector actions. |
| `desktop_agentic_selector` | Window title, automation technology, selectors, and action. | `{}` unless the executor returns a value. |
| `go_to_url` | `url`. | `{}`. |
| `get_url`, `get_full_html`, `get_simplified_html`, `get_screenshot`, `save_pdf_file` | `output_variable`. | `output_variables`. |
| `http_request` | Effective URL, method, headers, redacted auth, body mode, body or multipart fields, timeout, and output-variable name. | `response_body` and `output_variables`; other response fields only when returned by the executor. |
| `print` | Effective `message`. | `{}`. |
| `press_keys` | Recorded key events. | `{}`. |
| `wait` | Effective `duration`. | `{}`. |
| `wait_for_element` | Selectors, expected state, timeout, and output-variable name. | `output_variables` containing the observed boolean. |
| `execute_javascript_on_page`, `python` | Code and declared output-variable names where applicable. | `stdout`, `stderr`, and `output_variables` only when the runtime returns them. |
| `run_bash_script` | Script code. | `stdout`, `stderr`, and `exit_code` only when returned by the runtime. |
| `narada_code_project_executable` | Project identifier, executable path, and argument string. | Values explicitly returned by the executable, otherwise `{}`. |
| `read_csv` | Content and output-variable name. | `output_variables`. |
| `read_google_sheet`, `read_excel_sheet` | Workbook or spreadsheet, range, account/header controls, and output-variable name. | `output_variables`. |
| `write_google_sheet`, `write_excel_sheet` | Workbook or spreadsheet, range, account/header controls, and data-table input variable. | Actual provider response if returned, otherwise `{}`. |
| `email_action` | Connector, action, action-specific parameters, attachments, filters, and output-variable names. | Actual `provider_response` and `output_variables` when returned. |
| `slack_action` | Connector, target, message, and output-variable name. | Actual `provider_response` and `output_variables` when returned. |
| `data_table_insert_row`, `data_table_update_cell_value` | Data-table variable and the visible row, column, record, position, or value controls. | `output_variables` containing the updated data-table value when captured. |
| `data_table_export_as_csv` | Data-table input variable. | File result only when returned; otherwise `{}`. |
| `object_set_properties` | Output-variable name and property assignments. | `output_variables` containing the updated object. |
| `object_export_as_json` | Object input variable. | File result only when returned; otherwise `{}`. |
| `set_variable` | Output-variable name and effective new value. | `output_variables` containing the updated value. |
| `output` | Variable names selected for output. | `output_variables` containing their runtime values. |
| `prompt_for_user_input` | Prompt message and requested-variable definitions. | `output_variables` containing supplied values. |
| `user_approval` | Prompt, approve/reject labels, and output-variable name. | `output_variables` containing the approval result. |
| `for` | Loop controls visible in the editor: count or source variable, current item/row variable, and index variable. | Updated loop variables when captured; `total_iterations` remains an execution field. |
| `while` | Condition, maximum iterations, and index-variable name. | Updated loop variables when captured; `total_iterations` remains an execution field. |
| `if` | Authored condition and branch conditions/names, without recursively copying child steps. | `{}`; `selected_condition` remains an execution field. |
| `try_catch` | Catch conditions and branch names, without recursively copying child steps. | `{}`; `caught_condition` remains an execution field. |
| `run_custom_agent` | Workflow identifier, effective prompt, and input/output variable mappings. | Parent `output_variables` updated by the mapping; the child workflow span owns the nested run output. |
| `end` | Tree-termination choice, result status, and effective message. | `{}`. |
| `throw` | Effective error message. | `{}`; the thrown error belongs in `Span.error`. |
| `log_variables_to_file` | File name and variables selected for logging. | File result only when returned; otherwise `{}`. |
| `open_desktop_application` | Executable path. | `{}`. |
| `read_local_filesystem` | Source path and output-variable name. | `output_variables`. |
| `write_local_filesystem` | Destination folder and input variable. | File-system result only when returned; otherwise `{}`. |
| `start`, `break`, `continue`, `close_tab` | `{}`. | `{}`. |

### Control-flow spans

Control-flow spans preserve scopes that are useful for reconstructing execution hierarchy:

| `type` | Fields |
| --- | --- |
| `control_flow.iteration` | Required zero-based `iteration_index`. |
| `control_flow.try` | No additional fields. |
| `control_flow.catch` | No additional fields. |
| `control_flow.finally` | No additional fields. |

The loop step already identifies whether it is a `for` or `while` loop. The iteration span does not
repeat that authored information. Its parent identifies the loop, and `iteration_index` identifies
the concrete execution.

### Agent spans

`AgentSpanData` represents an agent execution whether it was invoked directly through the SDK or
under a GUI agent step:

```json
{
  "type": "agent",
  "name": "Operator",
  "agent_type": "operator",
  "input": {
    "prompt": "Update order 481 to approved",
    "attachments": [],
    "input_variables": {
      "order_id": "481"
    }
  },
  "output": {
    "response": {
      "type": "text",
      "content": "Order 481 was updated."
    },
    "output_variables": {
      "confirmation": "Order 481 was updated."
    }
  },
  "status": "success",
  "request_id": "request_123",
  "usage": {
    "actions": 3,
    "credits": 1.5
  }
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | Display name of the executed agent. |
| `agent_type` | `AgentType` | Concrete runtime agent type. |
| `input` | `AgentSpanInput \| None` | Effective agent request used for this execution. |
| `output` | `AgentSpanOutput \| None` | Actual response and structured output variables. |
| `status` | `AgentSpanStatus` | Terminal status reported by the agent response. |
| `request_id` | `str \| None` | Request identifier for the run. |
| `usage` | `UsageData \| None` | Aggregate actions and credits charged for the run. |

The proposed nested models are:

```python
class AgentSpanInput(BaseModel):
    prompt: str
    attachments: list[str] = Field(default_factory=list)
    input_variables: dict[str, Any] = Field(default_factory=dict)


class AgentTextResponse(BaseModel):
    type: Literal["text"]
    content: str


class AgentStructuredResponse(BaseModel):
    type: Literal["structured"]
    content: Any


class AgentSpanOutput(BaseModel):
    response: Annotated[
        AgentTextResponse | AgentStructuredResponse,
        Field(discriminator="type"),
    ]
    output_variables: dict[str, Any] = Field(default_factory=dict)
```

Attachment entries are stable references or filenames, not embedded file contents. Secret input
variables are redacted.

Agent statuses are `success`, `error`, and `input-required`.

Agent types are `operator`, `generalist`, `coreAgent`, `jira`, `googleDrive`, `gmail`,
`googleCalendar`, and `concur`. A custom agent is represented as a workflow span rather than a
synthetic `custom` agent type.

`UsageData.actions` is a billing aggregate. It is not a replacement for action spans and may differ
from the number of action spans returned to the caller.

This replaces the current top-level `output_variables` field on `AgentSpanData`. Keeping the
response and output variables together prevents two competing notions of agent output. It also
uses the same text-versus-structured response shape already returned by the SDK.

### Required model changes

Adding these shapes requires the following changes to the Stage 1 models:

1. Add nullable `input` and `output` dictionaries to `BaseGuiStepSpanData`.
2. Add typed `AgentSpanInput` and `AgentSpanOutput` fields to `AgentSpanData`.
3. Move `AgentSpanData.output_variables` into `AgentSpanOutput.output_variables`.
4. Put direct step results in `output` rather than adding parallel top-level result fields.
5. Keep execution facts such as `strategy`, `verification_status`, `total_iterations`,
   `selected_condition`, and `caught_condition` on the concrete span-data subtype.
6. Do not retain fields such as `final_url`, HTTP status code, or provider status unless the
   relevant executor actually returns them.

### Agent-action spans

`AgentActionSpanData` represents one user-facing action performed by an agent:

```json
{
  "type": "agent_action",
  "name": "Agent action",
  "message": "Opened the customer record",
  "url": "https://example.test/customers/123",
  "credits": null
}
```

| Field | Type | Meaning |
| --- | --- | --- |
| `name` | `str` | Short user-facing action name. |
| `message` | `str` | User-facing description of what occurred. |
| `url` | `str \| None` | Page associated with the action, when available. |
| `credits` | `float \| None` | Credits attributed to this action, when available. |

Action spans intentionally expose user-facing actions rather than raw internal tool calls.

## Hierarchy rules

1. A direct SDK agent run has a root `agent` span.
2. A GUI workflow run has a root `workflow` span.
3. Every executed GUI step is a child of its workflow or active control-flow span.
4. An agent invoked by a GUI agent step is a child `agent` span. Its representation is the same as
   a root agent span from a direct call.
5. Agent actions are children of the agent span that performed them.
6. A loop step parents its iteration spans. Steps executed in an iteration are children of that
   iteration.
7. A successful Run Custom Agent step parents a new `workflow` span for the invoked workflow.
8. Try, catch, and finally scopes may use control-flow spans when that scope is required to preserve
   parentage and timing.

## Flattened example

The returned JSON remains a flat list. The following abbreviated records describe a workflow,
its GUI agent step, and the child agent run:

```json
[
  {
    "object": "trace",
    "trace_id": "trace_123",
    "name": "Process renewals"
  },
  {
    "object": "trace.span",
    "span_id": "span_workflow",
    "trace_id": "trace_123",
    "parent_id": null,
    "span_data": {
      "type": "workflow",
      "workflow_name": "Process renewals",
      "workflow_id": "workflow_123",
      "status": "success"
    }
  },
  {
    "object": "trace.span",
    "span_id": "span_agent_step",
    "trace_id": "trace_123",
    "parent_id": "span_workflow",
    "span_data": {
      "type": "gui_step.agent",
      "step_id": "step_123",
      "status": "success",
      "starting_url": "https://example.test/customers/123",
      "input": {
        "agent_type": "operator",
        "query": "Update the renewal date",
        "output_variables": ["confirmation"]
      },
      "output": {}
    }
  },
  {
    "object": "trace.span",
    "span_id": "span_agent",
    "trace_id": "trace_123",
    "parent_id": "span_agent_step",
    "span_data": {
      "type": "agent",
      "name": "Operator",
      "agent_type": "operator",
      "input": {
        "prompt": "Update the renewal date",
        "attachments": [],
        "input_variables": {}
      },
      "output": {
        "response": {
          "type": "text",
          "content": "The renewal date was updated."
        },
        "output_variables": {
          "confirmation": "The renewal date was updated."
        }
      },
      "status": "success",
      "request_id": "request_agent_123"
    }
  }
]
```

The ordering should be parent before child so callers can stream through the list or reconstruct the
tree in one pass.

## Invariants

- Every span references exactly one trace through `trace_id`.
- Every non-root `parent_id` refers to another span in the same trace.
- Parent spans precede child spans in the flattened list.
- `span_data.type` determines the concrete span-data shape.
- Discriminators are snake_case.
- Timestamps are UTC ISO 8601 strings.
- Numeric counts, indices, usage, and credits are non-negative.
- GUI-step `input` contains effective runtime values for user-visible configuration fields.
- Runtime output dictionaries contain names and actual values, not authored variable definitions.
- Secrets are redacted from trace inputs.
- `None` means input or output was not captured; `{}` means it was captured and is empty.
- Optional values remain `null` under normal Pydantic serialization.
