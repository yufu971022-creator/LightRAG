from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any

from .candidate_extraction import CandidateExtractionReport
from .candidate_review_report import (
    DECISION_AUTO_ACCEPT,
    DECISION_AUTO_RESOLVE,
    DECISION_BLOCKED,
    DECISION_INFO_ONLY,
    DECISION_REVIEW_REQUIRED,
    CandidateReviewReport,
)
from .candidate_types import (
    CandidateEntity,
    CandidateRelation,
    VALIDATION_MISSING_EVIDENCE,
    VALIDATION_VALID,
)
from .kg_payload_types import (
    DslKgPayload,
    GraphWriteEligibility,
    KgChunk,
    KgEntity,
    KgPayloadIssue,
    KgRelationship,
)
from .kg_schema_policy import (
    ALLOWED_ENTITY_TYPES,
    FORBIDDEN_RELATION_TYPES,
    feature_relation_type,
    is_allowed_relation_type,
    resolve_entity_type,
    resolve_relation_type,
)
from .payload_types import DslAwareIngestionPayload, MetadataPayloadItem
from .pilot_report_types import PilotReportPack
from .version_relation_builder import augment_kg_payload_with_version_relations


STRUCTURAL_STATUS = "SourceMapped"
EVIDENCE_STATUS = "EvidenceOnly"
UNREVIEWED_DECISION = "UNREVIEWED"
FORMAL_GRAPH_DISABLED_ISSUE = KgPayloadIssue(
    severity="WARN",
    code="FORMAL_GRAPH_DISABLED",
    message="formal_graph target is disabled for Block 17 dry-run mapping.",
)


def build_dsl_kg_payload(
    *,
    ingestion_payload: DslAwareIngestionPayload,
    candidate_extraction_report: CandidateExtractionReport | None = None,
    candidate_review_report: CandidateReviewReport | None = None,
    pilot_report_pack: PilotReportPack | None = None,
    include_review_required: bool = False,
    include_info_only: bool = False,
    include_version_relations: bool = True,
    target: str = "test_graph",
) -> DslKgPayload:
    if target != "test_graph":
        return _disabled_payload(target, ingestion_payload)

    builder = _PayloadBuilder(
        ingestion_payload=ingestion_payload,
        candidate_extraction_report=candidate_extraction_report,
        candidate_review_report=candidate_review_report,
        pilot_report_pack=pilot_report_pack,
        include_review_required=include_review_required,
        include_info_only=include_info_only,
        target=target,
    )
    builder.build_chunks()
    builder.build_source_nodes()
    builder.build_candidate_nodes_and_edges()
    payload = builder.to_payload()
    if include_version_relations:
        return augment_kg_payload_with_version_relations(
            payload,
            candidate_extraction_report=candidate_extraction_report,
            candidate_review_report=candidate_review_report,
            ingestion_payload=ingestion_payload,
        )
    return payload


def serialize_dsl_kg_payload(payload: DslKgPayload) -> dict[str, Any]:
    return {
        "chunks": [_serialize_chunk(item) for item in payload.chunks],
        "entities": [_serialize_entity(item) for item in payload.entities],
        "relationships": [_serialize_relationship(item) for item in payload.relationships],
        "entityVdbPayload": payload.entity_vdb_payload,
        "relationshipVdbPayload": payload.relationship_vdb_payload,
        "evidenceMapping": payload.evidence_mapping,
        "versionMapping": payload.version_mapping,
        "metadata": _jsonable(payload.metadata),
        "issues": [_jsonable(asdict(issue)) for issue in payload.issues],
        "summary": _jsonable(payload.summary),
    }


class _PayloadBuilder:
    def __init__(
        self,
        *,
        ingestion_payload: DslAwareIngestionPayload,
        candidate_extraction_report: CandidateExtractionReport | None,
        candidate_review_report: CandidateReviewReport | None,
        pilot_report_pack: PilotReportPack | None,
        include_review_required: bool,
        include_info_only: bool,
        target: str,
    ) -> None:
        self.ingestion_payload = ingestion_payload
        self.candidate_extraction_report = candidate_extraction_report
        self.candidate_review_report = candidate_review_report
        self.pilot_report_pack = pilot_report_pack
        self.include_review_required = include_review_required
        self.include_info_only = include_info_only
        self.target = target
        self.contexts = _contexts_by_text_unit(ingestion_payload)
        self.review_by_candidate_id = _review_decisions(candidate_review_report)
        self.chunks: list[KgChunk] = []
        self.entities_by_name: dict[str, KgEntity] = {}
        self.relationships_by_key: dict[tuple[str, str, str, str], KgRelationship] = {}
        self.issues: list[KgPayloadIssue] = []
        self.evidence_mapping: dict[str, Any] = {}
        self.version_mapping: dict[str, Any] = {}
        self.duplicate_entity_count = 0
        self.duplicate_relationship_count = 0
        self.source_document_count = 0
        self.user_story_count = 0
        self.feature_count = 0
        self.evidence_span_count = 0
        self.test_graph_eligible_count = 0
        self.review_required_excluded_count = 0
        self.info_only_excluded_count = 0
        self.missing_evidence_excluded_count = 0
        self.invalid_relation_excluded_count = 0

    def build_chunks(self) -> None:
        for item in self.ingestion_payload.vector_payload:
            metadata = {
                **dict(item.metadata),
                "knowledgeStatus": STRUCTURAL_STATUS,
                "graphWriteCalled": False,
                "formalGraphEnabled": False,
            }
            self.chunks.append(
                KgChunk(
                    content=item.content,
                    source_id=item.chunk_id,
                    file_path=_string_or_none(item.metadata.get("filePath")),
                    metadata=metadata,
                )
            )

    def build_source_nodes(self) -> None:
        first_context = self._first_context()
        first_source_id = _source_id(first_context) or self.ingestion_payload.document_id
        document_name = f"SourceDocument:{self.ingestion_payload.document_id}"
        self._add_entity(
            KgEntity(
                entity_name=document_name,
                entity_type="SourceDocument",
                description=f"Source document {self.ingestion_payload.document_id}",
                source_id=first_source_id,
                metadata=self._metadata_from_context(
                    first_context,
                    knowledge_status=STRUCTURAL_STATUS,
                    validation_status="STRUCTURAL",
                    review_decision="STRUCTURAL",
                    extra={"documentNode": True},
                ),
            )
        )
        self.source_document_count = 1 if self.ingestion_payload.document_id else 0

        user_story_contexts = _first_context_by(self.contexts.values(), "sourceUsId")
        for source_us_id, context in user_story_contexts.items():
            user_story_name = f"UserStory:{source_us_id}"
            self._add_entity(
                KgEntity(
                    entity_name=user_story_name,
                    entity_type="UserStory",
                    description=f"User story {source_us_id}",
                    source_id=_source_id(context) or first_source_id,
                    metadata=self._metadata_from_context(
                        context,
                        knowledge_status=STRUCTURAL_STATUS,
                        validation_status="STRUCTURAL",
                        review_decision="STRUCTURAL",
                    ),
                )
            )
            self._add_relationship(
                self._relationship_from_context(
                    src_id=document_name,
                    tgt_id=user_story_name,
                    relation_type="HasUserStory",
                    description=f"{document_name} has user story {source_us_id}.",
                    context=context,
                    knowledge_status=STRUCTURAL_STATUS,
                    validation_status="STRUCTURAL",
                    review_decision="STRUCTURAL",
                )
            )
        self.user_story_count = len(user_story_contexts)

        feature_contexts = _first_context_by(self.contexts.values(), "featureKey")
        for feature_key, context in feature_contexts.items():
            self._add_entity(
                KgEntity(
                    entity_name=feature_key,
                    entity_type="FeatureCatalog",
                    description=f"Feature catalog {feature_key}",
                    source_id=_source_id(context) or first_source_id,
                    metadata=self._metadata_from_context(
                        context,
                        knowledge_status=STRUCTURAL_STATUS,
                        validation_status="STRUCTURAL",
                        review_decision="STRUCTURAL",
                    ),
                )
            )
            source_us_id = context.get("sourceUsId")
            if source_us_id:
                self._add_relationship(
                    self._relationship_from_context(
                        src_id=f"UserStory:{source_us_id}",
                        tgt_id=feature_key,
                        relation_type="HasFeatureCatalog",
                        description=f"User story {source_us_id} maps to {feature_key}.",
                        context=context,
                        knowledge_status=STRUCTURAL_STATUS,
                        validation_status="STRUCTURAL",
                        review_decision="STRUCTURAL",
                    )
                )
        self.feature_count = len(feature_contexts)

        for context in self.contexts.values():
            text_unit_id = _string_or_none(context.get("textUnitId"))
            if not text_unit_id:
                continue
            evidence_name = _evidence_name(text_unit_id)
            self._add_entity(
                KgEntity(
                    entity_name=evidence_name,
                    entity_type="EvidenceSpan",
                    description=f"Evidence span {text_unit_id}",
                    source_id=text_unit_id,
                    metadata=self._metadata_from_context(
                        context,
                        knowledge_status=EVIDENCE_STATUS,
                        validation_status="EVIDENCE",
                        review_decision="EVIDENCE",
                        extra={"evidenceText": _preview(context.get("evidenceText"), 240)},
                    ),
                )
            )
        self.evidence_span_count = len(self.contexts)

    def build_candidate_nodes_and_edges(self) -> None:
        for candidate in self._candidate_entities():
            self._handle_candidate_entity(candidate)
        for relation in self._candidate_relations():
            self._handle_candidate_relation(relation)

    def to_payload(self) -> DslKgPayload:
        entities = list(self.entities_by_name.values())
        relationships = list(self.relationships_by_key.values())
        return DslKgPayload(
            chunks=self.chunks,
            entities=entities,
            relationships=relationships,
            metadata={
                "target": self.target,
                "documentId": self.ingestion_payload.document_id,
                "dslVersion": self.ingestion_payload.dsl_version,
                "lightRagCustomKgMetadataPassThrough": False,
                "graphWriteCalled": False,
                "formalGraphEnabled": False,
            },
            issues=self.issues,
            summary=self._summary(entities, relationships),
            entity_vdb_payload=_entity_vdb_payload(entities),
            relationship_vdb_payload=_relationship_vdb_payload(relationships),
            evidence_mapping=self.evidence_mapping,
            version_mapping=self.version_mapping,
        )

    def _handle_candidate_entity(self, candidate: CandidateEntity) -> None:
        decision = self.review_by_candidate_id.get(candidate.candidate_id, {})
        review_decision = str(decision.get("decision") or UNREVIEWED_DECISION)
        eligibility = self._candidate_eligibility(candidate, review_decision)
        if not eligibility.eligible_for_test_graph:
            self._record_candidate_exclusion(candidate, eligibility.reason)
            if self.include_review_required and review_decision == DECISION_REVIEW_REQUIRED:
                self._add_review_item(candidate, review_decision, eligibility.reason)
            return

        type_resolution = resolve_entity_type(candidate.entity_type, section_type=candidate.section_type)
        entity_type = type_resolution.resolved
        if entity_type not in ALLOWED_ENTITY_TYPES:
            entity_type = "CandidateEntity"
        context = self._context_for_candidate(candidate)
        metadata = self._metadata_from_candidate(
            candidate,
            context,
            review_decision=review_decision,
            validation_status=candidate.validation_status,
            extra={
                "candidateType": "entity",
                "candidateId": candidate.candidate_id,
                "originalEntityType": candidate.entity_type,
                "resolvedEntityType": entity_type,
                "entityTypeResolution": type_resolution.reason_code,
                "confidenceScore": candidate.confidence_score,
            },
        )
        entity = KgEntity(
            entity_name=candidate.entity_name,
            entity_type=entity_type,
            description=_compact_description(candidate.description, candidate.evidence_text),
            source_id=candidate.source_text_unit_id or _source_id(context) or "UNKNOWN",
            metadata=metadata,
        )
        self._add_entity(entity)
        self.test_graph_eligible_count += 1
        self._add_feature_edge(candidate.entity_name, entity_type, context, metadata)
        self._add_evidence_edge(candidate.entity_name, candidate, context, metadata)
        self._add_version_edges(candidate.entity_name, candidate, context, metadata)
        self._add_term_edges(candidate, context, metadata)

    def _handle_candidate_relation(self, candidate: CandidateRelation) -> None:
        decision = self.review_by_candidate_id.get(candidate.candidate_id, {})
        review_decision = str(decision.get("decision") or UNREVIEWED_DECISION)
        context = self._context_for_candidate(candidate)
        target_entity = self.entities_by_name.get(candidate.target_entity_name)
        relation_resolution = resolve_relation_type(
            candidate.relation_type,
            candidate.relationship_keywords,
            allowed_relation_types=_string_list(candidate.raw.get("allowedRelationTypes")),
            section_type=candidate.section_type,
            domain_code=candidate.domain_code,
            source_entity_name=candidate.source_entity_name,
            target_entity_type=target_entity.entity_type if target_entity else None,
        )
        relation_valid = (
            relation_resolution.safe_to_use
            and is_allowed_relation_type(relation_resolution.resolved)
            and candidate.source_entity_name
            and candidate.target_entity_name
            and (
                candidate.validation_status == VALIDATION_VALID
                or review_decision == DECISION_AUTO_RESOLVE
            )
        )
        eligibility = self._candidate_eligibility(
            candidate,
            review_decision,
            invalid_relation=not relation_valid,
        )
        if not eligibility.eligible_for_test_graph:
            self._record_candidate_exclusion(candidate, eligibility.reason)
            if self.include_review_required and review_decision == DECISION_REVIEW_REQUIRED:
                self._add_review_item(candidate, review_decision, eligibility.reason)
            return

        relation_type = relation_resolution.resolved
        if relation_type is None:
            self.invalid_relation_excluded_count += 1
            self.issues.append(
                KgPayloadIssue(
                    severity="WARN",
                    code="RELATION_TYPE_UNRESOLVED",
                    message="Candidate relation has no resolved relation type.",
                    candidate_id=candidate.candidate_id,
                    source_id=candidate.source_text_unit_id,
                )
            )
            return

        metadata = self._metadata_from_candidate(
            candidate,
            context,
            review_decision=review_decision,
            validation_status=candidate.validation_status,
            extra={
                "candidateType": "relation",
                "candidateId": candidate.candidate_id,
                "relationType": relation_type,
                "originalRelationType": candidate.relation_type,
                "relationshipKeywords": candidate.relationship_keywords,
                "relationTypeResolution": relation_resolution.reason_code,
                "forbiddenRelationResolved": relation_resolution.forbidden_original,
                "confidenceScore": candidate.confidence_score,
            },
        )
        relationship = KgRelationship(
            src_id=candidate.source_entity_name,
            tgt_id=candidate.target_entity_name,
            description=_compact_description(candidate.description, candidate.evidence_text),
            keywords=relation_type,
            source_id=candidate.source_text_unit_id or _source_id(context) or "UNKNOWN",
            weight=max(candidate.confidence_score, 0.1),
            metadata=metadata,
        )
        self._add_relationship(relationship)
        self.test_graph_eligible_count += 1
        self._map_evidence(_relationship_evidence_key(relationship), candidate, context)

    def _candidate_eligibility(
        self,
        candidate: CandidateEntity | CandidateRelation,
        review_decision: str,
        *,
        invalid_relation: bool = False,
    ) -> GraphWriteEligibility:
        if candidate.knowledge_status == "Confirmed":
            self.issues.append(
                KgPayloadIssue(
                    severity="ERROR",
                    code="CONFIRMED_STATUS_NOT_ALLOWED",
                    message="Confirmed candidates are not allowed in Block 17 payload.",
                    candidate_id=candidate.candidate_id,
                    source_id=candidate.source_text_unit_id,
                )
            )
            return GraphWriteEligibility(False, False, "CONFIRMED_NOT_ALLOWED")
        if not _has_evidence(candidate) or candidate.validation_status == VALIDATION_MISSING_EVIDENCE:
            return GraphWriteEligibility(False, False, "MISSING_EVIDENCE")
        if invalid_relation:
            return GraphWriteEligibility(False, False, "INVALID_RELATION_TYPE")
        if review_decision == DECISION_AUTO_ACCEPT:
            return GraphWriteEligibility(True, False, "AUTO_ACCEPT_FOR_REPORT")
        if review_decision == DECISION_AUTO_RESOLVE:
            return GraphWriteEligibility(True, False, "AUTO_RESOLVE")
        if review_decision == DECISION_REVIEW_REQUIRED:
            if self.include_review_required:
                return GraphWriteEligibility(True, False, "REVIEW_REQUIRED_INCLUDED")
            return GraphWriteEligibility(False, False, "REVIEW_REQUIRED")
        if review_decision == DECISION_INFO_ONLY:
            if self.include_info_only:
                return GraphWriteEligibility(True, False, "INFO_ONLY_INCLUDED")
            return GraphWriteEligibility(False, False, "INFO_ONLY")
        if review_decision == DECISION_BLOCKED:
            return GraphWriteEligibility(False, False, "BLOCKED")
        return GraphWriteEligibility(False, False, "UNREVIEWED")

    def _record_candidate_exclusion(
        self,
        candidate: CandidateEntity | CandidateRelation,
        reason: str,
    ) -> None:
        if reason == "MISSING_EVIDENCE":
            self.missing_evidence_excluded_count += 1
        elif reason == "INVALID_RELATION_TYPE":
            self.invalid_relation_excluded_count += 1
        elif reason == "REVIEW_REQUIRED":
            self.review_required_excluded_count += 1
        elif reason == "INFO_ONLY":
            self.info_only_excluded_count += 1
        self.issues.append(
            KgPayloadIssue(
                severity="INFO",
                code=f"CANDIDATE_EXCLUDED_{reason}",
                message=f"Candidate excluded from graph payload: {reason}.",
                candidate_id=candidate.candidate_id,
                source_id=candidate.source_text_unit_id,
            )
        )

    def _add_feature_edge(
        self,
        entity_name: str,
        entity_type: str,
        context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        feature_key = _string_or_none(context.get("featureKey"))
        if not feature_key:
            return
        relation_type = feature_relation_type(entity_type)
        if relation_type == "ReviewRequiredFor":
            return
        src_id = entity_name if relation_type == "BelongsToFeature" else feature_key
        tgt_id = feature_key if relation_type == "BelongsToFeature" else entity_name
        self._add_relationship(
            self._relationship_from_context(
                src_id=src_id,
                tgt_id=tgt_id,
                relation_type=relation_type,
                description=f"{feature_key} maps to {entity_name}.",
                context=context,
                knowledge_status=str(metadata.get("knowledgeStatus") or "Candidate"),
                validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
            )
        )

    def _add_evidence_edge(
        self,
        entity_name: str,
        candidate: CandidateEntity,
        context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        text_unit_id = candidate.source_text_unit_id or _string_or_none(context.get("textUnitId"))
        if not text_unit_id:
            return
        evidence_node = _evidence_name(text_unit_id)
        self._add_relationship(
            self._relationship_from_context(
                src_id=entity_name,
                tgt_id=evidence_node,
                relation_type="SupportedByEvidence",
                description=f"{entity_name} is supported by {evidence_node}.",
                context=context,
                knowledge_status=str(metadata.get("knowledgeStatus") or "Candidate"),
                validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
            )
        )
        self._map_evidence(entity_name, candidate, context)

    def _add_version_edges(
        self,
        entity_name: str,
        candidate: CandidateEntity,
        context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        rule_version = _first_raw_value(candidate.raw, "ruleVersion", "version", "versionId")
        if rule_version is None:
            return
        version_name = _rule_version_name(rule_version)
        self._add_entity(
            KgEntity(
                entity_name=version_name,
                entity_type="RuleVersion",
                description=f"Rule version {rule_version}",
                source_id=candidate.source_text_unit_id or _source_id(context) or "UNKNOWN",
                metadata={
                    **self._metadata_from_candidate(
                        candidate,
                        context,
                        review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
                        validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                    ),
                    "ruleVersion": rule_version,
                    "versionStatus": _first_raw_value(candidate.raw, "versionStatus"),
                    "latestFlag": _first_raw_value(candidate.raw, "latestFlag"),
                },
            )
        )
        self._add_relationship(
            self._relationship_from_context(
                src_id=entity_name,
                tgt_id=version_name,
                relation_type="HasVersion",
                description=f"{entity_name} has rule version {rule_version}.",
                context=context,
                knowledge_status=str(metadata.get("knowledgeStatus") or "Candidate"),
                validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
            )
        )
        supersedes_values = _raw_values(candidate.raw, "supersedes", "supersedesVersion")
        for superseded in supersedes_values:
            superseded_name = _rule_version_name(superseded)
            self._add_entity(
                KgEntity(
                    entity_name=superseded_name,
                    entity_type="RuleVersion",
                    description=f"Rule version {superseded}",
                    source_id=candidate.source_text_unit_id or _source_id(context) or "UNKNOWN",
                    metadata=self._metadata_from_candidate(
                        candidate,
                        context,
                        review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
                        validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                        extra={"ruleVersion": superseded},
                    ),
                )
            )
            self._add_relationship(
                self._relationship_from_context(
                    src_id=version_name,
                    tgt_id=superseded_name,
                    relation_type="Supersedes",
                    description=f"{rule_version} supersedes {superseded}.",
                    context=context,
                    knowledge_status=str(metadata.get("knowledgeStatus") or "Candidate"),
                    validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                    review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
                )
            )
        self.version_mapping[entity_name] = {
            "ruleVersion": rule_version,
            "supersedes": supersedes_values,
            "latestFlag": _first_raw_value(candidate.raw, "latestFlag"),
            "versionStatus": _first_raw_value(candidate.raw, "versionStatus"),
        }

    def _add_term_edges(
        self,
        candidate: CandidateEntity,
        context: dict[str, Any],
        metadata: dict[str, Any],
    ) -> None:
        canonical_term = _first_raw_value(candidate.raw, "canonicalTerm", "canonical")
        original_term = _first_raw_value(candidate.raw, "originalTerm", "term")
        if not canonical_term or not original_term:
            return
        original_name = _canonical_term_name(original_term)
        canonical_name = _canonical_term_name(canonical_term)
        for term_name, term_value in (
            (original_name, original_term),
            (canonical_name, canonical_term),
        ):
            self._add_entity(
                KgEntity(
                    entity_name=term_name,
                    entity_type="CanonicalTerm",
                    description=f"Canonical term {term_value}",
                    source_id=candidate.source_text_unit_id or _source_id(context) or "UNKNOWN",
                    metadata=self._metadata_from_candidate(
                        candidate,
                        context,
                        review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
                        validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                        extra={"canonicalTerm": canonical_term, "originalTerm": original_term},
                    ),
                )
            )
        self._add_relationship(
            self._relationship_from_context(
                src_id=original_name,
                tgt_id=canonical_name,
                relation_type="NormalizedTo",
                description=f"{original_term} normalizes to {canonical_term}.",
                context=context,
                knowledge_status=str(metadata.get("knowledgeStatus") or "Candidate"),
                validation_status=str(metadata.get("validationStatus") or VALIDATION_VALID),
                review_decision=str(metadata.get("reviewDecision") or UNREVIEWED_DECISION),
                extra={"canonicalTerm": canonical_term, "originalTerm": original_term},
            )
        )

    def _add_review_item(
        self,
        candidate: CandidateEntity | CandidateRelation,
        review_decision: str,
        reason: str,
    ) -> None:
        context = self._context_for_candidate(candidate)
        review_item_name = f"CandidateReviewItem:{candidate.candidate_id}"
        metadata = self._metadata_from_candidate(
            candidate,
            context,
            review_decision=review_decision,
            validation_status=candidate.validation_status,
            extra={"candidateId": candidate.candidate_id, "reviewReason": reason},
        )
        self._add_entity(
            KgEntity(
                entity_name=review_item_name,
                entity_type="CandidateReviewItem",
                description=f"Review required for candidate {candidate.candidate_id}.",
                source_id=candidate.source_text_unit_id or _source_id(context) or "UNKNOWN",
                metadata=metadata,
            )
        )
        source_name = _string_or_none(context.get("featureKey")) or f"SourceDocument:{self.ingestion_payload.document_id}"
        self._add_relationship(
            self._relationship_from_context(
                src_id=source_name,
                tgt_id=review_item_name,
                relation_type="ReviewRequiredFor",
                description=f"{source_name} requires review for {candidate.candidate_id}.",
                context=context,
                knowledge_status="ReviewRequired",
                validation_status=candidate.validation_status,
                review_decision=review_decision,
            )
        )

    def _add_entity(self, entity: KgEntity) -> None:
        if entity.entity_name in self.entities_by_name:
            self.duplicate_entity_count += 1
            return
        self.entities_by_name[entity.entity_name] = entity

    def _add_relationship(self, relationship: KgRelationship) -> None:
        if relationship.keywords in FORBIDDEN_RELATION_TYPES:
            self.issues.append(
                KgPayloadIssue(
                    severity="ERROR",
                    code="FORBIDDEN_RELATION_OUTPUT_BLOCKED",
                    message=f"Forbidden relation {relationship.keywords} was blocked.",
                    source_id=relationship.source_id,
                )
            )
            self.invalid_relation_excluded_count += 1
            return
        key = (
            relationship.src_id,
            relationship.tgt_id,
            relationship.keywords,
            relationship.source_id,
        )
        if key in self.relationships_by_key:
            self.duplicate_relationship_count += 1
            return
        self.relationships_by_key[key] = relationship

    def _relationship_from_context(
        self,
        *,
        src_id: str,
        tgt_id: str,
        relation_type: str,
        description: str,
        context: dict[str, Any],
        knowledge_status: str,
        validation_status: str,
        review_decision: str,
        extra: dict[str, Any] | None = None,
    ) -> KgRelationship:
        return KgRelationship(
            src_id=src_id,
            tgt_id=tgt_id,
            description=description,
            keywords=relation_type,
            source_id=_source_id(context) or "UNKNOWN",
            weight=1.0,
            metadata=self._metadata_from_context(
                context,
                knowledge_status=knowledge_status,
                validation_status=validation_status,
                review_decision=review_decision,
                extra={"relationType": relation_type, **(extra or {})},
            ),
        )

    def _metadata_from_candidate(
        self,
        candidate: CandidateEntity | CandidateRelation,
        context: dict[str, Any],
        *,
        review_decision: str,
        validation_status: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        knowledge_status = _knowledge_status_for_decision(review_decision)
        return self._metadata_from_context(
            context,
            knowledge_status=knowledge_status,
            validation_status=validation_status,
            review_decision=review_decision,
            extra={
                "documentId": self.ingestion_payload.document_id,
                "sourceUsId": candidate.source_us_id,
                "textUnitId": candidate.source_text_unit_id,
                "sourceSpan": candidate.source_span,
                "textHash": candidate.text_hash,
                "featureKey": candidate.feature_key,
                "domainCode": candidate.domain_code,
                "sectionType": candidate.section_type,
                "ruleVersion": _first_raw_value(candidate.raw, "ruleVersion", "version", "versionId"),
                "latestFlag": _first_raw_value(candidate.raw, "latestFlag", default=context.get("latestFlag")),
                "versionStatus": _first_raw_value(candidate.raw, "versionStatus"),
                "supersedes": _raw_values(candidate.raw, "supersedes", "supersedesVersion"),
                "canonicalTerm": _first_raw_value(candidate.raw, "canonicalTerm", "canonical"),
                "originalTerm": _first_raw_value(candidate.raw, "originalTerm", "term"),
                "evidenceText": _preview(candidate.evidence_text, 320),
                "extractionRunId": getattr(candidate, "extraction_run_id", None),
                **(extra or {}),
            },
        )

    def _metadata_from_context(
        self,
        context: dict[str, Any],
        *,
        knowledge_status: str,
        validation_status: str,
        review_decision: str,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {
            "documentId": context.get("documentId") or self.ingestion_payload.document_id,
            "sourceUsId": context.get("sourceUsId"),
            "textUnitId": context.get("textUnitId"),
            "sourceSpan": context.get("sourceSpan"),
            "textHash": context.get("textHash"),
            "featureKey": context.get("featureKey"),
            "domainCode": context.get("domainCode"),
            "sectionType": context.get("sectionType"),
            "knowledgeStatus": knowledge_status,
            "validationStatus": validation_status,
            "reviewDecision": review_decision,
            "ruleVersion": context.get("ruleVersion"),
            "latestFlag": context.get("latestFlag"),
            "versionStatus": context.get("versionStatus"),
            "supersedes": context.get("supersedes"),
            "canonicalTerm": context.get("canonicalTerm"),
            "originalTerm": context.get("originalTerm"),
            "confidenceScore": context.get("confidenceScore"),
            "filePath": context.get("filePath"),
            "graphWriteCalled": False,
            "formalGraphEnabled": False,
            **(extra or {}),
        }

    def _map_evidence(
        self,
        key: str,
        candidate: CandidateEntity | CandidateRelation,
        context: dict[str, Any],
    ) -> None:
        self.evidence_mapping[key] = {
            "candidateId": candidate.candidate_id,
            "sourceUsId": candidate.source_us_id,
            "textUnitId": candidate.source_text_unit_id or context.get("textUnitId"),
            "sourceSpan": candidate.source_span or context.get("sourceSpan"),
            "textHash": candidate.text_hash or context.get("textHash"),
            "evidenceText": _preview(candidate.evidence_text or context.get("evidenceText"), 500),
        }

    def _candidate_entities(self) -> list[CandidateEntity]:
        if self.candidate_extraction_report is None:
            return []
        return list(self.candidate_extraction_report.candidate_entities)

    def _candidate_relations(self) -> list[CandidateRelation]:
        if self.candidate_extraction_report is None:
            return []
        return list(self.candidate_extraction_report.candidate_relations)

    def _context_for_candidate(
        self,
        candidate: CandidateEntity | CandidateRelation,
    ) -> dict[str, Any]:
        if candidate.source_text_unit_id and candidate.source_text_unit_id in self.contexts:
            return dict(self.contexts[candidate.source_text_unit_id])
        return self._first_context()

    def _first_context(self) -> dict[str, Any]:
        return dict(next(iter(self.contexts.values()), {}))

    def _summary(
        self,
        entities: list[KgEntity],
        relationships: list[KgRelationship],
    ) -> dict[str, Any]:
        return {
            "target": self.target,
            "chunk_count": len(self.chunks),
            "entity_count": len(entities),
            "relationship_count": len(relationships),
            "source_document_count": self.source_document_count,
            "user_story_count": self.user_story_count,
            "feature_count": self.feature_count,
            "evidence_span_count": self.evidence_span_count,
            "candidate_entity_count": len(self._candidate_entities()),
            "candidate_relation_count": len(self._candidate_relations()),
            "test_graph_eligible_count": self.test_graph_eligible_count,
            "formal_graph_eligible_count": 0,
            "review_required_excluded_count": self.review_required_excluded_count,
            "info_only_excluded_count": self.info_only_excluded_count,
            "missing_evidence_excluded_count": self.missing_evidence_excluded_count,
            "invalid_relation_excluded_count": self.invalid_relation_excluded_count,
            "duplicate_entity_count": self.duplicate_entity_count,
            "duplicate_relation_count": self.duplicate_relationship_count,
            "graph_write_called": False,
            "formal_graph_enabled": False,
            "metadata_pass_through_supported": False,
        }


def _disabled_payload(target: str, ingestion_payload: DslAwareIngestionPayload) -> DslKgPayload:
    issue = (
        FORMAL_GRAPH_DISABLED_ISSUE
        if target == "formal_graph"
        else KgPayloadIssue(
            severity="ERROR",
            code="UNSUPPORTED_TARGET",
            message=f"Unsupported KG payload target: {target}.",
        )
    )
    return DslKgPayload(
        chunks=[],
        entities=[],
        relationships=[],
        metadata={
            "target": target,
            "documentId": ingestion_payload.document_id,
            "dslVersion": ingestion_payload.dsl_version,
            "graphWriteCalled": False,
            "formalGraphEnabled": False,
        },
        issues=[issue],
        summary={
            "target": target,
            "chunk_count": 0,
            "entity_count": 0,
            "relationship_count": 0,
            "source_document_count": 0,
            "user_story_count": 0,
            "feature_count": 0,
            "evidence_span_count": 0,
            "candidate_entity_count": 0,
            "candidate_relation_count": 0,
            "test_graph_eligible_count": 0,
            "formal_graph_eligible_count": 0,
            "review_required_excluded_count": 0,
            "info_only_excluded_count": 0,
            "missing_evidence_excluded_count": 0,
            "invalid_relation_excluded_count": 0,
            "duplicate_entity_count": 0,
            "duplicate_relation_count": 0,
            "graph_write_called": False,
            "formal_graph_enabled": False,
            "disabled": True,
        },
    )


def _contexts_by_text_unit(payload: DslAwareIngestionPayload) -> dict[str, dict[str, Any]]:
    vector_by_chunk = {item.chunk_id: item for item in payload.vector_payload}
    contexts: dict[str, dict[str, Any]] = {}
    for item in payload.metadata_payload:
        vector = vector_by_chunk.get(item.vector_chunk_id)
        context = _metadata_item_context(item)
        if vector is not None:
            context.update(vector.metadata)
            context["evidenceText"] = vector.content
        contexts[item.text_unit_id] = context
    return contexts


def _metadata_item_context(item: MetadataPayloadItem) -> dict[str, Any]:
    return {
        "textUnitId": item.text_unit_id,
        "documentId": item.document_id,
        "sourceUsId": item.source_us_id,
        "featureKey": item.feature_key,
        "domainCode": item.domain_code,
        "sectionType": item.section_type,
        "sourceSpan": item.source_span,
        "textHash": item.text_hash,
        "vectorChunkId": item.vector_chunk_id,
        "extractionChunkId": item.extraction_chunk_id,
        "knowledgeStatus": item.knowledge_status,
        "mappingStatus": item.mapping_status,
    }


def _review_decisions(report: CandidateReviewReport | None) -> dict[str, dict[str, Any]]:
    if report is None:
        return {}
    values: dict[str, dict[str, Any]] = {}
    for item in report.auto_items_summary:
        candidate_id = item.get("candidate_id")
        if isinstance(candidate_id, str):
            values[candidate_id] = dict(item)
    for decision in [*report.review_required_items, *report.blocked_items]:
        values[decision.candidate_id] = {
            "candidate_id": decision.candidate_id,
            "candidate_type": decision.candidate_type,
            "decision": decision.decision,
            "reason_code": decision.reason_code,
            "reason": decision.reason,
        }
    return values


def _first_context_by(
    contexts: Any,
    key: str,
) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for context in contexts:
        value = _string_or_none(context.get(key))
        if value and value not in result:
            result[value] = dict(context)
    return result


def _knowledge_status_for_decision(decision: str) -> str:
    if decision == DECISION_AUTO_ACCEPT:
        return "AutoAcceptedForReport"
    if decision == DECISION_AUTO_RESOLVE:
        return "Candidate"
    if decision == DECISION_REVIEW_REQUIRED:
        return "ReviewRequired"
    if decision == DECISION_INFO_ONLY:
        return "InfoOnly"
    return "Candidate"


def _has_evidence(candidate: CandidateEntity | CandidateRelation) -> bool:
    return bool(candidate.source_text_unit_id and candidate.text_hash and candidate.evidence_text)


def _source_id(context: dict[str, Any]) -> str | None:
    return _string_or_none(context.get("textUnitId")) or _string_or_none(
        context.get("vectorChunkId")
    )


def _evidence_name(text_unit_id: str) -> str:
    return f"EvidenceSpan:{text_unit_id}"


def _rule_version_name(version: Any) -> str:
    return f"RuleVersion:{version}"


def _canonical_term_name(term: Any) -> str:
    return f"CanonicalTerm:{term}"


def _relationship_evidence_key(relationship: KgRelationship) -> str:
    return f"{relationship.src_id}->{relationship.keywords}->{relationship.tgt_id}:{relationship.source_id}"


def _compact_description(description: str | None, evidence_text: str | None) -> str:
    text = description or evidence_text or "No description provided."
    return _preview(" ".join(str(text).split()), 240)


def _preview(value: Any, limit: int = 160) -> str:
    text = "" if value is None else str(value)
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3]}..."


def _first_raw_value(raw: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        value = raw.get(key)
        if value is not None:
            return value
    return default


def _raw_values(raw: dict[str, Any], *keys: str) -> list[Any]:
    for key in keys:
        value = raw.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            return [item for item in value if item is not None]
        return [value]
    return []


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if isinstance(item, str)]
    return []


def _string_or_none(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _entity_vdb_payload(entities: list[KgEntity]) -> list[dict[str, Any]]:
    return [
        {
            "content": f"{entity.entity_name}\n{entity.description}",
            "entity_name": entity.entity_name,
            "source_id": entity.source_id,
            "description": entity.description,
            "entity_type": entity.entity_type,
            "file_path": entity.metadata.get("filePath"),
            "metadata": entity.metadata,
        }
        for entity in entities
    ]


def _relationship_vdb_payload(relationships: list[KgRelationship]) -> list[dict[str, Any]]:
    return [
        {
            "src_id": relationship.src_id,
            "tgt_id": relationship.tgt_id,
            "source_id": relationship.source_id,
            "content": (
                f"{relationship.keywords}\t{relationship.src_id}\n"
                f"{relationship.tgt_id}\n{relationship.description}"
            ),
            "keywords": relationship.keywords,
            "description": relationship.description,
            "weight": relationship.weight,
            "file_path": relationship.metadata.get("filePath"),
            "metadata": relationship.metadata,
        }
        for relationship in relationships
    ]


def _serialize_chunk(item: KgChunk) -> dict[str, Any]:
    return {
        "content": item.content,
        "source_id": item.source_id,
        "file_path": item.file_path,
        "metadata": _jsonable(item.metadata),
    }


def _serialize_entity(item: KgEntity) -> dict[str, Any]:
    return {
        "entity_name": item.entity_name,
        "entity_type": item.entity_type,
        "description": item.description,
        "source_id": item.source_id,
        "metadata": _jsonable(item.metadata),
    }


def _serialize_relationship(item: KgRelationship) -> dict[str, Any]:
    return {
        "src_id": item.src_id,
        "tgt_id": item.tgt_id,
        "description": item.description,
        "keywords": item.keywords,
        "source_id": item.source_id,
        "weight": item.weight,
        "metadata": _jsonable(item.metadata),
    }


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, tuple):
        return [_jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(_jsonable(item) for item in value)
    return value


__all__ = [
    "build_dsl_kg_payload",
    "serialize_dsl_kg_payload",
]
