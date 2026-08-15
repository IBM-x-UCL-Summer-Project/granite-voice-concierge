"""Protocols for the store the privacy centre reviews and controls."""

# Standard library
from typing import Protocol, runtime_checkable

from voice_concierge.memory.types import MemoryOperationOutcome, MemoryRecord


@runtime_checkable
class MemoryArchive(Protocol):
    """The slice of the memory system the privacy centre needs.

    Narrower than MemoryManager on purpose: this package may read, change and
    remove what is stored, but has no business writing new memories or running
    retrieval, so it cannot accidentally do either.
    """

    def get_all_memories(self) -> list[MemoryRecord]:
        """Return every authoritative stored memory record."""

    def update_memory(
        self,
        memory_id: int,
        content: str | None = None,
        expected_revision: int | None = None,
    ) -> MemoryOperationOutcome:
        """Change one exact revision and return its typed outcome."""

    def delete_memory(
        self,
        memory_id: int,
        expected_revision: int | None = None,
    ) -> MemoryOperationOutcome:
        """Remove one exact revision and return its typed outcome."""
