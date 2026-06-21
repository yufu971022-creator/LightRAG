from __future__ import annotations

import hashlib
import time
from typing import Any

from .sidecar_registry_types import (
    IngestionBatchRecord,
    SidecarPersistenceBundle,
    SidecarPersistenceConfig,
    SidecarPersistenceResult,
)


def persist_sidecar_bundle(
    *,
    repository,
    route_decision: Any,
    unified_parse_result: Any,
    raw_evidence_result: Any,
    semantic_branch_result: Any,
    config: SidecarPersistenceConfig,
) -> SidecarPersistenceResult:
    del route_decision, raw_evidence_result, semantic_branch_result, config
    if not isinstance(unified_parse_result, SidecarPersistenceBundle):
        raise TypeError("24C-0 persistence service expects a SidecarPersistenceBundle fixture or adapter output")
    bundle = unified_parse_result
    if bundle.batch.batch_id != _batch_id_from_trace(bundle.batch.trace_id):
        raise ValueError("trace_document_version_consistency_failed: batch_id must be stable from trace_id")
    existing = repository.get_batch(bundle.batch.batch_id)
    if existing is None:
        repository.begin_batch(bundle.batch)
    try:
        if bundle.batch.semantic_route == "PARSE_FAILED":
            repository.persist_bundle(bundle)
            repository.fail_batch(bundle.batch.batch_id, {"code": "PARSE_FAILED", "summary": "parse failed fixture"})
            status = "FAILED"
        else:
            repository.persist_bundle(bundle)
            integrity = repository.validate_referential_integrity()
            if not integrity["passed"]:
                raise RuntimeError("referential_integrity_failed")
            repository.complete_batch(bundle.batch.batch_id, repository.record_counts())
            status = "COMPLETED"
        return SidecarPersistenceResult(
            batch_id=bundle.batch.batch_id,
            trace_id=bundle.batch.trace_id,
            document_id=bundle.document["document_id"],
            document_version_id=bundle.document_version["document_version_id"],
            semantic_route=bundle.batch.semantic_route,
            status=status,
            record_counts=repository.record_counts(),
            referential_integrity=repository.validate_referential_integrity(),
        )
    except Exception as exc:
        repository.fail_batch(bundle.batch.batch_id, {"code": type(exc).__name__, "summary": str(exc)})
        return SidecarPersistenceResult(
            batch_id=bundle.batch.batch_id,
            trace_id=bundle.batch.trace_id,
            document_id=bundle.document["document_id"],
            document_version_id=bundle.document_version["document_version_id"],
            semantic_route=bundle.batch.semantic_route,
            status="FAILED",
            record_counts=repository.record_counts(),
            referential_integrity=repository.validate_referential_integrity(),
            error={"code": type(exc).__name__, "summary": str(exc)},
        )


def build_sidecar_fixture_bundle(
    route: str,
    *,
    trace_id: str | None = None,
    document_id: str = "doc-24c0-fixture",
    content_hash: str | None = None,
    batch_suffix: str | None = None,
    fail_after_semantic_relations: bool = False,
) -> SidecarPersistenceBundle:
    now = _now()
    trace_id = trace_id or f"trace-{route.lower()}-{batch_suffix or 'a'}"
    batch_id = _batch_id_from_trace(trace_id)
    content_hash = content_hash or _stable_hash(f"{document_id}:content:v1")
    document_version_id = "docver-" + _stable_hash(f"{document_id}:{content_hash}")[:16]
    document = {
        "document_id": document_id,
        "source_uri_hash": _stable_hash(f"synthetic://24c0/{document_id}"),
        "source_type": "synthetic",
        "module_code": "BLOCK24C0",
        "logical_name": "24C0 Sidecar Fixture",
        "created_at": now,
        "updated_at": now,
    }
    version = {
        "document_version_id": document_version_id,
        "document_id": document_id,
        "content_hash": content_hash,
        "parser_name": "unified_raw_evidence_parser",
        "parser_version": "24B-1",
        "normalized_text_hash": content_hash,
        "status": "FAILED" if route == "PARSE_FAILED" else "TEXT_INDEXED",
        "previous_version_id": None,
        "created_at": now,
    }
    batch = IngestionBatchRecord(
        batch_id=batch_id,
        trace_id=trace_id,
        requested_mode="shadow",
        semantic_route=route,
        started_at=now,
    )
    if route == "PARSE_FAILED":
        return SidecarPersistenceBundle(batch=batch, document=document, document_version=version)
    raw_chunks = _chunks(document_version_id, now)
    units = _source_units(document_version_id, now)
    links = _links(document_version_id)
    if route == "RAW_ONLY":
        return SidecarPersistenceBundle(batch=batch, document=document, document_version=version, raw_chunks=raw_chunks, source_text_units=units, chunk_text_unit_links=links)
    objects = _semantic_objects(document_version_id, now, route)
    relations = _semantic_relations(document_version_id, objects, now)
    graph_mappings = _graph_mappings(batch_id, objects, relations, now)
    evidence = _evidence_mappings(objects, relations, units, now)
    term_mappings = _term_mappings(now)
    version_groups = _version_groups(now)
    version_members = _version_members(objects, now)
    issues = _issues(batch_id, document_version_id, units, now) if route == "DSL_PARTIAL" else []
    rollback = _rollback_records(batch_id, graph_mappings, now)
    return SidecarPersistenceBundle(
        batch=batch,
        document=document,
        document_version=version,
        raw_chunks=raw_chunks,
        source_text_units=units,
        chunk_text_unit_links=links,
        semantic_objects=objects,
        semantic_relations=relations,
        graph_object_mappings=graph_mappings,
        evidence_mappings=evidence,
        term_mappings=term_mappings,
        version_groups=version_groups,
        version_members=version_members,
        issues=issues,
        rollback_records=rollback,
        fail_after_semantic_relations=fail_after_semantic_relations,
    )


def _chunks(document_version_id: str, now: str) -> list[dict[str, Any]]:
    suffix = _suffix(document_version_id)
    return [
        {"chunk_id": f"chunk-{suffix}-0", "document_version_id": document_version_id, "chunk_order": 0, "start_offset": 0, "end_offset": 120, "token_count": 120, "content_hash": _stable_hash(f"{document_version_id}:chunk0"), "source_span": {"start": 0, "end": 120}, "created_at": now},
        {"chunk_id": f"chunk-{suffix}-1", "document_version_id": document_version_id, "chunk_order": 1, "start_offset": 121, "end_offset": 240, "token_count": 119, "content_hash": _stable_hash(f"{document_version_id}:chunk1"), "source_span": {"start": 121, "end": 240}, "created_at": now},
    ]


def _source_units(document_version_id: str, now: str) -> list[dict[str, Any]]:
    suffix = _suffix(document_version_id)
    return [
        {"text_unit_id": f"tu-{suffix}-us", "document_version_id": document_version_id, "source_us_id": "US-2401", "section_type": "user_story", "start_offset": 0, "end_offset": 60, "text_hash": _stable_hash(f"{document_version_id}:tu-us"), "feature_key": "bank-status-query", "primary_domain": "MasterData", "related_domains": ["MasterData"], "evidence_excerpt": "US-2401 Bank Status query", "created_at": now},
        {"text_unit_id": f"tu-{suffix}-field", "document_version_id": document_version_id, "source_us_id": "US-2401", "section_type": "field", "start_offset": 61, "end_offset": 140, "text_hash": _stable_hash(f"{document_version_id}:tu-field"), "feature_key": "bank-status-query", "primary_domain": "MasterData", "related_domains": ["MasterData"], "evidence_excerpt": "Query Condition field", "created_at": now},
        {"text_unit_id": f"tu-{suffix}-rule", "document_version_id": document_version_id, "source_us_id": "US-2401", "section_type": "rule", "start_offset": 141, "end_offset": 230, "text_hash": _stable_hash(f"{document_version_id}:tu-rule"), "feature_key": "bank-status-query", "primary_domain": "MasterData", "related_domains": ["MasterData"], "evidence_excerpt": "Bank Status has Query Condition", "created_at": now},
    ]


def _links(document_version_id: str) -> list[dict[str, Any]]:
    suffix = _suffix(document_version_id)
    return [
        {"link_id": f"link-{suffix}-0", "document_version_id": document_version_id, "chunk_id": f"chunk-{suffix}-0", "text_unit_id": f"tu-{suffix}-us", "overlap_start_offset": 0, "overlap_end_offset": 60, "overlap_char_count": 60, "chunk_coverage_ratio": 0.5, "text_unit_coverage_ratio": 1.0, "link_type": "CONTAINS"},
        {"link_id": f"link-{suffix}-1", "document_version_id": document_version_id, "chunk_id": f"chunk-{suffix}-0", "text_unit_id": f"tu-{suffix}-field", "overlap_start_offset": 61, "overlap_end_offset": 120, "overlap_char_count": 59, "chunk_coverage_ratio": 0.49, "text_unit_coverage_ratio": 0.75, "link_type": "PARTIAL"},
        {"link_id": f"link-{suffix}-2", "document_version_id": document_version_id, "chunk_id": f"chunk-{suffix}-1", "text_unit_id": f"tu-{suffix}-rule", "overlap_start_offset": 141, "overlap_end_offset": 230, "overlap_char_count": 89, "chunk_coverage_ratio": 0.75, "text_unit_coverage_ratio": 1.0, "link_type": "CONTAINS"},
    ]


def _semantic_objects(document_version_id: str, now: str, route: str) -> list[dict[str, Any]]:
    if route == "DSL_PARTIAL":
        return [
            _object("sem:rule_version", document_version_id, "RuleVersion", "Rule Version", "RuleManagement", "rule-version-review", "vg-rule-version", now),
            _object("sem:approval_status", document_version_id, "FieldSpec", "Approval Status", "RuleManagement", "rule-version-review", "vg-rule-version", now),
        ]
    return [
        _object("sem:bank_status", document_version_id, "DomainObject", "Bank Status", "MasterData", "bank-status-query", "vg-bank-status", now),
        _object("sem:query_condition", document_version_id, "FieldSpec", "Query Condition", "MasterData", "bank-status-query", "vg-bank-status", now),
    ]


def _object(object_id: str, version_id: str, object_type: str, name: str, domain: str, feature: str, group: str, now: str) -> dict[str, Any]:
    return {"semantic_object_id": object_id, "document_version_id": version_id, "object_type": object_type, "canonical_name": name, "domain_code": domain, "feature_key": feature, "knowledge_status": "APPROVED", "validation_status": "VALID", "review_decision": "APPROVED_PFSS", "version_group_key": group, "idempotency_key": object_id, "created_at": now, "updated_at": now}


def _semantic_relations(document_version_id: str, objects: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    src = objects[0]["semantic_object_id"]
    tgt = objects[1]["semantic_object_id"]
    relation_id = f"rel:{src}:has_field:{tgt}"
    return [{"semantic_relation_id": relation_id, "document_version_id": document_version_id, "src_semantic_object_id": src, "relation_type": "HasField", "tgt_semantic_object_id": tgt, "knowledge_status": "APPROVED", "validation_status": "VALID", "review_decision": "APPROVED_PFSS", "idempotency_key": f"{src}:HasField:{tgt}", "created_at": now, "updated_at": now}]


def _graph_mappings(batch_id: str, objects: list[dict[str, Any]], relations: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    rows = []
    for obj in objects:
        rows.append({"mapping_id": f"map:{obj['semantic_object_id']}", "batch_id": batch_id, "graph_space": "PFSS", "graph_namespace": "pfss_test_graph", "graph_object_kind": "node", "graph_object_id": obj["semantic_object_id"], "semantic_object_id": obj["semantic_object_id"], "semantic_relation_id": None, "source_id": "chunk-24c0-0", "rollback_key": f"rb:{obj['semantic_object_id']}", "created_at": now})
    for rel in relations:
        rows.append({"mapping_id": f"map:{rel['semantic_relation_id']}", "batch_id": batch_id, "graph_space": "PFSS", "graph_namespace": "pfss_test_graph", "graph_object_kind": "edge", "graph_object_id": rel["semantic_relation_id"], "semantic_object_id": None, "semantic_relation_id": rel["semantic_relation_id"], "source_id": "chunk-24c0-1", "rollback_key": f"rb:{rel['semantic_relation_id']}", "created_at": now})
    return rows


def _evidence_mappings(objects: list[dict[str, Any]], relations: list[dict[str, Any]], units: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    rows = []
    for index, obj in enumerate(objects):
        unit = units[min(index, len(units) - 1)]
        rows.append({"evidence_mapping_id": f"ev:{obj['semantic_object_id']}", "semantic_object_id": obj["semantic_object_id"], "semantic_relation_id": None, "text_unit_id": unit["text_unit_id"], "source_span": {"start": unit["start_offset"], "end": unit["end_offset"]}, "text_hash": unit["text_hash"], "evidence_excerpt": unit["evidence_excerpt"], "evidence_role": "object_support", "created_at": now})
    for rel in relations:
        unit = units[-1]
        rows.append({"evidence_mapping_id": f"ev:{rel['semantic_relation_id']}", "semantic_object_id": None, "semantic_relation_id": rel["semantic_relation_id"], "text_unit_id": unit["text_unit_id"], "source_span": {"start": unit["start_offset"], "end": unit["end_offset"]}, "text_hash": unit["text_hash"], "evidence_excerpt": unit["evidence_excerpt"], "evidence_role": "relation_support", "created_at": now})
    return rows


def _term_mappings(now: str) -> list[dict[str, Any]]:
    return [{"term_mapping_id": "term:bank-status", "original_term": "Bank Status", "canonical_term": "Bank Status", "language_code": "en", "domain_code": "MasterData", "feature_key": "bank-status-query", "object_type": "DomainObject", "confidence": 1.0, "mapping_status": "CONFIRMED", "mapping_source": "fixture", "created_at": now}]


def _version_groups(now: str) -> list[dict[str, Any]]:
    return [
        {"version_group_key": "vg-bank-status", "module_code": "BLOCK24C0", "domain_code": "MasterData", "feature_key": "bank-status-query", "object_type": "DomainObject", "object_key": "bank-status", "rule_dimension": "canonical", "created_at": now, "updated_at": now},
        {"version_group_key": "vg-rule-version", "module_code": "BLOCK24C0", "domain_code": "RuleManagement", "feature_key": "rule-version-review", "object_type": "RuleVersion", "object_key": "rule-version", "rule_dimension": "approval", "created_at": now, "updated_at": now},
    ]


def _version_members(objects: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    first = objects[0]
    return [{"version_member_id": f"vm:{first['semantic_object_id']}", "version_group_key": first["version_group_key"], "semantic_object_id": first["semantic_object_id"], "rule_version": "v1", "version_status": "current", "latest_flag": True, "valid_from": now, "valid_to": None, "supersedes_member_id": None, "created_at": now}]


def _issues(batch_id: str, version_id: str, units: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    text_unit_id = units[-1]["text_unit_id"]
    return [
        {"issue_id": f"issue:{version_id}:version", "batch_id": batch_id, "document_version_id": version_id, "semantic_object_id": "sem:rule_version", "semantic_relation_id": None, "text_unit_id": text_unit_id, "issue_type": "VERSION_REVIEW_REQUIRED", "severity": "high", "reason_code": "version_policy_review_required", "review_required": True, "issue_status": "OPEN", "evidence_excerpt": "Version override requires manual approval", "created_at": now, "updated_at": now},
        {"issue_id": f"issue:{version_id}:missing", "batch_id": batch_id, "document_version_id": version_id, "semantic_object_id": "sem:rule_version", "semantic_relation_id": None, "text_unit_id": text_unit_id, "issue_type": "MISSING_EVIDENCE", "severity": "medium", "reason_code": "missing_explicit_source_unit", "review_required": True, "issue_status": "OPEN", "evidence_excerpt": "supersedes prior rule lacks explicit evidence link", "created_at": now, "updated_at": now},
    ]


def _rollback_records(batch_id: str, mappings: list[dict[str, Any]], now: str) -> list[dict[str, Any]]:
    return [{"rollback_record_id": f"rollback:{batch_id}:{m['graph_object_id']}", "batch_id": batch_id, "graph_space": m["graph_space"], "graph_namespace": m["graph_namespace"], "graph_object_kind": m["graph_object_kind"], "graph_object_id": m["graph_object_id"], "rollback_key": m["rollback_key"], "planned_action": "DELETE_GRAPH_OBJECT", "execution_status": "NOT_EXECUTED", "created_at": now} for m in mappings]


def _batch_id_from_trace(trace_id: str) -> str:
    return "batch-" + _stable_hash(trace_id)[:16]


def _suffix(document_version_id: str) -> str:
    return document_version_id[-8:]


def _stable_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
