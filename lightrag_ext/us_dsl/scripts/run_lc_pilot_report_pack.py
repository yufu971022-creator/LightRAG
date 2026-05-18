from __future__ import annotations

import argparse
import json
from pathlib import Path

from lightrag_ext.us_dsl.pilot_execution_pack import (
    build_pilot_execution_pack_from_source,
    serialize_pilot_execution_pack,
    write_pilot_execution_files,
)
from lightrag_ext.us_dsl.pilot_report_pack import serialize_pilot_report_pack


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = build_pilot_execution_pack_from_source(
        args.source_file,
        document_id=args.document_id,
        module_name=args.module_name,
        module_code=args.module_code,
        expected_us_count=args.expected_us_count,
        expected_first_us_id=args.expected_first_us_id,
        expected_last_us_id=args.expected_last_us_id,
        output_dir=args.output_dir,
        max_candidate_samples=args.max_candidate_samples,
        copy_fixture_if_missing=args.copy_fixture_if_missing,
        fixture_path=args.fixture_path,
        additional_coverage_notes=[
            "Current run validates only LC acceptable bank 66 US from the provided local file.",
            "AC/AT fixture not found; do not claim AC/AT coverage.",
        ],
    )
    written = write_pilot_execution_files(result, args.output_dir, file_prefix=args.file_prefix)
    summary = {
        "executionPack": serialize_pilot_execution_pack(result.execution_pack),
        "pilotReportSummary": {
            "documentId": result.pilot_report_pack.document_id,
            "sourceUsCount": result.pilot_report_pack.source_us_count,
            "sourceTextUnitCount": result.pilot_report_pack.source_text_unit_count,
            "candidateEntityCount": result.pilot_report_pack.candidate_entity_count,
            "candidateRelationCount": result.pilot_report_pack.candidate_relation_count,
            "humanReviewRatio": result.pilot_report_pack.review_summary["humanReviewRatio"],
            "readiness": result.pilot_report_pack.pilot_readiness.status,
        },
        "pilotReportPack": serialize_pilot_report_pack(result.pilot_report_pack),
        "writtenFiles": [str(path) for path in written],
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(description="Generate LC report-only pilot pack.")
    parser.add_argument(
        "--source-file",
        default="/Users/hufaofao/Projects/LC_Acceptable_Bank_US_v1.md",
    )
    parser.add_argument("--output-dir", default="/tmp/lcab_pilot_report_pack")
    parser.add_argument("--document-id", default="DOC_LCAB_001")
    parser.add_argument("--module-name", default="LC Acceptable Bank")
    parser.add_argument("--module-code", default="LCAB")
    parser.add_argument("--expected-us-count", type=int, default=66)
    parser.add_argument("--expected-first-us-id", default="US-LCAB-001")
    parser.add_argument("--expected-last-us-id", default="US-LCAB-066")
    parser.add_argument("--max-candidate-samples", type=int, default=6)
    parser.add_argument("--file-prefix", default="lc")
    parser.add_argument("--copy-fixture-if-missing", action="store_true")
    parser.add_argument(
        "--fixture-path",
        default=str(
            Path("lightrag_ext/us_dsl/tests/fixtures/LC_Acceptable_Bank_US_v1.md")
        ),
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
