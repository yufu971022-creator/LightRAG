from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class IngestionEntry:
    entry_id: str
    route_or_function: str
    file_path: str
    line_number: int
    function_name: str
    async_mode: bool
    caller: str
    callee: str
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    side_effects: list[str] = field(default_factory=list)


@dataclass
class IngestionCallChain:
    chain_name: str
    entry_point: str
    steps: list[IngestionEntry] = field(default_factory=list)
    final_storage_targets: list[str] = field(default_factory=list)
    calls_embedding: bool = False
    calls_llm: bool = False
    calls_extract_entities: bool = False
    calls_ainsert_custom_kg: bool = False
    writes_full_docs: bool = False
    writes_text_chunks: bool = False
    writes_doc_status: bool = False
    writes_graph: bool = False
    evidence: list[str] = field(default_factory=list)


@dataclass
class RuntimeModelBaseline:
    binding: str | None
    model: str | None
    endpoint_host: str | None
    config_sources: dict[str, str] = field(default_factory=dict)
    configured_dimension: int | None = None
    dimension_source: str | None = None
    sends_dimensions_parameter: bool | None = None
    context_limit: int | None = None
    batch_size: int | None = None
    concurrency: int | None = None
    proxy_detected: bool = False
    no_proxy_covers_endpoint: bool | None = None
    fake_model_detected: bool = False
    credential_configured: bool = False
    credential_fingerprint: str | None = None
    credential_source: str | None = None
    cache_enabled: bool | None = None
    timeout: int | None = None
    summary_context_limit: int | None = None
    extract_model_same_as_query_model: bool | None = None
    risks: list[str] = field(default_factory=list)


@dataclass
class StorageBaseline:
    kv_storage: str
    vector_storage: str
    graph_storage: str
    doc_status_storage: str
    workspace: str
    namespace: str
    working_dir: str
    config_sources: dict[str, str] = field(default_factory=dict)
    is_networkx: bool = False
    is_neo4j: bool = False
    is_postgresql: bool = False
    is_nano_vectordb: bool = False
    uses_redis: bool = False
    uses_mongo: bool = False
    uses_opensearch: bool = False
    storage_files_found: list[str] = field(default_factory=list)
    embedding_metadata_found: bool | None = None
    risks: list[str] = field(default_factory=list)


@dataclass
class BaselineConclusion:
    conclusion: str
    evidence_file: str | None
    evidence_line: int | None
    evidence_function: str | None
    explanation: str
    unresolved_reason: str | None = None


@dataclass
class IngestionBaselineReport:
    repository_path: str
    git_commit: str
    current_branch: str
    original_upload_chain: IngestionCallChain
    dsl_ingestion_chain: IngestionCallChain
    baseline_conclusions: dict[str, BaselineConclusion]
    embedding_baseline: RuntimeModelBaseline
    llm_baseline: RuntimeModelBaseline
    storage_baseline: StorageBaseline
    current_architecture_conclusion: str
    confirmed_facts: list[str] = field(default_factory=list)
    unresolved_questions: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    recommended_next_block: str = "Block 24A-1"
    generated_at: str = ""


def to_plain_dict(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_dict(item) for key, item in value.items()}
    return value
