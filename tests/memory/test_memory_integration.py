"""Integration tests for complete memory system."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voice_concierge.memory import (
    ApplyStructuredListCommand,
    DeleteMemoryCommand,
    MemoryCommandTarget,
    MemoryManager,
    MemoryOperationStatus,
    MemorySearchResult,
    MemoryStore,
    MemoryValidator,
    StoreMemoryCommand,
    StructuredListMutation,
    VectorStore,
)
from voice_concierge.privacy import PrivacyCentre


def _shopping_add(*items: str) -> StructuredListMutation:
    return StructuredListMutation(
        list_name="shopping",
        items=items,
    )


@pytest.fixture
def memory_manager(tmp_path, fake_embedding_service):
    """Create a complete memory manager for testing."""
    db_path = str(tmp_path / "test_memory.db")
    vector_db_path = str(tmp_path / "test_vector.db")

    memory_store = MemoryStore(db_path)
    vector_store = VectorStore(vector_db_path)
    validator = MemoryValidator()

    manager = MemoryManager(
        memory_store=memory_store,
        vector_store=vector_store,
        embedding_service=fake_embedding_service,
        validator=validator,
    )

    yield manager

    manager.close()


class TestMemoryManagerBasic:
    """Test basic memory operations through MemoryManager."""

    def test_store_and_retrieve(self, memory_manager):
        """Store a memory and retrieve it."""
        content = "user prefers short answers"
        store_outcome = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
        )

        assert store_outcome.succeeded is True
        assert store_outcome.memory_id is not None

        all_memories = memory_manager.get_all_memories()
        assert len(all_memories) == 1
        assert all_memories[0].content == content

    def test_store_with_metadata(self, memory_manager):
        """Store a memory with metadata."""
        store_outcome = memory_manager.store_memory(
            content="likes pizza",
            layer="profile",
            person="Kenny",
            topic="food",
            validate=False,
        )

        assert store_outcome.succeeded is True

        memories = memory_manager.retriever.retrieve_by_person("Kenny")
        assert len(memories) == 1
        assert memories[0].person == "Kenny"
        assert memories[0].topic == "food"

    def test_get_memory_by_key_does_not_depend_on_semantic_ranking(
        self,
        memory_manager,
        monkeypatch,
    ):
        """Project-owned records remain addressable when vector search misses."""

        store_outcome = memory_manager.store_memory(
            content="Shopping list: milk.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None
        monkeypatch.setattr(
            memory_manager.vector_store,
            "search_similar",
            lambda query_embedding, top_k: [],
        )

        memory = memory_manager.get_memory_by_key("list:shopping")

        assert memory is not None
        assert memory.id == memory_id
        assert memory.content == "Shopping list: milk."

    def test_update_memory(self, memory_manager):
        """Update an existing memory."""
        store_outcome = memory_manager.store_memory(
            content="old content",
            layer="profile",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        outcome = memory_manager.update_memory(
            memory_id=memory_id,
            content="new content",
        )

        assert outcome.succeeded is True

        memories = memory_manager.get_all_memories()
        assert memories[0].content == "new content"

    def test_invalid_memory_id_returns_typed_not_found(self, memory_manager):
        update = memory_manager.update_memory(0, content="new content")
        delete = memory_manager.delete_memory(False)

        assert update.status is MemoryOperationStatus.MEMORY_NOT_FOUND
        assert delete.status is MemoryOperationStatus.MEMORY_NOT_FOUND
        assert update.memory_id is None
        assert delete.memory_id is None

    def test_invalid_update_is_typed_and_preserves_record(self, memory_manager):
        store_outcome = memory_manager.store_memory(
            content="valid content",
            layer="profile",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        outcome = memory_manager.update_memory(memory_id, content="  ")

        assert outcome.status is MemoryOperationStatus.UPDATE_ERROR
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory is not None
        assert memory.content == "valid content"

    def test_validator_exception_returns_typed_failure(
        self,
        memory_manager,
        monkeypatch,
    ):
        def fail_validation(content):
            raise RuntimeError("validator unavailable")

        monkeypatch.setattr(
            memory_manager.validator,
            "should_store",
            fail_validation,
        )

        outcome = memory_manager.store_memory("remember this", "profile")

        assert outcome.status is MemoryOperationStatus.VALIDATION_FAILED
        assert outcome.detail == "validator unavailable"

    def test_optional_metadata_failure_does_not_block_storage(
        self,
        memory_manager,
        monkeypatch,
    ):
        def fail_metadata(content):
            raise RuntimeError("metadata unavailable")

        monkeypatch.setattr(
            memory_manager.validator,
            "extract_metadata",
            fail_metadata,
        )

        outcome = memory_manager.store_memory(
            "remember this",
            "profile",
            validate=False,
            auto_classify=False,
        )

        assert outcome.status is MemoryOperationStatus.STORED_SUCCESSFULLY

    def test_metadata_update_advances_indexed_revision_without_reembedding(
        self,
        memory_manager,
        monkeypatch,
    ):
        store_outcome = memory_manager.store_memory(
            content="Content stays the same",
            layer="profile",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        def fail_if_embedded(content):
            raise AssertionError("metadata-only update should not re-embed content")

        monkeypatch.setattr(
            memory_manager.embedding_service,
            "get_embedding",
            fail_if_embedded,
        )

        outcome = memory_manager.update_memory(
            memory_id,
            strength=8,
            expected_revision=1,
        )

        assert outcome.succeeded is True
        assert outcome.status is MemoryOperationStatus.UPDATED_SUCCESSFULLY
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory.strength == 8
        assert memory.indexed_revision == memory.revision == 2

    def test_delete_memory(self, memory_manager):
        """Delete a memory."""
        store_outcome = memory_manager.store_memory(
            content="to delete",
            layer="raw",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        outcome = memory_manager.delete_memory(memory_id)
        assert outcome.succeeded is True

        memories = memory_manager.get_all_memories()
        assert len(memories) == 0

    def test_privacy_centre_uses_typed_manager_boundary(self, memory_manager):
        """The real manager supports privacy review, correction, and deletion."""

        stored = memory_manager.store_memory(
            content="I prefer coffee",
            layer="profile",
            validate=False,
        )
        memory_id = stored.memory_id
        assert memory_id is not None
        centre = PrivacyCentre(memory_manager)

        listed = centre.list_memories()
        assert [(memory.identifier, memory.content) for memory in listed] == [
            (memory_id, "I prefer coffee")
        ]

        updated = centre.edit_memory(memory_id, "I prefer tea")
        assert updated.content == "I prefer tea"
        assert updated.revision == 2

        centre.delete_memory(memory_id)
        assert memory_manager.get_memory_by_id(memory_id) is None
        assert not memory_manager.vector_store.has_vector(memory_id)

    def test_execute_memory_store_command(self, memory_manager):
        command = StoreMemoryCommand(
            content="remember to call mom",
            layer="feedback",
        )

        outcome = memory_manager.execute_memory_command(command)
        assert outcome.succeeded is True

        memories = memory_manager.get_all_memories()
        assert len(memories) == 1
        assert "call mom" in memories[0].content

    def test_process_update_targets_exact_key_not_semantic_match(self, memory_manager):
        """A shopping update cannot overwrite an unrelated preference."""
        preference_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            memory_key="preference:drink",
            validate=False,
            check_duplicates=False,
        )
        preference_id = preference_outcome.memory_id
        assert preference_id is not None
        shopping_outcome = memory_manager.store_memory(
            content="Shopping list: bread.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        shopping_id = shopping_outcome.memory_id
        assert shopping_id is not None
        command = ApplyStructuredListCommand(
            target=MemoryCommandTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
            mutation=_shopping_add("milk"),
        )

        outcome = memory_manager.execute_memory_command(command)

        assert outcome.succeeded is True
        assert outcome.status is MemoryOperationStatus.UPDATED_SUCCESSFULLY
        assert (
            memory_manager.memory_store.get_memory_by_id(preference_id).content
            == "I prefer tea"
        )
        assert (
            memory_manager.memory_store.get_memory_by_id(shopping_id).content
            == "Shopping list: bread, milk."
        )

    def test_process_shopping_update_deduplicates_items(self, memory_manager):
        store_outcome = memory_manager.store_memory(
            content="Shopping list: bread, milk.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        shopping_id = store_outcome.memory_id
        assert shopping_id is not None
        command = ApplyStructuredListCommand(
            target=MemoryCommandTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
            mutation=_shopping_add("Milk", "eggs"),
        )

        outcome = memory_manager.execute_memory_command(command)

        assert outcome.succeeded is True
        assert outcome.status is MemoryOperationStatus.UPDATED_SUCCESSFULLY
        assert (
            memory_manager.memory_store.get_memory_by_id(shopping_id).content
            == "Shopping list: bread, milk, eggs."
        )

    def test_structured_list_operation_rejects_exact_non_list_target(
        self,
        memory_manager,
    ):
        store_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        preference_id = store_outcome.memory_id
        assert preference_id is not None
        command = ApplyStructuredListCommand(
            target=MemoryCommandTarget(
                memory_id=preference_id,
                expected_revision=1,
            ),
            mutation=_shopping_add("milk"),
        )

        outcome = memory_manager.execute_memory_command(command)

        assert outcome.succeeded is False
        assert outcome.status is MemoryOperationStatus.STRUCTURED_LIST_TARGET_MISMATCH
        assert (
            memory_manager.memory_store.get_memory_by_id(preference_id).content
            == "I prefer tea"
        )

    def test_process_update_without_stable_target_fails_closed(self, memory_manager):
        store_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        preference_id = store_outcome.memory_id
        assert preference_id is not None
        with pytest.raises(ValueError, match="requires an ID or stable key"):
            MemoryCommandTarget()

        assert (
            memory_manager.memory_store.get_memory_by_id(preference_id).content
            == "I prefer tea"
        )

    def test_process_delete_without_stable_target_fails_closed(self, memory_manager):
        store_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        preference_id = store_outcome.memory_id
        assert preference_id is not None
        with pytest.raises(ValueError, match="requires an ID or stable key"):
            MemoryCommandTarget()

        assert memory_manager.memory_store.get_memory_by_id(preference_id) is not None

    def test_process_delete_targets_exact_key(self, memory_manager):
        preference_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            memory_key="preference:drink",
            validate=False,
            check_duplicates=False,
        )
        preference_id = preference_outcome.memory_id
        assert preference_id is not None
        shopping_outcome = memory_manager.store_memory(
            content="Shopping list: bread.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        shopping_id = shopping_outcome.memory_id
        assert shopping_id is not None
        command = DeleteMemoryCommand(
            target=MemoryCommandTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
        )

        outcome = memory_manager.execute_memory_command(command)

        assert outcome.succeeded is True
        assert outcome.status is MemoryOperationStatus.DELETED_SUCCESSFULLY
        assert memory_manager.memory_store.get_memory_by_key("list:shopping") is None
        assert memory_manager.memory_store.get_memory_by_id(preference_id) is not None

    def test_process_update_rejects_stale_revision(self, memory_manager):
        store_outcome = memory_manager.store_memory(
            content="Shopping list: bread.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        shopping_id = store_outcome.memory_id
        assert shopping_id is not None
        update_outcome = memory_manager.update_memory(
            shopping_id,
            content="Shopping list: bread, eggs.",
            expected_revision=1,
        )
        assert update_outcome.status is MemoryOperationStatus.UPDATED_SUCCESSFULLY
        stale_command = ApplyStructuredListCommand(
            target=MemoryCommandTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
            mutation=_shopping_add("milk"),
        )

        outcome = memory_manager.execute_memory_command(stale_command)

        assert outcome.succeeded is False
        assert outcome.status is MemoryOperationStatus.MEMORY_REVISION_CONFLICT
        assert memory_manager.memory_store.get_memory_by_id(shopping_id).content == (
            "Shopping list: bread, eggs."
        )

    def test_missing_revision_checked_list_is_not_recreated(self, memory_manager):
        command = ApplyStructuredListCommand(
            target=MemoryCommandTarget(
                memory_key="list:shopping",
                expected_revision=1,
            ),
            mutation=_shopping_add("milk"),
        )

        outcome = memory_manager.execute_memory_command(command)

        assert outcome.status is MemoryOperationStatus.MEMORY_TARGET_NOT_FOUND
        assert memory_manager.get_memory_by_key("list:shopping") is None


class TestMemoryRetrieval:
    """Test memory retrieval capabilities."""

    def test_scoped_search_cannot_be_crowded_out_by_other_layers(
        self,
        memory_manager,
    ):
        for index in range(3):
            memory_manager.store_memory(
                content=f"Shopping item {index}",
                layer="feedback",
                topic="shopping",
                validate=False,
                auto_classify=False,
                auto_extract=False,
                check_duplicates=False,
            )
        profile_outcome = memory_manager.store_memory(
            content="User prefers tea",
            layer="profile",
            validate=False,
            auto_classify=False,
            auto_extract=False,
            check_duplicates=False,
        )

        results = memory_manager.retrieve_similar(
            "anything",
            top_k=1,
            layer="profile",
        )

        assert [result.memory.id for result in results] == [profile_outcome.memory_id]

    @pytest.mark.skip(reason="Requires Ollama embedding service running")
    def test_semantic_search(self, memory_manager):
        """Test semantic similarity search."""
        # Store related memories
        memory_manager.store_memory(
            "I love Italian food", "profile", topic="food", validate=False
        )
        memory_manager.store_memory(
            "Pizza is my favorite", "profile", topic="food", validate=False
        )
        memory_manager.store_memory(
            "I work as a software engineer", "profile", topic="job", validate=False
        )

        # Search for food-related memories
        results = memory_manager.retrieve_similar("what food do you like", top_k=2)

        assert len(results) <= 2
        assert all(isinstance(result.distance, float) for result in results)

    def test_retrieve_by_person(self, memory_manager):
        """Test filtering memories by person."""
        memory_manager.store_memory(
            "Kenny likes cats", "profile", person="Kenny", validate=False
        )
        memory_manager.store_memory(
            "Alice likes dogs", "profile", person="Alice", validate=False
        )

        kenny_memories = memory_manager.retriever.retrieve_by_person("Kenny")
        assert len(kenny_memories) == 1
        assert "cats" in kenny_memories[0].content

    def test_retrieve_by_topic(self, memory_manager):
        """Test filtering memories by topic."""
        memory_manager.store_memory(
            "favorite pizza place", "profile", topic="food", validate=False
        )
        memory_manager.store_memory(
            "software engineer role", "profile", topic="job", validate=False
        )

        food_memories = memory_manager.retriever.retrieve_by_topic("food")
        assert len(food_memories) == 1
        assert "pizza" in food_memories[0].content

    def test_metadata_filtering(self, memory_manager):
        """Test combined metadata filtering."""
        memory_manager.store_memory(
            "Kenny likes pizza", "profile", person="Kenny", topic="food", validate=False
        )
        memory_manager.store_memory(
            "Kenny is a developer",
            "profile",
            person="Kenny",
            topic="job",
            validate=False,
        )

        results = memory_manager.retriever.retrieve_by_metadata(
            person="Kenny", topic="food"
        )
        assert len(results) == 1
        assert "pizza" in results[0].content

    def test_retrieve_by_layer(self, memory_manager):
        """Test filtering memories by layer."""
        memory_manager.store_memory("Milk and eggs", "shopping-list", validate=False)
        memory_manager.store_memory(
            "Prefers coffee in the morning", "profile", validate=False
        )

        shopping_memories = memory_manager.retriever.retrieve_by_layer("shopping-list")
        assert len(shopping_memories) == 1
        assert "Milk and eggs" in shopping_memories[0].content

    def test_layer_and_source_type_separate(self, memory_manager):
        """Test that layer and source_type filters are independent."""
        memory_manager.store_memory(
            "Buy groceries",
            "shopping-list",
            source_type="user_input",
            validate=False,
            check_duplicates=False,
        )
        memory_manager.store_memory(
            "User likes hiking",
            "profile",
            source_type="inference",
            validate=False,
            check_duplicates=False,
        )

        # Filter by layer should not be affected by source_type
        shopping = memory_manager.retriever.retrieve_by_layer("shopping-list")
        assert len(shopping) == 1
        assert shopping[0].layer == "shopping-list"

        profile = memory_manager.retriever.retrieve_by_layer("profile")
        assert len(profile) == 1
        assert profile[0].layer == "profile"

    def test_metadata_filtering_with_layer(self, memory_manager):
        """Test metadata filtering including layer."""
        memory_manager.store_memory(
            "Milk",
            "shopping-list",
            person="Kenny",
            topic="groceries",
            validate=False,
        )
        memory_manager.store_memory(
            "Bread",
            "shopping-list",
            person="Alice",
            topic="groceries",
            validate=False,
        )

        results = memory_manager.retriever.retrieve_by_metadata(
            person="Kenny", layer="shopping-list"
        )
        assert len(results) == 1
        assert results[0].person == "Kenny"
        assert results[0].layer == "shopping-list"


class TestMemoryValidation:
    """Test memory validation."""

    def test_reject_empty_memory(self, memory_manager):
        """Validator should reject empty memory."""
        store_outcome = memory_manager.store_memory(
            content="",
            layer="raw",
            validate=True,
        )

        assert store_outcome.succeeded is False
        assert store_outcome.status is MemoryOperationStatus.VALIDATION_FAILED
        assert store_outcome.detail == "empty_content"

    def test_reject_short_memory(self, memory_manager):
        """Validator should reject very short memory."""
        store_outcome = memory_manager.store_memory(
            content="ab",
            layer="raw",
            validate=True,
        )

        assert store_outcome.succeeded is False
        assert store_outcome.status is MemoryOperationStatus.VALIDATION_FAILED

    def test_skip_validation_flag(self, memory_manager):
        """Can skip validation with validate=False."""
        store_outcome = memory_manager.store_memory(
            content="x",
            layer="raw",
            validate=False,
        )

        assert store_outcome.succeeded is True


class TestDuplicatePrevention:
    """Test deterministic prevention and non-blocking semantic evidence."""

    def test_duplicate_count_stays_same(self, memory_manager):
        """Adding same memory twice should keep count at 1."""
        content = "I prefer tea"

        # Store first time
        first_outcome = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
            auto_classify=False,
            auto_extract=False,
            check_duplicates=False,  # First one, no check
        )
        assert first_outcome.succeeded is True

        all_memories = memory_manager.get_all_memories()
        assert len(all_memories) == 1

        # Store second time with harmless text variation.
        second_outcome = memory_manager.store_memory(
            content="  I PREFER\nTEA  ",
            layer="profile",
            validate=False,
            auto_classify=False,
            auto_extract=False,
            check_duplicates=True,  # Check for duplicates
        )

        # Should reject as duplicate
        assert second_outcome.succeeded is False
        assert second_outcome.status is MemoryOperationStatus.DUPLICATE_FOUND

        # Count should still be 1 (not 2)
        all_memories = memory_manager.get_all_memories()
        assert len(all_memories) == 1

    def test_semantic_match_in_same_scope_is_advisory_not_rejection(
        self,
        memory_manager,
    ):
        """Embedding proximity must not veto distinct content."""

        first_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            topic="preference",
            validate=False,
            auto_classify=False,
            auto_extract=False,
        )
        second_outcome = memory_manager.store_memory(
            content="I prefer coffee",
            layer="profile",
            topic="preference",
            validate=False,
            auto_classify=False,
            auto_extract=False,
        )

        assert second_outcome.status is MemoryOperationStatus.STORED_SUCCESSFULLY
        assert second_outcome.succeeded is True
        assert len(memory_manager.get_all_memories()) == 2
        assert len(second_outcome.similarity_advisories) == 1
        advisory = second_outcome.similarity_advisories[0]
        assert advisory.memory_id == first_outcome.memory_id
        assert advisory.distance == 0.0

    def test_semantic_match_does_not_cross_metadata_scope(self, memory_manager):
        """Unrelated domains must not influence one another's writes."""

        preference_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            topic="preference",
            validate=False,
            auto_classify=False,
            auto_extract=False,
        )
        shopping_outcome = memory_manager.store_memory(
            content="Milk",
            layer="feedback",
            topic="shopping",
            validate=False,
            auto_classify=False,
            auto_extract=False,
        )

        assert preference_outcome.succeeded is True
        assert shopping_outcome.succeeded is True
        assert shopping_outcome.similarity_advisories == ()
        assert {memory.content for memory in memory_manager.get_all_memories()} == {
            "Milk",
            "I prefer tea",
        }

    def test_disable_duplicate_check_allows_duplicates(self, memory_manager):
        """Disabling check allows storing duplicates."""
        content = "I prefer tea"

        # Store first time
        first_outcome = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        assert first_outcome.succeeded is True
        assert len(memory_manager.get_all_memories()) == 1

        # Store duplicate with check disabled
        second_outcome = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
            check_duplicates=False,  # Disable check
        )

        # Should allow it
        assert second_outcome.succeeded is True
        assert first_outcome.memory_id != second_outcome.memory_id

        # Count should be 2 (both stored)
        assert len(memory_manager.get_all_memories()) == 2


class TestContextMemories:
    """Test retrieving memories for context."""

    @pytest.mark.skip(reason="Requires Ollama embedding service running")
    def test_get_context_memories(self, memory_manager):
        """Get relevant memories for context."""
        memory_manager.store_memory(
            "user is named Kenny",
            "profile",
            validate=False,
        )
        memory_manager.store_memory(
            "user works at IBM",
            "profile",
            validate=False,
        )
        memory_manager.store_memory(
            "user likes AI research",
            "profile",
            validate=False,
        )

        context = memory_manager.get_context_memories(
            query="Tell me about yourself",
            context_size=2,
        )

        assert len(context) <= 2
        assert all(
            isinstance(result, MemorySearchResult)
            and isinstance(result.memory.id, int)
            and isinstance(result.memory.content, str)
            and isinstance(result.memory.revision, int)
            for result in context
        )


class TestSQLVectorConsistency:
    """Test SQL and vector store consistency."""

    def test_store_creates_both_sql_and_vector(self, memory_manager):
        """Storing a memory should create both SQL record and vector."""
        store_outcome = memory_manager.store_memory(
            content="I like coffee",
            layer="profile",
            validate=False,
        )

        assert store_outcome.succeeded is True
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        # Verify SQL record exists
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory is not None
        assert memory.content == "I like coffee"

        # Verify vector exists (by checking if search finds it)
        results = memory_manager.retrieve_similar("coffee", top_k=5)
        assert any(result.memory.id == memory_id for result in results)

    def test_failed_vector_replacement_preserves_previous_entry(
        self,
        memory_manager,
        monkeypatch,
    ):
        store_outcome = memory_manager.store_memory(
            content="Keep the existing vector",
            layer="profile",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        def fail_serialization(embedding):
            raise RuntimeError("serialization failed after delete statement")

        monkeypatch.setattr(
            "voice_concierge.memory.vector_store.serialize_float32",
            fail_serialization,
        )

        with pytest.raises(RuntimeError, match="serialization failed"):
            memory_manager.vector_store.save_vector(memory_id, [1.0] * 768)

        assert memory_manager.vector_store.has_vector(memory_id)

    def test_delete_removes_both_sql_and_vector(self, memory_manager):
        """Deleting a memory should remove both SQL record and vector."""
        # Create a memory
        store_outcome = memory_manager.store_memory(
            content="Remember this",
            layer="profile",
            validate=False,
        )
        assert store_outcome.succeeded is True
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        # Delete it
        outcome = memory_manager.delete_memory(memory_id)
        assert outcome.succeeded is True

        # Verify SQL record is deleted
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory is None

        # Verify vector is deleted (search should not find it)
        results = memory_manager.retrieve_similar("Remember this", top_k=10)
        assert not any(result.memory.id == memory_id for result in results)

    def test_update_keeps_sql_and_vector_in_sync(self, memory_manager):
        """Updating a memory should update both SQL and vector."""
        # Create a memory
        store_outcome = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
        )
        assert store_outcome.succeeded is True
        memory_id = store_outcome.memory_id
        assert memory_id is not None

        # Update the content
        outcome = memory_manager.update_memory(
            memory_id=memory_id,
            content="I prefer coffee",
        )
        assert outcome.succeeded is True

        # Verify SQL record is updated
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory.content == "I prefer coffee"

        # Verify vector still exists (by checking we can retrieve it)
        results = memory_manager.retrieve_similar("I prefer", top_k=10)
        assert any(result.memory.id == memory_id for result in results)
        assert results[0].memory.content == "I prefer coffee"

    def test_store_survives_vector_failure_and_reconciles(
        self,
        memory_manager,
        monkeypatch,
    ):
        """A failed derived write must not discard authoritative memory."""

        save_vector = memory_manager.vector_store.save_vector

        # Mock embedding service to fail
        def failing_save_vector(memory_id, embedding):
            raise RuntimeError("Vector storage failed")

        monkeypatch.setattr(
            memory_manager.vector_store, "save_vector", failing_save_vector
        )

        # Try to store a memory
        store_outcome = memory_manager.store_memory(
            content="This should fail",
            layer="profile",
            validate=False,
        )

        assert store_outcome.succeeded is True
        assert store_outcome.status is MemoryOperationStatus.STORED_PENDING_INDEX
        memory_id = store_outcome.memory_id
        assert memory_id is not None
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory is not None
        assert memory.content == "This should fail"
        assert memory.indexed_revision == 0
        assert memory.revision == 1

        monkeypatch.setattr(memory_manager.vector_store, "save_vector", save_vector)
        result = memory_manager.reconcile_index()

        assert result.indexed_memories == 1
        assert result.failures == 0
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory.indexed_revision == memory.revision == 1
        assert memory_manager.vector_store.has_vector(memory_id)

    def test_update_failure_preserves_latest_revision_for_reconciliation(
        self,
        memory_manager,
        monkeypatch,
    ):
        """A derived-write failure cannot restore over a later SQL revision."""
        # Create a memory
        store_outcome = memory_manager.store_memory(
            content="Original content",
            layer="profile",
            validate=False,
        )
        assert store_outcome.succeeded is True
        memory_id = store_outcome.memory_id
        assert memory_id is not None
        save_vector = memory_manager.vector_store.save_vector

        # Mock vector_store to fail on save
        def failing_save_vector(memory_id, embedding):
            raise RuntimeError("Vector storage failed")

        monkeypatch.setattr(
            memory_manager.vector_store,
            "save_vector",
            failing_save_vector,
        )

        # Try to update the memory with new content
        outcome = memory_manager.update_memory(
            memory_id=memory_id,
            content="New content",
        )

        assert outcome.succeeded is True
        assert outcome.status is MemoryOperationStatus.UPDATED_PENDING_INDEX
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory.content == "New content"
        assert memory.indexed_revision == 1
        assert memory.revision == 2

        outcome = memory_manager.update_memory(
            memory_id=memory_id,
            content="Newest content",
            expected_revision=2,
        )
        assert outcome.succeeded is True
        assert outcome.status is MemoryOperationStatus.UPDATED_PENDING_INDEX

        monkeypatch.setattr(memory_manager.vector_store, "save_vector", save_vector)
        result = memory_manager.reconcile_index()

        assert result.indexed_memories == 1
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory.content == "Newest content"
        assert memory.indexed_revision == memory.revision == 3

    def test_delete_tombstone_hides_memory_until_vector_cleanup(
        self,
        memory_manager,
        monkeypatch,
    ):
        store_outcome = memory_manager.store_memory(
            content="Delete this safely",
            layer="profile",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None
        delete_vector = memory_manager.vector_store.delete_vector

        def failing_delete_vector(memory_id):
            raise RuntimeError("Vector deletion failed")

        monkeypatch.setattr(
            memory_manager.vector_store,
            "delete_vector",
            failing_delete_vector,
        )

        outcome = memory_manager.delete_memory(memory_id)

        assert outcome.succeeded is True
        assert outcome.status is MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP
        assert memory_manager.memory_store.get_memory_by_id(memory_id) is None
        tombstone = memory_manager.memory_store.get_memory_by_id_including_deleted(
            memory_id
        )
        assert tombstone is not None
        assert tombstone.deleted_at is not None
        assert (
            memory_manager.retriever.retrieve_similar(
                "Delete this safely",
                top_k=5,
            )
            == []
        )

        monkeypatch.setattr(
            memory_manager.vector_store,
            "delete_vector",
            delete_vector,
        )
        result = memory_manager.reconcile_index()

        assert result.cleaned_tombstones == 1
        assert result.failures == 0
        assert (
            memory_manager.memory_store.get_memory_by_id_including_deleted(memory_id)
            is None
        )
        assert not memory_manager.vector_store.has_vector(memory_id)

    def test_reconciliation_rebuilds_missing_vector(self, memory_manager):
        store_outcome = memory_manager.store_memory(
            content="Rebuild this index entry",
            layer="profile",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None
        memory_manager.vector_store.delete_vector(memory_id)
        assert not memory_manager.vector_store.has_vector(memory_id)

        result = memory_manager.reconcile_index()

        assert result.indexed_memories == 1
        assert result.failures == 0
        assert memory_manager.vector_store.has_vector(memory_id)

    def test_reconciliation_removes_orphan_vector(self, memory_manager):
        store_outcome = memory_manager.store_memory(
            content="Legacy partial deletion",
            layer="profile",
            validate=False,
        )
        memory_id = store_outcome.memory_id
        assert memory_id is not None
        assert memory_manager.memory_store.tombstone_memory(memory_id)
        assert memory_manager.memory_store.purge_tombstone(memory_id)
        assert memory_manager.vector_store.has_vector(memory_id)

        result = memory_manager.reconcile_index()

        assert result.removed_orphan_vectors == 1
        assert result.failures == 0
        assert not memory_manager.vector_store.has_vector(memory_id)
