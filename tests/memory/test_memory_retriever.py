"""Unit tests for decay-aware semantic memory retrieval."""

from __future__ import annotations

from voice_concierge.memory.decay import SECONDS_PER_DAY, MemoryDecayPolicy
from voice_concierge.memory.memory_retriever import MemoryRetriever

NOW = 2_000_000_000


class FakeEmbeddingService:
    def get_embedding(self, _query: str) -> list[float]:
        return [0.0]


class FakeVectorStore:
    def __init__(self, results: list[dict[str, float | int]]) -> None:
        self.results = results
        self.top_k_calls: list[int] = []

    def search_similar(
        self, _query_embedding: list[float], *, top_k: int
    ) -> list[dict[str, float | int]]:
        self.top_k_calls.append(top_k)
        return self.results[:top_k]


class FakeMemoryStore:
    def __init__(self, memories: list[dict[str, object]]) -> None:
        self.memories = memories
        self.get_calls = 0
        self.touch_calls: list[dict[str, object]] = []

    def get_memories(self, **filters: object) -> list[dict[str, object]]:
        self.get_calls += 1
        return [
            memory
            for memory in self.memories
            if all(memory.get(key) == value for key, value in filters.items())
        ]

    def touch_memories(self, memory_ids: list[int], *, accessed_at: int) -> int:
        self.touch_calls.append({"memory_ids": memory_ids, "accessed_at": accessed_at})
        return len(memory_ids)


def _retriever(
    memories: list[dict[str, object]],
    vector_results: list[dict[str, float | int]],
) -> tuple[MemoryRetriever, FakeMemoryStore, FakeVectorStore]:
    store = FakeMemoryStore(memories)
    vectors = FakeVectorStore(vector_results)
    retriever = MemoryRetriever(
        store,
        vectors,
        FakeEmbeddingService(),
        decay_policy=MemoryDecayPolicy(
            base_half_life_days=10,
            minimum_retention=0,
            retrieval_weight=1,
        ),
        clock=lambda: NOW,
    )
    return retriever, store, vectors


def test_decay_can_prioritize_fresh_memory_over_closer_old_memory() -> None:
    retriever, store, vectors = _retriever(
        [
            {
                "id": 1,
                "content": "old and slightly closer",
                "created_at": NOW - (100 * SECONDS_PER_DAY),
                "last_accessed": None,
                "strength": 1,
                "topic": "profile",
            },
            {
                "id": 2,
                "content": "fresh and slightly farther",
                "created_at": NOW,
                "last_accessed": None,
                "strength": 1,
                "topic": "profile",
            },
        ],
        [
            {"memory_id": 1, "distance": 0.1},
            {"memory_id": 2, "distance": 0.2},
        ],
    )

    results = retriever.retrieve_similar("query", top_k=2)

    assert [result["id"] for result in results] == [2, 1]
    assert all("retention_score" in result for result in results)
    assert all("retrieval_score" in result for result in results)
    assert store.get_calls == 1
    assert store.touch_calls == [
        {"memory_ids": [2, 1], "accessed_at": NOW},
    ]
    assert vectors.top_k_calls == [8]


def test_only_returned_memories_are_marked_as_accessed() -> None:
    retriever, store, _vectors = _retriever(
        [
            {
                "id": memory_id,
                "content": str(memory_id),
                "created_at": NOW,
                "last_accessed": None,
                "strength": 1,
                "topic": "profile",
            }
            for memory_id in (1, 2, 3)
        ],
        [
            {"memory_id": 1, "distance": 0.1},
            {"memory_id": 2, "distance": 0.2},
            {"memory_id": 3, "distance": 0.3},
        ],
    )

    results = retriever.retrieve_similar("query", top_k=2)

    assert len(results) == 2
    assert store.touch_calls[0]["memory_ids"] == [1, 2]


def test_duplicate_check_mode_preserves_distance_order_without_touching() -> None:
    retriever, store, vectors = _retriever(
        [
            {
                "id": 1,
                "content": "old",
                "created_at": NOW - (100 * SECONDS_PER_DAY),
                "last_accessed": None,
                "strength": 1,
            },
            {
                "id": 2,
                "content": "fresh",
                "created_at": NOW,
                "last_accessed": None,
                "strength": 1,
            },
        ],
        [
            {"memory_id": 1, "distance": 0.1},
            {"memory_id": 2, "distance": 0.2},
        ],
    )

    results = retriever.retrieve_similar(
        "query",
        top_k=2,
        apply_decay=False,
        track_access=False,
    )

    assert [result["id"] for result in results] == [1, 2]
    assert all("retention_score" not in result for result in results)
    assert store.touch_calls == []
    assert vectors.top_k_calls == [4]


def test_metadata_retrieval_does_not_apply_decay_or_touch_records() -> None:
    retriever, store, _vectors = _retriever(
        [
            {
                "id": 1,
                "content": "shopping_list:add:milk",
                "created_at": NOW - (100 * SECONDS_PER_DAY),
                "last_accessed": None,
                "strength": 1,
                "topic": "shopping",
            }
        ],
        [],
    )

    results = retriever.retrieve_by_metadata(topic="shopping")

    assert [result["id"] for result in results] == [1]
    assert store.touch_calls == []
