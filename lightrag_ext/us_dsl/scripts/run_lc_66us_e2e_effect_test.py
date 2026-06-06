from __future__ import annotations

import argparse
import json
from pathlib import Path

from lightrag_ext.us_dsl.lc_66us_e2e_effect_test import (
    DEFAULT_LC_US_FILE,
    DEFAULT_OUTPUT_DIR,
    NAMESPACE,
    run_lc_66us_e2e_effect_test,
    serialize_lc_66us_effect_test_result,
)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    result = run_lc_66us_e2e_effect_test(
        lc_us_file=args.lc_us_file,
        output_dir=args.output_dir,
        namespace=args.namespace,
        working_dir=args.working_dir,
        mode=args.mode,
    )
    print(json.dumps(serialize_lc_66us_effect_test_result(result), indent=2, ensure_ascii=False))
    return 0 if result.graph_write_succeeded else 1


def _parse_args(argv: list[str] | None):
    parser = argparse.ArgumentParser(
        description="Run LC 66US offline test graph effect test and write all reports."
    )
    parser.add_argument("--lc-us-file", default=str(DEFAULT_LC_US_FILE))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--namespace", default=NAMESPACE)
    parser.add_argument(
        "--working-dir",
        default=str(Path(DEFAULT_OUTPUT_DIR) / "test_graph_workspace"),
    )
    parser.add_argument("--mode", default="offline", choices=["offline"])
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
