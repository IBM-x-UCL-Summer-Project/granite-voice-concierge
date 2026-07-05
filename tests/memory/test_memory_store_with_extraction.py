"""Integration tests for memory storage with metadata extraction."""

import tempfile
from pathlib import Path

import pytest

from voice_concierge.memory.memory_manager import MemoryManager
from voice_concierge.memory.memory_store import MemoryStore
from voice_concierge.memory.memory_validator import MemoryValidator
from voice_concierge.memory.vector_store import VectorStore


class TestMemoryStorageWithExtraction:
    """Test memory storage with auto-extraction of metadata."""

    @pytest.fixture
    def manager(self, fake_embedding_service):
        """Create a memory manager with temporary databases."""
        with tempfile.TemporaryDirectory() as tmpdir:
            memory_db = Path(tmpdir) / "memory.db"
            vector_db = Path(tmpdir) / "vectors.db"

            memory_store = MemoryStore(str(memory_db))
            vector_store = VectorStore(str(vector_db))
            validator = MemoryValidator()

            manager = MemoryManager(
                memory_store=memory_store,
                vector_store=vector_store,
                embedding_service=fake_embedding_service,
                validator=validator,
            )
            yield manager
            manager.close()

    def test_store_memory_with_auto_extract(self, manager):
        """Test storing memory with automatic metadata extraction enabled."""
        content = "Had lunch with Bob at the Italian restaurant on Friday"

        success, reason, memory_id = manager.store_memory(
            content=content,
            layer="profile",
            auto_extract=True,
            validate=False,
        )

        assert success
        assert memory_id is not None
        assert reason == "stored_successfully"

    def test_store_memory_without_auto_extract(self, manager):
        """Test storing memory with auto-extraction disabled."""
        content = "Had lunch with Bob at the Italian restaurant"

        success, reason, memory_id = manager.store_memory(
            content=content,
            layer="profile",
            auto_extract=False,
            validate=False,
        )

        assert success
        assert memory_id is not None

    def test_store_memory_manual_override(self, manager):
        """Test that manually provided metadata overrides auto-extraction."""
        content = "Some memory content"

        success, reason, memory_id = manager.store_memory(
            content=content,
            layer="profile",
            person="ManualPerson",
            source_type="conversation",
            strength=9,
            auto_extract=True,
            validate=False,
        )

        assert success
        assert memory_id is not None

        # Retrieve and verify
        memories = manager.get_all_memories()
        stored = [m for m in memories if m["id"] == memory_id]
        assert len(stored) == 1
        assert stored[0]["person"] == "ManualPerson"
        assert stored[0]["source_type"] == "conversation"
        assert stored[0]["strength"] == 9

    def test_store_memory_with_validation_and_extraction(self, manager):
        """Test storing memory with both validation and auto-extraction enabled."""
        content = "Learned that Alice joined the product team at work"

        success, reason, memory_id = manager.store_memory(
            content=content,
            layer="profile",
            validate=True,
            auto_extract=True,
            auto_classify=True,
        )

        # May fail if validator rejects, but the call should not error
        assert isinstance(success, bool)
        assert isinstance(reason, str)
        if success:
            assert memory_id is not None

    def test_auto_extract_with_empty_content(self, manager):
        """Test auto-extraction handles empty content gracefully."""
        success, reason, memory_id = manager.store_memory(
            content="",
            layer="profile",
            auto_extract=True,
            validate=False,
        )

        # Should fail validation if validate=True, but test with validate=False
        assert not success or memory_id is not None
