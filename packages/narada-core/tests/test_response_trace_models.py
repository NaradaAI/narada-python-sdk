from datetime import UTC, datetime, timedelta, timezone

import pytest
from narada_core.tracing.response_trace import (
    AgentSpanData,
    ControlFlowSpanData,
    GuiStepSpanData,
    HttpRequestStepData,
    IterationSpanData,
    OperatorAgentSpanData,
    Span,
    Trace,
    TraceRecord,
    WorkflowSpanData,
)
from pydantic import TypeAdapter, ValidationError

GUI_STEP_TYPES = {
    "gui_step.agent",
    "gui_step.agentic_mouse_action",
    "gui_step.agentic_selector",
    "gui_step.break",
    "gui_step.close_tab",
    "gui_step.continue",
    "gui_step.critic_agent",
    "gui_step.data_table_export_as_csv",
    "gui_step.data_table_insert_row",
    "gui_step.data_table_update_cell_value",
    "gui_step.desktop_agentic_selector",
    "gui_step.email_action",
    "gui_step.end",
    "gui_step.execute_javascript_on_page",
    "gui_step.execute_python",
    "gui_step.for",
    "gui_step.get_full_html",
    "gui_step.get_screenshot",
    "gui_step.get_simplified_html",
    "gui_step.get_url",
    "gui_step.http_request",
    "gui_step.if",
    "gui_step.log_variables_to_file",
    "gui_step.navigate",
    "gui_step.object_export_as_json",
    "gui_step.object_set_properties",
    "gui_step.open_desktop_application",
    "gui_step.output",
    "gui_step.press_keys",
    "gui_step.print",
    "gui_step.project_executable",
    "gui_step.prompt_for_user_input",
    "gui_step.read_csv",
    "gui_step.read_excel_sheet",
    "gui_step.read_google_sheet",
    "gui_step.read_local_filesystem",
    "gui_step.run_bash_script",
    "gui_step.run_custom_agent",
    "gui_step.run_custom_agent_for_each",
    "gui_step.run_custom_agents_in_parallel",
    "gui_step.save_pdf_file",
    "gui_step.set_variable",
    "gui_step.slack_action",
    "gui_step.start",
    "gui_step.throw",
    "gui_step.try_catch",
    "gui_step.user_approval",
    "gui_step.wait",
    "gui_step.wait_for_element",
    "gui_step.while",
    "gui_step.write_excel_sheet",
    "gui_step.write_google_sheet",
    "gui_step.write_local_filesystem",
}


def _discriminator_values(annotation: object) -> set[str]:
    schema = TypeAdapter(annotation).json_schema()
    return set(schema["discriminator"]["mapping"])


def test_trace_serializes_with_openai_envelope() -> None:
    trace = Trace(id="trace_123", workflow_name="Process renewals")

    assert trace.model_dump(mode="json") == {
        "object": "trace",
        "id": "trace_123",
        "workflow_name": "Process renewals",
        "group_id": None,
        "metadata": {"schema_version": "1"},
    }


def test_span_serializes_with_openai_envelope_and_omits_narada_nulls() -> None:
    span = Span(
        id="span_workflow",
        trace_id="trace_123",
        started_at=datetime(2026, 7, 24, 18, 0, tzinfo=UTC),
        ended_at=datetime(2026, 7, 24, 18, 0, 5, tzinfo=UTC),
        span_data=WorkflowSpanData(
            name="Process renewals",
            workflow_id="workflow_123",
            workflow_run_id=None,
            status="success",
            termination_mode="completed",
        ),
    )

    assert span.model_dump(mode="json") == {
        "object": "trace.span",
        "id": "span_workflow",
        "trace_id": "trace_123",
        "parent_id": None,
        "started_at": "2026-07-24T18:00:00Z",
        "ended_at": "2026-07-24T18:00:05Z",
        "span_data": {
            "type": "workflow",
            "name": "Process renewals",
            "workflow_id": "workflow_123",
            "status": "success",
            "termination_mode": "completed",
        },
        "error": None,
    }


def test_agent_span_keeps_openai_nullable_fields() -> None:
    span = Span(
        id="span_agent",
        trace_id="trace_123",
        span_data=OperatorAgentSpanData(name="Operator", status="success"),
    )

    assert span.model_dump(mode="json")["span_data"] == {
        "type": "agent.operator",
        "name": "Operator",
        "handoffs": None,
        "tools": None,
        "output_type": None,
        "reasoning_effort": "agent_default",
        "status": "success",
    }


def test_agent_span_accepts_explicit_reasoning_effort() -> None:
    agent = OperatorAgentSpanData(
        name="Operator",
        reasoning_effort="high",
        status="success",
    )

    assert agent.model_dump(mode="json")["reasoning_effort"] == "high"

    with pytest.raises(ValidationError):
        OperatorAgentSpanData(
            name="Operator",
            reasoning_effort="unsupported",  # type: ignore[arg-type]
            status="success",
        )


def test_span_data_unions_parse_concrete_subtypes() -> None:
    gui_span = Span.model_validate(
        {
            "id": "span_http",
            "trace_id": "trace_123",
            "span_data": {
                "type": "gui_step.http_request",
                "step_id": "step_123",
                "status": "success",
                "method": "GET",
                "status_code": 200,
            },
        }
    )
    control_flow = TypeAdapter(ControlFlowSpanData).validate_python(
        {
            "type": "control_flow.iteration",
            "status": "success",
            "iteration_index": 2,
        }
    )

    assert isinstance(gui_span.span_data, HttpRequestStepData)
    assert isinstance(control_flow, IterationSpanData)
    assert control_flow.iteration_index == 2


def test_taxonomy_discriminators_are_complete() -> None:
    assert _discriminator_values(GuiStepSpanData) == GUI_STEP_TYPES
    assert _discriminator_values(ControlFlowSpanData) == {
        "control_flow.iteration",
        "control_flow.try",
        "control_flow.catch",
        "control_flow.finally",
    }
    assert _discriminator_values(AgentSpanData) == {
        "agent.operator",
        "agent.core",
        "agent.productivity",
        "agent.custom",
        "agent.critic",
        "agent.other",
    }


def test_trace_record_discriminator_parses_trace_and_span() -> None:
    adapter = TypeAdapter(TraceRecord)

    trace = adapter.validate_python(
        {"object": "trace", "id": "trace_123", "workflow_name": "Demo"}
    )
    span = adapter.validate_python(
        {
            "object": "trace.span",
            "id": "span_123",
            "trace_id": "trace_123",
            "span_data": {
                "type": "workflow",
                "name": "Demo",
                "workflow_id": "workflow_123",
                "workflow_run_id": None,
                "status": "success",
            },
        }
    )

    assert isinstance(trace, Trace)
    assert isinstance(span, Span)
    assert span.span_data.workflow_run_id is None


@pytest.mark.parametrize(
    "started_at, ended_at",
    [
        (
            datetime(2026, 7, 24, 18, 0),
            datetime(2026, 7, 24, 18, 0, 1, tzinfo=UTC),
        ),
        (
            datetime(
                2026,
                7,
                24,
                18,
                0,
                tzinfo=timezone(timedelta(hours=1)),
            ),
            datetime(2026, 7, 24, 18, 0, 1, tzinfo=UTC),
        ),
        (
            datetime(2026, 7, 24, 18, 0, 1, tzinfo=UTC),
            datetime(2026, 7, 24, 18, 0, tzinfo=UTC),
        ),
    ],
)
def test_span_rejects_non_utc_or_reversed_timestamps(
    started_at: datetime,
    ended_at: datetime,
) -> None:
    with pytest.raises(ValidationError):
        Span(
            id="span_123",
            trace_id="trace_123",
            started_at=started_at,
            ended_at=ended_at,
            span_data=WorkflowSpanData(
                name="Demo",
                workflow_id="workflow_123",
                status="success",
            ),
        )


def test_negative_numeric_values_are_rejected() -> None:
    with pytest.raises(ValidationError):
        HttpRequestStepData(
            step_id="step_123",
            status="success",
            status_code=-1,
        )

    with pytest.raises(ValidationError):
        IterationSpanData(status="success", iteration_index=-1)

    with pytest.raises(ValidationError):
        IterationSpanData(status="success")
