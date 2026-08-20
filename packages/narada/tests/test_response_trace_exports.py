import narada
import narada.tracing


def test_trace_models_are_publicly_exported() -> None:
    assert narada.Trace is narada.tracing.Trace
    assert narada.Span is narada.tracing.Span
    assert narada.WorkflowSpanData is narada.tracing.WorkflowSpanData
    assert narada.AgentActionSpanData is narada.tracing.AgentActionSpanData
    assert narada.AgentSpanData is narada.tracing.AgentSpanData
    assert narada.tracing.AgentStepData is not None
    assert narada.tracing.GoToUrlStepData is not None
    assert narada.tracing.HttpRequestStepData is not None
    assert not hasattr(narada.tracing, "AgentStepSpanInput")
    assert not hasattr(narada.tracing, "GoToUrlStepSpanInput")
    assert not hasattr(narada.tracing, "HttpRequestStepSpanInput")
