from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ShadowUpsertCall:
    keys: list[str]
    overwrite_existing_count: int


class ShadowKVStorage:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.upsert_calls: list[ShadowUpsertCall] = []
        self.delete_calls: list[list[str]] = []
        self.reset_calls = 0

    async def upsert(self, data: dict[str, dict[str, Any]]) -> None:
        overwrite_count = sum(1 for key in data if key in self.data)
        self.data.update(data)
        self.upsert_calls.append(
            ShadowUpsertCall(
                keys=list(data.keys()),
                overwrite_existing_count=overwrite_count,
            )
        )

    async def delete(self, keys: list[str]) -> None:
        for key in keys:
            self.data.pop(key, None)
        self.delete_calls.append(list(keys))

    def reset(self) -> None:
        self.data.clear()
        self.reset_calls += 1

    def count(self) -> int:
        return len(self.data)


class ShadowVectorStorage:
    def __init__(self) -> None:
        self.data: dict[str, dict[str, Any]] = {}
        self.upsert_calls: list[ShadowUpsertCall] = []
        self.delete_calls: list[list[str]] = []
        self.reset_calls = 0
        self.embedding_called = False

    async def upsert(self, data: dict[str, dict[str, Any]]) -> None:
        overwrite_count = sum(1 for key in data if key in self.data)
        self.data.update(data)
        self.upsert_calls.append(
            ShadowUpsertCall(
                keys=list(data.keys()),
                overwrite_existing_count=overwrite_count,
            )
        )

    async def delete(self, keys: list[str]) -> None:
        for key in keys:
            self.data.pop(key, None)
        self.delete_calls.append(list(keys))

    def reset(self) -> None:
        self.data.clear()
        self.reset_calls += 1

    def count(self) -> int:
        return len(self.data)


__all__ = [
    "ShadowKVStorage",
    "ShadowUpsertCall",
    "ShadowVectorStorage",
]
