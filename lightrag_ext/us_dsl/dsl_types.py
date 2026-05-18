from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class OntologyConfig:
    domains: set[str]
    entity_types: dict[str, set[str]]
    relation_types: dict[str, set[str]]
    domain_names: dict[str, str] = field(default_factory=dict)

    def allowed_entity_types(self, domain_code: str) -> set[str]:
        return set(self.entity_types.get("Common", set())) | set(
            self.entity_types.get(domain_code, set())
        )

    def allowed_relation_types(self, domain_code: str) -> set[str]:
        return set(self.relation_types.get("Common", set())) | set(
            self.relation_types.get(domain_code, set())
        )

    def is_valid_domain(self, domain_code: str) -> bool:
        return domain_code in self.domains

    def is_valid_entity_type(self, domain_code: str, entity_type: str) -> bool:
        return entity_type in self.allowed_entity_types(domain_code)

    def is_valid_relation_type(self, domain_code: str, relation_type: str) -> bool:
        return relation_type in self.allowed_relation_types(domain_code)


@dataclass(frozen=True)
class ValidationIssue:
    severity: str
    code: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.severity} {self.code} at {self.path}: {self.message}"


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)

    @property
    def errors(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]

    @property
    def warnings(self) -> list[ValidationIssue]:
        return [issue for issue in self.issues if issue.severity == "WARN"]


@dataclass
class DslCompiledResult:
    raw: dict[str, Any]
    dsl_version: str
    active_domains: list[str]
    feature_catalog_index: list[dict[str, Any]]
    source_vectorization_plan: list[dict[str, Any]]
    gleaning_input_blocks: list[dict[str, Any]]
    issues: list[ValidationIssue] = field(default_factory=list)


@dataclass(frozen=True)
class UsBlock:
    us_id: str | None
    title: str
    start: int
    end: int
    line_start: int
    line_end: int
    text: str


@dataclass(frozen=True)
class SourceTextUnit:
    text_unit_id: str
    document_id: str
    us_id: str | None
    feature_key: str | None
    domain_code: str | None
    section_type: str
    chunk_index: int
    chunk_text: str
    source_span: dict[str, int]
    text_hash: str
    file_path: str | None = None


@dataclass
class DslAwareChunk:
    chunk_id: str
    source_text: str
    vector_content: str
    extraction_content: str
    dsl_context: dict[str, Any]
    evidence: dict[str, Any]
    metadata: dict[str, Any]


@dataclass(frozen=True)
class DslAwareChunkBuildIssue:
    severity: str
    code: str
    message: str
    text_unit_id: str | None = None
    feature_key: str | None = None


@dataclass
class DslAwareChunkBuildResult:
    chunks: list[DslAwareChunk]
    issues: list[DslAwareChunkBuildIssue] = field(default_factory=list)


class DslValidationError(ValueError):
    def __init__(self, path: str | Path, issues: list[ValidationIssue]) -> None:
        self.path = str(path)
        self.issues = issues
        error_lines = [
            f"{self.path}: {issue.code} at {issue.path}: {issue.message}"
            for issue in issues
            if issue.severity == "ERROR"
        ]
        super().__init__("\n".join(error_lines) or f"{self.path}: DSL validation failed")
