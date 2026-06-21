from __future__ import annotations

import argparse
import json
from pathlib import Path

from lightrag_ext.us_dsl.migration_bundle_validator import validate_bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate intranet migration bundle")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--verify-checksums", action="store_true")
    parser.add_argument("--scan-secrets", action="store_true")
    parser.add_argument("--scan-real-data", action="store_true")
    parser.add_argument("--scan-absolute-paths", action="store_true")
    parser.add_argument("--scan-hardcodes", action="store_true")
    args = parser.parse_args(argv)
    report = validate_bundle(args.bundle, verify_checksums=args.verify_checksums or True, scan_hardcodes=args.scan_hardcodes or True)
    output_dir = Path(args.bundle).parent
    (output_dir / "checksums_validation.json").write_text(json.dumps(report["checksums"], ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if report["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
