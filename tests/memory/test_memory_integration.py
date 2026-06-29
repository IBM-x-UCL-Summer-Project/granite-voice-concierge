"""Integration tests for complete memory system."""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from voice_concierge.memory import (
    MemoryStore,
    VectorStore,
    EmbeddingService,
    MemoryValidator,
    MemoryManager,
)
from voice_concierge.reasoning.types import MemoryAction


@pytest.fixture
def memory_manager(tmp_path):
    """Create a complete memory manager for testing."""
    db_path = str(tmp_path / "test_memory.db")
    vector_db_path = str(tmp_path / "test_vector.db")

    memory_store = MemoryStore(db_path)
    vector_store = VectorStore(vector_db_path)
    embedding_service = EmbeddingService()
    validator = MemoryValidator()

    manager = MemoryManager(
        memory_store=memory_store,
        vector_store=vector_store,
        embedding_service=embedding_service,
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
            "Kenny is a developer", "profile", person="Kenny", topic="job", validate=False
        )

        results = memory_manager.retriever.retrieve_by_metadata(
            person="Kenny", topic="food"
        )
        assert len(results) == 1
        assert "pizza" in results[0]["content"]


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
        assert all(isinstance(m, str) for m in context)
