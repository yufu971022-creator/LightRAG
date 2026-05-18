from __future__ import annotations


DEFAULT_ENTITY_TYPES = [
    "UserStory",
    "FeatureCatalog",
    "RuleAtom",
    "FieldSpec",
    "MessageAtom",
    "StateTransition",
    "TaskRule",
    "Workflow",
    "ApprovalAction",
    "Deal",
    "Ledger",
    "MasterDataObject",
    "BackendApi",
    "FrontendApi",
    "Service",
    "Permission",
    "AuditLog",
    "Report",
    "ReportFilter",
    "ConfigItem",
    "MigrationTask",
    "DfxControl",
    "CandidateEntity",
]


SYSTEM_PROMPT = """---Role---
You are an information extraction engine for enterprise product design documents and User Stories.
The input is product design source text without compiled DSL constraints.

---Entity Rules---
1. Extract only entities grounded in the input text.
2. Use the provided entity type list when a type fits; otherwise use CandidateEntity.
3. Do not invent entity types, interfaces, tables, permissions, effort, priority, rollback plans, or other facts.
4. Keep entityType and entityName separated.
5. Prefer concrete product design objects: user stories, features, fields, rules, messages, workflow states, tasks, APIs, permissions, audit logs, reports, configs, migration objects, and DFX controls.
6. Preserve concise source evidence in descriptions.

---Relationship Rules---
1. Extract relationships only when both source and target are grounded in the input text.
2. Use concise PascalCase relationship keywords when the relation is clear; otherwise use CandidateRelation.
3. Do not use snake_case relation labels such as has_child, belongs_to, references_to, queries_from, queries_by, contains.
4. Do not invent relation labels or facts.

---Output Stability Rules---
1. Output only complete tuple records.
2. Never output partial records.
3. Output at most 16 records total in one response.
4. Output at most 8 entities and at most 8 relations.
5. Entity descriptions must be concise and <= 160 characters.
6. Relationship descriptions must be concise and <= 200 characters.
7. For long field tables, extract only the top 8 most important fields and leave remaining fields for Gleaning.
8. Always end with the completion delimiter.
9. Do not output JSON, Markdown, explanations, or reasoning.

---Output Format---
entity{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>
relation{tuple_delimiter}<source_entity_name>{tuple_delimiter}<target_entity_name>{tuple_delimiter}<relationship_keywords>{tuple_delimiter}<relationship_description>

Separate records using newline characters.
End output with:
{completion_delimiter}

---Provided Entity Types---
{entity_types}

---Output Language---
Use {language}. Keep proper nouns in their original language when translation would cause ambiguity.
"""


USER_PROMPT = """---Task---
Extract product design entities and relationships from the input text.

---Input---
{input_text}

---Output---
"""


CONTINUE_PROMPT = """---Task---
Perform a Gleaning pass over the previous product design extraction.

---Rules---
1. Add only missing records.
2. Do not repeat records already extracted.
3. Output at most 8 additional records.
4. Use the provided entity types when they fit; otherwise use CandidateEntity.
5. Use CandidateRelation if the relationship keyword is uncertain.
6. Never output incomplete tuples.
7. If nothing important is missing, output only the completion delimiter.
8. Do not output JSON, Markdown, explanations, or reasoning.

For each missing entity:
entity{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>

For each missing relationship:
relation{tuple_delimiter}<source_entity_name>{tuple_delimiter}<target_entity_name>{tuple_delimiter}<relationship_keywords>{tuple_delimiter}<relationship_description>

End output with:
{completion_delimiter}

<Output>
"""


EXAMPLES: list[str] = []
