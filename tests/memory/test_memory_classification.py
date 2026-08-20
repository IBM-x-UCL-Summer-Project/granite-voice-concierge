"""Tests for memory type classification."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import voice_concierge.memory.memory_validator as memory_validator_module
from voice_concierge.memory.memory_validator import MemoryType, MemoryValidator


def test_validator_uses_configured_ollama_host(monkeypatch):
    captured = {}

    def fake_client(*, host):
        captured["host"] = host
        return object()

    monkeypatch.setenv("OLLAMA_HOST", "http://host.docker.internal:11434")
    monkeypatch.setattr(memory_validator_module, "Client", fake_client)

    validator = MemoryValidator()

    assert validator.host == "http://host.docker.internal:11434"
    assert captured["host"] == "http://host.docker.internal:11434"


class TestMemoryClassification:
    """Test memory type classification."""

    @pytest.fixture
    def validator(self):
        return MemoryValidator()

    @pytest.mark.skip(reason="Requires Ollama running")
    def test_classify_episodic(self, validator):
        """Episodic: specific events with time/place."""
        memory_type, reason = validator.classify_memory_type(
            "Went to the coffee shop at 3pm yesterday"
        )
        assert memory_type == MemoryType.EPISODIC

    @pytest.mark.skip(reason="Requires Ollama running")
    def test_classify_semantic(self, validator):
        """Semantic: facts and knowledge."""
        memory_type, reason = validator.classify_memory_type(
            "Kenny likes Italian food and pasta"
        )
        assert memory_type == MemoryType.SEMANTIC

    @pytest.mark.skip(reason="Requires Ollama running")
    def test_classify_procedural(self, validator):
        """Procedural: skills and methods."""
        memory_type, reason = validator.classify_memory_type(
            "Kenny knows how to cook pizza from scratch"
        )
        assert memory_type == MemoryType.PROCEDURAL

    @pytest.mark.skip(reason="Requires Ollama running")
    def test_classify_emotional(self, validator):
        """Emotional: emotions and feelings."""
        memory_type, reason = validator.classify_memory_type(
            "Kenny felt nervous and anxious before the job interview"
        )
        assert memory_type == MemoryType.EMOTIONAL

    @pytest.mark.skip(reason="Requires Ollama running")
    def test_classify_reflective(self, validator):
        """Reflective: thoughts and reflections."""
        memory_type, reason = validator.classify_memory_type(
            "Kenny reflected that he should exercise more regularly"
        )
        assert memory_type == MemoryType.REFLECTIVE

    def test_classify_empty_content(self, validator):
        """Empty content should return None."""
        memory_type, reason = validator.classify_memory_type("")
        assert memory_type is None
        assert "empty" in reason.lower()

    @pytest.mark.skip(reason="Requires Ollama running")
    def test_validation_report_with_classification(self, validator):
        """Validation report should include memory type."""
        report = validator.get_validation_report("User went to the gym yesterday")
        assert "memory_type" in report
        assert "classification" in report


class TestMemoryTypeEnum:
    """Test MemoryType enum."""

    def test_memory_type_values(self):
        """Check all memory types are defined."""
        assert MemoryType.EPISODIC.value == "episodic"
        assert MemoryType.SEMANTIC.value == "semantic"
        assert MemoryType.PROCEDURAL.value == "procedural"
        assert MemoryType.EMOTIONAL.value == "emotional"
        assert MemoryType.REFLECTIVE.value == "reflective"

    def test_memory_type_count(self):
        """Should have exactly 5 memory types."""
        assert len(MemoryType) == 5
