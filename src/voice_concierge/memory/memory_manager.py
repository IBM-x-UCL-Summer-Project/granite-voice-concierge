"""High-level memory management orchestrating storage, validation, and retrieval."""

from typing import Optional, Tuple

from voice_concierge.memory.embedding_service import EmbeddingService
from voice_concierge.memory.memory_retriever import MemoryRetriever
from voice_concierge.memory.memory_store import MemoryStore
from voice_concierge.memory.memory_validator import MemoryValidator
from voice_concierge.memory.vector_store import VectorStore
from voice_concierge.reasoning.types import MemoryAction


class MemoryManager:
    """Orchestrates memory operations: validation, storage, retrieval, and updates."""

    def __init__(
        self,
        memory_store: MemoryStore,
        vector_store: VectorStore,
        embedding_service: EmbeddingService,
        validator: Optional[MemoryValidator] = None,
    ):
        """
        Initialize the memory manager with required components.

        Args:
            memory_store: Storage layer for memory content
            vector_store: Vector search layer
            embedding_service: Embedding generation service
            validator: Memory validator (optional, uses default if not provided)
        """
        self.memory_store = memory_store
        self.vector_store = vector_store
        self.embedding_service = embedding_service
        self.validator = validator or MemoryValidator()
        self.retriever = MemoryRetriever(memory_store, vector_store, embedding_service)

    def find_similar_memory(
        self,
        content: str,
        threshold: float = 0.85,
        top_k: int = 5,
    ) -> Optional[dict]:
        """
        Find semantically similar existing memory.

        Args:
            content: Memory content to match
            threshold: Similarity threshold (0-1), higher = more strict
            top_k: Number of candidates to check

        Returns:
            Most similar memory dict if found above threshold, else None
        """
        try:
            results = self.retrieve_similar(
                content,
                top_k=top_k,
                apply_decay=False,
                track_access=False,
            )
            if results and results[0].get("distance", 1.0) < (1.0 - threshold):
                return results[0]
            return None
        except Exception:
            return None

    def store_memory(
        self,
        content: str,
        layer: str,
        person: Optional[str] = None,
        topic: Optional[str] = None,
        source_type: Optional[str] = None,
        event_time: Optional[int] = None,
        strength: Optional[int] = None,
        validate: bool = True,
        auto_classify: bool = True,
        auto_extract: bool = True,
        check_duplicates: bool = True,
    ) -> Tuple[bool, str, Optional[int]]:
        """
        Store a memory after validation and optional auto-classification.
        Prevents duplicate/similar memories from being stored.

        Args:
            content: Memory content
            layer: Memory layer (profile, raw, feedback, etc.)
            person: Associated person (optional, auto-extracted if None)
            topic: Associated topic (optional)
            source_type: Source type (optional, auto-extracted if None)
            event_time: Event time timestamp (optional, auto-extracted if None)
            strength: Memory strength 1-10 (optional, auto-extracted if None)
            validate: Whether to validate with LLM first
            auto_classify: Whether to auto-classify memory type
            auto_extract: Whether to auto-extract metadata
            check_duplicates: Whether to check for duplicates (default: True)

        Returns:
            Tuple of (success: bool, reason: str, memory_id: Optional[int])
        """
        # Check for duplicates if enabled
        if check_duplicates:
            similar = self.find_similar_memory(content, threshold=0.9)
            if similar:
                mem_id = similar["id"]
                return False, f"duplicate_found: memory_id={mem_id}", mem_id

        # Validate if enabled
        if validate:
            should_store, reason = self.validator.should_store(content)
            if not should_store:
                return False, f"validation_failed: {reason}", None

        # Auto-extract metadata if enabled
        if auto_extract:
            extracted = self.validator.extract_metadata(content)
            person = person or extracted.get("person")
            source_type = source_type or extracted.get("source_type")
            event_time = event_time or extracted.get("event_time")
            strength = strength or extracted.get("strength", 1)

        # Set default strength if still None
        if strength is None:
            strength = 5

        # Auto-classify memory type if enabled and topic not provided
        classified_topic = topic
        if auto_classify and not topic:
            memory_type, _ = self.validator.classify_memory_type(content)
            if memory_type:
                classified_topic = memory_type.value

        memory_id = None
        try:
            # Store in memory_store
            memory_id = self.memory_store.create_memory(
                content=content,
                layer=layer,
                person=person,
                source_type=source_type,
                topic=classified_topic,
                event_time=event_time,
                strength=strength,
            )

            # Generate and store embedding
            try:
                embedding = self.embedding_service.get_embedding(content)
                self.vector_store.save_vector(memory_id, embedding)
            except Exception as e:
                # Rollback: delete SQL record if vector storage fails
                self.memory_store.delete_memory(memory_id)
                return False, f"vector_storage_failed_rolled_back: {str(e)}", None

            return True, "stored_successfully", memory_id

        except Exception as e:
            if memory_id is not None:
                self.memory_store.delete_memory(memory_id)
            return False, f"storage_error: {str(e)}", None

    def retrieve_similar(
        self,
        query: str,
        top_k: int = 5,
        person: Optional[str] = None,
        topic: Optional[str] = None,
        layer: Optional[str] = None,
        apply_decay: bool = True,
        track_access: bool = True,
    ) -> list[dict]:
        """
        Retrieve semantically similar memories.

        Args:
            query: Query text
            top_k: Number of results
            person: Filter by person
            topic: Filter by topic
            layer: Filter by layer

        Returns:
            List of similar memories with distance scores
        """
        return self.retriever.retrieve_similar(
            query=query,
            top_k=top_k,
            person=person,
            topic=topic,
            layer=layer,
            apply_decay=apply_decay,
            track_access=track_access,
        )

    def retrieve_by_metadata(
        self,
        *,
        person: Optional[str] = None,
        topic: Optional[str] = None,
        layer: Optional[str] = None,
    ) -> list[dict]:
        """Retrieve the complete matching collection without semantic ranking."""

        return self.retriever.retrieve_by_metadata(
            person=person,
            topic=topic,
            layer=layer,
        )

    def update_memory(
        self,
        memory_id: int,
        content: Optional[str] = None,
        layer: Optional[str] = None,
        person: Optional[str] = None,
        topic: Optional[str] = None,
        source_type: Optional[str] = None,
        event_time: Optional[int] = None,
        strength: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Update a memory and regenerate its embedding if content changed.
        Rolls back SQL changes if embedding generation/storage fails.

        Args:
            memory_id: ID of memory to update
            content: New content (optional)
            layer: New layer (optional)
            person: New person (optional)
            topic: New topic (optional)
            source_type: New source type (optional)
            event_time: New event time (optional)
            strength: New strength value (optional)

        Returns:
            Tuple of (success: bool, reason: str)
        """
        try:
            # Save original state for potential rollback
            original_memory = self.memory_store.get_memory_by_id(memory_id)
            if not original_memory:
                return False, "memory_not_found"

            # Update SQL
            success = self.memory_store.update_memory(
                memory_id=memory_id,
                content=content,
                layer=layer,
                person=person,
                topic=topic,
                source_type=source_type,
                event_time=event_time,
                strength=strength,
            )

            if not success:
                return False, "no_changes"

            # Regenerate embedding if content changed
            if content:
                try:
                    embedding = self.embedding_service.get_embedding(content)
                    self.vector_store.save_vector(memory_id, embedding)
                except Exception as e:
                    # Rollback SQL changes if embedding fails
                    self.memory_store.update_memory(
                        memory_id=memory_id,
                        content=original_memory.get("content"),
                        layer=original_memory.get("layer"),
                        person=original_memory.get("person"),
                        topic=original_memory.get("topic"),
                        source_type=original_memory.get("source_type"),
                        event_time=original_memory.get("event_time"),
                        strength=original_memory.get("strength"),
                    )
                    return False, f"embedding_error_rolled_back: {str(e)}"

            return True, "updated_successfully"

        except Exception as e:
            return False, f"update_error: {str(e)}"

    def delete_memory(self, memory_id: int) -> Tuple[bool, str]:
        """
        Delete a memory and its vector.

        Args:
            memory_id: ID of memory to delete

        Returns:
            Tuple of (success: bool, reason: str)
        """
        try:
            success = self.memory_store.delete_memory(memory_id)
            if not success:
                return False, "memory_not_found"

            # Also delete the associated vector
            try:
                self.vector_store.delete_vector(memory_id)
            except Exception as e:
                return False, f"vector_deletion_failed: {str(e)}"

            return True, "deleted_successfully"

        except Exception as e:
            return False, f"delete_error: {str(e)}"

    def process_memory_action(self, action: MemoryAction) -> Tuple[bool, str]:
        """
        Process a proposed memory action from the reasoning engine.

        Args:
            action: MemoryAction from ReasoningResponse

        Returns:
            Tuple of (success: bool, reason: str)
        """
        action_type = action.action

        if action_type == "store":
            success, reason, _ = self.store_memory(
                content=action.content,
                layer="feedback",
                validate=False,
            )
            return success, reason

        elif action_type == "update":
            # Parse memory_id from content if available
            # For now, find the most similar memory and update it
            similar = self.retrieve_similar(action.content, top_k=1)
            if similar:
                memory_id = similar[0]["id"]
                return self.update_memory(memory_id, content=action.content)
            return False, "no_similar_memory_found"

        elif action_type == "delete":
            # Find the most similar memory and delete it
            similar = self.retrieve_similar(action.content, top_k=1)
            if similar:
                memory_id = similar[0]["id"]
                return self.delete_memory(memory_id)
            return False, "no_similar_memory_found"

        else:
            return False, f"unknown_action: {action_type}"

    def get_context_memories(
        self,
        query: str,
        context_size: int = 3,
    ) -> list[str]:
        """
        Get relevant memory snippets for context (for reasoning engine).

        Args:
            query: Current conversation query
            context_size: Number of memories to retrieve

        Returns:
            List of memory content strings suitable for context
        """
        try:
            memories = self.retrieve_similar(query, top_k=context_size)
            return [m["content"] for m in memories]
        except Exception:
            return []

    def get_all_memories(self) -> list[dict]:
        """Get all stored memories."""
        return self.retriever.retrieve_all()

    def close(self):
        """Close all storage connections."""
        self.memory_store.close()
        self.vector_store.close()
