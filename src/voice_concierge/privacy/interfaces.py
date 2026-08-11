"""Protocols for the store the privacy centre reviews and controls."""

# Standard library
from typing import Protocol, runtime_checkable


@runtime_checkable
class MemoryArchive(Protocol):
    """The slice of the memory system the privacy centre needs.

    Narrower than MemoryManager on purpose: this package may read, change and
    remove what is stored, but has no business writing new memories or running
    retrieval, so it cannot accidentally do either.
    """

    def get_all_memories(self) -> list[dict]:
        """Return every stored memory as a raw record."""

    def update_memory(self, memory_id: int, content: str | None = None) -> tuple:
        """Change a stored memory, returning (succeeded, reason)."""

    def delete_memory(self, memory_id: int) -> tuple:
        """Remove a stored memory and its vector, returning (succeeded, reason)."""
