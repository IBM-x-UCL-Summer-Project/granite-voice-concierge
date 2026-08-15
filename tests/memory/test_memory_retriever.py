"""Unit tests for decay-aware semantic memory retrieval."""

from __future__ import annotations

from voice_concierge.memory.decay import SECONDS_PER_DAY, MemoryDecayPolicy
from voice_concierge.memory.memory_retriever import MemoryRetriever
from voice_concierge.memory.types import MemoryRecord, VectorSearchResult

NOW = 2_000_000_000


class FakeEmbeddingService:
    def get_embedding(self, _query: str) -> list[float]:
        return [0.0]


class FakeVectorStore:
    def __init__(self, results: list[VectorSearchResult]) -> None:
        self.results = results
        self.top_k_calls: list[int] = []

    def search_similar(
        self, _query_embedding: list[float], *, top_k: int
    ) -> list[VectorSearchResult]:
        self.top_k_calls.append(top_k)
        return self.results[:top_k]


class FakeMemoryStore:
    def __init__(self, memories: list[MemoryRecord]) -> None:
        self.memories = memories
        self.get_calls = 0
        self.touch_calls: list[dict[str, object]] = []

    def get_memories(self, **filters: object) -> list[MemoryRecord]:
        self.get_calls += 1
        return [
            memory
            for memory in self.memories
            if all(
                value is None or getattr(memory, key) == value
                for key, value in filters.items()
            )
        ]

    def touch_memories(self, memory_ids: list[int], *, accessed_at: int) -> int:
        self.touch_calls.append({"memory_ids": memory_ids, "accessed_at": accessed_at})
        return len(memory_ids)


def _retriever(
    memories: list[MemoryRecord],
    vector_results: list[VectorSearchResult],
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


def _memory(
    memory_id: int,
    content: str,
    *,
    created_at: int,
    topic: str | None = None,
    last_accessed: int | None = None,
    strength: int = 1,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        content=content,
        layer="profile",
        memory_key=None,
        revision=1,
        indexed_revision=1,
        deleted_at=None,
        created_at=created_at,
        event_time=None,
        last_accessed=last_accessed,
        strength=strength,
        person=None,
        source_type=None,
        topic=topic,
    )


def test_decay_can_prioritize_fresh_memory_over_closer_old_memory() -> None:
    retriever, store, vectors = _retriever(
        [
            _memory(
                1,
                "old and slightly closer",
                created_at=NOW - (100 * SECONDS_PER_DAY),
                topic="profile",
            ),
            _memory(2, "fresh and slightly farther", created_at=NOW, topic="profile"),
        ],
        [
            VectorSearchResult(memory_id=1, distance=0.1),
            VectorSearchResult(memory_id=2, distance=0.2),
        ],
    )

    results = retriever.retrieve_similar("query", top_k=2)

    assert [result.memory.id for result in results] == [2, 1]
    assert all(result.retention_score is not None for result in results)
    assert all(result.retrieval_score is not None for result in results)
    assert store.get_calls == 1
    assert store.touch_calls == [
        {"memory_ids": [2, 1], "accessed_at": NOW},
    ]
    assert vectors.top_k_calls == [2]


def test_decay_ranks_every_active_candidate_not_only_a_fixed_window() -> None:
    retriever, _store, vectors = _retriever(
        [
            _memory(
                memory_id,
                f"old {memory_id}",
                created_at=NOW - (100 * SECONDS_PER_DAY),
            )
            for memory_id in (1, 2, 3, 4)
        ]
        + [_memory(5, "fresh", created_at=NOW)],
        [
            VectorSearchResult(memory_id=memory_id, distance=distance)
            for memory_id, distance in (
                (1, 0.1),
                (2, 0.2),
                (3, 0.3),
                (4, 0.4),
                (5, 0.5),
            )
        ],
    )

    results = retriever.retrieve_similar("query", top_k=1)

    assert [result.memory.id for result in results] == [5]
    assert vectors.top_k_calls == [5]


def test_only_returned_memories_are_marked_as_accessed() -> None:
    retriever, store, _vectors = _retriever(
        [
            _memory(memory_id, str(memory_id), created_at=NOW, topic="profile")
            for memory_id in (1, 2, 3)
        ],
        [
            VectorSearchResult(memory_id=1, distance=0.1),
            VectorSearchResult(memory_id=2, distance=0.2),
            VectorSearchResult(memory_id=3, distance=0.3),
        ],
    )

    results = retriever.retrieve_similar("query", top_k=2)

    assert len(results) == 2
    assert store.touch_calls[0]["memory_ids"] == [1, 2]


def test_duplicate_check_mode_preserves_distance_order_without_touching() -> None:
    retriever, store, vectors = _retriever(
        [
            _memory(1, "old", created_at=NOW - (100 * SECONDS_PER_DAY)),
            _memory(2, "fresh", created_at=NOW),
        ],
        [
            VectorSearchResult(memory_id=1, distance=0.1),
            VectorSearchResult(memory_id=2, distance=0.2),
        ],
    )

    results = retriever.retrieve_similar(
        "query",
        top_k=2,
        apply_decay=False,
        track_access=False,
    )

    assert [result.memory.id for result in results] == [1, 2]
    assert all(result.retention_score is None for result in results)
    assert all(result.retrieval_score is None for result in results)
    assert store.touch_calls == []
    assert vectors.top_k_calls == [2]


def test_metadata_retrieval_does_not_apply_decay_or_touch_records() -> None:
    retriever, store, _vectors = _retriever(
        [
            _memory(
                1,
                "shopping_list:add:milk",
                created_at=NOW - (100 * SECONDS_PER_DAY),
                topic="shopping",
            )
        ],
        [],
    )

    results = retriever.retrieve_by_metadata(topic="shopping")

    assert [result.id for result in results] == [1]
    assert store.touch_calls == []
