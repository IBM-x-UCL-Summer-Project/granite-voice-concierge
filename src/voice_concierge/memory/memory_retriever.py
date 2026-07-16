"""Retrieves memories using semantic similarity and metadata filters."""

from typing import Optional

from voice_concierge.memory.embedding_service import EmbeddingService
from voice_concierge.memory.memory_store import MemoryStore
from voice_concierge.memory.vector_store import VectorStore


class MemoryRetriever:
    """Retrieves memories using semantic search and filtering."""

    def __init__(
        self,
        memory_store: MemoryStore,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
    ):
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
    ) -> list[dict]:
        """
        Retrieve similar memories using semantic search with optional filters.

        Args:
            query: Query text to find similar memories
            top_k: Number of results to return
            person: Filter by person (optional)
            topic: Filter by topic (optional)
            layer: Filter by layer (optional)

        Returns:
            List of memory dicts with distance scores, sorted by similarity
        """
        try:
            # Generate embedding for query
            query_embedding = self.embedding_service.get_embedding(query)

            # Search for similar vectors
            vector_results = self.vector_store.search_similar(
                query_embedding, top_k=top_k * 2
            )

            # Get full memory details and apply filters
            memories = []
            for result in vector_results:
                memory_id = result["memory_id"]
                all_memories = self.memory_store.get_memories()

                memory = next((m for m in all_memories if m["id"] == memory_id), None)
                if not memory:
                    continue

                # Apply filters
                if person and memory.get("person") != person:
                    continue
                if topic and memory.get("topic") != topic:
                    continue
                if layer and memory.get("layer") != layer:
                    continue

                memory_with_score = {**memory, "distance": result["distance"]}
                memories.append(memory_with_score)

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
    ) -> list[dict]:
        """
        Retrieve memories by metadata filters only (no semantic search).

        Args:
            person: Filter by person
            topic: Filter by topic
            layer: Filter by layer

        Returns:
            List of matching memory dicts
        """
        return self.memory_store.get_memories(person=person, topic=topic, layer=layer)

    def retrieve_by_person(self, person: str, top_k: int = 10) -> list[dict]:
        """Get all memories for a specific person."""
        memories = self.memory_store.get_memories(person=person)
        return memories[:top_k]

    def retrieve_by_topic(self, topic: str, top_k: int = 10) -> list[dict]:
        """Get all memories for a specific topic."""
        memories = self.memory_store.get_memories(topic=topic)
        return memories[:top_k]

    def retrieve_by_layer(self, layer: str, top_k: int = 10) -> list[dict]:
        """Get all memories from a specific layer."""
        memories = self.memory_store.get_memories(layer=layer)
        return memories[:top_k]

    def retrieve_all(self) -> list[dict]:
        """Retrieve all memories."""
        return self.memory_store.get_memories()
