from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any, Literal

RequirementScenario = Literal["ZERO_TO_ONE", "ONE_TO_MANY", "ONE_TO_ONE_X"]
ScenarioClassificationStatus = Literal["CONFIDENT", "AMBIGUOUS", "MIXED", "INSUFFICIENT_EVIDENCE", "MANUAL_OVERRIDE"]
SkillCapabilityStatus = Literal["AVAILABLE", "ADAPTER_AVAILABLE", "PLANNED_NOT_IMPLEMENTED", "BLOCKED_DEPENDENCY", "DISABLED"]
SkillExecutionMode = Literal["PLAN_ONLY", "DRY_RUN", "DETERMINISTIC_EXECUTION", "FUTURE_LLM_EXECUTION", "FUTURE_EXTERNAL_AGENT"]
HarnessState = Literal[
    "CREATED",
    "PROFILED",
    "ROUTED",
    "WAITING_FOR_CLARIFICATION",
    "CONTEXT_READY",
    "PLAN_READY",
    "EXECUTING",
    "CHECKPOINT_BLOCKED",
    "BLOCKED_BY_MISSING_CAPABILITY",
    "BLOCKED_BY_INSUFFICIENT_EVIDENCE",
    "DRY_RUN_COMPLETED",
    "FAILED",
    "CANCELLED",
]
CheckpointType = Literal[
    "EVIDENCE_CHECK",
    "VERSION_CHECK",
    "IMPACT_BREADTH_CHECK",
    "CAPABILITY_CHECK",
    "CLARIFICATION_CHECK",
    "HUMAN_DECISION_REQUIRED",
    "FINAL_OUTPUT_CHECK",
]


@dataclass(frozen=True)
class RequirementInput:
    requirement_id: str
    requirement_text: str
    module_code: str | None = None
    explicit_scenario_override: RequirementScenario | None = None
    source_document_refs: list[str] = field(default_factory=list)
    requested_outputs: list[str] = field(default_factory=list)
    available_code_context: bool = False
    available_design_context: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RequirementScenarioProfile:
    requirement_id: str
    primary_change_targets: list[str] = field(default_factory=list)
    existing_feature_coverage: float = 0.0
    existing_semantic_object_coverage: float = 0.0
    existing_relation_coverage: float = 0.0
    existing_design_evidence_coverage: float = 0.0
    existing_code_asset_coverage: float = 0.0
    novelty_score: float = 0.0
    new_business_object_ratio: float = 0.0
    affected_feature_count: int = 0
    affected_domain_count: int = 0
    direct_impact_count: int = 0
    indirect_impact_count: int = 0
    graph_path_count: int = 0
    version_issue_count: int = 0
    term_issue_count: int = 0
    type_issue_count: int = 0
    local_change_score: float = 0.0
    cross_system_signal_count: int = 0
    evidence_sufficiency_score: float = 0.0
    profile_confidence: float = 0.0
    signals: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ScenarioRouteDecision:
    requirement_id: str
    selected_scenario: RequirementScenario | None
    classification_status: ScenarioClassificationStatus
    confidence: float
    alternative_scenarios: list[RequirementScenario] = field(default_factory=list)
    profile: RequirementScenarioProfile | None = None
    reason_codes: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    clarification_questions: list[dict[str, str]] = field(default_factory=list)
    manual_override_used: bool = False
    router_policy_version: str = "27A-router-v1"


@dataclass(frozen=True)
class SkillContract:
    skill_id: str
    name: str
    description: str
    capability_status: SkillCapabilityStatus
    supported_scenarios: list[RequirementScenario]
    required_inputs: list[str]
    optional_inputs: list[str]
    output_schema: dict[str, Any]
    preconditions: list[str]
    postconditions: list[str]
    failure_modes: list[str]
    checkpoint_after: bool
    side_effect_policy: str
    adapter_target: str | None
    version: str = "27A-skill-v1"


@dataclass(frozen=True)
class CapabilityGap:
    gap_id: str
    skill_id: str
    gap_type: str
    severity: str
    required_for_completion: bool
    missing_dependency: str
    available_fallback: str | None
    manual_action: str
    blocks_plan: bool


@dataclass(frozen=True)
class SkillPlanNode:
    node_id: str
    skill_id: str
    dependencies: list[str]
    required: bool
    execution_mode: SkillExecutionMode
    capability_status: SkillCapabilityStatus
    input_bindings: dict[str, str]
    expected_output_schema: dict[str, Any]
    checkpoint_after: bool
    skip_condition: str | None = None
    block_condition: str | None = None
    fallback_skill_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HarnessExecutionPlan:
    plan_id: str
    requirement_id: str
    scenario_route: ScenarioRouteDecision
    nodes: list[SkillPlanNode]
    edges: list[tuple[str, str]]
    topological_order: list[str]
    required_context: list[str]
    capability_gaps: list[CapabilityGap]
    blocking_gaps: list[CapabilityGap]
    optional_gaps: list[CapabilityGap]
    manual_checkpoints: list[str]
    estimated_steps: int
    plan_hash: str
    policy_version: str = "27A-plan-v1"


@dataclass(frozen=True)
class HarnessContext:
    requirement_input: RequirementInput
    scenario_profile: RequirementScenarioProfile
    scenario_route: ScenarioRouteDecision
    trusted_context_pack: dict[str, Any]
    version_context: dict[str, Any]
    impact_context: dict[str, Any]
    term_context: dict[str, Any]
    type_context: dict[str, Any]
    available_code_context: dict[str, Any]
    source_evidence: list[dict[str, Any]]
    issues_and_warnings: list[dict[str, Any]]
    assumptions: list[str]
    open_questions: list[dict[str, str]]
    context_budget: dict[str, int]


@dataclass(frozen=True)
class CheckpointResult:
    checkpoint_type: CheckpointType
    passed: bool
    blocks_downstream: bool
    reason_codes: list[str] = field(default_factory=list)
    required_clarifications: list[dict[str, str]] = field(default_factory=list)


@dataclass(frozen=True)
class StateTransition:
    from_state: HarnessState
    to_state: HarnessState
    event: str
    reason: str
    timestamp: str
    actor: str = "SYSTEM"


@dataclass(frozen=True)
class SkillExecutionTrace:
    node_id: str
    skill_id: str
    status: str
    capability_status: SkillCapabilityStatus
    execution_mode: SkillExecutionMode
    reason: str
    output: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class HarnessRunResult:
    requirement_id: str
    final_state: HarnessState
    plan: HarnessExecutionPlan | None
    context: HarnessContext | None
    checkpoint_results: list[CheckpointResult]
    execution_trace: list[SkillExecutionTrace]
    state_transitions: list[StateTransition]
    capability_gaps: list[CapabilityGap]
    final_us_generated: bool = False
    final_solution_document_generated: bool = False


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
