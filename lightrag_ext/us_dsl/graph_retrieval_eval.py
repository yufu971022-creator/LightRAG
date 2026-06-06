from __future__ import annotations

from dataclasses import asdict, replace
import re
from typing import Any

from .fx_mini_graph_smoke import (
    FX_MINI_NAMESPACE,
    FX_SOURCE_NAME,
    build_fx_mini_kg_payload,
)
from .graph_retrieval_index import (
    GraphRetrievalIndexes,
    KgEdgeIndex,
    KgEdgeRecord,
    KgNodeIndex,
    KgNodeRecord,
    TextEvidenceIndex,
    TextEvidenceRecord,
    build_graph_retrieval_indexes,
    edge_record_to_path_item,
)
from .graph_retrieval_types import (
    DEGRADED,
    HIT_EDGE,
    HIT_NODE,
    HIT_PATH,
    HIT_TEXT,
    IMPROVED,
    INCONCLUSIVE,
    MODE_GRAPH_AWARE,
    MODE_TEXT_ONLY,
    SAME,
    GraphRetrievalEvaluationReport,
    GraphRetrievalQuery,
    RetrievalComparisonResult,
    RetrievalHit,
    RetrievalResult,
)
from .kg_metadata_sidecar import (
    KgMetadataSidecarRecord,
    build_graph_insert_sidecar_records,
)
from .kg_payload_types import DslKgPayload
from .kg_test_graph_write import to_lightrag_custom_kg_input
from .lc_mini_graph_smoke import (
    LC_MINI_NAMESPACE,
    LC_SOURCE_NAME,
    build_lc_mini_kg_payload,
)


_RUNTIME_FLAGS = {
    "llm_called": False,
    "storage_written": False,
    "neo4j_connected": False,
}


def build_retrieval_queries_from_graph_payload(
    payload: DslKgPayload,
    sidecar_records: list[KgMetadataSidecarRecord],
    *,
    max_queries: int = 8,
) -> list[GraphRetrievalQuery]:
    entity_names = {entity.entity_name for entity in payload.entities}
    selected: list[GraphRetrievalQuery] = []
    seen_domains: set[str] = set()
    seen_relations: set[str] = set()
    sidecar_source_ids = {record.source_id for record in sidecar_records if record.source_id}

    relationships = [
        relationship
        for relationship in payload.relationships
        if relationship.src_id in entity_names
        and relationship.tgt_id in entity_names
        and relationship.source_id in sidecar_source_ids
    ]
    relationships = sorted(
        relationships,
        key=lambda item: (
            str(item.metadata.get("domainCode") or ""),
            str(item.metadata.get("sectionType") or ""),
            item.keywords,
            item.src_id,
            item.tgt_id,
        ),
    )

    for relationship in relationships:
        domain = _string_or_none(relationship.metadata.get("domainCode"))
        relation_type = str(relationship.metadata.get("relationType") or relationship.keywords)
        if domain in seen_domains and relation_type in seen_relations:
            continue
        selected.append(_query_from_relationship(relationship, len(selected) + 1))
        if domain:
            seen_domains.add(domain)
        seen_relations.add(relation_type)
        if len(selected) >= max_queries:
            break

    for relationship in relationships:
        if len(selected) >= max_queries:
            break
        query = _query_from_relationship(relationship, len(selected) + 1)
        if query.query_id not in {item.query_id for item in selected}:
            selected.append(query)

    return selected[:max_queries]


def run_text_only_retrieval(
    query: GraphRetrievalQuery,
    text_index: TextEvidenceIndex,
    *,
    top_k: int = 5,
) -> RetrievalResult:
    scored = [
        (_score_text_record(query, record), record)
        for record in text_index.records
        if _domain_allowed(record.domain_code, query)
    ]
    hits = [
        _text_hit(record, score, reason="lexical evidence match")
        for score, record in sorted(scored, key=lambda item: item[0], reverse=True)
        if score > 0
    ][:top_k]
    result = RetrievalResult(
        query_id=query.query_id,
        query_text=query.query_text,
        mode=MODE_TEXT_ONLY,
        hits=hits,
    )
    return _with_metrics(result, query)


def run_graph_aware_retrieval(
    query: GraphRetrievalQuery,
    text_index: TextEvidenceIndex,
    node_index: KgNodeIndex,
    edge_index: KgEdgeIndex,
    path_index,
    *,
    top_k: int = 8,
) -> RetrievalResult:
    text_result = run_text_only_retrieval(query, text_index, top_k=min(3, top_k))
    hits: list[RetrievalHit] = list(text_result.hits)
    seed_entities = _seed_entities(query, text_result, node_index)

    node_hits = _node_hits(query, node_index, seed_entities)
    edge_hits = _edge_hits(query, edge_index, seed_entities)
    path_hits = _path_hits(query, path_index, seed_entities)
    for hit in [*node_hits, *edge_hits, *path_hits]:
        if _hit_has_evidence(hit):
            hits.append(hit)

    hits = _dedupe_hits(sorted(hits, key=lambda item: item.score, reverse=True))[:top_k]
    issues = []
    missing_evidence_count = sum(
        1 for hit in hits if hit.hit_type != HIT_TEXT and not _hit_has_evidence(hit)
    )
    if missing_evidence_count:
        issues.append(
            {
                "severity": "WARN",
                "code": "GRAPH_HIT_MISSING_EVIDENCE",
                "message": f"Graph hits missing evidence: {missing_evidence_count}",
            }
        )
    result = RetrievalResult(
        query_id=query.query_id,
        query_text=query.query_text,
        mode=MODE_GRAPH_AWARE,
        hits=hits,
        issues=issues,
    )
    return _with_metrics(result, query)


def evaluate_retrieval_result(
    result: RetrievalResult,
    query: GraphRetrievalQuery,
) -> dict[str, Any]:
    measured = _measure(result.hits, query)
    return {
        "evidence_coverage": measured["evidence_coverage"],
        "expected_entity_recall": measured["entity_recall"],
        "expected_relation_recall": measured["relation_recall"],
        "source_span_coverage": measured["source_span_coverage"],
        "graph_path_count": measured["graph_path_count"],
        "unsupported_claim_risk": measured["unsupported_claim_risk"],
    }


def compare_retrieval_results(
    query: GraphRetrievalQuery,
    text_only_result: RetrievalResult,
    graph_aware_result: RetrievalResult,
) -> RetrievalComparisonResult:
    entity_delta = (
        graph_aware_result.expected_entity_recall
        - text_only_result.expected_entity_recall
    )
    relation_delta = (
        graph_aware_result.expected_relation_recall
        - text_only_result.expected_relation_recall
    )
    evidence_delta = graph_aware_result.evidence_coverage - text_only_result.evidence_coverage
    span_delta = graph_aware_result.source_span_coverage - text_only_result.source_span_coverage
    path_delta = graph_aware_result.graph_path_count - text_only_result.graph_path_count
    label, reasons = _improvement_label(
        query,
        entity_delta=entity_delta,
        relation_delta=relation_delta,
        evidence_delta=evidence_delta,
        span_delta=span_delta,
        path_delta=path_delta,
        graph_aware_result=graph_aware_result,
    )
    return RetrievalComparisonResult(
        query_id=query.query_id,
        text_only_result=text_only_result,
        graph_aware_result=graph_aware_result,
        entity_recall_delta=entity_delta,
        relation_recall_delta=relation_delta,
        evidence_coverage_delta=evidence_delta,
        source_span_coverage_delta=span_delta,
        graph_path_delta=path_delta,
        improvement_label=label,
        reasons=reasons,
    )


def build_graph_retrieval_evaluation_report(
    *,
    source: str,
    payload: DslKgPayload,
    sidecar_records: list[KgMetadataSidecarRecord],
    max_queries: int = 8,
) -> GraphRetrievalEvaluationReport:
    indexes = build_graph_retrieval_indexes(payload, sidecar_records)
    queries = build_retrieval_queries_from_graph_payload(
        payload,
        sidecar_records,
        max_queries=max_queries,
    )
    comparison_results = [
        _run_comparison(query, indexes)
        for query in queries
        if query.expected_entities or query.expected_relations
    ]
    labels = [item.improvement_label for item in comparison_results]
    risks = _report_risks(comparison_results)
    return GraphRetrievalEvaluationReport(
        source=source,
        query_count=len(comparison_results),
        improved_count=labels.count(IMPROVED),
        same_count=labels.count(SAME),
        degraded_count=labels.count(DEGRADED),
        inconclusive_count=labels.count(INCONCLUSIVE),
        avg_entity_recall_delta=_avg(
            item.entity_recall_delta for item in comparison_results
        ),
        avg_relation_recall_delta=_avg(
            item.relation_recall_delta for item in comparison_results
        ),
        avg_evidence_coverage_delta=_avg(
            item.evidence_coverage_delta for item in comparison_results
        ),
        avg_source_span_coverage_delta=_avg(
            item.source_span_coverage_delta for item in comparison_results
        ),
        avg_graph_path_delta=_avg(item.graph_path_delta for item in comparison_results),
        recommended_next_step=_recommended_next_step(labels, risks),
        risks=risks,
        comparison_results=comparison_results,
    )


def build_lc_mini_graph_retrieval_evaluation_report(
    *,
    max_queries: int = 8,
) -> GraphRetrievalEvaluationReport:
    payload = build_lc_mini_kg_payload()
    sidecar_records = _graph_insert_sidecar(payload, LC_MINI_NAMESPACE)
    return build_graph_retrieval_evaluation_report(
        source=LC_SOURCE_NAME,
        payload=payload,
        sidecar_records=sidecar_records,
        max_queries=max_queries,
    )


def build_fx_mini_graph_retrieval_evaluation_report(
    *,
    max_queries: int = 8,
) -> GraphRetrievalEvaluationReport:
    payload = build_fx_mini_kg_payload()
    sidecar_records = _graph_insert_sidecar(payload, FX_MINI_NAMESPACE)
    return build_graph_retrieval_evaluation_report(
        source=FX_SOURCE_NAME,
        payload=payload,
        sidecar_records=sidecar_records,
        max_queries=max_queries,
    )


def serialize_graph_retrieval_evaluation_report(
    report: GraphRetrievalEvaluationReport,
) -> dict[str, Any]:
    return asdict(report)


def get_retrieval_eval_runtime_flags() -> dict[str, bool]:
    return dict(_RUNTIME_FLAGS)


def _run_comparison(
    query: GraphRetrievalQuery,
    indexes: GraphRetrievalIndexes,
) -> RetrievalComparisonResult:
    text_result = run_text_only_retrieval(query, indexes.text_index)
    graph_result = run_graph_aware_retrieval(
        query,
        indexes.text_index,
        indexes.node_index,
        indexes.edge_index,
        indexes.path_index,
    )
    return compare_retrieval_results(query, text_result, graph_result)


def _query_from_relationship(
    relationship,
    index: int,
) -> GraphRetrievalQuery:
    domain = _string_or_none(relationship.metadata.get("domainCode"))
    section = _string_or_none(relationship.metadata.get("sectionType"))
    relation_type = str(relationship.metadata.get("relationType") or relationship.keywords)
    return GraphRetrievalQuery(
        query_id=f"q-{index:02d}-{_slug(relation_type)}",
        query_text=(
            f"{relationship.tgt_id} 在当前图谱中和 {relationship.src_id} "
            f"有什么关系？请返回证据和 source_span。"
        ),
        expected_focus=[
            value for value in [relationship.src_id, relationship.tgt_id, relation_type] if value
        ],
        expected_domains=[domain] if domain else [],
        expected_sections=[section] if section else [],
        expected_entities=[relationship.src_id, relationship.tgt_id],
        expected_relations=[relation_type],
        expected_evidence_keywords=[relationship.src_id, relationship.tgt_id, relation_type],
        level="L1",
    )


def _score_text_record(
    query: GraphRetrievalQuery,
    record: TextEvidenceRecord,
) -> float:
    text = " ".join(
        [
            query.query_text,
            record.evidence_text,
            record.source_us_id or "",
            record.feature_key or "",
            record.domain_code or "",
            record.section_type or "",
        ]
    )
    score = _token_overlap(query.query_text, record.evidence_text)
    score += sum(2.0 for entity in query.expected_entities if _contains(record.evidence_text, entity))
    score += sum(
        1.0
        for keyword in query.expected_evidence_keywords
        if _contains(record.evidence_text, keyword)
    )
    score += sum(1.0 for domain in query.expected_domains if domain == record.domain_code)
    score += sum(0.5 for section in query.expected_sections if section == record.section_type)
    score += _token_overlap(" ".join(query.expected_focus), text) * 0.25
    return score


def _text_hit(record: TextEvidenceRecord, score: float, *, reason: str) -> RetrievalHit:
    return RetrievalHit(
        hit_type=HIT_TEXT,
        score=score,
        source_id=record.source_id,
        source_us_id=record.source_us_id,
        text_unit_id=record.text_unit_id,
        domain_code=record.domain_code,
        feature_key=record.feature_key,
        section_type=record.section_type,
        evidence_text=record.evidence_text,
        source_span=record.source_span,
        text_hash=record.text_hash,
        reason=reason,
    )


def _seed_entities(
    query: GraphRetrievalQuery,
    text_result: RetrievalResult,
    node_index: KgNodeIndex,
) -> list[str]:
    seeds: list[str] = []
    for entity in query.expected_entities:
        if entity in node_index.by_name:
            _append_unique(seeds, entity)
    query_text = query.query_text.lower()
    for record in node_index.records:
        if record.entity_name.lower() in query_text:
            _append_unique(seeds, record.entity_name)
    for hit in text_result.hits:
        evidence = hit.evidence_text or ""
        for record in node_index.records:
            if _contains(evidence, record.entity_name):
                _append_unique(seeds, record.entity_name)
    return seeds


def _node_hits(
    query: GraphRetrievalQuery,
    node_index: KgNodeIndex,
    seed_entities: list[str],
) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    for record in node_index.records:
        if not _domain_allowed(_string_or_none(record.metadata.get("domainCode")), query):
            continue
        score = _score_node_record(query, record, seed_entities)
        if score <= 0:
            continue
        hits.append(
            RetrievalHit(
                hit_type=HIT_NODE,
                score=score,
                source_id=record.source_id,
                source_us_id=_string_or_none(record.metadata.get("sourceUsId")),
                text_unit_id=_string_or_none(record.metadata.get("textUnitId")),
                domain_code=_string_or_none(record.metadata.get("domainCode")),
                feature_key=_string_or_none(record.metadata.get("featureKey")),
                section_type=_string_or_none(record.metadata.get("sectionType")),
                entity_name=record.entity_name,
                entity_type=record.entity_type,
                evidence_text=_string_or_none(record.metadata.get("evidenceText")),
                source_span=_dict_or_none(record.metadata.get("sourceSpan")),
                text_hash=_string_or_none(record.metadata.get("textHash")),
                reason="graph node seed match",
            )
        )
    return hits


def _edge_hits(
    query: GraphRetrievalQuery,
    edge_index: KgEdgeIndex,
    seed_entities: list[str],
) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    for record in edge_index.records:
        if not _domain_allowed(_string_or_none(record.metadata.get("domainCode")), query):
            continue
        score = _score_edge_record(query, record, seed_entities)
        if score <= 0:
            continue
        hits.append(
            RetrievalHit(
                hit_type=HIT_EDGE,
                score=score,
                source_id=record.source_id,
                source_us_id=_string_or_none(record.metadata.get("sourceUsId")),
                text_unit_id=_string_or_none(record.metadata.get("textUnitId")),
                domain_code=_string_or_none(record.metadata.get("domainCode")),
                feature_key=_string_or_none(record.metadata.get("featureKey")),
                section_type=_string_or_none(record.metadata.get("sectionType")),
                entity_name=f"{record.src_id}->{record.tgt_id}",
                relation_type=record.relation_type,
                evidence_text=_string_or_none(record.metadata.get("evidenceText")),
                source_span=_dict_or_none(record.metadata.get("sourceSpan")),
                text_hash=_string_or_none(record.metadata.get("textHash")),
                reason="graph edge relation match",
            )
        )
    return hits


def _path_hits(
    query: GraphRetrievalQuery,
    path_index,
    seed_entities: list[str],
) -> list[RetrievalHit]:
    hits: list[RetrievalHit] = []
    for path in path_index.retrieve_paths(seed_entities, max_hops=2, max_paths=5):
        if not path:
            continue
        if not all(
            _domain_allowed(_string_or_none(edge.metadata.get("domainCode")), query)
            for edge in path
        ):
            continue
        first = path[0]
        evidence_text = "\n".join(
            str(edge.metadata.get("evidenceText") or edge.description)
            for edge in path
            if edge.metadata.get("evidenceText") or edge.description
        )
        if not evidence_text:
            continue
        relation_types = [edge.relation_type for edge in path]
        score = 1.0 + sum(
            2.0
            for relation in query.expected_relations
            if relation in relation_types
        )
        score += sum(
            1.0
            for entity in query.expected_entities
            if any(entity in {edge.src_id, edge.tgt_id} for edge in path)
        )
        hits.append(
            RetrievalHit(
                hit_type=HIT_PATH,
                score=score,
                source_id=first.source_id,
                source_us_id=_string_or_none(first.metadata.get("sourceUsId")),
                text_unit_id=_string_or_none(first.metadata.get("textUnitId")),
                domain_code=_string_or_none(first.metadata.get("domainCode")),
                feature_key=_string_or_none(first.metadata.get("featureKey")),
                section_type=_string_or_none(first.metadata.get("sectionType")),
                relation_type=first.relation_type,
                path=[edge_record_to_path_item(edge) for edge in path],
                evidence_text=evidence_text,
                source_span=_dict_or_none(first.metadata.get("sourceSpan")),
                text_hash=_string_or_none(first.metadata.get("textHash")),
                reason="graph path expansion",
            )
        )
    return hits


def _score_node_record(
    query: GraphRetrievalQuery,
    record: KgNodeRecord,
    seed_entities: list[str],
) -> float:
    score = _token_overlap(query.query_text, f"{record.entity_name} {record.description}")
    if record.entity_name in query.expected_entities:
        score += 3.0
    if record.entity_name in seed_entities:
        score += 2.0
    if record.entity_type in query.expected_focus:
        score += 1.0
    return score


def _score_edge_record(
    query: GraphRetrievalQuery,
    record: KgEdgeRecord,
    seed_entities: list[str],
) -> float:
    edge_text = f"{record.src_id} {record.tgt_id} {record.relation_type} {record.description}"
    score = _token_overlap(query.query_text, edge_text)
    if record.relation_type in query.expected_relations:
        score += 4.0
    if record.src_id in query.expected_entities:
        score += 1.5
    if record.tgt_id in query.expected_entities:
        score += 1.5
    if record.src_id in seed_entities or record.tgt_id in seed_entities:
        score += 1.0
    return score


def _with_metrics(result: RetrievalResult, query: GraphRetrievalQuery) -> RetrievalResult:
    measured = _measure(result.hits, query)
    return replace(
        result,
        expected_entities=list(query.expected_entities),
        expected_relations=list(query.expected_relations),
        expected_evidence_keywords=list(query.expected_evidence_keywords),
        evidence_coverage=measured["evidence_coverage"],
        expected_entity_recall=measured["entity_recall"],
        expected_relation_recall=measured["relation_recall"],
        source_span_coverage=measured["source_span_coverage"],
        graph_path_count=measured["graph_path_count"],
        unsupported_claim_risk=measured["unsupported_claim_risk"],
        issues=[*result.issues, *measured["issues"]],
    )


def _measure(
    hits: list[RetrievalHit],
    query: GraphRetrievalQuery,
) -> dict[str, Any]:
    entity_hits = _covered_entities(hits, query.expected_entities)
    relation_hits = _covered_relations(hits, query.expected_relations)
    evidence_count = sum(1 for hit in hits if _hit_has_evidence(hit))
    span_count = sum(1 for hit in hits if hit.source_span and hit.text_hash)
    total = len(hits)
    issues = _false_positive_issues(hits, query)
    missing_evidence = total - evidence_count
    return {
        "entity_recall": _ratio(len(query.expected_entities), len(entity_hits)),
        "relation_recall": _ratio(len(query.expected_relations), len(relation_hits)),
        "evidence_coverage": _ratio(total, evidence_count),
        "source_span_coverage": _ratio(total, span_count),
        "graph_path_count": sum(1 for hit in hits if hit.hit_type == HIT_PATH),
        "unsupported_claim_risk": _ratio(total, missing_evidence),
        "issues": issues,
    }


def _covered_entities(
    hits: list[RetrievalHit],
    expected_entities: list[str],
) -> set[str]:
    covered: set[str] = set()
    for expected in expected_entities:
        for hit in hits:
            if hit.entity_name and expected in hit.entity_name:
                covered.add(expected)
            elif hit.evidence_text and _contains(hit.evidence_text, expected):
                covered.add(expected)
            elif hit.path and any(
                expected in {str(item.get("src_id")), str(item.get("tgt_id"))}
                for item in hit.path
            ):
                covered.add(expected)
    return covered


def _covered_relations(
    hits: list[RetrievalHit],
    expected_relations: list[str],
) -> set[str]:
    covered: set[str] = set()
    for expected in expected_relations:
        for hit in hits:
            if hit.hit_type == HIT_EDGE and hit.relation_type == expected:
                covered.add(expected)
            elif hit.hit_type == HIT_PATH and (
                hit.relation_type == expected
                or any(item.get("relation_type") == expected for item in hit.path or [])
            ):
                covered.add(expected)
    return covered


def _false_positive_issues(
    hits: list[RetrievalHit],
    query: GraphRetrievalQuery,
) -> list[dict[str, Any]]:
    if not query.expected_domains:
        return []
    return [
        {
            "severity": "WARN",
            "code": "POTENTIAL_FALSE_POSITIVE_DOMAIN",
            "message": f"Hit domain {hit.domain_code} is outside expected domains.",
        }
        for hit in hits
        if hit.domain_code and hit.domain_code not in query.expected_domains
    ]


def _improvement_label(
    query: GraphRetrievalQuery,
    *,
    entity_delta: float,
    relation_delta: float,
    evidence_delta: float,
    span_delta: float,
    path_delta: int,
    graph_aware_result: RetrievalResult,
) -> tuple[str, list[str]]:
    if not query.expected_entities and not query.expected_relations:
        return INCONCLUSIVE, ["Query has no expected graph objects."]
    if graph_aware_result.issues:
        severe = [issue for issue in graph_aware_result.issues if issue.get("code")]
        if severe and evidence_delta < -0.2:
            return DEGRADED, ["Graph-aware retrieval introduced issue and lost evidence."]

    reasons: list[str] = []
    if entity_delta > 0:
        reasons.append("entity recall improved")
    if relation_delta > 0:
        reasons.append("relation recall improved")
    if evidence_delta >= 0:
        reasons.append("evidence coverage maintained")
    if span_delta >= 0:
        reasons.append("source span coverage maintained")
    if path_delta > 0:
        reasons.append("graph paths returned")

    positive_count = sum(
        [
            entity_delta > 0,
            relation_delta > 0,
            evidence_delta >= 0,
            span_delta >= 0,
            path_delta > 0,
        ]
    )
    if positive_count >= 2 and (entity_delta > 0 or relation_delta > 0 or path_delta > 0):
        return IMPROVED, reasons
    if entity_delta == 0 and relation_delta == 0 and evidence_delta == 0 and path_delta == 0:
        return SAME, ["No metric changed."]
    if evidence_delta < -0.2 or span_delta < -0.2:
        return DEGRADED, ["Evidence or source span coverage degraded."]
    return SAME, reasons or ["No material improvement."]


def _report_risks(
    comparison_results: list[RetrievalComparisonResult],
) -> list[str]:
    risks: list[str] = []
    if any(item.improvement_label == DEGRADED for item in comparison_results):
        risks.append("At least one graph-aware retrieval comparison degraded.")
    if any(
        issue.get("code") == "GRAPH_HIT_MISSING_EVIDENCE"
        for item in comparison_results
        for issue in item.graph_aware_result.issues
    ):
        risks.append("At least one graph hit was missing evidence.")
    if any(
        issue.get("code") == "POTENTIAL_FALSE_POSITIVE_DOMAIN"
        for item in comparison_results
        for issue in item.graph_aware_result.issues
    ):
        risks.append("Potential false positive domain hit detected.")
    return risks


def _recommended_next_step(labels: list[str], risks: list[str]) -> str:
    if risks:
        return "TUNE_GRAPH_RETRIEVAL_FILTERS"
    if labels and labels.count(IMPROVED) > 0 and DEGRADED not in labels:
        return "PREPARE_GRAPH_AWARE_ANSWER_SMOKE"
    if not labels:
        return "EXPAND_MINI_GRAPH_COVERAGE"
    return "REVIEW_GRAPH_RETRIEVAL_QUERIES"


def _graph_insert_sidecar(
    payload: DslKgPayload,
    namespace: str,
) -> list[KgMetadataSidecarRecord]:
    custom_kg = to_lightrag_custom_kg_input(payload)
    return build_graph_insert_sidecar_records(payload, custom_kg, namespace=namespace)


def _domain_allowed(domain_code: str | None, query: GraphRetrievalQuery) -> bool:
    return not query.expected_domains or domain_code is None or domain_code in query.expected_domains


def _hit_has_evidence(hit: RetrievalHit) -> bool:
    return bool(hit.evidence_text and hit.text_hash)


def _ratio(total: int, count: int) -> float:
    if total == 0:
        return 1.0
    return count / total


def _avg(values: Any) -> float:
    values = list(values)
    if not values:
        return 0.0
    return sum(values) / len(values)


def _token_overlap(left: str, right: str) -> float:
    left_tokens = set(_tokens(left))
    right_tokens = set(_tokens(right))
    if not left_tokens or not right_tokens:
        return 0.0
    return float(len(left_tokens & right_tokens))


def _tokens(value: str) -> list[str]:
    return [
        item.lower()
        for item in re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]+", value)
        if item
    ]


def _contains(text: str, value: str) -> bool:
    return bool(value) and value.lower() in text.lower()


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _dedupe_hits(hits: list[RetrievalHit]) -> list[RetrievalHit]:
    result: list[RetrievalHit] = []
    seen: set[tuple[Any, ...]] = set()
    for hit in hits:
        key = (
            hit.hit_type,
            hit.source_id,
            hit.entity_name,
            hit.relation_type,
            tuple(
                str(item)
                for item in (hit.path or [])
            ),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(hit)
    return result


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _dict_or_none(value: Any) -> dict[str, Any] | None:
    return dict(value) if isinstance(value, dict) else None


def _slug(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower() or "query"


__all__ = [
    "build_fx_mini_graph_retrieval_evaluation_report",
    "build_graph_retrieval_evaluation_report",
    "build_lc_mini_graph_retrieval_evaluation_report",
    "build_retrieval_queries_from_graph_payload",
    "compare_retrieval_results",
    "evaluate_retrieval_result",
    "get_retrieval_eval_runtime_flags",
    "run_graph_aware_retrieval",
    "run_text_only_retrieval",
    "serialize_graph_retrieval_evaluation_report",
]
