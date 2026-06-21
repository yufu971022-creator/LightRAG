from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

GenericNERTypeDisposition = Literal[
    "BLOCK_FROM_PFSS",
    "REQUIRES_RESOLUTION",
    "ALLOW_ONLY_IN_GENERIC_GRAPH",
    "IGNORE_AS_LITERAL",
]

GENERIC_NER_TYPES = {
    "Location",
    "LOC",
    "GPE",
    "Person",
    "PER",
    "Organization",
    "ORG",
    "Event",
    "Product",
    "Misc",
}
LITERAL_NER_TYPES = {"Date", "Time", "Money", "Percent", "Number"}


@dataclass(frozen=True)
class GenericNERTypePolicy:
    generic_types: set[str]
    literal_types: set[str]

    def disposition(self, entity_type: str | None) -> GenericNERTypeDisposition:
        if entity_type in self.literal_types:
            return "IGNORE_AS_LITERAL"
        if entity_type in self.generic_types:
            return "REQUIRES_RESOLUTION"
        return "ALLOW_ONLY_IN_GENERIC_GRAPH"

    def is_generic_ner_type(self, entity_type: str | None) -> bool:
        return bool(entity_type in self.generic_types or entity_type in self.literal_types)

    def to_report(self) -> dict[str, object]:
        return {
            "generic_types": sorted(self.generic_types),
            "literal_types": sorted(self.literal_types),
            "default_generic_disposition": "REQUIRES_RESOLUTION",
            "default_literal_disposition": "IGNORE_AS_LITERAL",
        }


def default_generic_ner_type_policy() -> GenericNERTypePolicy:
    return GenericNERTypePolicy(generic_types=set(GENERIC_NER_TYPES), literal_types=set(LITERAL_NER_TYPES))
