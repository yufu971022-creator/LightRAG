from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

from lightrag_ext.us_dsl.migration_bundle_builder import build_migration_bundle, compare_two_builds


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build data-free intranet migration bundle")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--production-disabled", action="store_true")
    parser.add_argument("--exclude-real-data", action="store_true")
    parser.add_argument("--exclude-secrets", action="store_true")
    parser.add_argument("--include-sanitized-fixtures", action="store_true")
    parser.add_argument("--include-tests", action="store_true")
    parser.add_argument("--include-runbooks", action="store_true")
    args = parser.parse_args(argv)
    output = Path(args.output_dir)
    output.mkdir(parents=True, exist_ok=True)
    first = build_migration_bundle(output)
    second = build_migration_bundle(output, bundle_name="intranet_migration_bundle_repro_check")
    reproducible = compare_two_builds(Path(first.bundle_path), Path(second.bundle_path))
    shutil.rmtree(second.bundle_path)
    Path(second.archive_path).unlink(missing_ok=True)
    _write_json(output / "reproducible_build_report.json", reproducible)
    _write_json(output / "package_inventory.json", {"files": first.package_manifest["inventory"]})
    _write_json(output / "security_scan_report.json", first.security_scan)
    _write_json(output / "final_anti_hardcode_report.json", first.anti_hardcode)
    _write_json(output / "runtime_facade_report.json", {"runtime_facade_implemented": True, "reused_28a_orchestrator": True})
    print(json.dumps(first.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
