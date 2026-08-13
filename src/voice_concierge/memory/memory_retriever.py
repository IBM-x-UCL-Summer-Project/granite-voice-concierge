"""Retrieves memories using semantic similarity and metadata filters."""

from typing import Optional

from voice_concierge.memory.embedding_service import EmbeddingService
from voice_concierge.memory.memory_store import MemoryStore
from voice_concierge.memory.types import MemoryRecord, MemorySearchResult
from voice_concierge.memory.vector_store import VectorStore


class MemoryRetriever:
    """Retrieves memories using semantic search and filtering."""

    def __init__(
        self,
        memory_store: MemoryStore,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
    ) -> None:
        """
        Initialize retriever with required components.

        Args:
            memory_store: Storage layer for memory content
            vector_store: Vector search layer
            embedding_service: Embedding generation service
        """
        self.memory_store = memory_store
        self.vector_store = vector_store
        self.embedding_service = embedding_service

    def retrieve_similar(
        self,
        query: str,
        top_k: int = 5,
        person: Optional[str] = None,
        topic: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> list[MemorySearchResult]:
        """
        Retrieve similar memories using semantic search with optional filters.

        Args:
            query: Query text to find similar memories
            top_k: Number of results to return
            person: Filter by person (optional)
            topic: Filter by topic (optional)
            layer: Filter by layer (optional)

        Returns:
            Typed memory search results sorted by similarity
        """
        try:
            # Generate embedding for query
            query_embedding = self.embedding_service.get_embedding(query)

            indexed_memories = {
                memory.id: memory
                for memory in self.memory_store.get_memories()
                if memory.indexed_revision == memory.revision
            }
            search_limit = top_k * 2
            if person is not None or topic is not None or layer is not None:
                # sqlite-vec ranks before SQL metadata is available. Search all
                # active vectors for a scoped query so globally close records
                # cannot crowd the requested scope out of the candidate set.
                search_limit = max(search_limit, len(indexed_memories))
            vector_results = self.vector_store.search_similar(
                query_embedding,
                top_k=search_limit,
            )

            memories: list[MemorySearchResult] = []
            for result in vector_results:
                memory_id = result.memory_id
                memory = indexed_memories.get(memory_id)
                if not memory:
                    continue

                # Apply filters
                if person and memory.person != person:
                    continue
                if topic and memory.topic != topic:
                    continue
                if layer and memory.layer != layer:
                    continue

                memories.append(
                    MemorySearchResult(memory=memory, distance=result.distance)
                )

                if len(memories) >= top_k:
                    break

            return memories

        except Exception as e:
            raise RuntimeError(f"Memory retrieval failed: {str(e)}")

    def retrieve_by_metadata(
        self,
        person: Optional[str] = None,
        topic: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> list[MemoryRecord]:
        """
        Retrieve memories by metadata filters only (no semantic search).

        Args:
            person: Filter by person
            topic: Filter by topic
            layer: Filter by layer

        Returns:
            Validated matching memory records
        """
        return self.memory_store.get_memories(person=person, topic=topic, layer=layer)

    def retrieve_by_person(
        self,
        person: str,
        top_k: int = 10,
    ) -> list[MemoryRecord]:
        """Get all memories for a specific person."""
        memories = self.memory_store.get_memories(person=person)
        return memories[:top_k]

    def retrieve_by_topic(
        self,
        topic: str,
        top_k: int = 10,
    ) -> list[MemoryRecord]:
        """Get all memories for a specific topic."""
        memories = self.memory_store.get_memories(topic=topic)
        return memories[:top_k]

    def retrieve_by_layer(
        self,
        layer: str,
        top_k: int = 10,
    ) -> list[MemoryRecord]:
        """Get all memories from a specific layer."""
        memories = self.memory_store.get_memories(layer=layer)
        return memories[:top_k]

    def retrieve_all(self) -> list[MemoryRecord]:
        """Retrieve all memories."""
        return self.memory_store.get_memories()
