"""Tests for LLM-based metadata extraction in memory validator."""

import pytest

from voice_concierge.memory.memory_validator import MemoryValidator


class TestMetadataExtraction:
    """Test the extract_metadata method of MemoryValidator."""

    @pytest.fixture
    def validator(self):
        """Create a validator instance for testing."""
        return MemoryValidator()

    def test_extract_metadata_with_person(self, validator):
        """Test extracting person name from content."""
        content = "Had coffee with Alice yesterday"
        metadata = validator.extract_metadata(content)

        assert metadata is not None
        assert isinstance(metadata, dict)
        assert "person" in metadata
        assert "source_type" in metadata
        assert "event_time" in metadata
        assert "strength" in metadata

    def test_extract_metadata_with_all_fields(self, validator):
        """Test extracting all metadata fields."""
        content = "Ran into Sarah at the coffee shop last Tuesday. She mentioned starting a new job at Google."  # noqa: E501
        metadata = validator.extract_metadata(content)

        assert metadata["strength"] >= 1 and metadata["strength"] <= 10
        # Other fields may or may not be extracted depending on LLM

    def test_extract_metadata_empty_content(self, validator):
        """Test extracting metadata from empty content."""
        metadata = validator.extract_metadata("")

        assert metadata["person"] is None
        assert metadata["source_type"] is None
        assert metadata["event_time"] is None
        assert metadata["strength"] == 1

    def test_extract_metadata_whitespace_only(self, validator):
        """Test extracting metadata from whitespace-only content."""
        metadata = validator.extract_metadata("   ")

        assert metadata["person"] is None
        assert metadata["source_type"] is None
        assert metadata["event_time"] is None
        assert metadata["strength"] == 1

    def test_extract_metadata_returns_dict(self, validator):
        """Test that extract_metadata always returns a dict with expected keys."""
        content = "Some random memory content"
        metadata = validator.extract_metadata(content)

        assert isinstance(metadata, dict)
        assert "person" in metadata
        assert "source_type" in metadata
        assert "event_time" in metadata
        assert "strength" in metadata

    def test_extract_metadata_strength_range(self, validator):
        """Test that extracted strength is within valid range."""
        content = "This is a very important memory about a critical event"
        metadata = validator.extract_metadata(content)

        strength = metadata.get("strength")
        assert strength is not None
        assert isinstance(strength, int)
        assert 1 <= strength <= 10
