"""High-level memory management orchestrating storage, validation, and retrieval."""

from dataclasses import dataclass
from typing import Optional

from voice_concierge.memory.embedding_service import EmbeddingService
from voice_concierge.memory.memory_retriever import MemoryRetriever
from voice_concierge.memory.memory_store import MemoryStore
from voice_concierge.memory.memory_validator import MemoryValidator
from voice_concierge.memory.structured_lists import (
    apply_structured_list_operation,
    create_structured_list,
    structured_list_topic,
)
from voice_concierge.memory.types import (
    ExtractedMemoryMetadata,
    MemoryOperationOutcome,
    MemoryOperationStatus,
    MemoryRecord,
    MemorySearchResult,
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
    ) -> MemorySearchResult | None:
        """
        Find semantically similar existing memory.

        Args:
            content: Memory content to match
            threshold: Similarity threshold (0-1), higher = more strict
            top_k: Number of candidates to check

        Returns:
            Most similar typed search result above the threshold, else None
        """
        try:
            results = self.retrieve_similar(content, top_k=top_k)
            if results and results[0].distance < (1.0 - threshold):
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
    ) -> MemoryOperationOutcome:
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
            Typed operation outcome with an optional affected memory ID
        """
        if not isinstance(content, str):
            return MemoryOperationOutcome(
                MemoryOperationStatus.VALIDATION_FAILED,
                detail="invalid_content_type",
            )
        if not content.strip():
            return MemoryOperationOutcome(
                MemoryOperationStatus.VALIDATION_FAILED,
                detail="empty_content",
            )

        if memory_key is not None:
            try:
                keyed_memory = self.memory_store.get_memory_by_key(memory_key)
            except Exception as error:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.STORAGE_ERROR,
                    detail=_exception_detail(error),
                )
            if keyed_memory is not None:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.DUPLICATE_KEY,
                    memory_id=keyed_memory.id,
                    detail=f"memory_id={keyed_memory.id}",
                )

        # Check for semantic duplicates if enabled for unkeyed stores.
        if check_duplicates and memory_key is None:
            similar = self.find_similar_memory(content, threshold=0.9)
            if similar:
                memory_id = similar.memory.id
                return MemoryOperationOutcome(
                    MemoryOperationStatus.DUPLICATE_FOUND,
                    memory_id=memory_id,
                    detail=f"memory_id={memory_id}",
                )

        # Validate if enabled
        if validate:
            try:
                should_store, reason = self.validator.should_store(content)
            except Exception as error:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.VALIDATION_FAILED,
                    detail=_exception_detail(error),
                )
            if not should_store:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.VALIDATION_FAILED,
                    detail=reason,
                )

        # Auto-extract metadata if enabled
        if auto_extract:
            try:
                extracted_value = self.validator.extract_metadata(content)
            except Exception:
                extracted_value = None
            extracted = ExtractedMemoryMetadata.from_value(extracted_value)
            if person is None:
                person = extracted.person
            if source_type is None:
                source_type = extracted.source_type
            if event_time is None:
                event_time = extracted.event_time
            if strength is None:
                strength = extracted.strength

        # Set default strength if still None
        if strength is None:
            strength = 5

        # Auto-classify memory type if enabled and topic not provided
        classified_topic = topic
        if auto_classify and topic is None:
            try:
                memory_type, _ = self.validator.classify_memory_type(content)
            except Exception:
                memory_type = None
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
            return MemoryOperationOutcome(
                MemoryOperationStatus.STORAGE_ERROR,
                detail=_exception_detail(e),
            )

        try:
            memory = self.memory_store.get_memory_by_id(memory_id)
            if memory is not None and self._index_memory(memory):
                return MemoryOperationOutcome(
                    MemoryOperationStatus.STORED_SUCCESSFULLY,
                    memory_id=memory_id,
                )
        except Exception:
            pass
        return MemoryOperationOutcome(
            MemoryOperationStatus.STORED_PENDING_INDEX,
            memory_id=memory_id,
        )

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
                self.vector_store.delete_vector(memory.id)
                if not self.memory_store.purge_tombstone(memory.id):
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
            needs_index = memory.indexed_revision != memory.revision or (
                vector_ids is not None and memory.id not in vector_ids
            )
            if not needs_index:
                continue
            try:
                if self._index_memory(memory):
                    indexed_memories += 1
                    if vector_ids is not None:
                        vector_ids.add(memory.id)
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
    ) -> list[MemorySearchResult]:
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

    def get_memory_by_key(self, memory_key: str) -> MemoryRecord | None:
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
    ) -> MemoryOperationOutcome:
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
            Typed operation outcome
        """
        if not _is_positive_int(memory_id):
            return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_NOT_FOUND)

        try:
            original_memory = self.memory_store.get_memory_by_id(memory_id)
            if not original_memory:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.MEMORY_NOT_FOUND,
                    memory_id=memory_id,
                )

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
                    return MemoryOperationOutcome(
                        MemoryOperationStatus.MEMORY_NOT_FOUND,
                        memory_id=memory_id,
                    )
                if (
                    expected_revision is not None
                    and current_memory.revision != expected_revision
                ):
                    return MemoryOperationOutcome(
                        MemoryOperationStatus.MEMORY_REVISION_CONFLICT,
                        memory_id=memory_id,
                    )
                return MemoryOperationOutcome(
                    MemoryOperationStatus.NO_CHANGES,
                    memory_id=memory_id,
                )

            current_memory = self.memory_store.get_memory_by_id(memory_id)
            if current_memory is None:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.MEMORY_NOT_FOUND,
                    memory_id=memory_id,
                )

            try:
                if content is not None:
                    indexed = self._index_memory(current_memory)
                elif self._memory_index_is_current(original_memory):
                    indexed = self.memory_store.mark_memory_indexed(
                        memory_id,
                        current_memory.revision,
                    )
                else:
                    indexed = False
            except Exception:
                indexed = False

            if indexed:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.UPDATED_SUCCESSFULLY,
                    memory_id=memory_id,
                )
            return MemoryOperationOutcome(
                MemoryOperationStatus.UPDATED_PENDING_INDEX,
                memory_id=memory_id,
            )

        except Exception as e:
            return MemoryOperationOutcome(
                MemoryOperationStatus.UPDATE_ERROR,
                memory_id=memory_id,
                detail=_exception_detail(e),
            )

    def delete_memory(
        self,
        memory_id: int,
        expected_revision: Optional[int] = None,
    ) -> MemoryOperationOutcome:
        """
        Delete a memory and its vector.

        Args:
            memory_id: ID of memory to delete

        Returns:
            Typed operation outcome
        """
        if not _is_positive_int(memory_id):
            return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_NOT_FOUND)

        try:
            success = self.memory_store.tombstone_memory(
                memory_id,
                expected_revision=expected_revision,
            )
            if not success:
                current_memory = self.memory_store.get_memory_by_id(memory_id)
                if current_memory is not None and expected_revision is not None:
                    return MemoryOperationOutcome(
                        MemoryOperationStatus.MEMORY_REVISION_CONFLICT,
                        memory_id=memory_id,
                    )
                return MemoryOperationOutcome(
                    MemoryOperationStatus.MEMORY_NOT_FOUND,
                    memory_id=memory_id,
                )

            try:
                self.vector_store.delete_vector(memory_id)
                if not self.memory_store.purge_tombstone(memory_id):
                    return MemoryOperationOutcome(
                        MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP,
                        memory_id=memory_id,
                    )
            except Exception:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP,
                    memory_id=memory_id,
                )

            return MemoryOperationOutcome(
                MemoryOperationStatus.DELETED_SUCCESSFULLY,
                memory_id=memory_id,
            )

        except Exception as e:
            return MemoryOperationOutcome(
                MemoryOperationStatus.DELETE_ERROR,
                memory_id=memory_id,
                detail=_exception_detail(e),
            )

    def process_memory_action(self, action: MemoryAction) -> MemoryOperationOutcome:
        """
        Process a proposed memory action from the reasoning engine.

        Args:
            action: MemoryAction from ReasoningResponse

        Returns:
            Typed operation outcome
        """
        try:
            return self._apply_memory_action(action)
        except Exception as error:
            return MemoryOperationOutcome(
                MemoryOperationStatus.MEMORY_ACTION_ERROR,
                detail=_exception_detail(error),
            )

    def _apply_memory_action(self, action: MemoryAction) -> MemoryOperationOutcome:
        """Apply one already-validated memory proposal."""

        if action.list_operation is not None:
            return self._process_structured_list_action(action)

        if action.action == "store":
            assert action.content is not None
            memory_key = action.target.memory_key if action.target is not None else None
            return self.store_memory(
                content=action.content,
                layer="feedback",
                memory_key=memory_key,
                validate=False,
            )

        elif action.action == "update":
            assert action.content is not None
            assert action.target is not None
            target, error = self._resolve_memory_target(action.target)
            if target is None:
                assert error is not None
                return MemoryOperationOutcome(error)
            return self.update_memory(
                target.id,
                content=action.content,
                expected_revision=action.target.expected_revision,
            )

        elif action.action == "delete":
            assert action.target is not None
            target, error = self._resolve_memory_target(action.target)
            if target is None:
                assert error is not None
                return MemoryOperationOutcome(error)
            return self.delete_memory(
                target.id,
                expected_revision=action.target.expected_revision,
            )

        else:
            return MemoryOperationOutcome(
                MemoryOperationStatus.UNKNOWN_ACTION,
                detail=action.action,
            )

    def _process_structured_list_action(
        self,
        action: MemoryAction,
    ) -> MemoryOperationOutcome:
        operation = action.list_operation
        target = action.target
        assert operation is not None
        assert target is not None

        if action.action == "store":
            return self.store_memory(
                content=create_structured_list(operation),
                layer="feedback",
                memory_key=operation.memory_key,
                topic=structured_list_topic(operation),
                validate=False,
                auto_classify=False,
                auto_extract=False,
            )

        memory, error = self._resolve_memory_target(target)
        if memory is None:
            assert error is not None
            return MemoryOperationOutcome(error)
        if memory.memory_key != operation.memory_key:
            return MemoryOperationOutcome(
                MemoryOperationStatus.STRUCTURED_LIST_TARGET_MISMATCH
            )

        updated_content = apply_structured_list_operation(
            memory.content,
            operation,
        )
        if updated_content is None:
            return MemoryOperationOutcome(
                MemoryOperationStatus.INVALID_STRUCTURED_LIST_CONTENT
            )
        return self.update_memory(
            memory.id,
            content=updated_content,
            expected_revision=target.expected_revision,
        )

    def _resolve_memory_target(
        self,
        target: MemoryTarget,
    ) -> tuple[MemoryRecord | None, MemoryOperationStatus | None]:
        if target.memory_id is not None:
            memory = self.memory_store.get_memory_by_id(target.memory_id)
        else:
            assert target.memory_key is not None
            memory = self.memory_store.get_memory_by_key(target.memory_key)

        if memory is None:
            return None, MemoryOperationStatus.MEMORY_TARGET_NOT_FOUND
        if target.memory_key is not None and memory.memory_key != target.memory_key:
            return None, MemoryOperationStatus.MEMORY_TARGET_MISMATCH
        if (
            target.expected_revision is not None
            and memory.revision != target.expected_revision
        ):
            return None, MemoryOperationStatus.MEMORY_REVISION_CONFLICT
        return memory, None

    def get_context_memories(
        self,
        query: str,
        context_size: int = 3,
    ) -> list[MemorySearchResult]:
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

    def get_all_memories(self) -> list[MemoryRecord]:
        """Get all stored memories."""
        return self.retriever.retrieve_all()

    def _index_memory(self, memory: MemoryRecord) -> bool:
        """Write one derived vector and mark only its still-current revision."""

        embedding = self.embedding_service.get_embedding(memory.content)
        self.vector_store.save_vector(memory.id, embedding)
        return self.memory_store.mark_memory_indexed(
            memory.id,
            memory.revision,
        )

    def _memory_index_is_current(self, memory: MemoryRecord) -> bool:
        """Return whether SQL and the derived vector agree for one revision."""

        revision_is_indexed = memory.indexed_revision == memory.revision
        return revision_is_indexed and self.vector_store.has_vector(memory.id)

    def close(self) -> None:
        """Close all storage connections."""
        self.memory_store.close()
        self.vector_store.close()


def _is_positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _exception_detail(error: Exception) -> str:
    """Return a non-blank diagnostic without changing the stable status code."""

    return str(error).strip() or error.__class__.__name__
