from __future__ import annotations

from lightrag_ext.us_dsl.runtime_observability import StructuredRuntimeLogger, logs_contain_forbidden_payload, required_trace_fields_present


def test_structured_log_has_required_trace_fields() -> None:
    logger = StructuredRuntimeLogger()
    record = logger.emit(trace_id="t", run_id="r", batch_id="b", stage="S", component="C", event="E")
    assert required_trace_fields_present(record)


def test_structured_log_excludes_secrets_and_full_text() -> None:
    logger = StructuredRuntimeLogger()
    logger.emit(
        trace_id="t",
        run_id="r",
        batch_id="b",
        stage="S",
        component="C",
        event="E",
        extra={"api_key": "sk-unsafeunsafeunsafe", "raw_text": "full raw document"},
    )
    flags = logs_contain_forbidden_payload(logger.to_list())
    assert flags["logs_contain_secret"] is False
    assert flags["logs_contain_full_document"] is False
