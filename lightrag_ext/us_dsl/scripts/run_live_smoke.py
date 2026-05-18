from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from lightrag_ext.us_dsl.ingestion_adapter import build_dsl_aware_ingestion_payload
from lightrag_ext.us_dsl.live_llm_adapter import (
    resolve_live_llm_status_from_env_or_lightrag,
)
from lightrag_ext.us_dsl.live_smoke_eval import (
    live_smoke_enabled,
    run_live_extraction_smoke,
    serialize_live_smoke_report,
)
from lightrag_ext.us_dsl.source_text_unit_builder import detect_us_blocks
from lightrag_ext.us_dsl.tests.test_ingestion_adapter import (
    _valid_fx_dsl_result,
    _validator_ready,
)
from lightrag_ext.us_dsl.tests.test_lc_acceptable_bank_large_us import (
    build_minimal_lc_dsl_result_from_us_blocks,
    load_lc_acceptable_bank_fixture,
)
from lightrag_ext.us_dsl.tests.test_source_text_unit_builder import FX_THREE_US_FULL
from lightrag_ext.us_dsl.extraction_eval import select_extraction_eval_samples


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.max_output_tokens is not None:
        os.environ["LIGHTRAG_DSL_LIVE_SMOKE_MAX_TOKENS"] = str(
            args.max_output_tokens
        )
    pairs = _build_input_pairs(include_fx=args.include_fx, include_lc=args.include_lc)
    resolution = resolve_live_llm_status_from_env_or_lightrag()
    llm_callable = resolution.llm_callable if live_smoke_enabled() else None
    report = run_live_extraction_smoke(
        pairs,
        llm_callable=llm_callable,
        max_samples=args.max_samples,
        run_gleaning=args.run_gleaning,
        max_gleaning_samples=args.max_gleaning_samples,
        max_output_tokens=args.max_output_tokens,
    )
    serialized = serialize_live_smoke_report(report, include_raw_output=True)
    serialized["llmResolution"] = {
        "binding": resolution.binding,
        "model": resolution.model,
        "hostConfigured": resolution.host_configured,
        "apiKeyConfigured": resolution.api_key_configured,
        "envLoadedFrom": resolution.env_loaded_from,
        "reason": resolution.reason,
    }
    output = json.dumps(serialized, ensure_ascii=False, indent=2)
    print(output)
    if args.report_file:
        report_path = Path(args.report_file)
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(output, encoding="utf-8")
    return 0


def _build_input_pairs(*, include_fx: bool, include_lc: bool):
    pairs = []
    if include_fx:
        fx_payload = build_dsl_aware_ingestion_payload(
            FX_THREE_US_FULL,
            document_id="DOC_FX_001",
            dsl_result=_valid_fx_dsl_result(),
        )
        pairs.extend(select_extraction_eval_samples(fx_payload, max_samples=4))
    if include_lc:
        content = load_lc_acceptable_bank_fixture()
        blocks = detect_us_blocks(content)
        dsl_result = _validator_ready(build_minimal_lc_dsl_result_from_us_blocks(blocks))
        lc_payload = build_dsl_aware_ingestion_payload(
            content,
            document_id="DOC_LCAB_001",
            dsl_result=dsl_result,
        )
        lc_pairs = select_extraction_eval_samples(lc_payload, max_samples=8)
        pairs.extend(lc_pairs[:4])
    return _interleave_pairs(pairs)


def _interleave_pairs(pairs):
    fx_pairs = [pair for pair in pairs if pair.source_us_id in {"1", "2", "3"}]
    lc_pairs = [pair for pair in pairs if pair.source_us_id not in {"1", "2", "3"}]
    result = []
    while fx_pairs or lc_pairs:
        if fx_pairs:
            result.append(fx_pairs.pop(0))
        if lc_pairs:
            result.append(lc_pairs.pop(0))
    return result


def _parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(description="Run DSL-aware live smoke evaluation.")
    parser.add_argument("--max-samples", type=int, default=6)
    parser.add_argument("--include-fx", type=_bool_arg, default=True)
    parser.add_argument("--include-lc", type=_bool_arg, default=True)
    parser.add_argument("--include-generic-text", type=_bool_arg, default=True)
    parser.add_argument("--run-gleaning", type=_bool_arg, default=False)
    parser.add_argument("--max-gleaning-samples", type=int, default=2)
    parser.add_argument("--max-output-tokens", type=int, default=None)
    parser.add_argument("--report-file", default=None)
    args = parser.parse_args(argv)
    if not args.include_generic_text:
        # Generic samples are appended by the smoke harness. Reducing max samples is
        # the current lightweight way to keep this runner storage-free and simple.
        args.max_samples = max(1, args.max_samples - 1)
    return args


def _bool_arg(value: str | bool) -> bool:
    if isinstance(value, bool):
        return value
    return value.lower() in {"1", "true", "yes", "y", "on"}


if __name__ == "__main__":
    raise SystemExit(main())
