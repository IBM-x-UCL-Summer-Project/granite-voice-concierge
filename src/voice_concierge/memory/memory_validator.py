"""Validates whether content should be stored as a memory using LLM judgment."""

import json
from enum import Enum
from typing import Any, Dict, Optional, Tuple

from ollama import Client


class ValidationReason(Enum):
    """Reasons why a memory should or should not be stored."""

    VALID = "should_store"
    INVALID = "should_not_store"
    ERROR = "validation_error"


class MemoryType(Enum):
    """Memory classification based on psychology research."""

    EPISODIC = "episodic"  # Specific events and time points
    SEMANTIC = "semantic"  # Facts and knowledge
    PROCEDURAL = "procedural"  # Skills and methods
    EMOTIONAL = "emotional"  # Emotions and feelings
    REFLECTIVE = "reflective"  # Thoughts and reflections


class MemoryValidator:
    """Uses LLM to determine if content is worth storing as a memory."""

    VALIDATION_PROMPT = """Analyze whether this content should be stored as a memory.

Content: "{content}"

Consider:
1. Is it meaningful and not trivial?
2. Is it worth remembering for future context?
3. Is it actionable or provides useful information?
4. Is it not spam/noise?

Respond with ONLY "yes" or "no"."""

    CLASSIFICATION_PROMPT = """Classify this memory into ONE category:

Content: "{content}"

Categories:
- episodic: Specific events with time/place (e.g., "went to cafe at 3pm")
- semantic: Facts/knowledge/preferences (e.g., "likes Italian food")
- procedural: Skills/methods/how-to (e.g., "knows how to cook pasta")
- emotional: Emotions/feelings/moods (e.g., "felt nervous about interview")
- reflective: Thoughts/reflections/analysis (e.g., "realized I should exercise more")

Respond with ONLY the category name (episodic/semantic/procedural/emotional/reflective)."""

    EXTRACTION_PROMPT = """Extract structured metadata from this memory content.

Content: "{content}"

Extract and return as JSON (only these exact keys):
{{
    "person": "name of person mentioned (or null if none)",
    "source_type": "one of: conversation, document, observation, experience (or null)",
    "event_time": "ISO timestamp if event time is mentioned (or null)",
    "strength": integer from 1 to 10 indicating importance (1=trivial, 10=critical)
}}

Respond with ONLY valid JSON, no other text."""

    def __init__(self, model: str = "granite:7b", host: str = "http://localhost:11434"):
        """
        Initialize the validator with Ollama configuration.

        Args:
            model: The model to use for validation (default: granite:7b)
            host: Ollama server host (default: http://localhost:11434)
        """
        self.model = model
        self.client = Client(host=host)

    def should_store(self, content: str) -> Tuple[bool, str]:
        """
        Determine if content should be stored using LLM judgment.

        Args:
            content: The content to validate

        Returns:
            Tuple of (should_store: bool, reason: str)
        """
        # Basic validation first
        if not content or not content.strip():
            return False, "empty_content"

        if len(content.strip()) < 3:
            return False, "too_short"

        # Use LLM for intelligent judgment
        try:
            prompt = self.VALIDATION_PROMPT.format(content=content[:500])
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
            )

            result = response.response.strip().lower()

            if "yes" in result:
                return True, "llm_approved"
            else:
                return False, "llm_rejected"

        except Exception as e:
            return False, f"validation_error: {str(e)}"

    def classify_memory_type(self, content: str) -> Tuple[Optional[MemoryType], str]:
        """
        Classify memory into one of five psychological categories using LLM.

        Args:
            content: Memory content to classify

        Returns:
            Tuple of (memory_type: MemoryType, classification_reason: str)
        """
        if not content or not content.strip():
            return None, "empty_content"

        try:
            prompt = self.CLASSIFICATION_PROMPT.format(content=content[:500])
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
            )

            result = response.response.strip().lower()

            # Map response to MemoryType
            for mem_type in MemoryType:
                if mem_type.value in result:
                    return mem_type, f"classified_as_{mem_type.value}"

            return None, "classification_failed"

        except Exception as e:
            return None, f"classification_error: {str(e)}"

    def extract_metadata(self, content: str) -> Dict[str, Any]:
        """
        Extract structured metadata from memory content using LLM.

        Args:
            content: Memory content to extract metadata from

        Returns:
            Dict with keys: person, source_type, event_time, strength
            All values are optional and may be None if not extractable
        """
        if not content or not content.strip():
            return {
                "person": None,
                "source_type": None,
                "event_time": None,
                "strength": 1,
            }

        try:
            prompt = self.EXTRACTION_PROMPT.format(content=content[:500])
            response = self.client.generate(
                model=self.model,
                prompt=prompt,
                stream=False,
            )

            result = response.response.strip()

            try:
                data = json.loads(result)
                return {
                    "person": data.get("person"),
                    "source_type": data.get("source_type"),
                    "event_time": data.get("event_time"),
                    "strength": data.get("strength", 5),
                }
            except json.JSONDecodeError:
                return {
                    "person": None,
                    "source_type": None,
                    "event_time": None,
                    "strength": 5,
                }

        except Exception:
            return {
                "person": None,
                "source_type": None,
                "event_time": None,
                "strength": 5,
            }

    def get_validation_report(self, content: str) -> dict:
        """Get detailed validation report for debugging."""
        should_store, reason = self.should_store(content)
        memory_type, classification = self.classify_memory_type(content)

        return {
            "should_store": should_store,
            "reason": reason,
            "memory_type": memory_type.value if memory_type else None,
            "classification": classification,
            "content_length": len(content),
            "content_stripped_length": len(content.strip()) if content else 0,
            "model": self.model,
        }
