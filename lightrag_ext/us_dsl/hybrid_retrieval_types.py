from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

RetrievalTaskType = Literal[
    "FACT_QA",
    "TRACEABILITY",
    "IMPACT_ANALYSIS",
    "VERSION_COMPARE",
    "BACKGROUND",
]
RetrievalChannel = Literal[
    "RAW_TEXT",
    "PFSS_ENTITY",
    "PFSS_RELATION",
    "PFSS_PATH",
    "GENERIC_GRAPH",
    "ISSUE_SIDECAR",
    "VERSION_CONTEXT",
]
TrustTier = Literal["T1_DIRECT", "T2_SEMANTIC", "T3_TENTATIVE", "T4_BACKGROUND", "T5_WARNING"]
CandidateKind = Literal["TEXT", "ENTITY", "RELATION", "PATH", "ISSUE", "VERSION"]
PathValidationStatus = Literal[
    "FACTUAL",
    "TENTATIVE_VERSION_CONFLICT",
    "BACKGROUND_ONLY",
    "NOT_FACTUAL_MISSING_EVIDENCE",
    "NOT_FACTUAL_ISSUE_EDGE",
    "INVALID_HOP_LIMIT",
    "DANGLING_PATH",
]
FallbackState = Literal[
    "HYBRID_EVIDENCE_READY",
    "TEXT_ONLY_FALLBACK",
    "PFSS_WITH_VERSION_WARNING",
    "GENERIC_ONLY_LOW_TRUST",
    "ISSUE_ONLY",
    "INSUFFICIENT_EVIDENCE",
    "STRICT_SCOPE_EMPTY",
]


@dataclass(frozen=True)
class HybridRetrievalRequest:
    query_text: str
    task_type: RetrievalTaskType = "FACT_QA"
    module_code: str | None = None
    domain_code: str | None = None
    feature_key: str | None = None
    object_type: str | None = None
    strict_scope: bool = False
    include_generic: bool = True
    include_historical: bool = False
    top_k: int = 8
    max_hops: int | None = None
    explicit_version_intent: str | None = None
    as_of_time: str | None = None


@dataclass
class QuerySemanticProfile:
    query_text: str
    task_type: RetrievalTaskType
    canonical_terms: list[str] = field(default_factory=list)
    confirmed_aliases: list[str] = field(default_factory=list)
    candidate_aliases: list[str] = field(default_factory=list)
    rejected_aliases: list[str] = field(default_factory=list)
    version_intent: str = "UNSPECIFIED"
    domain_hints: list[str] = field(default_factory=list)
    feature_hints: list[str] = field(default_factory=list)
    object_type_hints: list[str] = field(default_factory=list)
    strict_scope: bool = False
    scope_key: str | None = None
    reason_codes: list[str] = field(default_factory=list)


@dataclass
class EvidenceRef:
    document_id: str
    document_version_id: str
    text_unit_id: str
    source_span: dict[str, int] = field(default_factory=dict)
    text_hash: str | None = None
    excerpt: str | None = None
    active: bool = True
    deleted: bool = False


@dataclass
class PathCandidate:
    path_id: str
    node_ids: list[str]
    edge_ids: list[str]
    evidence_refs: list[str] = field(default_factory=list)
    has_issue_edge: bool = False
    version_conflict: bool = False
    generic_only: bool = False
    dangling: bool = False
    task_type: RetrievalTaskType = "FACT_QA"
    validation_status: PathValidationStatus | None = None
    validation_reasons: list[str] = field(default_factory=list)

    @property
    def hop_count(self) -> int:
        return len(self.edge_ids)

    @property
    def signature(self) -> str:
        return "->".join([*self.node_ids, *self.edge_ids])


@dataclass
class RetrievalCandidate:
    candidate_id: str
    channel: RetrievalChannel
    kind: CandidateKind
    text: str
    raw_score: float
    source: str
    trust_tier: TrustTier
    factual_weight: float = 1.0
    semantic_object_id: str | None = None
    semantic_relation_id: str | None = None
    stable_identity_key: str | None = None
    path: PathCandidate | None = None
    evidence: list[EvidenceRef] = field(default_factory=list)
    version_status: str | None = None
    version_intent: str | None = None
    issue_type: str | None = None
    severity: str | None = None
    domain_code: str | None = None
    feature_key: str | None = None
    object_type: str | None = None
    active: bool = True
    deleted: bool = False
    channel_rank: int | None = None
    normalized_score: float = 0.0
    fused_score: float = 0.0
    fusion_reasons: list[str] = field(default_factory=list)
    reason_codes: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class NormalizationReport:
    channel_counts: dict[str, int] = field(default_factory=dict)
    direct_raw_score_addition_used: bool = False
    score_ranges: dict[str, dict[str, float]] = field(default_factory=dict)


@dataclass
class DeduplicationReport:
    input_count: int
    output_count: int
    duplicate_groups: list[dict[str, Any]] = field(default_factory=list)
    generic_overrode_pfss_count: int = 0
    raw_evidence_preserved: bool = True
    deterministic_path_signature: bool = True


@dataclass
class FusionReport:
    fusion_method: str = "WEIGHTED_RRF"
    issue_factual_weight: float = 0.0
    direct_raw_score_addition_used: bool = False
    candidate_scores: list[dict[str, Any]] = field(default_factory=list)
    deterministic_ranking_passed: bool = True
    domain_match_boost_applied: bool = False
    feature_match_boost_applied: bool = False
    version_conflict_penalty_visible: bool = False
    missing_evidence_penalty_visible: bool = False
    entity_name_specific_weight_rule_count: int = 0


@dataclass
class PathValidationReport:
    path_statuses: list[dict[str, Any]] = field(default_factory=list)
    missing_evidence_factual_path_count: int = 0
    issue_edges_in_factual_path_count: int = 0
    generic_background_count: int = 0
    dangling_path_count: int = 0


@dataclass
class FallbackResult:
    state: FallbackState
    safe_for_deterministic_answer: bool
    reasons: list[str] = field(default_factory=list)


@dataclass
class TokenBudgetReport:
    max_items: int
    kept_items: int
    token_budget_preserved_required_evidence: bool
    dropped_candidate_ids: list[str] = field(default_factory=list)


@dataclass
class TrustedContextPack:
    request: HybridRetrievalRequest
    profile: QuerySemanticProfile
    fallback: FallbackResult
    factual_candidates: list[RetrievalCandidate] = field(default_factory=list)
    direct_evidence: list[EvidenceRef] = field(default_factory=list)
    factual_paths: list[PathCandidate] = field(default_factory=list)
    tentative_paths: list[PathCandidate] = field(default_factory=list)
    generic_context: list[RetrievalCandidate] = field(default_factory=list)
    issue_warnings: list[RetrievalCandidate] = field(default_factory=list)
    score_explanations: list[dict[str, Any]] = field(default_factory=list)
    citations: list[dict[str, Any]] = field(default_factory=list)
    token_budget: TokenBudgetReport | None = None
    final_answer_generated: bool = False


@dataclass
class HybridRetrievalResult:
    request: HybridRetrievalRequest
    profile: QuerySemanticProfile
    raw_candidates: list[RetrievalCandidate]
    pfss_candidates: list[RetrievalCandidate]
    generic_candidates: list[RetrievalCandidate]
    issue_candidates: list[RetrievalCandidate]
    normalized_candidates: list[RetrievalCandidate]
    deduplicated_candidates: list[RetrievalCandidate]
    fused_candidates: list[RetrievalCandidate]
    fallback: FallbackResult
    context_pack: TrustedContextPack
    normalization_report: NormalizationReport
    deduplication_report: DeduplicationReport
    fusion_report: FusionReport
    path_validation_report: PathValidationReport


def to_plain_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, tuple):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {str(key): to_plain_dict(item) for key, item in value.items()}
    return value
