from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lightrag_ext.us_dsl.dsl_aware_runtime_facade import DslAwareRuntimeFacade
from lightrag_ext.us_dsl.runtime_config_loader import load_runtime_config


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="DSL-aware runtime facade CLI")
    parser.add_argument("command", choices=["preflight", "health", "readiness", "ingest", "query", "impact", "rebuild", "diagnostics"])
    parser.add_argument("--config")
    parser.add_argument("--manifest")
    parser.add_argument("--request")
    parser.add_argument("--trace-id")
    args = parser.parse_args(argv)
    config = load_runtime_config(args.config) if args.config else load_runtime_config()
    facade = DslAwareRuntimeFacade(config)
    payload = _load_payload(args)
    if args.command == "preflight":
        result = facade.preflight(payload)
    elif args.command == "health":
        result = facade.health()
    elif args.command == "readiness":
        result = facade.readiness()
    elif args.command == "ingest":
        result = facade.ingest_documents(payload)
    elif args.command == "query":
        result = facade.query_function(payload)
    elif args.command == "impact":
        result = facade.analyze_impact(payload)
    elif args.command == "rebuild":
        result = facade.rebuild_document_version(payload)
    else:
        result = facade.diagnostics(payload)
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _load_payload(args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if args.request:
        payload.update(json.loads(Path(args.request).read_text(encoding="utf-8")))
    if args.manifest:
        payload["manifest"] = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.trace_id:
        payload["trace_id"] = args.trace_id
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
