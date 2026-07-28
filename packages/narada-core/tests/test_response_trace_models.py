from typing import Any

import pytest
from narada_core.tracing import response_trace
from narada_core.tracing.response_trace import (
    AgentSpanData,
    AgentStepData,
    ControlFlowSpanData,
    GoToUrlStepData,
    GuiStepSpanData,
    HttpRequestStepData,
    IfStepData,
    IterationSpanData,
    NaradaCodeProjectExecutableStepData,
    PythonStepData,
    RunCustomAgentStepData,
    Span,
    SpanDataUnion,
    SpanError,
    Trace,
    TryCatchStepData,
    UsageData,
    WorkflowSpanData,
)
from pydantic import BaseModel, TypeAdapter, ValidationError

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
    "gui_step.for",
    "gui_step.get_full_html",
    "gui_step.get_screenshot",
    "gui_step.get_simplified_html",
    "gui_step.get_url",
    "gui_step.go_to_url",
    "gui_step.http_request",
    "gui_step.if",
    "gui_step.log_variables_to_file",
    "gui_step.narada_code_project_executable",
    "gui_step.object_export_as_json",
    "gui_step.object_set_properties",
    "gui_step.open_desktop_application",
    "gui_step.output",
    "gui_step.press_keys",
    "gui_step.print",
    "gui_step.prompt_for_user_input",
    "gui_step.python",
    "gui_step.read_csv",
    "gui_step.read_excel_sheet",
    "gui_step.read_google_sheet",
    "gui_step.read_local_filesystem",
    "gui_step.run_bash_script",
    "gui_step.run_custom_agent",
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


def test_trace_uses_openai_python_object_fields() -> None:
    trace = Trace(trace_id="trace_123", name="Process renewals")

    assert trace.model_dump(mode="json") == {
        "object": "trace",
        "trace_id": "trace_123",
        "name": "Process renewals",
        "group_id": None,
        "metadata": None,
    }
    assert trace.trace_id == "trace_123"
    assert trace.name == "Process renewals"


def test_span_uses_openai_python_object_fields() -> None:
    span = Span(
        span_id="span_workflow",
        trace_id="trace_123",
        started_at="2026-07-24T18:00:00+00:00",
        ended_at="2026-07-24T18:00:05+00:00",
        span_data=WorkflowSpanData(
            workflow_name="Process renewals",
            workflow_id="workflow_123",
            status="success",
        ),
    )

    assert span.model_dump(mode="json") == {
        "object": "trace.span",
        "span_id": "span_workflow",
        "trace_id": "trace_123",
        "parent_id": None,
        "started_at": "2026-07-24T18:00:00+00:00",
        "ended_at": "2026-07-24T18:00:05+00:00",
        "span_data": {
            "type": "workflow",
            "workflow_name": "Process renewals",
            "workflow_id": "workflow_123",
            "status": "success",
            "request_id": None,
            "output_variables": None,
        },
        "error": None,
    }
    assert span.span_id == "span_workflow"


def test_span_error_preserves_openai_nullable_data_field() -> None:
    assert SpanError(message="Step failed", data=None).model_dump(mode="json") == {
        "message": "Step failed",
        "data": None,
    }


def test_agent_span_contains_only_execution_results() -> None:
    span = Span(
        span_id="span_agent",
        trace_id="trace_123",
        span_data=AgentSpanData(
            name="Operator",
            agent_type="operator",
            status="success",
        ),
    )

    assert span.model_dump(mode="json")["span_data"] == {
        "type": "agent",
        "name": "Operator",
        "agent_type": "operator",
        "output_variables": {},
        "status": "success",
        "request_id": None,
        "usage": None,
    }


def test_usage_data_contains_billable_action_and_credit_totals() -> None:
    usage = UsageData(actions=2, credits=1)

    assert usage.model_dump(mode="json") == {"actions": 2, "credits": 1.0}
    assert set(UsageData.model_json_schema()["properties"]) == {"actions", "credits"}


def test_agent_span_serializes_runtime_output_variables() -> None:
    agent = AgentSpanData(
        name="Operator",
        agent_type="operator",
        output_variables={"renewal_date": "2027-01-01"},
        status="success",
    )

    serialized = agent.model_dump(mode="json")

    assert serialized["output_variables"] == {"renewal_date": "2027-01-01"}
    assert {
        "additional_tools",
        "attachments",
        "vector_stores",
        "reasoning_effort",
        "input_summary",
        "output_summary",
        "page_url",
    }.isdisjoint(serialized)


def test_span_data_unions_parse_concrete_subtypes() -> None:
    gui_span = Span[SpanDataUnion].model_validate(
        {
            "span_id": "span_http",
            "trace_id": "trace_123",
            "span_data": {
                "type": "gui_step.http_request",
                "step_id": "step_123",
                "status": "success",
                "status_code": 200,
            },
        }
    )
    control_flow = TypeAdapter(ControlFlowSpanData).validate_python(
        {
            "type": "control_flow.iteration",
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
    assert AgentSpanData.model_json_schema()["properties"]["type"]["const"] == "agent"


def test_flat_trace_list_uses_openai_trace_and_span_types_directly() -> None:
    adapter = TypeAdapter(list[Trace | Span[Any]])

    trace, span = adapter.validate_python(
        [
            {
                "object": "trace",
                "trace_id": "trace_123",
                "name": "Demo",
                "group_id": None,
                "metadata": None,
            },
            {
                "object": "trace.span",
                "span_id": "span_123",
                "trace_id": "trace_123",
                "span_data": {
                    "type": "workflow",
                    "workflow_name": "Demo",
                    "workflow_id": "workflow_123",
                    "status": "success",
                },
            },
        ]
    )

    assert isinstance(trace, Trace)
    assert isinstance(span, Span)
    assert trace.trace_id == "trace_123"
    assert span.span_id == "span_123"
    assert span.span_data["type"] == "workflow"


def test_span_types_use_their_source_statuses() -> None:
    workflow = WorkflowSpanData(
        workflow_name="Demo",
        workflow_id="workflow_123",
        status="input-required",
    )
    agent = AgentSpanData(
        name="Operator",
        agent_type="operator",
        status="input-required",
    )
    iteration = IterationSpanData(iteration_index=0)
    gui_step = AgentStepData(
        step_id="step_123",
        status="end_tree",
    )

    assert workflow.status == "input-required"
    assert agent.status == "input-required"
    assert gui_step.status == "end_tree"
    assert "status" not in type(iteration).model_fields

    with pytest.raises(ValidationError):
        WorkflowSpanData(
            workflow_name="Demo",
            workflow_id="workflow_123",
            status="running",  # type: ignore[arg-type]
        )

    with pytest.raises(ValidationError):
        AgentSpanData(
            name="Operator",
            agent_type="operator",
            status="aborted",  # type: ignore[arg-type]
        )


def test_status_literals_match_runtime_contracts() -> None:
    assert set(
        TypeAdapter(response_trace.WorkflowSpanStatus).json_schema()["enum"]
    ) == {
        "pending",
        "input-required",
        "success",
        "error",
        "expired",
    }
    assert set(TypeAdapter(response_trace.GuiStepSpanStatus).json_schema()["enum"]) == {
        "success",
        "error",
        "aborted",
        "end_tree",
    }
    assert set(TypeAdapter(response_trace.AgentSpanStatus).json_schema()["enum"]) == {
        "success",
        "error",
        "input-required",
    }


def test_if_and_try_catch_preserve_authored_conditions() -> None:
    branch = IfStepData(
        step_id="if_123",
        status="success",
        selected_condition="${renewalDate} < '2027-01-01'",
    )
    trace = TryCatchStepData(
        step_id="step_123",
        status="success",
        caught_condition="${errorCode} == 409",
    )

    assert branch.selected_condition == "${renewalDate} < '2027-01-01'"
    assert trace.caught_condition == "${errorCode} == 409"
    assert (
        TryCatchStepData(step_id="step_123", status="success").caught_condition is None
    )


def test_agent_types_match_agent_studio_runtime_values() -> None:
    agent_types = {
        "operator",
        "generalist",
        "coreAgent",
        "jira",
        "googleDrive",
        "gmail",
        "googleCalendar",
        "concur",
    }
    assert (
        set(TypeAdapter(response_trace.AgentType).json_schema()["enum"]) == agent_types
    )

    for agent_type in agent_types:
        agent = AgentSpanData(
            name=agent_type,
            agent_type=agent_type,  # type: ignore[arg-type]
            status="success",
        )
        assert agent.agent_type == agent_type

    with pytest.raises(ValidationError):
        AgentSpanData(
            name="Custom Agent",
            agent_type="custom",  # type: ignore[arg-type]
            status="success",
        )


def test_canonical_gui_step_names_are_public() -> None:
    go_to_url = GoToUrlStepData(step_id="step_123", status="success")
    project = NaradaCodeProjectExecutableStepData(
        step_id="step_456",
        status="success",
    )
    python = PythonStepData(step_id="step_789", status="success")

    assert go_to_url.type == "gui_step.go_to_url"
    assert project.type == "gui_step.narada_code_project_executable"
    assert python.type == "gui_step.python"


def test_successful_run_custom_agent_step_can_parent_a_workflow_span() -> None:
    gui_step = Span(
        span_id="span_run_custom_agent",
        trace_id="trace_123",
        span_data=RunCustomAgentStepData(
            step_id="step_123",
            status="success",
        ),
    )
    child_workflow = Span(
        span_id="span_child_workflow",
        trace_id="trace_123",
        parent_id=gui_step.span_id,
        span_data=WorkflowSpanData(
            workflow_name="Child workflow",
            workflow_id="workflow_child",
            status="success",
        ),
    )

    assert child_workflow.parent_id == gui_step.span_id


def test_every_public_model_field_has_a_description() -> None:
    for name in response_trace.__all__:
        value = getattr(response_trace, name)
        if not isinstance(value, type) or not issubclass(value, BaseModel):
            continue
        for field_name, field in value.model_fields.items():
            assert field.description, f"{name}.{field_name} has no description"


@pytest.mark.parametrize(
    "started_at, ended_at",
    [
        (
            "2026-07-24T18:00:00",
            "2026-07-24T18:00:01+00:00",
        ),
        (
            "2026-07-24T18:00:00+01:00",
            "2026-07-24T18:00:01+00:00",
        ),
        (
            "2026-07-24T18:00:01+00:00",
            "2026-07-24T18:00:00+00:00",
        ),
    ],
)
def test_span_rejects_non_utc_or_reversed_timestamps(
    started_at: str,
    ended_at: str,
) -> None:
    with pytest.raises(ValidationError):
        Span(
            span_id="span_123",
            trace_id="trace_123",
            started_at=started_at,
            ended_at=ended_at,
            span_data=WorkflowSpanData(
                workflow_name="Demo",
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
        IterationSpanData(iteration_index=-1)

    with pytest.raises(ValidationError):
        IterationSpanData()
