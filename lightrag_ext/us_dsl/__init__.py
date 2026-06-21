"""US DSL loading and validation helpers."""

from .candidate_extraction import (
    CandidateExtractionReport,
    CandidateExtractionWriteConfig,
    build_candidates_from_extract_result,
    run_candidate_extraction_write_dry_run,
    serialize_candidate_extraction_report,
)
from .candidate_quality import (
    validate_candidate_entity,
    validate_candidate_relation,
)
from .candidate_review import (
    CandidateReviewDecision,
    CandidateReviewPolicy,
    CandidateReviewReport,
    build_candidate_review_decisions,
    build_candidate_review_report,
    build_candidate_review_report_from_candidate_extraction_report,
    detect_term_review_required,
    detect_version_review_required,
    serialize_candidate_review_report,
)
from .candidate_store import CandidateStore
from .candidate_types import (
    CandidateEntity,
    CandidateExtractionIssue,
    CandidateRelation,
)
from .config_registry import (
    BusinessObjectTypeRule,
    ConfigRegistry,
    DEFAULT_CONFIG_REGISTRY,
    EntityAliasRule,
    RelationMappingRule,
    default_config_registry,
)
from .dsl_loader import load_dsl_compiled
from .dsl_types import (
    DslAwareChunk,
    DslAwareChunkBuildIssue,
    DslAwareChunkBuildResult,
    DslCompiledResult,
    DslValidationError,
    OntologyConfig,
    SourceTextUnit,
    UsBlock,
    ValidationIssue,
    ValidationResult,
)
from .dsl_aware_chunk_builder import build_dsl_aware_chunks
from .extraction_eval import (
    ExtractionEvaluationReport,
    ExtractionInputPair,
    deterministic_fake_extraction_output,
    live_smoke_enabled,
    run_deterministic_extraction_pair,
    run_lightrag_extract_entities_if_available,
    run_offline_extraction_evaluation,
    select_extraction_eval_samples,
)
from .extraction_metrics import (
    ExtractedEntity,
    ExtractedRelation,
    ExtractionComparisonMetrics,
    ExtractionRunResult,
    compare_extraction_results,
    parse_tuple_extraction_output,
)
from .extraction_hook_dry_run import (
    ExtractionHookDryRunItem,
    ExtractionHookDryRunPlan,
    build_extraction_hook_dry_run_plan,
    serialize_extraction_hook_dry_run_plan,
)
from .extract_entities_dry_run import (
    ExtractEntitiesDryRunConfig,
    ExtractEntitiesDryRunReport,
    ExtractEntitiesDryRunSampleResult,
    arun_extract_entities_dry_run_from_payload,
    arun_native_extract_entities_dry_run,
    run_extract_entities_dry_run_from_payload,
    run_native_extract_entities_dry_run,
    serialize_extract_entities_dry_run_report,
    temporary_prompt_overrides,
)
from .ingestion_adapter import (
    build_dsl_aware_ingestion_payload,
    serialize_ingestion_payload,
)
from .kg_metadata_sidecar import (
    GraphInsertSidecarAlignmentReport,
    KgMetadataSidecarRecord,
    KgMetadataSidecarStore,
    SidecarCoverageIssue,
    SidecarCoverageReport,
    build_graph_insert_sidecar_records,
    build_metadata_sidecar_records,
    serialize_graph_insert_sidecar_alignment_report,
    serialize_sidecar_coverage_report,
    serialize_sidecar_record,
    validate_graph_insert_sidecar_alignment,
    validate_sidecar_coverage,
)
from .kg_metadata_strategy import KgMetadataStrategy, determine_metadata_strategy
from .kg_payload_mapper import build_dsl_kg_payload, serialize_dsl_kg_payload
from .kg_payload_types import (
    DslKgPayload,
    GraphWriteEligibility,
    KgChunk,
    KgEntity,
    KgPayloadIssue,
    KgRelationship,
)
try:
    from .kg_real_graph_smoke import (
        RealCustomKgSmokeConfig,
        RealGraphSmokeReport,
        build_minimal_real_smoke_custom_kg_input,
        build_minimal_real_smoke_payload,
        run_real_custom_kg_smoke,
        serialize_real_graph_smoke_report,
    )
except ModuleNotFoundError as exc:
    if exc.name != "numpy":
        raise

    RealCustomKgSmokeConfig = None  # type: ignore[assignment]
    RealGraphSmokeReport = None  # type: ignore[assignment]

    def _kg_real_graph_smoke_unavailable(*args, _missing_exc=exc, **kwargs):
        raise ModuleNotFoundError("kg_real_graph_smoke requires optional dependency numpy") from _missing_exc

    build_minimal_real_smoke_custom_kg_input = _kg_real_graph_smoke_unavailable
    build_minimal_real_smoke_payload = _kg_real_graph_smoke_unavailable
    run_real_custom_kg_smoke = _kg_real_graph_smoke_unavailable
    serialize_real_graph_smoke_report = _kg_real_graph_smoke_unavailable
from .kg_schema_policy import (
    ALLOWED_ENTITY_TYPES,
    ALLOWED_RELATION_TYPES,
    FORBIDDEN_RELATION_TYPES,
    RelationResolution,
    TypeResolution,
    feature_relation_type,
    is_allowed_relation_type,
    resolve_entity_type,
    resolve_relation_type,
)
from .kg_test_graph_write import (
    TestGraphWriteConfig,
    TestGraphWriteReport,
    arun_test_graph_write_dry_run,
    run_test_graph_write_dry_run,
    serialize_test_graph_write_report,
    to_lightrag_custom_kg_input,
)
from .generalization_audit import (
    GeneralizationAuditFinding,
    GeneralizationAuditReport,
    run_generalization_audit,
    serialize_generalization_audit_report,
)
from .live_smoke_eval import (
    GenericPromptImpactMetrics,
    LiveSmokeReport,
    LiveSmokeSample,
    LiveSmokeSampleMetric,
    arun_live_extraction_smoke,
    build_extraction_prompts,
    build_gleaning_prompt,
    build_live_smoke_samples,
    run_live_extraction_smoke,
    serialize_live_smoke_report,
)
from .live_llm_adapter import (
    LiveLlmResolution,
    resolve_live_llm_callable_from_env_or_lightrag,
    resolve_live_llm_status_from_env_or_lightrag,
)
from .ontology_loader import load_ontology
from .ontology_auto_resolver import (
    OntologyResolveResult,
    resolve_candidate_ontology,
)
from .payload_types import (
    DslAwareIngestionIssue,
    DslAwareIngestionPayload,
    ExtractionPayloadItem,
    MetadataPayloadItem,
    VectorPayloadItem,
)
from .payload_quality import (
    apply_payload_quality_metrics,
    build_integration_readiness,
    build_quality_gate,
    build_quality_metrics,
)
from .pipeline_mapping import (
    EvidenceMappingItem,
    ExtractionMappingItem,
    PipelineMappingIssue,
    PipelineMappingPlan,
    VectorStoreMappingItem,
    build_pipeline_mapping_plan,
    serialize_pipeline_mapping_plan,
)
from .pipeline_hook import (
    DslAwarePipelineDocumentReport,
    DslAwarePipelineHookConfig,
    DslAwarePipelineHookReport,
    ainsert_with_dsl_dry_run,
    insert_with_dsl_dry_run,
    resolve_dsl_path,
)
from .pilot_report_pack import (
    build_pilot_report_pack,
    evaluate_pilot_readiness,
    render_pilot_report_markdown,
    serialize_pilot_report_pack,
)
from .pilot_report_types import PilotReadiness, PilotReportPack
from .pilot_execution_pack import (
    PilotExecutionBuildResult,
    PilotExecutionPack,
    build_minimal_pilot_dsl_result_from_us_blocks,
    build_pilot_execution_pack_from_source,
    render_ba_se_review_checklist,
    render_pilot_execution_pack_markdown,
    render_pilot_feedback_form,
    render_pilot_summary_report,
    serialize_pilot_execution_pack,
    write_pilot_execution_files,
)
from .module_onboarding import render_module_onboarding_checklist
try:
    from .real_storage_write_dry_run import (
        RealStorageWriteDryRunConfig,
        RealStorageWriteDryRunReport,
        RealStorageWriteItemResult,
        arun_real_storage_write_dry_run,
        run_real_storage_write_dry_run,
        serialize_real_storage_write_dry_run_report,
    )
except ModuleNotFoundError as exc:
    if exc.name != "numpy":
        raise

    RealStorageWriteDryRunConfig = None  # type: ignore[assignment]
    RealStorageWriteDryRunReport = None  # type: ignore[assignment]
    RealStorageWriteItemResult = None  # type: ignore[assignment]

    def _real_storage_write_dry_run_unavailable(*args, _missing_exc=exc, **kwargs):
        raise ModuleNotFoundError("real_storage_write_dry_run requires optional dependency numpy") from _missing_exc

    arun_real_storage_write_dry_run = _real_storage_write_dry_run_unavailable
    run_real_storage_write_dry_run = _real_storage_write_dry_run_unavailable
    serialize_real_storage_write_dry_run_report = _real_storage_write_dry_run_unavailable
from .prompt_selector import (
    PromptSelectionResult,
    PromptSelectorConfig,
    select_continue_prompt,
    select_extraction_prompts,
)
from .prompt_context_builder import build_prompt_context
from .source_text_unit_builder import (
    build_source_text_units,
    detect_us_blocks,
    stable_hash,
)
from .shadow_storage import ShadowKVStorage, ShadowVectorStorage
from .storage_mapping import (
    ChunksVdbShadowWriteItem,
    LightRagChunkCandidate,
    TextChunksShadowWriteItem,
    build_lightrag_chunk_candidates,
)
from .storage_write_dry_run import (
    ShadowStorageWriteIssue,
    ShadowStorageWriteReport,
    StorageWriteDryRunConfig,
    build_shadow_storage_write_plan,
    run_shadow_storage_write,
    serialize_shadow_storage_write_report,
)

__all__ = [
    "DslAwareChunk",
    "DslAwareChunkBuildIssue",
    "DslAwareChunkBuildResult",
    "CandidateEntity",
    "CandidateExtractionIssue",
    "CandidateExtractionReport",
    "CandidateExtractionWriteConfig",
    "CandidateReviewDecision",
    "CandidateReviewPolicy",
    "CandidateReviewReport",
    "CandidateRelation",
    "CandidateStore",
    "BusinessObjectTypeRule",
    "ConfigRegistry",
    "DEFAULT_CONFIG_REGISTRY",
    "DslAwareIngestionIssue",
    "DslAwareIngestionPayload",
    "DslAwarePipelineDocumentReport",
    "DslAwarePipelineHookConfig",
    "DslAwarePipelineHookReport",
    "DslCompiledResult",
    "DslKgPayload",
    "DslValidationError",
    "ChunksVdbShadowWriteItem",
    "ExtractedEntity",
    "ExtractedRelation",
    "ExtractionComparisonMetrics",
    "ExtractEntitiesDryRunConfig",
    "ExtractEntitiesDryRunReport",
    "ExtractEntitiesDryRunSampleResult",
    "ExtractionEvaluationReport",
    "ExtractionInputPair",
    "ExtractionPayloadItem",
    "ExtractionRunResult",
    "GenericPromptImpactMetrics",
    "GeneralizationAuditFinding",
    "GeneralizationAuditReport",
    "GraphInsertSidecarAlignmentReport",
    "GraphWriteEligibility",
    "EntityAliasRule",
    "KgChunk",
    "KgEntity",
    "KgMetadataSidecarRecord",
    "KgMetadataSidecarStore",
    "KgMetadataStrategy",
    "KgPayloadIssue",
    "KgRelationship",
    "LiveSmokeReport",
    "LiveSmokeSample",
    "LiveSmokeSampleMetric",
    "LiveLlmResolution",
    "EvidenceMappingItem",
    "ExtractionMappingItem",
    "ExtractionHookDryRunItem",
    "ExtractionHookDryRunPlan",
    "MetadataPayloadItem",
    "OntologyConfig",
    "OntologyResolveResult",
    "PipelineMappingIssue",
    "PipelineMappingPlan",
    "PilotReadiness",
    "PilotExecutionBuildResult",
    "PilotExecutionPack",
    "PilotReportPack",
    "PromptSelectionResult",
    "PromptSelectorConfig",
    "RealStorageWriteDryRunConfig",
    "RealStorageWriteDryRunReport",
    "RealStorageWriteItemResult",
    "RealCustomKgSmokeConfig",
    "RealGraphSmokeReport",
    "RelationMappingRule",
    "RelationResolution",
    "LightRagChunkCandidate",
    "SourceTextUnit",
    "ShadowKVStorage",
    "ShadowStorageWriteIssue",
    "ShadowStorageWriteReport",
    "ShadowVectorStorage",
    "SidecarCoverageIssue",
    "SidecarCoverageReport",
    "StorageWriteDryRunConfig",
    "TestGraphWriteConfig",
    "TestGraphWriteReport",
    "TextChunksShadowWriteItem",
    "TypeResolution",
    "UsBlock",
    "ValidationIssue",
    "ValidationResult",
    "VectorPayloadItem",
    "VectorStoreMappingItem",
    "ALLOWED_ENTITY_TYPES",
    "ALLOWED_RELATION_TYPES",
    "FORBIDDEN_RELATION_TYPES",
    "apply_payload_quality_metrics",
    "arun_extract_entities_dry_run_from_payload",
    "arun_live_extraction_smoke",
    "arun_native_extract_entities_dry_run",
    "arun_real_storage_write_dry_run",
    "arun_test_graph_write_dry_run",
    "ainsert_with_dsl_dry_run",
    "build_extraction_prompts",
    "build_candidates_from_extract_result",
    "build_candidate_review_decisions",
    "build_candidate_review_report",
    "build_candidate_review_report_from_candidate_extraction_report",
    "build_pilot_report_pack",
    "build_minimal_pilot_dsl_result_from_us_blocks",
    "build_pilot_execution_pack_from_source",
    "build_dsl_aware_chunks",
    "build_dsl_aware_ingestion_payload",
    "build_dsl_kg_payload",
    "build_extraction_hook_dry_run_plan",
    "build_gleaning_prompt",
    "build_integration_readiness",
    "build_live_smoke_samples",
    "build_graph_insert_sidecar_records",
    "build_metadata_sidecar_records",
    "build_minimal_real_smoke_custom_kg_input",
    "build_minimal_real_smoke_payload",
    "build_prompt_context",
    "build_pipeline_mapping_plan",
    "build_quality_gate",
    "build_quality_metrics",
    "build_source_text_units",
    "build_lightrag_chunk_candidates",
    "build_shadow_storage_write_plan",
    "compare_extraction_results",
    "detect_us_blocks",
    "detect_term_review_required",
    "detect_version_review_required",
    "default_config_registry",
    "deterministic_fake_extraction_output",
    "determine_metadata_strategy",
    "evaluate_pilot_readiness",
    "feature_relation_type",
    "load_dsl_compiled",
    "load_ontology",
    "live_smoke_enabled",
    "parse_tuple_extraction_output",
    "run_deterministic_extraction_pair",
    "run_candidate_extraction_write_dry_run",
    "run_extract_entities_dry_run_from_payload",
    "run_lightrag_extract_entities_if_available",
    "run_native_extract_entities_dry_run",
    "run_offline_extraction_evaluation",
    "run_real_custom_kg_smoke",
    "run_real_storage_write_dry_run",
    "run_test_graph_write_dry_run",
    "select_extraction_eval_samples",
    "insert_with_dsl_dry_run",
    "is_allowed_relation_type",
    "resolve_dsl_path",
    "resolve_candidate_ontology",
    "resolve_entity_type",
    "resolve_relation_type",
    "resolve_live_llm_callable_from_env_or_lightrag",
    "resolve_live_llm_status_from_env_or_lightrag",
    "run_live_extraction_smoke",
    "run_generalization_audit",
    "run_shadow_storage_write",
    "render_pilot_report_markdown",
    "render_ba_se_review_checklist",
    "render_module_onboarding_checklist",
    "render_pilot_execution_pack_markdown",
    "render_pilot_feedback_form",
    "render_pilot_summary_report",
    "serialize_live_smoke_report",
    "serialize_candidate_extraction_report",
    "serialize_candidate_review_report",
    "serialize_generalization_audit_report",
    "serialize_ingestion_payload",
    "serialize_dsl_kg_payload",
    "serialize_extraction_hook_dry_run_plan",
    "serialize_shadow_storage_write_report",
    "serialize_extract_entities_dry_run_report",
    "serialize_pipeline_mapping_plan",
    "serialize_pilot_report_pack",
    "serialize_pilot_execution_pack",
    "serialize_graph_insert_sidecar_alignment_report",
    "serialize_real_graph_smoke_report",
    "serialize_real_storage_write_dry_run_report",
    "serialize_sidecar_coverage_report",
    "serialize_sidecar_record",
    "serialize_test_graph_write_report",
    "select_continue_prompt",
    "select_extraction_prompts",
    "stable_hash",
    "temporary_prompt_overrides",
    "to_lightrag_custom_kg_input",
    "validate_candidate_entity",
    "validate_candidate_relation",
    "validate_graph_insert_sidecar_alignment",
    "validate_sidecar_coverage",
    "write_pilot_execution_files",
]
