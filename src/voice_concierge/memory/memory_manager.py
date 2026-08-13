"""High-level memory management orchestrating storage, validation, and retrieval."""

from dataclasses import dataclass
from typing import Optional, Tuple

from voice_concierge.memory.embedding_service import EmbeddingService
from voice_concierge.memory.memory_retriever import MemoryRetriever
from voice_concierge.memory.memory_store import MemoryStore
from voice_concierge.memory.memory_validator import MemoryValidator
from voice_concierge.memory.structured_lists import (
    apply_structured_list_operation,
    create_structured_list,
    structured_list_topic,
)
from voice_concierge.memory.vector_store import VectorStore
from voice_concierge.reasoning.types import MemoryAction, MemoryTarget


@dataclass(frozen=True)
class IndexReconciliationResult:
    """Summary of repairing the derived vector index from authoritative SQL."""

    indexed_memories: int = 0
    cleaned_tombstones: int = 0
    removed_orphan_vectors: int = 0
    failures: int = 0


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
            results = self.retrieve_similar(content, top_k=top_k)
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
        memory_key: Optional[str] = None,
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
            memory_key: Stable key for an exact structured-memory record

        Returns:
            Tuple of (success: bool, reason: str, memory_id: Optional[int])
        """
        if memory_key is not None:
            keyed_memory = self.memory_store.get_memory_by_key(memory_key)
            if keyed_memory is not None:
                return (
                    False,
                    f"duplicate_key: memory_id={keyed_memory['id']}",
                    keyed_memory["id"],
                )

        # Check for semantic duplicates if enabled for unkeyed stores.
        if check_duplicates and memory_key is None:
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

        try:
            memory_id = self.memory_store.create_memory(
                content=content,
                layer=layer,
                memory_key=memory_key,
                person=person,
                source_type=source_type,
                topic=classified_topic,
                event_time=event_time,
                strength=strength,
            )
        except Exception as e:
            return False, f"storage_error: {str(e)}", None

        try:
            memory = self.memory_store.get_memory_by_id(memory_id)
            if memory is not None and self._index_memory(memory):
                return True, "stored_successfully", memory_id
        except Exception:
            pass
        return True, "stored_pending_index", memory_id

    def reconcile_index(self) -> IndexReconciliationResult:
        """Repair derived vectors and finish tombstoned deletions safely."""

        indexed_memories = 0
        cleaned_tombstones = 0
        removed_orphan_vectors = 0
        failures = 0

        try:
            tombstones = self.memory_store.get_tombstoned_memories()
        except Exception:
            tombstones = []
            failures += 1
        for memory in tombstones:
            try:
                self.vector_store.delete_vector(memory["id"])
                if not self.memory_store.purge_tombstone(memory["id"]):
                    failures += 1
                    continue
                cleaned_tombstones += 1
            except Exception:
                failures += 1

        try:
            active_memories = self.memory_store.get_memories()
        except Exception:
            active_memories = []
            failures += 1
        try:
            vector_ids: set[int] | None = self.vector_store.list_memory_ids()
        except Exception:
            vector_ids = None
            failures += 1
        for memory in active_memories:
            needs_index = memory["indexed_revision"] != memory["revision"] or (
                vector_ids is not None and memory["id"] not in vector_ids
            )
            if not needs_index:
                continue
            try:
                if self._index_memory(memory):
                    indexed_memories += 1
                    if vector_ids is not None:
                        vector_ids.add(memory["id"])
                else:
                    failures += 1
            except Exception:
                failures += 1

        if vector_ids is None:
            orphan_ids: set[int] = set()
        else:
            try:
                stored_ids = self.memory_store.get_all_memory_ids()
                orphan_ids = vector_ids - stored_ids
            except Exception:
                orphan_ids = set()
                failures += 1
        for memory_id in orphan_ids:
            try:
                self.vector_store.delete_vector(memory_id)
                removed_orphan_vectors += 1
            except Exception:
                failures += 1

        return IndexReconciliationResult(
            indexed_memories=indexed_memories,
            cleaned_tombstones=cleaned_tombstones,
            removed_orphan_vectors=removed_orphan_vectors,
            failures=failures,
        )

    def retrieve_similar(
        self,
        query: str,
        top_k: int = 5,
        person: Optional[str] = None,
        topic: Optional[str] = None,
        layer: Optional[str] = None,
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
        self.reconcile_index()
        return self.retriever.retrieve_similar(
            query=query,
            top_k=top_k,
            person=person,
            topic=topic,
            layer=layer,
        )

    def get_memory_by_key(self, memory_key: str) -> Optional[dict]:
        """Retrieve one project-owned structured record by stable key."""

        return self.memory_store.get_memory_by_key(memory_key)

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
        expected_revision: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Update authoritative memory state and refresh its derived embedding.

        Args:
            memory_id: ID of memory to update
            content: New content (optional)
            layer: New layer (optional)
            person: New person (optional)
            topic: New topic (optional)
            source_type: New source type (optional)
            event_time: New event time (optional)
            strength: New strength value (optional)
            expected_revision: Revision that must still be current (optional)

        Returns:
            Tuple of (success: bool, reason: str)
        """
        try:
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
                expected_revision=expected_revision,
            )

            if not success:
                current_memory = self.memory_store.get_memory_by_id(memory_id)
                if current_memory is None:
                    return False, "memory_not_found"
                if (
                    expected_revision is not None
                    and current_memory["revision"] != expected_revision
                ):
                    return False, "memory_revision_conflict"
                return False, "no_changes"

            current_memory = self.memory_store.get_memory_by_id(memory_id)
            if current_memory is None:
                return False, "memory_not_found"

            try:
                if content is not None:
                    indexed = self._index_memory(current_memory)
                elif self._memory_index_is_current(original_memory):
                    indexed = self.memory_store.mark_memory_indexed(
                        memory_id,
                        current_memory["revision"],
                    )
                else:
                    indexed = False
            except Exception:
                indexed = False

            if indexed:
                return True, "updated_successfully"
            return True, "updated_pending_index"

        except Exception as e:
            return False, f"update_error: {str(e)}"

    def delete_memory(
        self,
        memory_id: int,
        expected_revision: Optional[int] = None,
    ) -> Tuple[bool, str]:
        """
        Delete a memory and its vector.

        Args:
            memory_id: ID of memory to delete

        Returns:
            Tuple of (success: bool, reason: str)
        """
        try:
            success = self.memory_store.tombstone_memory(
                memory_id,
                expected_revision=expected_revision,
            )
            if not success:
                current_memory = self.memory_store.get_memory_by_id(memory_id)
                if current_memory is not None and expected_revision is not None:
                    return False, "memory_revision_conflict"
                return False, "memory_not_found"

            try:
                self.vector_store.delete_vector(memory_id)
                if not self.memory_store.purge_tombstone(memory_id):
                    return True, "deleted_pending_index_cleanup"
            except Exception:
                return True, "deleted_pending_index_cleanup"

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

        if action.list_operation is not None:
            return self._process_structured_list_action(action)

        if action_type == "store":
            assert action.content is not None
            memory_key = action.target.memory_key if action.target is not None else None
            success, reason, _ = self.store_memory(
                content=action.content,
                layer="feedback",
                memory_key=memory_key,
                validate=False,
            )
            return success, reason

        elif action_type == "update":
            assert action.content is not None
            assert action.target is not None
            target, error = self._resolve_memory_target(action.target)
            if target is None:
                return False, error
            return self.update_memory(
                target["id"],
                content=action.content,
                expected_revision=action.target.expected_revision,
            )

        elif action_type == "delete":
            assert action.target is not None
            target, error = self._resolve_memory_target(action.target)
            if target is None:
                return False, error
            return self.delete_memory(
                target["id"],
                expected_revision=action.target.expected_revision,
            )

        else:
            return False, f"unknown_action: {action_type}"

    def _process_structured_list_action(
        self,
        action: MemoryAction,
    ) -> Tuple[bool, str]:
        operation = action.list_operation
        target = action.target
        assert operation is not None
        assert target is not None

        if action.action == "store":
            success, reason, _ = self.store_memory(
                content=create_structured_list(operation),
                layer="feedback",
                memory_key=operation.memory_key,
                topic=structured_list_topic(operation),
                validate=False,
                auto_classify=False,
                auto_extract=False,
            )
            return success, reason

        memory, error = self._resolve_memory_target(target)
        if memory is None:
            return False, error
        if memory.get("memory_key") != operation.memory_key:
            return False, "structured_list_target_mismatch"

        updated_content = apply_structured_list_operation(
            memory["content"],
            operation,
        )
        if updated_content is None:
            return False, "invalid_structured_list_content"
        return self.update_memory(
            memory["id"],
            content=updated_content,
            expected_revision=target.expected_revision,
        )

    def _resolve_memory_target(
        self,
        target: MemoryTarget,
    ) -> tuple[dict | None, str]:
        if target.memory_id is not None:
            memory = self.memory_store.get_memory_by_id(target.memory_id)
        else:
            assert target.memory_key is not None
            memory = self.memory_store.get_memory_by_key(target.memory_key)

        if memory is None:
            return None, "memory_target_not_found"
        if (
            target.memory_key is not None
            and memory.get("memory_key") != target.memory_key
        ):
            return None, "memory_target_mismatch"
        if (
            target.expected_revision is not None
            and memory.get("revision") != target.expected_revision
        ):
            return None, "memory_revision_conflict"
        return memory, ""

    def get_context_memories(
        self,
        query: str,
        context_size: int = 3,
    ) -> list[dict]:
        """
        Get relevant memory snippets for context (for reasoning engine).

        Args:
            query: Current conversation query
            context_size: Number of memories to retrieve

        Returns:
            Identified memory records suitable for an application adapter
        """
        try:
            memories = self.retrieve_similar(query, top_k=context_size)
            return memories
        except Exception:
            return []

    def get_all_memories(self) -> list[dict]:
        """Get all stored memories."""
        return self.retriever.retrieve_all()

    def _index_memory(self, memory: dict) -> bool:
        """Write one derived vector and mark only its still-current revision."""

        embedding = self.embedding_service.get_embedding(memory["content"])
        self.vector_store.save_vector(memory["id"], embedding)
        return self.memory_store.mark_memory_indexed(
            memory["id"],
            memory["revision"],
        )

    def _memory_index_is_current(self, memory: dict) -> bool:
        """Return whether SQL and the derived vector agree for one revision."""

        revision_is_indexed = memory["indexed_revision"] == memory["revision"]
        return revision_is_indexed and self.vector_store.has_vector(memory["id"])

    def close(self):
        """Close all storage connections."""
        self.memory_store.close()
        self.vector_store.close()
