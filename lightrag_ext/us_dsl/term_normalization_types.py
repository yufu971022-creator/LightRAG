from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

TermMappingStatus = Literal["CONFIRMED", "CANDIDATE", "REJECTED", "DEPRECATED"]
TermMappingSource = Literal["CONFIG", "HUMAN_REVIEW", "DETERMINISTIC_RULE", "HISTORICAL_IMPORT", "MODEL_SUGGESTION"]
SynonymType = Literal[
    "CASE_VARIANT",
    "WHITESPACE_VARIANT",
    "PUNCTUATION_VARIANT",
    "ABBREVIATION",
    "TRANSLATION",
    "LEGACY_NAME",
    "BUSINESS_ALIAS",
    "TYPO_CORRECTION",
]
TermDecision = Literal[
    "IDENTITY",
    "AUTO_NORMALIZED",
    "REGISTRY_CONFIRMED",
    "CANDIDATE_REVIEW",
    "REJECTED_MAPPING",
    "NO_MAPPING",
    "CONFLICT",
]


@dataclass(frozen=True)
class TermScope:
    system_name: str | None = None
    module_code: str | None = None
    domain_code: str | None = None
    feature_key: str | None = None
    object_type: str | None = None
    language_code: str | None = None

    def normalized(self) -> "TermScope":
        return TermScope(
            system_name=_clean(self.system_name),
            module_code=_clean(self.module_code),
            domain_code=_clean(self.domain_code),
            feature_key=_clean(self.feature_key),
            object_type=_clean(self.object_type),
            language_code=_clean(self.language_code),
        )

    def scope_key(self, *, include_language: bool = False) -> str:
        scope = self.normalized()
        parts = [scope.system_name, scope.module_code, scope.domain_code, scope.feature_key, scope.object_type]
        if include_language:
            parts.append(scope.language_code)
        return "|".join(part or "*" for part in parts)

    def semantic_scope_key(self) -> str:
        return self.scope_key(include_language=False)

    def without_language(self) -> "TermScope":
        scope = self.normalized()
        return TermScope(
            system_name=scope.system_name,
            module_code=scope.module_code,
            domain_code=scope.domain_code,
            feature_key=scope.feature_key,
            object_type=scope.object_type,
            language_code=None,
        )


@dataclass(frozen=True)
class TermMappingRecord:
    term_mapping_id: str
    source_term: str
    canonical_term: str
    source_language: str | None
    canonical_language: str | None
    synonym_type: SynonymType
    scope: TermScope
    confidence: float
    status: TermMappingStatus
    mapping_source: TermMappingSource
    requires_scope: bool = False
    effective_from: str | None = None
    effective_to: str | None = None
    owner: str | None = None
    comments: str | None = None
    registry_version: str = "25A-0"
    created_at: str = ""
    updated_at: str = ""
    source_lexical_key: str = ""
    canonical_key: str = ""


@dataclass(frozen=True)
class TermNormalizationConfig:
    auto_confirm_threshold: float = 0.95
    candidate_threshold: float = 0.70


@dataclass(frozen=True)
class TermNormalizationDecision:
    original_term: str
    lexically_normalized_term: str
    canonical_term: str
    canonical_key: str
    semantic_scope_key: str
    decision: TermDecision
    mapping_status: TermMappingStatus | None
    mapping_source: TermMappingSource | None
    confidence: float
    matched_mapping_ids: list[str] = field(default_factory=list)
    conflict_mapping_ids: list[str] = field(default_factory=list)
    requires_review: bool = False
    reason_codes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SemanticIdentityKey:
    system_name: str | None
    module_code: str | None
    domain_code: str | None
    feature_key: str | None
    object_type: str
    canonical_object_key: str
    rule_dimension: str | None = None

    def components(self) -> list[str]:
        return [
            _clean(self.system_name) or "global",
            _clean(self.module_code) or "module",
            _clean(self.domain_code) or "domain",
            _clean(self.feature_key) or "feature",
            _clean(self.object_type) or "object",
            _clean(self.canonical_object_key) or "identity",
            _clean(self.rule_dimension) or "default",
        ]


@dataclass(frozen=True)
class TermExpansionResult:
    original_terms: list[str]
    canonical_terms: list[str]
    confirmed_aliases: list[str]
    candidate_aliases: list[str]
    rejected_aliases: list[str]
    scope_used: str
    ambiguities: list[str]
    live_query_connected: bool = False


@dataclass(frozen=True)
class TermNormalizationMigrationPlan:
    affected_semantic_object_ids: list[str]
    alias_groups: dict[str, list[str]]
    merge_candidate_groups: list[list[str]]
    confirmed_merge_groups: list[list[str]]
    conflict_groups: list[list[str]]
    version_group_rekey_count: int
    graph_rebuild_required_count: int
    sidecar_only_update_count: int
    planned_actions: list[dict[str, Any]]


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped or None
