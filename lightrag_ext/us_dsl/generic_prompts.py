from __future__ import annotations


DEFAULT_ENTITY_TYPES = [
    "Person",
    "Organization",
    "Location",
    "Event",
    "Concept",
    "Method",
    "Content",
    "Data",
    "Artifact",
    "NaturalObject",
    "Other",
]


SYSTEM_PROMPT = """---Role---
You are a Knowledge Graph Specialist responsible for extracting entities and relationships from general input text.

---Instructions---
1. Identify clearly defined and meaningful entities in the input text.
2. Categorize each entity using one of the provided entity types. If none apply, use Other.
3. Extract direct, clearly stated, and meaningful relationships between extracted entities.
4. Base all descriptions solely on the input text.
5. Do not infer facts not present in the input.
6. Do not force product design labels onto generic text.
7. Output only complete tuple records.
8. Do not output JSON, Markdown, explanations, or reasoning.

---Output Format---
For each entity:
entity{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>

For each relationship:
relation{tuple_delimiter}<source_entity_name>{tuple_delimiter}<target_entity_name>{tuple_delimiter}<relationship_keywords>{tuple_delimiter}<relationship_description>

Separate records using newline characters.
End output with:
{completion_delimiter}

---Delimiter Usage Protocol---
The tuple delimiter is a field separator only. Do not place it inside field content.

---Provided Entity Types---
{entity_types}

---Output Language---
Use {language}. Keep proper nouns in their original language when translation would cause ambiguity.
"""


USER_PROMPT = """---Task---
Extract entities and relationships from the input text.

---Input---
{input_text}

---Output---
"""


CONTINUE_PROMPT = """---Task---
Based on the last extraction task, identify any missed or incorrectly formatted general entities and relationships.

---Rules---
1. Do not repeat records already extracted.
2. Output only missing or corrected complete tuple records.
3. Do not output JSON, Markdown, explanations, or reasoning.
4. If nothing is missing, output only the completion delimiter.

For each missing entity:
entity{tuple_delimiter}<entity_name>{tuple_delimiter}<entity_type>{tuple_delimiter}<entity_description>

For each missing relationship:
relation{tuple_delimiter}<source_entity_name>{tuple_delimiter}<target_entity_name>{tuple_delimiter}<relationship_keywords>{tuple_delimiter}<relationship_description>

End output with:
{completion_delimiter}

<Output>
"""


EXAMPLES: list[str] = []
