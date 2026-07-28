from __future__ import annotations

from typing import Any, get_args

from narada_core.models import AgentKind
from narada_core.tracing.conversion import (
    _GUI_STEP_DATA_TYPES,
    build_response_trace,
)
from narada_core.tracing.model import parse_action_trace
from narada_core.tracing.response_trace import (
    AgentActionSpanData,
    AgentSpanData,
    BaseGuiStepSpanData,
    GuiStepSpanData,
    IfStepData,
    IterationSpanData,
    Span,
    Trace,
    TryCatchStepData,
    WorkflowSpanData,
)


def _spans(records: list[Trace | Span[Any]]) -> list[Span[Any]]:
    return [record for record in records if isinstance(record, Span)]


def _span_with_data(
    records: list[Trace | Span[Any]],
    data_type: type[Any],
    *,
    step_id: str | None = None,
) -> Span[Any]:
    for span in _spans(records):
        if not isinstance(span.span_data, data_type):
            continue
        if step_id is None or getattr(span.span_data, "step_id", None) == step_id:
            return span
    raise AssertionError(f"No span found for {data_type.__name__} and {step_id=}")


def test_converter_covers_every_typed_gui_step() -> None:
    gui_step_union = get_args(GuiStepSpanData.__value__)[0]
    gui_step_models = get_args(gui_step_union)

    expected_types = {model.model_fields["type"].default for model in gui_step_models}
    converted_types = {
        model.model_fields["type"].default for model in _GUI_STEP_DATA_TYPES.values()
    }

    assert converted_types == expected_types


def test_direct_operator_trace_contains_agent_and_action_spans() -> None:
    action_trace = parse_action_trace(
        [
            {
                "action": "Opened the customer record",
                "url": "https://example.test/customers/123",
                "startTs": "2026-07-28T18:00:00.000Z",
                "endTs": "2026-07-28T18:00:01.000Z",
                "durationMs": 1000,
            },
            {
                "action": "Updated the renewal date",
                "url": "https://example.test/customers/123",
                "startTs": "2026-07-28T18:00:02.000Z",
                "endTs": "2026-07-28T18:00:03.500Z",
                "durationMs": 1500,
            },
        ]
    )

    records = build_response_trace(
        request_id="request-123",
        response_status="success",
        usage_actions=2,
        usage_credits=1.5,
        agent_kind=AgentKind.OPERATOR,
        action_trace=action_trace,
        workflow_trace=None,
    )

    trace = records[0]
    assert isinstance(trace, Trace)
    assert trace.name == "Operator"
    assert trace.metadata == {"schema_version": 1}

    spans = _spans(records)
    assert len(spans) == 3
    agent_span = _span_with_data(records, AgentSpanData)
    assert agent_span.parent_id is None
    assert agent_span.started_at == "2026-07-28T18:00:00.000Z"
    assert agent_span.ended_at == "2026-07-28T18:00:03.500Z"
    assert agent_span.span_data.request_id == "request-123"
    assert agent_span.span_data.usage.actions == 2
    assert agent_span.span_data.usage.credits == 1.5

    action_spans = [
        span for span in spans if isinstance(span.span_data, AgentActionSpanData)
    ]
    assert [span.span_data.message for span in action_spans] == [
        "Opened the customer record",
        "Updated the renewal date",
    ]
    assert all(span.parent_id == agent_span.span_id for span in action_spans)

    exported = [record.model_dump(mode="json") for record in records]
    assert exported[0]["id"] == trace.trace_id
    assert exported[0]["workflow_name"] == "Operator"
    assert exported[1]["object"] == "trace.span"
    assert exported[1]["id"] == agent_span.span_id


def test_complex_workflow_trace_preserves_hierarchy() -> None:
    workflow_trace = {
        "workflowId": "workflow-root",
        "workflowName": "Renewal workflow",
        "runtime": "gui",
        "status": "success",
        "startTs": 1_000,
        "endTs": 12_000,
        "variables": {"renewal_date": "2027-01-01"},
        "children": [
            {
                "kind": "gui_step",
                "stepId": "step-print",
                "stepType": "print",
                "label": "Starting",
                "status": "success",
                "startTs": 1_100,
                "endTs": 1_200,
                "data": {
                    "step_type": "print",
                    "message": "Starting renewal",
                    "url": "https://example.test",
                },
                "children": [],
            },
            {
                "kind": "gui_step",
                "stepId": "step-agent",
                "stepType": "agent",
                "label": "Update the customer",
                "status": "success",
                "startTs": 2_000,
                "endTs": 4_000,
                "data": {
                    "step_type": "agent",
                    "agent_type": "operator",
                    "action_trace": [
                        {
                            "action": "Clicked Edit",
                            "url": "https://example.test/customer",
                            "startTs": "1970-01-01T00:00:02.100Z",
                            "endTs": "1970-01-01T00:00:02.300Z",
                            "durationMs": 200,
                        }
                    ],
                },
                "children": [
                    {
                        "kind": "sub_workflow",
                        "trace": {
                            "workflowId": "workflow-child",
                            "workflowName": "Child workflow",
                            "runtime": "gui",
                            "status": "success",
                            "startTs": 2_500,
                            "endTs": 3_500,
                            "children": [],
                        },
                    }
                ],
            },
            {
                "kind": "gui_step",
                "stepId": "step-loop",
                "stepType": "for",
                "label": "Process rows",
                "status": "success",
                "startTs": 5_000,
                "endTs": 8_000,
                "data": {"step_type": "for", "description": "Processed rows"},
                "children": [
                    {
                        "kind": "gui_step",
                        "stepId": "step-loop:iter-0",
                        "stepType": "forIteration",
                        "status": "success",
                        "startTs": 5_000,
                        "endTs": 8_000,
                        "children": [
                            {
                                "kind": "gui_step",
                                "stepId": "iteration-print-0",
                                "stepType": "print",
                                "status": "success",
                                "startTs": 5_100,
                                "endTs": 5_200,
                                "data": {
                                    "step_type": "print",
                                    "message": "First row",
                                },
                                "children": [],
                            }
                        ],
                    },
                    {
                        "kind": "gui_step",
                        "stepId": "step-loop:iter-1",
                        "stepType": "forIteration",
                        "status": "success",
                        "startTs": 5_000,
                        "endTs": 8_000,
                        "children": [
                            {
                                "kind": "gui_step",
                                "stepId": "iteration-print-1",
                                "stepType": "print",
                                "status": "success",
                                "startTs": 6_100,
                                "endTs": 6_400,
                                "data": {
                                    "step_type": "print",
                                    "message": "Second row",
                                },
                                "children": [],
                            }
                        ],
                    },
                ],
            },
            {
                "kind": "gui_step",
                "stepId": "step-if",
                "stepType": "if",
                "status": "success",
                "startTs": 8_100,
                "endTs": 9_000,
                "data": {
                    "step_type": "if",
                    "description": "Took else branch",
                    "selected_branch_role": "else",
                },
                "children": [],
            },
            {
                "kind": "gui_step",
                "stepId": "if-child",
                "stepType": "print",
                "status": "success",
                "startTs": 8_200,
                "endTs": 8_300,
                "data": {"step_type": "print", "message": "Else branch"},
                "children": [],
            },
            {
                "kind": "gui_step",
                "stepId": "step-try",
                "stepType": "tryCatch",
                "status": "success",
                "startTs": 9_100,
                "endTs": 10_000,
                "data": {
                    "step_type": "tryCatch",
                    "description": "Catch handled the error",
                    "caught_error": True,
                    "executed_catch": True,
                    "executed_finally": True,
                },
                "children": [],
            },
            {
                "kind": "gui_step",
                "stepId": "try-child",
                "stepType": "print",
                "status": "success",
                "startTs": 9_200,
                "endTs": 9_300,
                "data": {"step_type": "print", "message": "Recovered"},
                "children": [],
            },
        ],
    }

    records = build_response_trace(
        request_id="workflow-request-123",
        response_status="success",
        usage_actions=3,
        usage_credits=2,
        agent_kind="/owner/renewal-workflow",
        action_trace=None,
        workflow_trace=workflow_trace,
    )

    trace = records[0]
    assert isinstance(trace, Trace)
    assert trace.name == "Renewal workflow"
    span_indexes = {span.span_id: index for index, span in enumerate(_spans(records))}
    assert all(
        span.parent_id is None
        or (
            span.parent_id in span_indexes
            and span_indexes[span.parent_id] < span_indexes[span.span_id]
        )
        for span in _spans(records)
    )
    workflow_span = _span_with_data(records, WorkflowSpanData, step_id=None)
    assert workflow_span.parent_id is None
    assert workflow_span.started_at == "1970-01-01T00:00:01.000Z"
    assert workflow_span.ended_at == "1970-01-01T00:00:12.000Z"
    assert workflow_span.span_data.output_variables == {"renewal_date": "2027-01-01"}

    agent_gui_span = next(
        span
        for span in _spans(records)
        if getattr(span.span_data, "step_id", None) == "step-agent"
    )
    agent_span = _span_with_data(records, AgentSpanData)
    action_span = _span_with_data(records, AgentActionSpanData)
    child_workflow_span = next(
        span
        for span in _spans(records)
        if isinstance(span.span_data, WorkflowSpanData)
        and span.span_data.workflow_id == "workflow-child"
    )
    assert agent_span.parent_id == agent_gui_span.span_id
    assert action_span.parent_id == agent_span.span_id
    assert child_workflow_span.parent_id == agent_span.span_id

    loop_span = next(
        span
        for span in _spans(records)
        if getattr(span.span_data, "step_id", None) == "step-loop"
    )
    iteration_spans = [
        span
        for span in _spans(records)
        if isinstance(span.span_data, IterationSpanData)
    ]
    assert [span.span_data.iteration_index for span in iteration_spans] == [0, 1]
    assert all(span.parent_id == loop_span.span_id for span in iteration_spans)
    assert iteration_spans[0].started_at == "1970-01-01T00:00:05.100Z"
    assert iteration_spans[0].ended_at == "1970-01-01T00:00:05.200Z"

    if_span = _span_with_data(records, IfStepData, step_id="step-if")
    if_child = next(
        span
        for span in _spans(records)
        if getattr(span.span_data, "step_id", None) == "if-child"
    )
    assert if_span.span_data.selected_branch_role == "else"
    assert if_child.parent_id == if_span.span_id

    try_span = _span_with_data(records, TryCatchStepData, step_id="step-try")
    try_child = next(
        span
        for span in _spans(records)
        if getattr(span.span_data, "step_id", None) == "try-child"
    )
    assert try_span.span_data.executed_finally is True
    assert try_child.parent_id == try_span.span_id

    second_records = build_response_trace(
        request_id="workflow-request-123",
        response_status="success",
        usage_actions=3,
        usage_credits=2,
        agent_kind="/owner/renewal-workflow",
        action_trace=None,
        workflow_trace=workflow_trace,
    )
    assert [record.model_dump(mode="json") for record in records] == [
        record.model_dump(mode="json") for record in second_records
    ]


def test_incomplete_and_unknown_gui_steps_use_the_readable_base_shape() -> None:
    workflow_trace = {
        "workflowId": "workflow-root",
        "workflowName": "Forward-compatible workflow",
        "runtime": "gui",
        "status": "success",
        "startTs": 1_000,
        "endTs": 2_000,
        "children": [
            {
                "kind": "gui_step",
                "stepId": "old-try",
                "stepType": "tryCatch",
                "status": "success",
                "startTs": 1_100,
                "endTs": 1_200,
                "data": {
                    "step_type": "tryCatch",
                    "description": "Legacy data without structured booleans",
                },
                "children": [],
            },
            {
                "kind": "gui_step",
                "stepId": "future-step",
                "stepType": "futureBrowserAction",
                "status": "success",
                "startTs": 1_300,
                "endTs": 1_400,
                "data": {"description": "A future action"},
                "children": [],
            },
        ],
    }

    records = build_response_trace(
        request_id="request-123",
        response_status="success",
        usage_actions=0,
        usage_credits=0,
        agent_kind="/owner/workflow",
        action_trace=None,
        workflow_trace=workflow_trace,
    )

    old_try = next(
        span
        for span in _spans(records)
        if getattr(span.span_data, "step_id", None) == "old-try"
    )
    future_step = next(
        span
        for span in _spans(records)
        if getattr(span.span_data, "step_id", None) == "future-step"
    )
    assert type(old_try.span_data) is BaseGuiStepSpanData
    assert old_try.span_data.type == "gui_step.try_catch"
    assert type(future_step.span_data) is BaseGuiStepSpanData
    assert future_step.span_data.type == "gui_step.future_browser_action"


def test_nested_control_flow_inference_preserves_grandchildren() -> None:
    workflow_trace = {
        "workflowId": "workflow-root",
        "workflowName": "Nested control flow",
        "runtime": "gui",
        "status": "success",
        "startTs": 1_000,
        "endTs": 6_000,
        "children": [
            {
                "kind": "gui_step",
                "stepId": "outer-if",
                "stepType": "if",
                "status": "success",
                "startTs": 1_100,
                "endTs": 5_000,
                "data": {
                    "step_type": "if",
                    "selected_branch_role": "then",
                },
                "children": [],
            },
            {
                "kind": "gui_step",
                "stepId": "inner-try",
                "stepType": "tryCatch",
                "status": "success",
                "startTs": 2_000,
                "endTs": 4_000,
                "data": {
                    "step_type": "tryCatch",
                    "caught_error": False,
                    "executed_catch": False,
                    "executed_finally": True,
                },
                "children": [],
            },
            {
                "kind": "gui_step",
                "stepId": "nested-print",
                "stepType": "print",
                "status": "success",
                "startTs": 2_500,
                "endTs": 3_000,
                "data": {"step_type": "print", "message": "Nested"},
                "children": [],
            },
        ],
    }

    records = build_response_trace(
        request_id="request-123",
        response_status="success",
        usage_actions=0,
        usage_credits=0,
        agent_kind="/owner/workflow",
        action_trace=None,
        workflow_trace=workflow_trace,
    )

    outer_if = _span_with_data(records, IfStepData, step_id="outer-if")
    inner_try = _span_with_data(records, TryCatchStepData, step_id="inner-try")
    nested_print = next(
        span
        for span in _spans(records)
        if getattr(span.span_data, "step_id", None) == "nested-print"
    )

    assert inner_try.parent_id == outer_if.span_id
    assert nested_print.parent_id == inner_try.span_id
