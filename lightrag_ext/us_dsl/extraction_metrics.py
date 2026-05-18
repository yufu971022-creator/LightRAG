from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

try:
    from lightrag.prompt import PROMPTS

    DEFAULT_TUPLE_DELIMITER = PROMPTS["DEFAULT_TUPLE_DELIMITER"]
    DEFAULT_COMPLETION_DELIMITER = PROMPTS["DEFAULT_COMPLETION_DELIMITER"]
except Exception:  # pragma: no cover - import fallback for isolated extension use.
    DEFAULT_TUPLE_DELIMITER = "<|#|>"
    DEFAULT_COMPLETION_DELIMITER = "<|COMPLETE|>"


SNAKE_CASE_RELATIONS = {
    "has_child",
    "belongs_to",
    "references_to",
    "queries_from",
    "queries_by",
    "contains",
}
SNAKE_CASE_PATTERN = re.compile(r"^[a-z]+(?:_[a-z]+)+$")


@dataclass(frozen=True)
class ExtractedEntity:
    entity_name: str
    entity_type: str
    description: str
    source: str


@dataclass(frozen=True)
class ExtractedRelation:
    source_entity: str
    target_entity: str
    relation_type: str | None
    relationship_keywords: str
    description: str
    source: str


@dataclass
class ExtractionRunResult:
    sample_id: str
    mode: str
    entities: list[ExtractedEntity]
    relations: list[ExtractedRelation]
    raw_output: str
    parse_errors: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionComparisonMetrics:
    sample_id: str
    domain_code: str
    section_type: str
    baseline_entity_count: int
    baseline_relation_count: int
    baseline_invalid_entity_type_count: int
    baseline_invalid_relation_type_count: int
    baseline_snake_case_relation_count: int
    baseline_candidate_entity_count: int
    baseline_candidate_relation_count: int
    baseline_allowed_entity_type_hit_rate: float
    baseline_allowed_relation_type_hit_rate: float
    baseline_expected_entity_coverage: float
    baseline_expected_relation_coverage: float
    baseline_evidence_keyword_coverage: float
    dsl_entity_count: int
    dsl_relation_count: int
    dsl_invalid_entity_type_count: int
    dsl_invalid_relation_type_count: int
    dsl_snake_case_relation_count: int
    dsl_candidate_entity_count: int
    dsl_candidate_relation_count: int
    dsl_allowed_entity_type_hit_rate: float
    dsl_allowed_relation_type_hit_rate: float
    dsl_expected_entity_coverage: float
    dsl_expected_relation_coverage: float
    dsl_evidence_keyword_coverage: float
    entity_type_hit_rate_delta: float
    relation_type_hit_rate_delta: float
    invalid_entity_type_delta: int
    invalid_relation_type_delta: int
    snake_case_relation_delta: int
    candidate_relation_delta: int
    expected_entity_coverage_delta: float
    expected_relation_coverage_delta: float
    evidence_keyword_coverage_delta: float
    improvement_label: str
    reasons: list[str]


def parse_tuple_extraction_output(
    raw_output: str,
    *,
    sample_id: str = "sample",
    mode: str = "baseline",
    allowed_relation_types: list[str] | None = None,
    tuple_delimiter: str = DEFAULT_TUPLE_DELIMITER,
    completion_delimiter: str = DEFAULT_COMPLETION_DELIMITER,
) -> ExtractionRunResult:
    entities: list[ExtractedEntity] = []
    relations: list[ExtractedRelation] = []
    parse_errors: list[str] = []
    allowed_relations = allowed_relation_types or []

    for raw_record in _split_records(raw_output, completion_delimiter):
        record = raw_record.strip().strip("()")
        if not record:
            continue
        parts = _split_record(record, tuple_delimiter)
        record_type = parts[0].strip().lower() if parts else ""
        if record_type == "entity":
            if len(parts) != 4:
                parse_errors.append(f"Malformed entity record: {record}")
                continue
            entities.append(
                ExtractedEntity(
                    entity_name=_clean(parts[1]),
                    entity_type=_clean(parts[2]),
                    description=_clean(parts[3]),
                    source=mode,
                )
            )
        elif record_type in {"relation", "relationship"}:
            if len(parts) != 5:
                parse_errors.append(f"Malformed relation record: {record}")
                continue
            keywords = _clean(parts[3])
            relations.append(
                ExtractedRelation(
                    source_entity=_clean(parts[1]),
                    target_entity=_clean(parts[2]),
                    relation_type=detect_relation_type(keywords, allowed_relations),
                    relationship_keywords=keywords,
                    description=_clean(parts[4]),
                    source=mode,
                )
            )
        else:
            parse_errors.append(f"Unknown tuple record: {record}")

    return ExtractionRunResult(
        sample_id=sample_id,
        mode=mode,
        entities=entities,
        relations=relations,
        raw_output=raw_output,
        parse_errors=parse_errors,
    )


def compare_extraction_results(
    *,
    sample_id: str,
    domain_code: str,
    section_type: str,
    allowed_entity_types: list[str],
    allowed_relation_types: list[str],
    expected_entities: list[dict[str, Any]],
    expected_relations: list[dict[str, Any]],
    evidence_keywords: list[str],
    baseline_result: ExtractionRunResult,
    dsl_result: ExtractionRunResult,
) -> ExtractionComparisonMetrics:
    baseline = _score_result(
        baseline_result,
        allowed_entity_types=allowed_entity_types,
        allowed_relation_types=allowed_relation_types,
        expected_entities=expected_entities,
        expected_relations=expected_relations,
        evidence_keywords=evidence_keywords,
    )
    dsl = _score_result(
        dsl_result,
        allowed_entity_types=allowed_entity_types,
        allowed_relation_types=allowed_relation_types,
        expected_entities=expected_entities,
        expected_relations=expected_relations,
        evidence_keywords=evidence_keywords,
    )
    label, reasons = _improvement_label(baseline, dsl, baseline_result, dsl_result)

    return ExtractionComparisonMetrics(
        sample_id=sample_id,
        domain_code=domain_code,
        section_type=section_type,
        baseline_entity_count=baseline["entity_count"],
        baseline_relation_count=baseline["relation_count"],
        baseline_invalid_entity_type_count=baseline["invalid_entity_type_count"],
        baseline_invalid_relation_type_count=baseline["invalid_relation_type_count"],
        baseline_snake_case_relation_count=baseline["snake_case_relation_count"],
        baseline_candidate_entity_count=baseline["candidate_entity_count"],
        baseline_candidate_relation_count=baseline["candidate_relation_count"],
        baseline_allowed_entity_type_hit_rate=baseline["entity_hit_rate"],
        baseline_allowed_relation_type_hit_rate=baseline["relation_hit_rate"],
        baseline_expected_entity_coverage=baseline["expected_entity_coverage"],
        baseline_expected_relation_coverage=baseline["expected_relation_coverage"],
        baseline_evidence_keyword_coverage=baseline["evidence_keyword_coverage"],
        dsl_entity_count=dsl["entity_count"],
        dsl_relation_count=dsl["relation_count"],
        dsl_invalid_entity_type_count=dsl["invalid_entity_type_count"],
        dsl_invalid_relation_type_count=dsl["invalid_relation_type_count"],
        dsl_snake_case_relation_count=dsl["snake_case_relation_count"],
        dsl_candidate_entity_count=dsl["candidate_entity_count"],
        dsl_candidate_relation_count=dsl["candidate_relation_count"],
        dsl_allowed_entity_type_hit_rate=dsl["entity_hit_rate"],
        dsl_allowed_relation_type_hit_rate=dsl["relation_hit_rate"],
        dsl_expected_entity_coverage=dsl["expected_entity_coverage"],
        dsl_expected_relation_coverage=dsl["expected_relation_coverage"],
        dsl_evidence_keyword_coverage=dsl["evidence_keyword_coverage"],
        entity_type_hit_rate_delta=dsl["entity_hit_rate"] - baseline["entity_hit_rate"],
        relation_type_hit_rate_delta=dsl["relation_hit_rate"]
        - baseline["relation_hit_rate"],
        invalid_entity_type_delta=baseline["invalid_entity_type_count"]
        - dsl["invalid_entity_type_count"],
        invalid_relation_type_delta=baseline["invalid_relation_type_count"]
        - dsl["invalid_relation_type_count"],
        snake_case_relation_delta=baseline["snake_case_relation_count"]
        - dsl["snake_case_relation_count"],
        candidate_relation_delta=baseline["candidate_relation_count"]
        - dsl["candidate_relation_count"],
        expected_entity_coverage_delta=dsl["expected_entity_coverage"]
        - baseline["expected_entity_coverage"],
        expected_relation_coverage_delta=dsl["expected_relation_coverage"]
        - baseline["expected_relation_coverage"],
        evidence_keyword_coverage_delta=dsl["evidence_keyword_coverage"]
        - baseline["evidence_keyword_coverage"],
        improvement_label=label,
        reasons=reasons,
    )


def detect_relation_type(
    relationship_keywords: str,
    allowed_relation_types: list[str],
) -> str | None:
    tokens = _keyword_tokens(relationship_keywords)
    for relation_type in allowed_relation_types:
        if relation_type in tokens:
            return relation_type
    if "CandidateRelation" in tokens:
        return "CandidateRelation"
    return None


def is_snake_case_relation(value: str | None) -> bool:
    if not value:
        return False
    tokens = _keyword_tokens(value)
    return any(
        token in SNAKE_CASE_RELATIONS or bool(SNAKE_CASE_PATTERN.fullmatch(token))
        for token in tokens
    )


def _score_result(
    result: ExtractionRunResult,
    *,
    allowed_entity_types: list[str],
    allowed_relation_types: list[str],
    expected_entities: list[dict[str, Any]],
    expected_relations: list[dict[str, Any]],
    evidence_keywords: list[str],
) -> dict[str, Any]:
    allowed_entities = set(allowed_entity_types)
    allowed_relations = set(allowed_relation_types)
    entity_count = len(result.entities)
    relation_count = len(result.relations)
    candidate_entity_count = sum(
        1 for entity in result.entities if entity.entity_type == "CandidateEntity"
    )
    candidate_relation_count = sum(
        1
        for relation in result.relations
        if relation.relation_type == "CandidateRelation"
        or "CandidateRelation" in relation.relationship_keywords
    )
    entity_hits = sum(
        1 for entity in result.entities if entity.entity_type in allowed_entities
    )
    relation_hits = sum(
        1
        for relation in result.relations
        if relation.relation_type in allowed_relations
    )
    invalid_entity_type_count = sum(
        1
        for entity in result.entities
        if entity.entity_type not in allowed_entities
        and entity.entity_type != "CandidateEntity"
    )
    invalid_relation_type_count = sum(
        1
        for relation in result.relations
        if relation.relation_type not in allowed_relations
        and relation.relation_type != "CandidateRelation"
    )
    snake_case_relation_count = sum(
        1
        for relation in result.relations
        if is_snake_case_relation(relation.relation_type)
        or is_snake_case_relation(relation.relationship_keywords)
    )
    return {
        "entity_count": entity_count,
        "relation_count": relation_count,
        "invalid_entity_type_count": invalid_entity_type_count,
        "invalid_relation_type_count": invalid_relation_type_count,
        "snake_case_relation_count": snake_case_relation_count,
        "candidate_entity_count": candidate_entity_count,
        "candidate_relation_count": candidate_relation_count,
        "entity_hit_rate": entity_hits / entity_count if entity_count else 0.0,
        "relation_hit_rate": relation_hits / relation_count if relation_count else 0.0,
        "expected_entity_coverage": _expected_entity_coverage(
            result.entities,
            expected_entities,
        ),
        "expected_relation_coverage": _expected_relation_coverage(
            result.relations,
            expected_relations,
        ),
        "evidence_keyword_coverage": _evidence_keyword_coverage(
            result,
            evidence_keywords,
        ),
    }


def _expected_entity_coverage(
    entities: list[ExtractedEntity],
    expected_entities: list[dict[str, Any]],
) -> float:
    if not expected_entities:
        return 0.0
    matched = 0
    for expected in expected_entities:
        expected_name = _expected_value(expected, "entityName", "entity_name", "name")
        expected_type = _expected_value(expected, "entityType", "entity_type", "type")
        if any(
            (not expected_name or expected_name in entity.entity_name)
            and (not expected_type or expected_type == entity.entity_type)
            for entity in entities
        ):
            matched += 1
    return matched / len(expected_entities)


def _expected_relation_coverage(
    relations: list[ExtractedRelation],
    expected_relations: list[dict[str, Any]],
) -> float:
    if not expected_relations:
        return 0.0
    matched = 0
    for expected in expected_relations:
        expected_type = _expected_value(
            expected,
            "relationType",
            "relation_type",
            "relationship_keywords",
        )
        if any(
            expected_type
            and (
                expected_type == relation.relation_type
                or expected_type in relation.relationship_keywords
            )
            for relation in relations
        ):
            matched += 1
    return matched / len(expected_relations)


def _evidence_keyword_coverage(
    result: ExtractionRunResult,
    evidence_keywords: list[str],
) -> float:
    if not evidence_keywords:
        return 0.0
    haystack = "\n".join(
        [
            result.raw_output,
            *[entity.description for entity in result.entities],
            *[relation.description for relation in result.relations],
        ]
    ).lower()
    matched = sum(1 for keyword in evidence_keywords if keyword.lower() in haystack)
    return matched / len(evidence_keywords)


def _improvement_label(
    baseline: dict[str, Any],
    dsl: dict[str, Any],
    baseline_result: ExtractionRunResult,
    dsl_result: ExtractionRunResult,
) -> tuple[str, list[str]]:
    if (
        baseline["entity_count"] == 0
        and baseline["relation_count"] == 0
        and dsl["entity_count"] == 0
        and dsl["relation_count"] == 0
    ):
        return "INCONCLUSIVE", ["No valid entities or relations parsed."]

    positive = []
    negative = []
    _append_delta(
        positive,
        negative,
        dsl["entity_hit_rate"],
        baseline["entity_hit_rate"],
        "entity type hit rate",
    )
    _append_delta(
        positive,
        negative,
        dsl["relation_hit_rate"],
        baseline["relation_hit_rate"],
        "relation type hit rate",
    )
    _append_delta(
        positive,
        negative,
        baseline["invalid_entity_type_count"],
        dsl["invalid_entity_type_count"],
        "invalid entity type count reduced",
    )
    _append_delta(
        positive,
        negative,
        baseline["invalid_relation_type_count"],
        dsl["invalid_relation_type_count"],
        "invalid relation type count reduced",
    )
    _append_delta(
        positive,
        negative,
        baseline["snake_case_relation_count"],
        dsl["snake_case_relation_count"],
        "snake_case relation count reduced",
    )
    _append_delta(
        positive,
        negative,
        dsl["expected_relation_coverage"],
        baseline["expected_relation_coverage"],
        "expected relation coverage",
    )

    if len(dsl_result.parse_errors) > len(baseline_result.parse_errors) + 1:
        negative.append("DSL-aware output has more parse errors.")

    if len(positive) >= 2:
        return "IMPROVED", positive
    if len(negative) >= 2:
        return "DEGRADED", negative
    if positive or negative:
        return "SAME", [*(positive or []), *(negative or [])]
    return "INCONCLUSIVE", ["No measurable extraction-quality movement."]


def _append_delta(
    positive: list[str],
    negative: list[str],
    left: float | int,
    right: float | int,
    reason: str,
) -> None:
    if left > right:
        positive.append(f"Improved {reason}.")
    elif left < right:
        negative.append(f"Degraded {reason}.")


def _split_records(raw_output: str, completion_delimiter: str) -> list[str]:
    normalized = raw_output.replace(completion_delimiter, "\n")
    normalized = normalized.replace(completion_delimiter.lower(), "\n")
    return normalized.splitlines()


def _split_record(record: str, tuple_delimiter: str) -> list[str]:
    if tuple_delimiter in record:
        return [part.strip() for part in record.split(tuple_delimiter)]
    if "|" in record:
        return [part.strip() for part in record.split("|")]
    return [record]


def _keyword_tokens(value: str) -> set[str]:
    return {
        token.strip()
        for token in re.split(r"[,，;；/\s]+", value)
        if token.strip()
    }


def _clean(value: str) -> str:
    return value.strip().strip('"').strip("'")


def _expected_value(expected: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = expected.get(key)
        if isinstance(value, str) and value:
            return value
    return ""
