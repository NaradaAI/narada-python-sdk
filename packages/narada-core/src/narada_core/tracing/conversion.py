from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any, cast

from narada_core.models import AgentKind
from narada_core.tracing import model as legacy_trace
from narada_core.tracing import response_trace

_GUI_STEP_DATA_TYPES: dict[str, type[response_trace.BaseGuiStepSpanData]] = {
    "agent": response_trace.AgentStepData,
    "agenticMouseAction": response_trace.AgenticMouseActionStepData,
    "agenticSelector": response_trace.AgenticSelectorStepData,
    "break": response_trace.BreakStepData,
    "closeTab": response_trace.CloseTabStepData,
    "continue": response_trace.ContinueStepData,
    "criticAgent": response_trace.CriticAgentStepData,
    "dataTableExportAsCsv": response_trace.DataTableExportAsCsvStepData,
    "dataTableInsertRow": response_trace.DataTableInsertRowStepData,
    "dataTableUpdateCellValue": response_trace.DataTableUpdateCellValueStepData,
    "desktopAgenticSelector": response_trace.DesktopAgenticSelectorStepData,
    "emailAction": response_trace.EmailActionStepData,
    "end": response_trace.EndStepData,
    "executeJavaScriptOnPage": response_trace.ExecuteJavaScriptOnPageStepData,
    "for": response_trace.ForStepData,
    "getFullHtml": response_trace.GetFullHtmlStepData,
    "getScreenshot": response_trace.GetScreenshotStepData,
    "getSimplifiedHtml": response_trace.GetSimplifiedHtmlStepData,
    "getUrl": response_trace.GetUrlStepData,
    "goToUrl": response_trace.GoToUrlStepData,
    "httpRequest": response_trace.HttpRequestStepData,
    "if": response_trace.IfStepData,
    "logVariablesToFile": response_trace.LogVariablesToFileStepData,
    "objectExportAsJson": response_trace.ObjectExportAsJsonStepData,
    "objectSetProperties": response_trace.ObjectSetPropertiesStepData,
    "openDesktopApplication": response_trace.OpenDesktopApplicationStepData,
    "output": response_trace.OutputStepData,
    "pressKeys": response_trace.PressKeysStepData,
    "print": response_trace.PrintStepData,
    "projectExecutable": response_trace.NaradaCodeProjectExecutableStepData,
    "promptForUserInput": response_trace.PromptForUserInputStepData,
    "python": response_trace.PythonStepData,
    "readCsv": response_trace.ReadCsvStepData,
    "readExcelSheet": response_trace.ReadExcelSheetStepData,
    "readGoogleSheet": response_trace.ReadGoogleSheetStepData,
    "readLocalFilesystem": response_trace.ReadLocalFilesystemStepData,
    "runBashScript": response_trace.RunBashScriptStepData,
    "runCustomAgent": response_trace.RunCustomAgentStepData,
    "savePdfFile": response_trace.SavePdfFileStepData,
    "setVariable": response_trace.SetVariableStepData,
    "slackAction": response_trace.SlackActionStepData,
    "start": response_trace.StartStepData,
    "throw": response_trace.ThrowStepData,
    "tryCatch": response_trace.TryCatchStepData,
    "userApproval": response_trace.UserApprovalStepData,
    "wait": response_trace.WaitStepData,
    "waitForElement": response_trace.WaitForElementStepData,
    "while": response_trace.WhileStepData,
    "writeExcelSheet": response_trace.WriteExcelSheetStepData,
    "writeGoogleSheet": response_trace.WriteGoogleSheetStepData,
    "writeLocalFilesystem": response_trace.WriteLocalFilesystemStepData,
}

_CONTAINER_STEP_TYPES = {"if", "tryCatch"}
_AGENT_STEP_TYPES = {"agent", "criticAgent"}


class _TraceBuilder:
    def __init__(self, *, request_id: str, name: str) -> None:
        self.trace_id = _stable_id("trace", request_id, length=32)
        self.trace = response_trace.Trace(
            trace_id=self.trace_id,
            name=name,
            metadata={"schema_version": 1},
        )
        self.spans: list[response_trace.Span[Any]] = []

    def add_span(
        self,
        *,
        path: str,
        parent_id: str | None,
        span_data: response_trace.SpanData,
        started_at: str | None = None,
        ended_at: str | None = None,
        error: response_trace.SpanError | None = None,
    ) -> str:
        span_id = _stable_id("span", f"{self.trace_id}:{path}", length=24)
        self.spans.append(
            response_trace.Span[Any](
                span_id=span_id,
                trace_id=self.trace_id,
                parent_id=parent_id,
                started_at=started_at,
                ended_at=ended_at,
                span_data=span_data,
                error=error,
            )
        )
        return span_id

    def records(
        self,
    ) -> list[response_trace.Trace | response_trace.Span[Any]]:
        return [self.trace, *self.spans]


def build_response_trace(
    *,
    request_id: str,
    response_status: str,
    usage_actions: int,
    usage_credits: float,
    agent_kind: AgentKind | str,
    action_trace: legacy_trace.ActionTrace | None,
    workflow_trace: Mapping[str, Any] | None,
) -> list[response_trace.Trace | response_trace.Span[Any]]:
    """Convert the existing completed-run traces into the response trace format."""
    agent_name, agent_type = _agent_identity(agent_kind)
    trace_name = _workflow_name(workflow_trace) or agent_name
    builder = _TraceBuilder(request_id=request_id, name=trace_name)

    if workflow_trace is not None:
        _convert_workflow(
            builder=builder,
            workflow=workflow_trace,
            parent_id=None,
            path="workflow",
            fallback_request_id=request_id,
        )
    else:
        _convert_direct_agent(
            builder=builder,
            request_id=request_id,
            response_status=response_status,
            usage_actions=usage_actions,
            usage_credits=usage_credits,
            agent_name=agent_name,
            agent_type=agent_type,
            action_trace=action_trace,
        )

    return builder.records()


def _convert_direct_agent(
    *,
    builder: _TraceBuilder,
    request_id: str,
    response_status: str,
    usage_actions: int,
    usage_credits: float,
    agent_name: str,
    agent_type: response_trace.AgentType,
    action_trace: legacy_trace.ActionTrace | None,
) -> None:
    actions = _operator_actions(action_trace)
    started_at = min((action.start_ts for action in actions), default=None)
    ended_at = max((action.end_ts for action in actions), default=None)
    agent_span_id = builder.add_span(
        path="agent",
        parent_id=None,
        started_at=started_at,
        ended_at=ended_at,
        span_data=response_trace.AgentSpanData(
            name=agent_name,
            agent_type=agent_type,
            status=_agent_status(response_status),
            request_id=request_id,
            usage=response_trace.UsageData(
                actions=usage_actions,
                credits=usage_credits,
            ),
        ),
    )
    _add_action_spans(
        builder=builder,
        actions=actions,
        parent_id=agent_span_id,
        path="agent/actions",
    )


def _convert_workflow(
    *,
    builder: _TraceBuilder,
    workflow: Mapping[str, Any],
    parent_id: str | None,
    path: str,
    fallback_request_id: str | None,
) -> None:
    workflow_span_id = builder.add_span(
        path=path,
        parent_id=parent_id,
        started_at=_timestamp(workflow.get("startTs")),
        ended_at=_timestamp(workflow.get("endTs")),
        error=_span_error(workflow),
        span_data=response_trace.WorkflowSpanData(
            workflow_name=_workflow_name(workflow) or "Workflow",
            workflow_id=_string(workflow.get("workflowId")) or "",
            status=_workflow_status(_string(workflow.get("status"))),
            request_id=(
                _string(workflow.get("requestId"))
                or _string(workflow.get("request_id"))
                or fallback_request_id
            ),
            output_variables=_mapping(workflow.get("variables")),
        ),
    )
    children = workflow.get("children")
    if isinstance(children, list):
        _convert_sibling_nodes(
            builder=builder,
            nodes=children,
            parent_id=workflow_span_id,
            path=f"{path}/children",
        )


def _convert_sibling_nodes(
    *,
    builder: _TraceBuilder,
    nodes: list[Any],
    parent_id: str,
    path: str,
) -> None:
    nested_nodes = _nest_control_flow_nodes(
        [node for node in nodes if isinstance(node, Mapping)]
    )
    iteration_index = 0
    for index, node in enumerate(nested_nodes):
        step_type = _string(node.get("stepType"))
        current_iteration_index = None
        if step_type in {"forIteration", "whileIteration"}:
            current_iteration_index = iteration_index
            iteration_index += 1
        _convert_trace_node(
            builder=builder,
            node=node,
            parent_id=parent_id,
            path=f"{path}/{index}",
            iteration_index=current_iteration_index,
        )


def _convert_trace_node(
    *,
    builder: _TraceBuilder,
    node: Mapping[str, Any],
    parent_id: str,
    path: str,
    iteration_index: int | None,
) -> None:
    kind = _string(node.get("kind"))
    if kind == "sub_workflow":
        nested_workflow = node.get("trace")
        if isinstance(nested_workflow, Mapping):
            _convert_workflow(
                builder=builder,
                workflow=nested_workflow,
                parent_id=parent_id,
                path=f"{path}/workflow",
                fallback_request_id=None,
            )
        return

    if kind != "gui_step":
        return

    step_type = _string(node.get("stepType")) or "unknown"
    children = node.get("children")
    direct_children = (
        [child for child in children if isinstance(child, Mapping)]
        if isinstance(children, list)
        else []
    )

    if step_type in {"forIteration", "whileIteration"}:
        started_at, ended_at = _child_timestamp_range(direct_children)
        iteration_span_id = builder.add_span(
            path=path,
            parent_id=parent_id,
            started_at=started_at or _timestamp(node.get("startTs")),
            ended_at=ended_at or _timestamp(node.get("endTs")),
            error=_span_error(node),
            span_data=response_trace.IterationSpanData(
                iteration_index=iteration_index or 0
            ),
        )
        _convert_sibling_nodes(
            builder=builder,
            nodes=direct_children,
            parent_id=iteration_span_id,
            path=f"{path}/children",
        )
        return

    data = _mapping(node.get("data")) or {}
    gui_span_id = builder.add_span(
        path=path,
        parent_id=parent_id,
        started_at=_timestamp(node.get("startTs")),
        ended_at=_timestamp(node.get("endTs")),
        error=_span_error(node),
        span_data=_gui_step_span_data(node=node, data=data, step_type=step_type),
    )

    child_parent_id = gui_span_id
    if step_type in _AGENT_STEP_TYPES:
        child_parent_id = _add_agent_span_for_gui_step(
            builder=builder,
            node=node,
            data=data,
            parent_id=gui_span_id,
            path=f"{path}/agent",
        )

    if direct_children:
        direct_children.sort(key=_node_start_millis)
        _convert_sibling_nodes(
            builder=builder,
            nodes=direct_children,
            parent_id=child_parent_id,
            path=f"{path}/children",
        )


def _add_agent_span_for_gui_step(
    *,
    builder: _TraceBuilder,
    node: Mapping[str, Any],
    data: Mapping[str, Any],
    parent_id: str,
    path: str,
) -> str:
    raw_agent_type = _string(data.get("agent_type"))
    agent_type = _normalize_agent_type(
        raw_agent_type or ("critic" if node.get("stepType") == "criticAgent" else None)
    )
    name = _agent_display_name(raw_agent_type, fallback=agent_type)
    agent_span_id = builder.add_span(
        path=path,
        parent_id=parent_id,
        started_at=_timestamp(node.get("startTs")),
        ended_at=_timestamp(node.get("endTs")),
        error=_span_error(node),
        span_data=response_trace.AgentSpanData(
            name=name,
            agent_type=agent_type,
            status=_agent_status(_string(node.get("status"))),
            request_id=(
                _string(data.get("request_id")) or _string(data.get("requestId"))
            ),
        ),
    )
    _add_action_spans(
        builder=builder,
        actions=_operator_actions(data.get("action_trace")),
        parent_id=agent_span_id,
        path=f"{path}/actions",
    )
    return agent_span_id


def _add_action_spans(
    *,
    builder: _TraceBuilder,
    actions: list[legacy_trace.OperatorActionTraceItem],
    parent_id: str,
    path: str,
) -> None:
    for index, action in enumerate(actions):
        builder.add_span(
            path=f"{path}/{index}",
            parent_id=parent_id,
            started_at=action.start_ts,
            ended_at=action.end_ts,
            span_data=response_trace.AgentActionSpanData(
                name="Agent action",
                message=action.action,
                url=action.url,
            ),
        )


def _gui_step_span_data(
    *,
    node: Mapping[str, Any],
    data: Mapping[str, Any],
    step_type: str,
) -> response_trace.BaseGuiStepSpanData:
    model = _GUI_STEP_DATA_TYPES.get(step_type)
    common: dict[str, Any] = {
        "step_id": _string(node.get("stepId")) or "",
        "name": _string(node.get("label")),
        "status": _gui_status(_string(node.get("status"))),
        "description": _string(data.get("description")),
        "starting_url": _string(data.get("url")),
    }
    extra = _gui_step_specific_fields(
        node=node,
        data=data,
        step_type=step_type,
    )

    if model is None:
        return response_trace.BaseGuiStepSpanData(
            type=_gui_step_discriminator(step_type),
            **common,
        )
    return model(**common, **extra)


def _gui_step_specific_fields(
    *,
    node: Mapping[str, Any],
    data: Mapping[str, Any],
    step_type: str,
) -> dict[str, Any]:
    children = node.get("children")
    child_nodes = children if isinstance(children, list) else []

    if step_type == "agenticMouseAction":
        return {
            "strategy": (
                "operator_fallback"
                if _operator_actions(data.get("action_trace"))
                else "direct"
            ),
            "verification_status": _boolean(
                data.get("verification_status"),
                data.get("verificationStatus"),
            ),
        }
    if step_type == "agenticSelector":
        return {
            "strategy": (
                "operator_fallback"
                if _operator_actions(data.get("action_trace"))
                else "selector"
            )
        }
    if step_type == "end":
        result_status = _string(data.get("result_status")) or _string(
            data.get("terminate_tree_result_status")
        )
        return {
            "result_status": (
                result_status if result_status in {"success", "error"} else None
            ),
            "message": _string(data.get("message")),
        }
    if step_type in {"for", "while"}:
        return {
            "total_iterations": sum(
                1
                for child in child_nodes
                if isinstance(child, Mapping)
                and child.get("stepType") in {"forIteration", "whileIteration"}
            )
        }
    if step_type == "getUrl":
        return {"url": _string(data.get("url"))}
    if step_type == "if":
        return {
            "selected_condition": _string(data.get("selected_condition"))
            or _string(data.get("selectedCondition")),
        }
    if step_type == "httpRequest":
        return {
            "status_code": _integer(
                data.get("status_code"),
                data.get("statusCode"),
            )
        }
    if step_type == "print":
        return {"message": _string(data.get("message"))}
    if step_type in {"emailAction", "slackAction"}:
        provider_response = data.get("providerResponse")
        return {
            "provider_status": (
                _string(provider_response.get("status"))
                if isinstance(provider_response, Mapping)
                else None
            )
        }
    if step_type == "tryCatch":
        return {
            "caught_condition": _string(data.get("caught_condition"))
            or _string(data.get("caughtCondition")),
        }
    if step_type == "output":
        return {
            "output_variables": (
                _mapping(data.get("output_variables"))
                or _mapping(data.get("variables"))
                or {}
            )
        }
    return {}


def _nest_control_flow_nodes(
    nodes: list[Mapping[str, Any]],
) -> list[Mapping[str, Any]]:
    parent_by_child: dict[int, int] = {}
    for child_index, child in enumerate(nodes):
        child_range = _node_time_range(child)
        if child_range is None:
            continue

        candidates: list[tuple[float, int]] = []
        for parent_index, possible_parent in enumerate(nodes):
            if parent_index == child_index:
                continue
            if possible_parent.get("kind") != "gui_step":
                continue
            if possible_parent.get("stepType") not in _CONTAINER_STEP_TYPES:
                continue
            parent_range = _node_time_range(possible_parent)
            if parent_range is None:
                continue
            if (
                parent_range[0] <= child_range[0]
                and child_range[1] <= parent_range[1]
                and parent_range != child_range
            ):
                candidates.append((parent_range[1] - parent_range[0], parent_index))

        if candidates:
            parent_by_child[child_index] = min(candidates)[1]

    children_by_parent: dict[int, list[int]] = {}
    for child_index, parent_index in parent_by_child.items():
        children_by_parent.setdefault(parent_index, []).append(child_index)

    child_indexes = set(parent_by_child)

    def build_node(index: int) -> Mapping[str, Any]:
        node = dict(nodes[index])
        existing_children = node.get("children")
        children = (
            [child for child in existing_children if isinstance(child, Mapping)]
            if isinstance(existing_children, list)
            else []
        )
        children.extend(
            build_node(child_index) for child_index in children_by_parent.get(index, [])
        )
        if children:
            children.sort(key=_node_start_millis)
            node["children"] = children
        return node

    return [
        build_node(index) for index in range(len(nodes)) if index not in child_indexes
    ]


def _child_timestamp_range(
    children: list[Mapping[str, Any]],
) -> tuple[str | None, str | None]:
    starts = [
        value
        for child in children
        if (value := _node_start_millis(child)) != float("inf")
    ]
    ends = [
        value
        for child in children
        if (value := _number(child.get("endTs"))) is not None
    ]
    return (
        _timestamp(min(starts)) if starts else None,
        _timestamp(max(ends)) if ends else None,
    )


def _operator_actions(
    value: object,
) -> list[legacy_trace.OperatorActionTraceItem]:
    if value is None:
        return []
    if isinstance(value, list) and (
        not value or isinstance(value[0], legacy_trace.OperatorActionTraceItem)
    ):
        return [
            item
            for item in value
            if isinstance(item, legacy_trace.OperatorActionTraceItem)
        ]
    if not isinstance(value, list):
        return []
    try:
        parsed = legacy_trace.parse_action_trace(value)
    except (TypeError, ValueError):
        return []
    return [
        item
        for item in parsed
        if isinstance(item, legacy_trace.OperatorActionTraceItem)
    ]


def _agent_identity(
    agent_kind: AgentKind | str,
) -> tuple[str, response_trace.AgentType]:
    if agent_kind is AgentKind.OPERATOR:
        return "Operator", "operator"
    if agent_kind is AgentKind.PRODUCTIVITY:
        return "Productivity", "generalist"
    if agent_kind is AgentKind.CORE_AGENT:
        return "Core Agent", "coreAgent"

    name = agent_kind.strip("/").rsplit("/", maxsplit=1)[-1] or "Custom Agent"
    return name, "generalist"


def _normalize_agent_type(value: str | None) -> response_trace.AgentType:
    normalized = (value or "").replace("_", "").lower()
    if normalized == "operator":
        return "operator"
    if normalized in {"generalist", "productivity"}:
        return "generalist"
    if normalized in {"core", "coreagent"}:
        return "coreAgent"
    runtime_types: dict[str, response_trace.AgentType] = {
        "jira": "jira",
        "googledrive": "googleDrive",
        "gmail": "gmail",
        "googlecalendar": "googleCalendar",
        "concur": "concur",
    }
    return runtime_types.get(normalized, "generalist")


def _agent_display_name(
    value: str | None,
    *,
    fallback: response_trace.AgentType,
) -> str:
    if value == "coreAgent":
        return "Core Agent"
    if value == "generalist":
        return "Productivity"
    if value:
        return _humanize(value)
    return _humanize(fallback)


def _workflow_status(value: str | None) -> response_trace.WorkflowSpanStatus:
    if value in {"pending", "input-required", "success", "error", "expired"}:
        return cast(response_trace.WorkflowSpanStatus, value)
    if value in {"completed", "endTree", "end_tree"}:
        return "success"
    return "error"


def _gui_status(value: str | None) -> response_trace.GuiStepSpanStatus:
    if value == "endTree":
        return "end_tree"
    if value in {"success", "error", "aborted", "end_tree"}:
        return cast(response_trace.GuiStepSpanStatus, value)
    return "error"


def _agent_status(value: str | None) -> response_trace.AgentSpanStatus:
    if value == "endTree":
        return "success"
    if value in {"success", "error", "input-required"}:
        return cast(response_trace.AgentSpanStatus, value)
    return "error"


def _span_error(value: Mapping[str, Any]) -> response_trace.SpanError | None:
    message = _string(value.get("errorMessage")) or _string(value.get("error_message"))
    if message is None:
        return None
    error_type = _string(value.get("errorType")) or _string(value.get("error_type"))
    return response_trace.SpanError(
        message=message,
        data={"error_type": error_type} if error_type else None,
    )


def _workflow_name(workflow: Mapping[str, Any] | None) -> str | None:
    if workflow is None:
        return None
    return _string(workflow.get("workflowName"))


def _stable_id(prefix: str, value: str, *, length: int) -> str:
    digest = hashlib.sha256(value.encode()).hexdigest()[:length]
    return f"{prefix}_{digest}"


def _timestamp(value: object) -> str | None:
    milliseconds = _number(value)
    if milliseconds is None:
        return None
    timestamp = datetime.fromtimestamp(milliseconds / 1000, tz=timezone.utc)
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _node_time_range(node: Mapping[str, Any]) -> tuple[float, float] | None:
    start = _number(node.get("startTs"))
    end = _number(node.get("endTs"))
    if start is None or end is None:
        return None
    return start, end


def _node_start_millis(node: Mapping[str, Any]) -> float:
    if node.get("kind") == "sub_workflow":
        trace = node.get("trace")
        if isinstance(trace, Mapping):
            start = _number(trace.get("startTs"))
            return start if start is not None else float("inf")
    start = _number(node.get("startTs"))
    return start if start is not None else float("inf")


def _gui_step_discriminator(step_type: str) -> str:
    return f"gui_step.{_snake_case(step_type)}"


def _snake_case(value: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()


def _humanize(value: str) -> str:
    return _snake_case(value).replace("_", " ").title()


def _mapping(value: object) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, Mapping) else None


def _string(value: object) -> str | None:
    return value if isinstance(value, str) else None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _integer(*values: object) -> int | None:
    return next(
        (
            value
            for value in values
            if isinstance(value, int) and not isinstance(value, bool)
        ),
        None,
    )


def _boolean(*values: object) -> bool | None:
    return next((value for value in values if isinstance(value, bool)), None)


__all__ = ["build_response_trace"]
