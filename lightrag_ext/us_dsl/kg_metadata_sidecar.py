from __future__ import annotations

from collections import Counter
import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .kg_payload_types import DslKgPayload, KgChunk, KgEntity, KgRelationship


OBJECT_KIND_CHUNK = "chunk"
OBJECT_KIND_ENTITY = "entity"
OBJECT_KIND_RELATIONSHIP = "relationship"

REQUIRED_METADATA_KEYS = (
    "documentId",
    "sourceUsId",
    "textUnitId",
    "sourceSpan",
    "textHash",
    "evidenceText",
    "featureKey",
    "domainCode",
    "sectionType",
    "knowledgeStatus",
    "validationStatus",
    "reviewDecision",
    "confidenceScore",
    "ruleVersion",
    "latestFlag",
    "versionStatus",
    "supersedes",
    "originalTerm",
    "canonicalTerm",
    "candidateId",
    "extractionRunId",
    "pilotReportId",
)

EVIDENCE_REQUIRED_KEYS = ("sourceUsId", "textUnitId", "sourceSpan", "textHash", "evidenceText")
REVIEW_REQUIRED_KEYS = ("knowledgeStatus", "validationStatus", "reviewDecision")
VERSION_KEYS = ("ruleVersion", "latestFlag", "versionStatus", "supersedes")


@dataclass(frozen=True)
class KgMetadataSidecarRecord:
    sidecar_id: str
    object_kind: str
    external_key: str
    lightrag_ref_key: str | None
    source_id: str | None
    entity_name: str | None
    entity_type: str | None
    src_id: str | None
    tgt_id: str | None
    relation_type: str | None
    keywords: str | None
    metadata: dict[str, Any]
    metadata_hash: str
    payload_hash: str
    namespace: str
    created_at: str


@dataclass(frozen=True)
class SidecarCoverageIssue:
    severity: str
    code: str
    message: str
    external_key: str | None = None


@dataclass(frozen=True)
class SidecarCoverageReport:
    chunk_coverage_ratio: float
    entity_coverage_ratio: float
    relationship_coverage_ratio: float
    missing_chunk_metadata_count: int
    missing_entity_metadata_count: int
    missing_relationship_metadata_count: int
    evidence_missing_count: int
    version_metadata_missing_count: int
    review_metadata_missing_count: int
    pass_status: str
    issues: list[SidecarCoverageIssue] = field(default_factory=list)


@dataclass(frozen=True)
class GraphInsertSidecarAlignmentReport:
    chunk_alignment_ratio: float
    entity_alignment_ratio: float
    relationship_alignment_ratio: float
    extra_sidecar_record_count: int
    missing_sidecar_record_count: int
    pass_status: str
    issues: list[SidecarCoverageIssue] = field(default_factory=list)


class KgMetadataSidecarStore:
    def __init__(self, json_path: str | Path | None = None) -> None:
        self.json_path = Path(json_path) if json_path is not None else None
        self._records: dict[str, KgMetadataSidecarRecord] = {}

    def upsert_records(self, records: list[KgMetadataSidecarRecord]) -> int:
        for record in records:
            self._records[record.sidecar_id] = record
        self._persist()
        return len(records)

    def get_by_external_key(self, key: str) -> KgMetadataSidecarRecord | None:
        for record in self._records.values():
            if record.external_key == key:
                return record
        return None

    def get_by_source_id(self, source_id: str) -> list[KgMetadataSidecarRecord]:
        return [record for record in self._records.values() if record.source_id == source_id]

    def get_by_entity_name(self, entity_name: str) -> list[KgMetadataSidecarRecord]:
        return [
            record
            for record in self._records.values()
            if record.entity_name == entity_name
        ]

    def get_by_relationship(
        self,
        src_id: str,
        tgt_id: str,
        relation_type: str,
    ) -> list[KgMetadataSidecarRecord]:
        return [
            record
            for record in self._records.values()
            if record.src_id == src_id
            and record.tgt_id == tgt_id
            and record.relation_type == relation_type
        ]

    def delete_by_namespace(self, namespace: str) -> int:
        before = len(self._records)
        self._records = {
            key: record
            for key, record in self._records.items()
            if record.namespace != namespace
        }
        self._persist()
        return before - len(self._records)

    def reset(self) -> None:
        self._records = {}
        self._persist()

    def count(self) -> int:
        return len(self._records)

    def export_json(self) -> str:
        records = [asdict(record) for record in sorted(self._records.values(), key=_record_sort_key)]
        return json.dumps(records, ensure_ascii=False, sort_keys=True)

    def import_json(self, data: str | list[dict[str, Any]]) -> None:
        values = json.loads(data) if isinstance(data, str) else data
        self._records = {}
        for item in values:
            record = KgMetadataSidecarRecord(**dict(item))
            self._records[record.sidecar_id] = record
        self._persist()

    def records(self) -> list[KgMetadataSidecarRecord]:
        return sorted(self._records.values(), key=_record_sort_key)

    def _persist(self) -> None:
        if self.json_path is None:
            return
        self.json_path.parent.mkdir(parents=True, exist_ok=True)
        self.json_path.write_text(self.export_json(), encoding="utf-8")


def build_metadata_sidecar_records(
    payload: DslKgPayload,
    *,
    namespace: str,
) -> list[KgMetadataSidecarRecord]:
    created_at = _stable_created_at()
    records: list[KgMetadataSidecarRecord] = []
    for chunk in payload.chunks:
        metadata = _metadata_for_chunk(chunk)
        external_key = chunk_external_key(chunk.source_id)
        records.append(
            _record(
                object_kind=OBJECT_KIND_CHUNK,
                external_key=external_key,
                lightrag_ref_key=chunk.source_id,
                source_id=chunk.source_id,
                entity_name=None,
                entity_type=None,
                src_id=None,
                tgt_id=None,
                relation_type=None,
                keywords=None,
                metadata=metadata,
                payload={"content": chunk.content, "source_id": chunk.source_id},
                namespace=namespace,
                created_at=created_at,
            )
        )

    for entity in payload.entities:
        metadata = _metadata_for_entity(entity)
        external_key = entity_external_key(
            entity.entity_type,
            entity.entity_name,
            entity.source_id,
        )
        records.append(
            _record(
                object_kind=OBJECT_KIND_ENTITY,
                external_key=external_key,
                lightrag_ref_key=entity.entity_name,
                source_id=entity.source_id,
                entity_name=entity.entity_name,
                entity_type=entity.entity_type,
                src_id=None,
                tgt_id=None,
                relation_type=None,
                keywords=None,
                metadata=metadata,
                payload={
                    "entity_name": entity.entity_name,
                    "entity_type": entity.entity_type,
                    "description": entity.description,
                    "source_id": entity.source_id,
                },
                namespace=namespace,
                created_at=created_at,
            )
        )

    for relationship in payload.relationships:
        metadata = _metadata_for_relationship(relationship)
        relation_type = str(metadata.get("relationType") or relationship.keywords)
        external_key = relationship_external_key(
            relationship.src_id,
            relationship.tgt_id,
            relation_type,
            relationship.source_id,
        )
        records.append(
            _record(
                object_kind=OBJECT_KIND_RELATIONSHIP,
                external_key=external_key,
                lightrag_ref_key=f"{relationship.src_id}->{relationship.tgt_id}",
                source_id=relationship.source_id,
                entity_name=None,
                entity_type=None,
                src_id=relationship.src_id,
                tgt_id=relationship.tgt_id,
                relation_type=relation_type,
                keywords=relationship.keywords,
                metadata=metadata,
                payload={
                    "src_id": relationship.src_id,
                    "tgt_id": relationship.tgt_id,
                    "description": relationship.description,
                    "keywords": relationship.keywords,
                    "source_id": relationship.source_id,
                    "weight": relationship.weight,
                },
                namespace=namespace,
                created_at=created_at,
            )
        )
    return records


def build_graph_insert_sidecar_records(
    payload: DslKgPayload,
    custom_kg_input: dict[str, list[dict[str, Any]]],
    *,
    namespace: str,
) -> list[KgMetadataSidecarRecord]:
    """Return sidecar records only for objects present in the graph insert input."""
    full_records = build_metadata_sidecar_records(payload, namespace=namespace)
    records_by_key = {record.external_key: record for record in full_records}
    graph_insert_records: list[KgMetadataSidecarRecord] = []

    for key in _custom_kg_external_keys(custom_kg_input, OBJECT_KIND_CHUNK):
        record = records_by_key.get(key)
        if record is not None:
            graph_insert_records.append(record)
    for key in _custom_kg_external_keys(custom_kg_input, OBJECT_KIND_ENTITY):
        record = records_by_key.get(key)
        if record is not None:
            graph_insert_records.append(record)
    for key in _custom_kg_external_keys(custom_kg_input, OBJECT_KIND_RELATIONSHIP):
        record = records_by_key.get(key)
        if record is not None:
            graph_insert_records.append(record)

    return graph_insert_records


def validate_sidecar_coverage(
    payload: DslKgPayload,
    records: list[KgMetadataSidecarRecord],
) -> SidecarCoverageReport:
    by_key = {record.external_key: record for record in records}
    issues: list[SidecarCoverageIssue] = []
    missing_chunk = 0
    missing_entity = 0
    missing_relationship = 0
    evidence_missing = 0
    version_missing = 0
    review_missing = 0

    for chunk in payload.chunks:
        key = chunk_external_key(chunk.source_id)
        record = by_key.get(key)
        if record is None:
            missing_chunk += 1
            issues.append(_issue("MISSING_CHUNK_RECORD", key))
            continue
        missing_keys = _missing_required_metadata(record.metadata)
        if missing_keys:
            missing_chunk += 1
            issues.append(_issue("MISSING_CHUNK_METADATA", key, missing_keys))
        if _missing_evidence(record.metadata):
            evidence_missing += 1

    for entity in payload.entities:
        key = entity_external_key(entity.entity_type, entity.entity_name, entity.source_id)
        record = by_key.get(key)
        if record is None:
            missing_entity += 1
            issues.append(_issue("MISSING_ENTITY_RECORD", key))
            continue
        missing_keys = _missing_required_metadata(record.metadata)
        if missing_keys:
            missing_entity += 1
            issues.append(_issue("MISSING_ENTITY_METADATA", key, missing_keys))
        if _missing_evidence(record.metadata):
            evidence_missing += 1
        if _payload_has_version(entity.metadata) and _missing_version(record.metadata):
            version_missing += 1
        if _missing_review(record.metadata):
            review_missing += 1

    for relationship in payload.relationships:
        relation_type = str(
            relationship.metadata.get("relationType") or relationship.keywords
        )
        key = relationship_external_key(
            relationship.src_id,
            relationship.tgt_id,
            relation_type,
            relationship.source_id,
        )
        record = by_key.get(key)
        if record is None:
            missing_relationship += 1
            issues.append(_issue("MISSING_RELATIONSHIP_RECORD", key))
            continue
        missing_keys = _missing_required_metadata(record.metadata)
        if missing_keys:
            missing_relationship += 1
            issues.append(_issue("MISSING_RELATIONSHIP_METADATA", key, missing_keys))
        if _missing_evidence(record.metadata):
            evidence_missing += 1
        if _payload_has_version(relationship.metadata) and _missing_version(record.metadata):
            version_missing += 1
        if _missing_review(record.metadata):
            review_missing += 1

    chunk_ratio = _coverage_ratio(len(payload.chunks), missing_chunk)
    entity_ratio = _coverage_ratio(len(payload.entities), missing_entity)
    relationship_ratio = _coverage_ratio(len(payload.relationships), missing_relationship)
    passed = (
        chunk_ratio == 1.0
        and entity_ratio == 1.0
        and relationship_ratio == 1.0
        and evidence_missing == 0
        and version_missing == 0
        and review_missing == 0
    )
    return SidecarCoverageReport(
        chunk_coverage_ratio=chunk_ratio,
        entity_coverage_ratio=entity_ratio,
        relationship_coverage_ratio=relationship_ratio,
        missing_chunk_metadata_count=missing_chunk,
        missing_entity_metadata_count=missing_entity,
        missing_relationship_metadata_count=missing_relationship,
        evidence_missing_count=evidence_missing,
        version_metadata_missing_count=version_missing,
        review_metadata_missing_count=review_missing,
        pass_status="PASS" if passed else "FAIL",
        issues=issues,
    )


def validate_graph_insert_sidecar_alignment(
    custom_kg_input: dict[str, list[dict[str, Any]]],
    graph_insert_sidecar_records: list[KgMetadataSidecarRecord],
) -> GraphInsertSidecarAlignmentReport:
    expected_by_kind = {
        OBJECT_KIND_CHUNK: Counter(_custom_kg_external_keys(custom_kg_input, OBJECT_KIND_CHUNK)),
        OBJECT_KIND_ENTITY: Counter(_custom_kg_external_keys(custom_kg_input, OBJECT_KIND_ENTITY)),
        OBJECT_KIND_RELATIONSHIP: Counter(
            _custom_kg_external_keys(custom_kg_input, OBJECT_KIND_RELATIONSHIP)
        ),
    }
    actual_by_kind = {
        OBJECT_KIND_CHUNK: Counter(
            record.external_key
            for record in graph_insert_sidecar_records
            if record.object_kind == OBJECT_KIND_CHUNK
        ),
        OBJECT_KIND_ENTITY: Counter(
            record.external_key
            for record in graph_insert_sidecar_records
            if record.object_kind == OBJECT_KIND_ENTITY
        ),
        OBJECT_KIND_RELATIONSHIP: Counter(
            record.external_key
            for record in graph_insert_sidecar_records
            if record.object_kind == OBJECT_KIND_RELATIONSHIP
        ),
    }

    issues: list[SidecarCoverageIssue] = []
    missing_by_kind: dict[str, int] = {}
    extra_by_kind: dict[str, int] = {}
    for kind, expected in expected_by_kind.items():
        actual = actual_by_kind[kind]
        missing = expected - actual
        extra = actual - expected
        missing_by_kind[kind] = sum(missing.values())
        extra_by_kind[kind] = sum(extra.values())
        issues.extend(_alignment_issues(kind, "MISSING", missing))
        issues.extend(_alignment_issues(kind, "EXTRA", extra))

    unknown_kind_count = sum(
        1
        for record in graph_insert_sidecar_records
        if record.object_kind not in expected_by_kind
    )
    if unknown_kind_count:
        issues.append(
            SidecarCoverageIssue(
                severity="ERROR",
                code="GRAPH_INSERT_SIDECAR_UNKNOWN_KIND",
                message=f"Unknown sidecar object kind count: {unknown_kind_count}",
            )
        )

    missing_count = sum(missing_by_kind.values())
    extra_count = sum(extra_by_kind.values()) + unknown_kind_count
    chunk_ratio = _coverage_ratio(
        sum(expected_by_kind[OBJECT_KIND_CHUNK].values()),
        missing_by_kind[OBJECT_KIND_CHUNK],
    )
    entity_ratio = _coverage_ratio(
        sum(expected_by_kind[OBJECT_KIND_ENTITY].values()),
        missing_by_kind[OBJECT_KIND_ENTITY],
    )
    relationship_ratio = _coverage_ratio(
        sum(expected_by_kind[OBJECT_KIND_RELATIONSHIP].values()),
        missing_by_kind[OBJECT_KIND_RELATIONSHIP],
    )
    passed = (
        chunk_ratio == 1.0
        and entity_ratio == 1.0
        and relationship_ratio == 1.0
        and missing_count == 0
        and extra_count == 0
    )
    return GraphInsertSidecarAlignmentReport(
        chunk_alignment_ratio=chunk_ratio,
        entity_alignment_ratio=entity_ratio,
        relationship_alignment_ratio=relationship_ratio,
        extra_sidecar_record_count=extra_count,
        missing_sidecar_record_count=missing_count,
        pass_status="PASS" if passed else "FAIL",
        issues=issues,
    )


def serialize_sidecar_record(record: KgMetadataSidecarRecord) -> dict[str, Any]:
    return asdict(record)


def serialize_sidecar_coverage_report(report: SidecarCoverageReport) -> dict[str, Any]:
    return asdict(report)


def serialize_graph_insert_sidecar_alignment_report(
    report: GraphInsertSidecarAlignmentReport,
) -> dict[str, Any]:
    return asdict(report)


def chunk_external_key(source_id: str) -> str:
    return f"chunk:{source_id}"


def entity_external_key(entity_type: str, entity_name: str, source_id: str) -> str:
    return f"entity:{entity_type}:{_normalize_key_part(entity_name)}:{source_id}"


def relationship_external_key(
    src_id: str,
    tgt_id: str,
    relation_type: str,
    source_id: str,
) -> str:
    return (
        f"relation:{_normalize_key_part(src_id)}:{_normalize_key_part(tgt_id)}:"
        f"{relation_type}:{source_id}"
    )


def _record(
    *,
    object_kind: str,
    external_key: str,
    lightrag_ref_key: str | None,
    source_id: str | None,
    entity_name: str | None,
    entity_type: str | None,
    src_id: str | None,
    tgt_id: str | None,
    relation_type: str | None,
    keywords: str | None,
    metadata: dict[str, Any],
    payload: dict[str, Any],
    namespace: str,
    created_at: str,
) -> KgMetadataSidecarRecord:
    metadata = _ensure_required_metadata(metadata)
    return KgMetadataSidecarRecord(
        sidecar_id=_stable_hash("sidecar", namespace, object_kind, external_key),
        object_kind=object_kind,
        external_key=external_key,
        lightrag_ref_key=lightrag_ref_key,
        source_id=source_id,
        entity_name=entity_name,
        entity_type=entity_type,
        src_id=src_id,
        tgt_id=tgt_id,
        relation_type=relation_type,
        keywords=keywords,
        metadata=metadata,
        metadata_hash=_dict_hash(metadata),
        payload_hash=_dict_hash(payload),
        namespace=namespace,
        created_at=created_at,
    )


def _metadata_for_chunk(chunk: KgChunk) -> dict[str, Any]:
    metadata = dict(chunk.metadata)
    metadata.setdefault("textUnitId", chunk.source_id)
    metadata.setdefault("evidenceText", chunk.content)
    metadata.setdefault("validationStatus", "CHUNK")
    metadata.setdefault("reviewDecision", "CHUNK")
    metadata.setdefault("confidenceScore", None)
    return _ensure_required_metadata(metadata)


def _metadata_for_entity(entity: KgEntity) -> dict[str, Any]:
    metadata = dict(entity.metadata)
    metadata.setdefault("textUnitId", entity.source_id)
    metadata.setdefault("evidenceText", entity.description)
    metadata.setdefault("validationStatus", "UNKNOWN")
    metadata.setdefault("reviewDecision", "UNKNOWN")
    metadata.setdefault("confidenceScore", None)
    return _ensure_required_metadata(metadata)


def _metadata_for_relationship(relationship: KgRelationship) -> dict[str, Any]:
    metadata = dict(relationship.metadata)
    metadata.setdefault("textUnitId", relationship.source_id)
    metadata.setdefault("evidenceText", relationship.description)
    metadata.setdefault("relationType", relationship.keywords)
    metadata.setdefault("validationStatus", "UNKNOWN")
    metadata.setdefault("reviewDecision", "UNKNOWN")
    metadata.setdefault("confidenceScore", None)
    return _ensure_required_metadata(metadata)


def _ensure_required_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    result = dict(metadata)
    for key in REQUIRED_METADATA_KEYS:
        result.setdefault(key, None)
    return result


def _missing_required_metadata(metadata: dict[str, Any]) -> list[str]:
    return [key for key in REQUIRED_METADATA_KEYS if key not in metadata]


def _missing_evidence(metadata: dict[str, Any]) -> bool:
    return any(_is_blank(metadata.get(key)) for key in EVIDENCE_REQUIRED_KEYS)


def _missing_review(metadata: dict[str, Any]) -> bool:
    return any(_is_blank(metadata.get(key)) for key in REVIEW_REQUIRED_KEYS)


def _missing_version(metadata: dict[str, Any]) -> bool:
    return any(key not in metadata for key in VERSION_KEYS)


def _payload_has_version(metadata: dict[str, Any]) -> bool:
    return any(metadata.get(key) not in (None, "", []) for key in VERSION_KEYS)


def _coverage_ratio(total: int, missing: int) -> float:
    if total == 0:
        return 1.0
    return (total - missing) / total


def _issue(
    code: str,
    external_key: str,
    missing_keys: list[str] | None = None,
) -> SidecarCoverageIssue:
    suffix = f": {', '.join(missing_keys)}" if missing_keys else ""
    return SidecarCoverageIssue(
        severity="ERROR",
        code=code,
        message=f"{code}{suffix}",
        external_key=external_key,
    )


def _custom_kg_external_keys(
    custom_kg_input: dict[str, list[dict[str, Any]]],
    object_kind: str,
) -> list[str]:
    if object_kind == OBJECT_KIND_CHUNK:
        return [
            chunk_external_key(str(item.get("source_id")))
            for item in custom_kg_input.get("chunks", [])
        ]
    if object_kind == OBJECT_KIND_ENTITY:
        return [
            entity_external_key(
                str(item.get("entity_type")),
                str(item.get("entity_name")),
                str(item.get("source_id")),
            )
            for item in custom_kg_input.get("entities", [])
        ]
    if object_kind == OBJECT_KIND_RELATIONSHIP:
        return [
            relationship_external_key(
                str(item.get("src_id")),
                str(item.get("tgt_id")),
                str(item.get("keywords")),
                str(item.get("source_id")),
            )
            for item in custom_kg_input.get("relationships", [])
        ]
    return []


def _alignment_issues(
    kind: str,
    status: str,
    keys: Counter[str],
) -> list[SidecarCoverageIssue]:
    code = f"GRAPH_INSERT_SIDECAR_{status}_{kind.upper()}"
    return [
        SidecarCoverageIssue(
            severity="ERROR",
            code=code,
            message=f"{code}: {count}",
            external_key=key,
        )
        for key, count in sorted(keys.items())
    ]


def _stable_created_at() -> str:
    return datetime.fromtimestamp(0, timezone.utc).isoformat()


def _dict_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _stable_hash(*parts: str) -> str:
    raw = "|".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _normalize_key_part(value: str) -> str:
    return " ".join(str(value).strip().split()).replace(":", "_")


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == {}


def _record_sort_key(record: KgMetadataSidecarRecord) -> tuple[str, str]:
    return record.namespace, record.sidecar_id


__all__ = [
    "GraphInsertSidecarAlignmentReport",
    "KgMetadataSidecarRecord",
    "KgMetadataSidecarStore",
    "OBJECT_KIND_CHUNK",
    "OBJECT_KIND_ENTITY",
    "OBJECT_KIND_RELATIONSHIP",
    "SidecarCoverageIssue",
    "SidecarCoverageReport",
    "build_graph_insert_sidecar_records",
    "build_metadata_sidecar_records",
    "chunk_external_key",
    "entity_external_key",
    "relationship_external_key",
    "serialize_graph_insert_sidecar_alignment_report",
    "serialize_sidecar_coverage_report",
    "serialize_sidecar_record",
    "validate_graph_insert_sidecar_alignment",
    "validate_sidecar_coverage",
]
