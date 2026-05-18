from __future__ import annotations

from dataclasses import dataclass, field

from .candidate_types import CandidateEntity, CandidateRelation


@dataclass
class CandidateStore:
    entities: dict[str, CandidateEntity] = field(default_factory=dict)
    relations: dict[str, CandidateRelation] = field(default_factory=dict)
    upsert_calls: list[dict[str, int]] = field(default_factory=list)
    delete_calls: list[list[str]] = field(default_factory=list)
    reset_calls: int = 0
    duplicate_candidate_count: int = 0

    def upsert_entities(self, entities: list[CandidateEntity]) -> int:
        duplicate_count = sum(1 for entity in entities if entity.candidate_id in self.entities)
        self.duplicate_candidate_count += duplicate_count
        for entity in entities:
            self.entities[entity.candidate_id] = entity
        self.upsert_calls.append({"entities": len(entities), "relations": 0})
        return len(entities)

    def upsert_relations(self, relations: list[CandidateRelation]) -> int:
        duplicate_count = sum(
            1 for relation in relations if relation.candidate_id in self.relations
        )
        self.duplicate_candidate_count += duplicate_count
        for relation in relations:
            self.relations[relation.candidate_id] = relation
        self.upsert_calls.append({"entities": 0, "relations": len(relations)})
        return len(relations)

    def delete_candidates(self, ids: list[str]) -> int:
        deleted = 0
        for candidate_id in ids:
            if self.entities.pop(candidate_id, None) is not None:
                deleted += 1
            if self.relations.pop(candidate_id, None) is not None:
                deleted += 1
        self.delete_calls.append(list(ids))
        return deleted

    def reset(self) -> None:
        self.entities.clear()
        self.relations.clear()
        self.reset_calls += 1

    def count_entities(self) -> int:
        return len(self.entities)

    def count_relations(self) -> int:
        return len(self.relations)

    def count_all(self) -> int:
        return self.count_entities() + self.count_relations()


__all__ = ["CandidateStore"]
