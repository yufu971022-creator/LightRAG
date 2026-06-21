from __future__ import annotations

import argparse
import json
from pathlib import Path

from lightrag_ext.us_dsl.portable_bundle_smoke import run_portable_bundle_smoke


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run portable bundle smoke outside the source tree")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--extract-to", required=True)
    parser.add_argument("--sanitized-config", action="store_true")
    parser.add_argument("--sanitized-fixtures", action="store_true")
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--fake-deterministic-embedding", action="store_true")
    parser.add_argument("--fake-query-llm", action="store_true")
    parser.add_argument("--enable-functional-qa", action="store_true")
    parser.add_argument("--enable-impact-analysis", action="store_true")
    parser.add_argument("--enable-lifecycle-rebuild", action="store_true")
    parser.add_argument("--enable-quality-gates", action="store_true")
    parser.add_argument("--cleanup", action="store_true")
    args = parser.parse_args(argv)
    report = run_portable_bundle_smoke(args.bundle, args.extract_to, cleanup=args.cleanup)
    output_dir = Path(args.bundle).parent
    (output_dir / "portable_bundle_smoke_report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["portable_smoke_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
