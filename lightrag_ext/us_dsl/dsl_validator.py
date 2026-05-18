from __future__ import annotations

import re
from typing import Any

from .dsl_types import OntologyConfig, ValidationIssue, ValidationResult


REQUIRED_TOP_LEVEL_KEYS = {
    "dslVersion",
    "outputFormat",
    "fixedDomains",
    "runSummary",
    "activeDomainOverview",
    "termNormalization",
    "versionManagement",
    "featureCatalogIndex",
    "confirmedDslObjects",
    "sourceVectorizationPlan",
    "gleaningInputBlocks",
}

ALLOWED_CONFIRMED_OBJECT_KEYS = {
    "usDocs",
    "featureCatalogs",
    "ruleVersions",
    "ruleAtoms",
    "fieldSpecs",
    "messageAtoms",
    "stateTransitions",
    "taskRules",
    "dependencyEdges",
    "entities",
    "relations",
}

BANNED_CONFIRMED_FIELDS = {
    "estimatedEffort",
    "priority",
    "complexity",
    "businessValue",
    "coveragePercent",
    "rollbackStrategy",
    "nextVersionPlan",
    "databaseTable",
    "integrationProtocol",
    "authMethod",
    "timeoutSeconds",
    "fallbackStrategy",
}

SOURCE_VECTORIZATION_REQUIRED_KEYS = {
    "sourceUsId",
    "featureKey",
    "domainCode",
    "sectionType",
    "targetCollections",
    "sourceChunkRequired",
    "dslContextRequired",
}

GLEANING_BLOCK_REQUIRED_KEYS = {
    "sourceType",
    "featureKey",
    "domainCode",
    "allowedEntityTypes",
    "allowedRelationTypes",
    "instruction",
}

BANNED_SNAKE_RELATION_TYPES = {
    "has_child",
    "belongs_to",
    "references_to",
    "queries_from",
    "queries_by",
    "contains",
}

SNAKE_CASE_PATTERN = re.compile(r"^[a-z]+(?:_[a-z]+)+$")


def validate_dsl_compiled(dsl: dict, ontology: OntologyConfig) -> ValidationResult:
    issues: list[ValidationIssue] = []

    if not isinstance(dsl, dict):
        return ValidationResult(
            passed=False,
            issues=[
                ValidationIssue(
                    "ERROR", "DSL_ROOT_TYPE", "$", "DSL compiled content must be a JSON object"
                )
            ],
        )

    _check_required_top_level_keys(dsl, issues)
    _check_output_format(dsl, issues)
    _check_fixed_domains(dsl, ontology, issues)
    _check_active_domains(dsl, ontology, issues)
    _check_confirmed_object_container(dsl, issues)
    _check_confirmed_entities(dsl, ontology, issues)
    _check_confirmed_relations(dsl, ontology, issues)
    _check_banned_confirmed_fields(dsl, issues)
    _check_source_vectorization_plan(dsl, ontology, issues)
    _check_gleaning_input_blocks(dsl, ontology, issues)
    _check_lightrag_phase1_policy(dsl, issues)

    return ValidationResult(
        passed=not any(issue.severity == "ERROR" for issue in issues),
        issues=issues,
    )


def _add_issue(
    issues: list[ValidationIssue], severity: str, code: str, path: str, message: str
) -> None:
    issues.append(ValidationIssue(severity=severity, code=code, path=path, message=message))


def _check_required_top_level_keys(dsl: dict[str, Any], issues: list[ValidationIssue]) -> None:
    missing = sorted(REQUIRED_TOP_LEVEL_KEYS - set(dsl.keys()))
    for key in missing:
        _add_issue(
            issues,
            "ERROR",
            "REQUIRED_TOP_LEVEL_KEYS",
            f"$.{key}",
            f"Missing required top-level key: {key}",
        )


def _check_output_format(dsl: dict[str, Any], issues: list[ValidationIssue]) -> None:
    output_format = dsl.get("outputFormat")
    if output_format != "json-only":
        _add_issue(
            issues,
            "ERROR",
            "OUTPUT_FORMAT",
            "$.outputFormat",
            'outputFormat must be "json-only"',
        )


def _domain_code(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        candidate = value.get("domainCode")
        if isinstance(candidate, str):
            return candidate
    return None


def _iter_domain_list(value: Any, path: str) -> list[tuple[str, str]]:
    if not isinstance(value, list):
        return []

    result = []
    for index, item in enumerate(value):
        domain_code = _domain_code(item)
        if domain_code is not None:
            result.append((domain_code, f"{path}[{index}]"))
    return result


def _check_domain_value(
    domain_code: Any,
    path: str,
    ontology: OntologyConfig,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(domain_code, str) or not domain_code:
        _add_issue(
            issues,
            "ERROR",
            "ACTIVE_DOMAIN_CHECK",
            path,
            "Domain code must be a non-empty string",
        )
        return

    if not ontology.is_valid_domain(domain_code):
        _add_issue(
            issues,
            "ERROR",
            "UNKNOWN_DOMAIN",
            path,
            f"Unknown domainCode: {domain_code}",
        )


def _check_fixed_domains(
    dsl: dict[str, Any], ontology: OntologyConfig, issues: list[ValidationIssue]
) -> None:
    fixed_domains = dsl.get("fixedDomains")
    if fixed_domains is None:
        return
    if not isinstance(fixed_domains, list):
        _add_issue(
            issues,
            "ERROR",
            "FIXED_DOMAIN_CHECK",
            "$.fixedDomains",
            "fixedDomains must be a list",
        )
        return

    seen_domains = set()
    for index, item in enumerate(fixed_domains):
        path = f"$.fixedDomains[{index}]"
        domain_code = _domain_code(item)
        if domain_code is None:
            _add_issue(
                issues,
                "ERROR",
                "FIXED_DOMAIN_CHECK",
                path,
                "Each fixedDomains item must be a domainCode string or object",
            )
            continue
        seen_domains.add(domain_code)
        if not ontology.is_valid_domain(domain_code):
            _add_issue(
                issues,
                "ERROR",
                "UNKNOWN_DOMAIN",
                path,
                f"Unknown domainCode: {domain_code}",
            )

    missing_domains = sorted(ontology.domains - seen_domains)
    if missing_domains:
        _add_issue(
            issues,
            "ERROR",
            "FIXED_DOMAIN_CHECK",
            "$.fixedDomains",
            "fixedDomains must contain all fixed domains: "
            + ", ".join(missing_domains),
        )


def _check_active_domains(
    dsl: dict[str, Any], ontology: OntologyConfig, issues: list[ValidationIssue]
) -> None:
    run_summary = dsl.get("runSummary")
    if isinstance(run_summary, dict) and "activeDomains" in run_summary:
        active_domains = run_summary.get("activeDomains")
        if not isinstance(active_domains, list):
            _add_issue(
                issues,
                "ERROR",
                "ACTIVE_DOMAIN_CHECK",
                "$.runSummary.activeDomains",
                "activeDomains must be a list",
            )
        else:
            for domain_code, path in _iter_domain_list(
                active_domains, "$.runSummary.activeDomains"
            ):
                _check_domain_value(domain_code, path, ontology, issues)

    active_overview = dsl.get("activeDomainOverview")
    if isinstance(active_overview, list):
        for index, item in enumerate(active_overview):
            path = f"$.activeDomainOverview[{index}]"
            if not isinstance(item, dict):
                _add_issue(
                    issues,
                    "ERROR",
                    "ACTIVE_DOMAIN_CHECK",
                    path,
                    "activeDomainOverview item must be an object",
                )
                continue
            _check_domain_value(item.get("domainCode"), f"{path}.domainCode", ontology, issues)

    feature_catalog = dsl.get("featureCatalogIndex")
    if isinstance(feature_catalog, list):
        for index, item in enumerate(feature_catalog):
            path = f"$.featureCatalogIndex[{index}]"
            if not isinstance(item, dict):
                _add_issue(
                    issues,
                    "ERROR",
                    "ACTIVE_DOMAIN_CHECK",
                    path,
                    "featureCatalogIndex item must be an object",
                )
                continue
            if "primaryDomain" in item:
                _check_domain_value(
                    item.get("primaryDomain"),
                    f"{path}.primaryDomain",
                    ontology,
                    issues,
                )
            related_domains = item.get("relatedDomains")
            if related_domains is not None:
                if not isinstance(related_domains, list):
                    _add_issue(
                        issues,
                        "ERROR",
                        "ACTIVE_DOMAIN_CHECK",
                        f"{path}.relatedDomains",
                        "relatedDomains must be a list",
                    )
                else:
                    for domain_code, domain_path in _iter_domain_list(
                        related_domains, f"{path}.relatedDomains"
                    ):
                        _check_domain_value(domain_code, domain_path, ontology, issues)


def _check_confirmed_object_container(
    dsl: dict[str, Any], issues: list[ValidationIssue]
) -> None:
    confirmed = dsl.get("confirmedDslObjects")
    if confirmed is None:
        return
    if not isinstance(confirmed, dict):
        _add_issue(
            issues,
            "ERROR",
            "CONFIRMED_OBJECTS_TYPE",
            "$.confirmedDslObjects",
            "confirmedDslObjects must be an object",
        )
        return

    for key in confirmed:
        if key not in ALLOWED_CONFIRMED_OBJECT_KEYS:
            _add_issue(
                issues,
                "WARN",
                "UNKNOWN_CONFIRMED_OBJECT_COLLECTION",
                f"$.confirmedDslObjects.{key}",
                f"Unknown confirmedDslObjects collection: {key}",
            )


def _object_domain_code(item: dict[str, Any]) -> str:
    for key in ("domainCode", "primaryDomain", "domain"):
        value = item.get(key)
        if isinstance(value, str) and value:
            return value
    return "Other"


def _check_confirmed_entities(
    dsl: dict[str, Any], ontology: OntologyConfig, issues: list[ValidationIssue]
) -> None:
    entities = _confirmed_collection(dsl, "entities")
    if entities is None:
        return

    for index, entity in enumerate(entities):
        path = f"$.confirmedDslObjects.entities[{index}]"
        if not isinstance(entity, dict):
            _add_issue(issues, "ERROR", "ENTITY_TYPE_CHECK", path, "Entity must be an object")
            continue

        entity_name = entity.get("entityName")
        entity_type = entity.get("entityType")
        domain_code = _object_domain_code(entity)
        if "domainCode" in entity:
            _check_domain_value(entity.get("domainCode"), f"{path}.domainCode", ontology, issues)

        if not isinstance(entity_name, str) or not entity_name.strip():
            _add_issue(
                issues,
                "ERROR",
                "ENTITY_TYPE_CHECK",
                f"{path}.entityName",
                "Entity must include entityName separately from entityType",
            )

        if not isinstance(entity_type, str) or not entity_type.strip():
            _add_issue(
                issues,
                "ERROR",
                "ENTITY_TYPE_CHECK",
                f"{path}.entityType",
                "Entity must include entityType separately from entityName",
            )
            continue

        if entity_type == "CandidateEntity":
            _add_issue(
                issues,
                "WARN",
                "CANDIDATE_ENTITY",
                f"{path}.entityType",
                "CandidateEntity is allowed but should not be treated as confirmed ontology",
            )
            continue

        if not ontology.is_valid_entity_type(domain_code, entity_type):
            _add_issue(
                issues,
                "ERROR",
                "ENTITY_TYPE_CHECK",
                f"{path}.entityType",
                f"Invalid entityType '{entity_type}' for domainCode '{domain_code}'. "
                "entityName and entityType must be separated.",
            )


def _check_confirmed_relations(
    dsl: dict[str, Any], ontology: OntologyConfig, issues: list[ValidationIssue]
) -> None:
    relations = _confirmed_collection(dsl, "relations")
    if relations is None:
        return

    for index, relation in enumerate(relations):
        path = f"$.confirmedDslObjects.relations[{index}]"
        if not isinstance(relation, dict):
            _add_issue(
                issues, "ERROR", "RELATION_TYPE_CHECK", path, "Relation must be an object"
            )
            continue

        relation_type = relation.get("relationType")
        domain_code = _object_domain_code(relation)
        if "domainCode" in relation:
            _check_domain_value(
                relation.get("domainCode"), f"{path}.domainCode", ontology, issues
            )

        if not isinstance(relation_type, str) or not relation_type.strip():
            _add_issue(
                issues,
                "ERROR",
                "RELATION_TYPE_CHECK",
                f"{path}.relationType",
                "Relation must include relationType",
            )
            continue

        if relation_type == "CandidateRelation":
            _add_issue(
                issues,
                "WARN",
                "CANDIDATE_RELATION",
                f"{path}.relationType",
                "CandidateRelation is allowed but should not be treated as confirmed ontology",
            )
            continue

        if relation_type in BANNED_SNAKE_RELATION_TYPES or SNAKE_CASE_PATTERN.match(
            relation_type
        ):
            _add_issue(
                issues,
                "ERROR",
                "SNAKE_CASE_RELATION_TYPE",
                f"{path}.relationType",
                f"Relation type '{relation_type}' must use the DSL relation whitelist, not snake_case/free-form labels",
            )
            continue

        if not ontology.is_valid_relation_type(domain_code, relation_type):
            _add_issue(
                issues,
                "ERROR",
                "RELATION_TYPE_CHECK",
                f"{path}.relationType",
                f"Invalid relationType '{relation_type}' for domainCode '{domain_code}'",
            )


def _confirmed_collection(dsl: dict[str, Any], name: str) -> list[Any] | None:
    confirmed = dsl.get("confirmedDslObjects")
    if not isinstance(confirmed, dict) or name not in confirmed:
        return None
    value = confirmed.get(name)
    if isinstance(value, list):
        return value
    return []


def _check_banned_confirmed_fields(
    dsl: dict[str, Any], issues: list[ValidationIssue]
) -> None:
    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            if value.get("knowledgeStatus") == "Confirmed":
                for field_name in sorted(BANNED_CONFIRMED_FIELDS):
                    if field_name in value:
                        _add_issue(
                            issues,
                            "ERROR",
                            "CONFIRMED_INFERENCE_BANNED_FIELD",
                            f"{path}.{field_name}",
                            f'Confirmed object must not contain inferred field "{field_name}"',
                        )
            for key, child in value.items():
                walk(child, f"{path}.{key}")
        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(dsl, "$")


def _check_source_vectorization_plan(
    dsl: dict[str, Any], ontology: OntologyConfig, issues: list[ValidationIssue]
) -> None:
    plan = dsl.get("sourceVectorizationPlan")
    if not isinstance(plan, list):
        _add_issue(
            issues,
            "ERROR",
            "SOURCE_VECTORIZATION_PLAN_CHECK",
            "$.sourceVectorizationPlan",
            "sourceVectorizationPlan must be a non-empty list",
        )
        return
    if not plan:
        _add_issue(
            issues,
            "ERROR",
            "SOURCE_VECTORIZATION_PLAN_CHECK",
            "$.sourceVectorizationPlan",
            "sourceVectorizationPlan must not be empty",
        )
        return

    for index, item in enumerate(plan):
        path = f"$.sourceVectorizationPlan[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                "ERROR",
                "SOURCE_VECTORIZATION_PLAN_CHECK",
                path,
                "sourceVectorizationPlan item must be an object",
            )
            continue
        _check_required_item_keys(
            item, SOURCE_VECTORIZATION_REQUIRED_KEYS, path, "SOURCE_VECTORIZATION_PLAN_CHECK", issues
        )
        _check_domain_value(item.get("domainCode"), f"{path}.domainCode", ontology, issues)
        if item.get("sourceChunkRequired") is not True:
            _add_issue(
                issues,
                "ERROR",
                "SOURCE_VECTORIZATION_PLAN_CHECK",
                f"{path}.sourceChunkRequired",
                "sourceChunkRequired must be true",
            )
        if item.get("dslContextRequired") is not True:
            _add_issue(
                issues,
                "ERROR",
                "SOURCE_VECTORIZATION_PLAN_CHECK",
                f"{path}.dslContextRequired",
                "dslContextRequired must be true",
            )


def _check_gleaning_input_blocks(
    dsl: dict[str, Any], ontology: OntologyConfig, issues: list[ValidationIssue]
) -> None:
    blocks = dsl.get("gleaningInputBlocks")
    if not isinstance(blocks, list):
        _add_issue(
            issues,
            "ERROR",
            "GLEANING_BLOCK_CHECK",
            "$.gleaningInputBlocks",
            "gleaningInputBlocks must be a non-empty list",
        )
        return
    if not blocks:
        _add_issue(
            issues,
            "ERROR",
            "GLEANING_BLOCK_CHECK",
            "$.gleaningInputBlocks",
            "gleaningInputBlocks must not be empty",
        )
        return

    for index, item in enumerate(blocks):
        path = f"$.gleaningInputBlocks[{index}]"
        if not isinstance(item, dict):
            _add_issue(
                issues,
                "ERROR",
                "GLEANING_BLOCK_CHECK",
                path,
                "gleaningInputBlocks item must be an object",
            )
            continue
        _check_required_item_keys(
            item, GLEANING_BLOCK_REQUIRED_KEYS, path, "GLEANING_BLOCK_CHECK", issues
        )
        domain_code = item.get("domainCode")
        _check_domain_value(domain_code, f"{path}.domainCode", ontology, issues)
        if not isinstance(domain_code, str) or not ontology.is_valid_domain(domain_code):
            domain_code = "Other"

        _check_allowed_entity_type_list(
            item.get("allowedEntityTypes"),
            f"{path}.allowedEntityTypes",
            domain_code,
            ontology,
            issues,
        )
        _check_allowed_relation_type_list(
            item.get("allowedRelationTypes"),
            f"{path}.allowedRelationTypes",
            domain_code,
            ontology,
            issues,
        )


def _check_required_item_keys(
    item: dict[str, Any],
    required_keys: set[str],
    path: str,
    code: str,
    issues: list[ValidationIssue],
) -> None:
    for key in sorted(required_keys - set(item.keys())):
        _add_issue(issues, "ERROR", code, f"{path}.{key}", f"Missing required key: {key}")


def _check_allowed_entity_type_list(
    value: Any,
    path: str,
    domain_code: str,
    ontology: OntologyConfig,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(value, list):
        _add_issue(issues, "ERROR", "GLEANING_BLOCK_CHECK", path, "Must be a list")
        return
    for index, entity_type in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(entity_type, str) or not entity_type:
            _add_issue(
                issues,
                "ERROR",
                "ENTITY_TYPE_CHECK",
                item_path,
                "allowedEntityTypes item must be a non-empty string",
            )
            continue
        if entity_type == "CandidateEntity":
            _add_issue(
                issues,
                "WARN",
                "CANDIDATE_ENTITY",
                item_path,
                "CandidateEntity is allowed in gleaning but should remain candidate-only",
            )
            continue
        if not ontology.is_valid_entity_type(domain_code, entity_type):
            _add_issue(
                issues,
                "ERROR",
                "ENTITY_TYPE_CHECK",
                item_path,
                f"Invalid allowed entity type '{entity_type}' for domainCode '{domain_code}'",
            )


def _check_allowed_relation_type_list(
    value: Any,
    path: str,
    domain_code: str,
    ontology: OntologyConfig,
    issues: list[ValidationIssue],
) -> None:
    if not isinstance(value, list):
        _add_issue(issues, "ERROR", "GLEANING_BLOCK_CHECK", path, "Must be a list")
        return
    for index, relation_type in enumerate(value):
        item_path = f"{path}[{index}]"
        if not isinstance(relation_type, str) or not relation_type:
            _add_issue(
                issues,
                "ERROR",
                "RELATION_TYPE_CHECK",
                item_path,
                "allowedRelationTypes item must be a non-empty string",
            )
            continue
        if relation_type == "CandidateRelation":
            _add_issue(
                issues,
                "WARN",
                "CANDIDATE_RELATION",
                item_path,
                "CandidateRelation is allowed in gleaning but should remain candidate-only",
            )
            continue
        if relation_type in BANNED_SNAKE_RELATION_TYPES or SNAKE_CASE_PATTERN.match(
            relation_type
        ):
            _add_issue(
                issues,
                "ERROR",
                "SNAKE_CASE_RELATION_TYPE",
                item_path,
                f"Relation type '{relation_type}' must use the DSL relation whitelist",
            )
            continue
        if not ontology.is_valid_relation_type(domain_code, relation_type):
            _add_issue(
                issues,
                "ERROR",
                "RELATION_TYPE_CHECK",
                item_path,
                f"Invalid allowed relation type '{relation_type}' for domainCode '{domain_code}'",
            )


def _check_lightrag_phase1_policy(
    dsl: dict[str, Any], issues: list[ValidationIssue]
) -> None:
    policies = dsl.get("policies")
    if not isinstance(policies, dict):
        return

    recommended_mode = policies.get("lightRagRecommendedMode")
    if recommended_mode is not None and recommended_mode != "tuple_prompt_context":
        _add_issue(
            issues,
            "WARN",
            "LIGHTRAG_PHASE1_POLICY",
            "$.policies.lightRagRecommendedMode",
            'Recommended LightRAG phase-1 mode is "tuple_prompt_context"',
        )

    has_parser_migration = bool(
        policies.get("parserMigration")
        or policies.get("parserMigrationReady")
        or policies.get("allowParserMigration")
    )
    if policies.get("forceJsonParser") is True and not has_parser_migration:
        _add_issue(
            issues,
            "WARN",
            "LIGHTRAG_PHASE1_POLICY",
            "$.policies.forceJsonParser",
            "forceJsonParser=true is not recommended without parser migration",
        )
    if policies.get("parserMode") == "json" and not has_parser_migration:
        _add_issue(
            issues,
            "WARN",
            "LIGHTRAG_PHASE1_POLICY",
            "$.policies.parserMode",
            'parserMode="json" is not recommended without parser migration',
        )

