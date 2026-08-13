"""Integration tests for complete memory system."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voice_concierge.memory import (
    MemoryManager,
    MemoryStore,
    MemoryValidator,
    VectorStore,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryTarget,
    StructuredListOperation,
)


def _shopping_add(*items: str) -> StructuredListOperation:
    return StructuredListOperation(
        list_name="shopping",
        operation="add_items",
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
        success, reason, memory_id = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
        )

        assert success is True
        assert memory_id is not None

        all_memories = memory_manager.get_all_memories()
        assert len(all_memories) == 1
        assert all_memories[0]["content"] == content

    def test_store_with_metadata(self, memory_manager):
        """Store a memory with metadata."""
        success, reason, memory_id = memory_manager.store_memory(
            content="likes pizza",
            layer="profile",
            person="Kenny",
            topic="food",
            validate=False,
        )

        assert success is True

        memories = memory_manager.retriever.retrieve_by_person("Kenny")
        assert len(memories) == 1
        assert memories[0]["person"] == "Kenny"
        assert memories[0]["topic"] == "food"

    def test_update_memory(self, memory_manager):
        """Update an existing memory."""
        _, _, memory_id = memory_manager.store_memory(
            content="old content",
            layer="profile",
            validate=False,
        )

        success, reason = memory_manager.update_memory(
            memory_id=memory_id,
            content="new content",
        )

        assert success is True

        memories = memory_manager.get_all_memories()
        assert memories[0]["content"] == "new content"

    def test_delete_memory(self, memory_manager):
        """Delete a memory."""
        _, _, memory_id = memory_manager.store_memory(
            content="to delete",
            layer="raw",
            validate=False,
        )

        success, reason = memory_manager.delete_memory(memory_id)
        assert success is True

        memories = memory_manager.get_all_memories()
        assert len(memories) == 0

    def test_process_memory_action_store(self, memory_manager):
        """Process a store action from reasoning engine."""
        action = MemoryAction(
            action="store",
            content="remember to call mom",
            rationale="important reminder",
            requires_confirmation=False,
        )

        success, reason = memory_manager.process_memory_action(action)
        assert success is True

        memories = memory_manager.get_all_memories()
        assert len(memories) == 1
        assert "call mom" in memories[0]["content"]

    def test_process_update_targets_exact_key_not_semantic_match(self, memory_manager):
        """A shopping update cannot overwrite an unrelated preference."""
        _, _, preference_id = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            memory_key="preference:drink",
            validate=False,
            check_duplicates=False,
        )
        _, _, shopping_id = memory_manager.store_memory(
            content="Shopping list: bread.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        action = MemoryAction(
            action="update",
            content=None,
            rationale="User asked to add milk.",
            target=MemoryTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
            list_operation=_shopping_add("milk"),
        )

        success, reason = memory_manager.process_memory_action(action)

        assert success is True
        assert reason == "updated_successfully"
        assert (
            memory_manager.memory_store.get_memory_by_id(preference_id)["content"]
            == "I prefer tea"
        )
        assert (
            memory_manager.memory_store.get_memory_by_id(shopping_id)["content"]
            == "Shopping list: bread, milk."
        )

    def test_process_shopping_update_deduplicates_items(self, memory_manager):
        _, _, shopping_id = memory_manager.store_memory(
            content="Shopping list: bread, milk.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        action = MemoryAction(
            action="update",
            content=None,
            rationale="User asked to add milk and eggs.",
            target=MemoryTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
            list_operation=_shopping_add("Milk", "eggs"),
        )

        success, reason = memory_manager.process_memory_action(action)

        assert success is True
        assert reason == "updated_successfully"
        assert (
            memory_manager.memory_store.get_memory_by_id(shopping_id)["content"]
            == "Shopping list: bread, milk, eggs."
        )

    def test_structured_list_operation_rejects_exact_non_list_target(
        self,
        memory_manager,
    ):
        _, _, preference_id = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        action = MemoryAction(
            action="update",
            content=None,
            rationale="Incorrect exact target supplied for a list operation.",
            target=MemoryTarget(memory_id=preference_id, expected_revision=1),
            list_operation=_shopping_add("milk"),
        )

        success, reason = memory_manager.process_memory_action(action)

        assert success is False
        assert reason == "structured_list_target_mismatch"
        assert memory_manager.memory_store.get_memory_by_id(preference_id)[
            "content"
        ] == ("I prefer tea")

    def test_process_update_without_stable_target_fails_closed(self, memory_manager):
        _, _, preference_id = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        with pytest.raises(ValueError, match="requires an exact target"):
            MemoryAction(
                action="update",
                content=None,
                rationale="User asked to add milk.",
                list_operation=_shopping_add("milk"),
            )

        assert (
            memory_manager.memory_store.get_memory_by_id(preference_id)["content"]
            == "I prefer tea"
        )

    def test_process_delete_without_stable_target_fails_closed(self, memory_manager):
        _, _, preference_id = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        with pytest.raises(ValueError, match="requires an exact target"):
            MemoryAction(
                action="delete",
                content="I prefer tea",
                rationale="User asked to delete a memory.",
            )

        assert memory_manager.memory_store.get_memory_by_id(preference_id) is not None

    def test_process_delete_targets_exact_key(self, memory_manager):
        _, _, preference_id = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            memory_key="preference:drink",
            validate=False,
            check_duplicates=False,
        )
        _, _, shopping_id = memory_manager.store_memory(
            content="Shopping list: bread.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        action = MemoryAction(
            action="delete",
            content="my shopping list",
            rationale="User asked to delete the shopping list.",
            target=MemoryTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
        )

        success, reason = memory_manager.process_memory_action(action)

        assert success is True
        assert reason == "deleted_successfully"
        assert memory_manager.memory_store.get_memory_by_key("list:shopping") is None
        assert memory_manager.memory_store.get_memory_by_id(preference_id) is not None

    def test_process_update_rejects_stale_revision(self, memory_manager):
        _, _, shopping_id = memory_manager.store_memory(
            content="Shopping list: bread.",
            layer="feedback",
            memory_key="list:shopping",
            topic="shopping",
            validate=False,
            check_duplicates=False,
        )
        assert memory_manager.update_memory(
            shopping_id,
            content="Shopping list: bread, eggs.",
            expected_revision=1,
        ) == (True, "updated_successfully")
        stale_action = MemoryAction(
            action="update",
            content=None,
            rationale="User acted on an old list view.",
            target=MemoryTarget(
                memory_id=shopping_id,
                memory_key="list:shopping",
                expected_revision=1,
            ),
            list_operation=_shopping_add("milk"),
        )

        success, reason = memory_manager.process_memory_action(stale_action)

        assert success is False
        assert reason == "memory_revision_conflict"
        assert memory_manager.memory_store.get_memory_by_id(shopping_id)["content"] == (
            "Shopping list: bread, eggs."
        )


class TestMemoryRetrieval:
    """Test memory retrieval capabilities."""

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
        assert all("distance" in r for r in results)

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
        assert "cats" in kenny_memories[0]["content"]

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
        assert "pizza" in food_memories[0]["content"]

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
        assert "pizza" in results[0]["content"]

    def test_retrieve_by_layer(self, memory_manager):
        """Test filtering memories by layer."""
        memory_manager.store_memory("Milk and eggs", "shopping-list", validate=False)
        memory_manager.store_memory(
            "Prefers coffee in the morning", "profile", validate=False
        )

        shopping_memories = memory_manager.retriever.retrieve_by_layer("shopping-list")
        assert len(shopping_memories) == 1
        assert "Milk and eggs" in shopping_memories[0]["content"]

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
        assert shopping[0]["layer"] == "shopping-list"

        profile = memory_manager.retriever.retrieve_by_layer("profile")
        assert len(profile) == 1
        assert profile[0]["layer"] == "profile"

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
        assert results[0]["person"] == "Kenny"
        assert results[0]["layer"] == "shopping-list"


class TestMemoryValidation:
    """Test memory validation."""

    def test_reject_empty_memory(self, memory_manager):
        """Validator should reject empty memory."""
        success, reason, memory_id = memory_manager.store_memory(
            content="",
            layer="raw",
            validate=True,
        )

        assert success is False
        assert "empty" in reason.lower() or "validation" in reason.lower()

    def test_reject_short_memory(self, memory_manager):
        """Validator should reject very short memory."""
        success, reason, memory_id = memory_manager.store_memory(
            content="ab",
            layer="raw",
            validate=True,
        )

        assert success is False

    def test_skip_validation_flag(self, memory_manager):
        """Can skip validation with validate=False."""
        success, reason, memory_id = memory_manager.store_memory(
            content="x",
            layer="raw",
            validate=False,
        )

        assert success is True


class TestDuplicatePrevention:
    """Test duplicate memory prevention."""

    def test_duplicate_count_stays_same(self, memory_manager):
        """Adding same memory twice should keep count at 1."""
        content = "I prefer tea"

        # Store first time
        success1, reason1, id1 = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
            check_duplicates=False,  # First one, no check
        )
        assert success1 is True

        all_memories = memory_manager.get_all_memories()
        assert len(all_memories) == 1

        # Store second time (same content)
        success2, reason2, id2 = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
            check_duplicates=True,  # Check for duplicates
        )

        # Should reject as duplicate
        assert success2 is False
        assert "duplicate" in reason2.lower()

        # Count should still be 1 (not 2)
        all_memories = memory_manager.get_all_memories()
        assert len(all_memories) == 1

    @pytest.mark.skip(reason="Requires real embeddings for semantic similarity")
    def test_store_different_increases_count(self, memory_manager):
        """Adding different memory should increase count."""
        # This test requires actual vector embeddings to distinguish different content
        # With fake_embedding_service (all zeros), all memories appear identical
        pass

    def test_disable_duplicate_check_allows_duplicates(self, memory_manager):
        """Disabling check allows storing duplicates."""
        content = "I prefer tea"

        # Store first time
        success1, _, id1 = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
            check_duplicates=False,
        )
        assert success1 is True
        assert len(memory_manager.get_all_memories()) == 1

        # Store duplicate with check disabled
        success2, _, id2 = memory_manager.store_memory(
            content=content,
            layer="profile",
            validate=False,
            check_duplicates=False,  # Disable check
        )

        # Should allow it
        assert success2 is True
        assert id1 != id2

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
            isinstance(memory, dict)
            and isinstance(memory.get("id"), int)
            and isinstance(memory.get("content"), str)
            and isinstance(memory.get("revision"), int)
            for memory in context
        )


class TestSQLVectorConsistency:
    """Test SQL and vector store consistency."""

    def test_store_creates_both_sql_and_vector(self, memory_manager):
        """Storing a memory should create both SQL record and vector."""
        success, reason, memory_id = memory_manager.store_memory(
            content="I like coffee",
            layer="profile",
            validate=False,
        )

        assert success is True
        assert memory_id is not None

        # Verify SQL record exists
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory is not None
        assert memory["content"] == "I like coffee"

        # Verify vector exists (by checking if search finds it)
        results = memory_manager.retrieve_similar("coffee", top_k=5)
        assert any(r["id"] == memory_id for r in results)

    def test_delete_removes_both_sql_and_vector(self, memory_manager):
        """Deleting a memory should remove both SQL record and vector."""
        # Create a memory
        success, reason, memory_id = memory_manager.store_memory(
            content="Remember this",
            layer="profile",
            validate=False,
        )
        assert success is True

        # Delete it
        success, reason = memory_manager.delete_memory(memory_id)
        assert success is True

        # Verify SQL record is deleted
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory is None

        # Verify vector is deleted (search should not find it)
        results = memory_manager.retrieve_similar("Remember this", top_k=10)
        assert not any(r["id"] == memory_id for r in results)

    def test_update_keeps_sql_and_vector_in_sync(self, memory_manager):
        """Updating a memory should update both SQL and vector."""
        # Create a memory
        success, reason, memory_id = memory_manager.store_memory(
            content="I prefer tea",
            layer="profile",
            validate=False,
        )
        assert success is True

        # Update the content
        success, reason = memory_manager.update_memory(
            memory_id=memory_id,
            content="I prefer coffee",
        )
        assert success is True

        # Verify SQL record is updated
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory["content"] == "I prefer coffee"

        # Verify vector still exists (by checking we can retrieve it)
        results = memory_manager.retrieve_similar("I prefer", top_k=10)
        assert any(r["id"] == memory_id for r in results)
        assert results[0]["content"] == "I prefer coffee"

    def test_store_rollback_on_vector_failure(self, memory_manager, monkeypatch):
        """If vector storage fails, SQL record should be deleted."""

        # Mock embedding service to fail
        def failing_save_vector(memory_id, embedding):
            raise RuntimeError("Vector storage failed")

        monkeypatch.setattr(
            memory_manager.vector_store, "save_vector", failing_save_vector
        )

        # Try to store a memory
        success, reason, memory_id = memory_manager.store_memory(
            content="This should fail",
            layer="profile",
            validate=False,
        )

        # Should fail
        assert success is False
        assert "vector" in reason.lower()

        # Verify no SQL record was left behind
        if memory_id:
            memory = memory_manager.memory_store.get_memory_by_id(memory_id)
            assert memory is None

    def test_update_rollback_on_vector_failure(self, memory_manager, monkeypatch):
        """If vector update fails, SQL record should be reverted."""
        # Create a memory
        success, reason, memory_id = memory_manager.store_memory(
            content="Original content",
            layer="profile",
            validate=False,
        )
        assert success is True

        # Mock vector_store to fail on save
        def failing_save_vector(memory_id, embedding):
            raise RuntimeError("Vector storage failed")

        monkeypatch.setattr(
            memory_manager.vector_store,
            "save_vector",
            failing_save_vector,
        )

        # Try to update the memory with new content
        success, reason = memory_manager.update_memory(
            memory_id=memory_id,
            content="New content",
        )

        # Should fail due to vector storage error
        assert success is False
        assert "embedding" in reason.lower() or "vector" in reason.lower()

        # Verify SQL record was reverted to original content
        memory = memory_manager.memory_store.get_memory_by_id(memory_id)
        assert memory["content"] == "Original content"
