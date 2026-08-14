"""PrivacyCentre - review, correct and remove what is stored about you.

The pure core of the privacy package: no printing, no prompting, no database
access of its own. It turns typed stored records into views a person can read,
and turns a person's decision into a single call on the archive.

Two rules shape it. Nothing here reports success it did not achieve, because a
privacy control that quietly fails is worse than one that refuses. And deleting
is always explicit about how much it removed, so "forget everything" can be
confirmed rather than assumed.
"""

# Standard library
from collections import Counter

# Local
from voice_concierge.memory.types import (
    MemoryOperationOutcome,
    MemoryOperationStatus,
    MemoryRecord,
)
from voice_concierge.privacy.errors import PrivacyError
from voice_concierge.privacy.interfaces import MemoryArchive
from voice_concierge.privacy.types import StoredMemory


class PrivacyCentre:
    """Read and control the memories held about the user."""

    def __init__(self, archive: MemoryArchive) -> None:
        self._archive = archive

    def list_memories(
        self, *, layer: str | None = None, search: str | None = None
    ) -> tuple[StoredMemory, ...]:
        """Return stored memories, newest first, optionally filtered.

        Filtering happens here rather than in a query so the same behaviour
        holds for any archive implementation, and so a search never has to be
        turned into SQL by a caller.
        """
        memories = tuple(_to_view(record) for record in self._read_all())
        if layer is not None:
            memories = tuple(item for item in memories if item.layer == layer)
        if search:
            needle = search.casefold()
            memories = tuple(
                item for item in memories if needle in item.content.casefold()
            )
        return tuple(
            sorted(memories, key=lambda item: item.created_at or 0, reverse=True)
        )

    def get_memory(self, identifier: int) -> StoredMemory | None:
        """Return one stored memory, or None when nothing has that id."""
        for record in self._read_all():
            if record.id == identifier:
                return _to_view(record)
        return None

    def counts_by_layer(self) -> dict[str, int]:
        """Count stored memories per layer, for the storage summary."""
        return dict(Counter(item.layer for item in self.list_memories()))

    def edit_memory(self, identifier: int, content: str) -> StoredMemory:
        """Replace a memory's content, returning the corrected memory.

        Correcting is offered alongside deleting because a wrong memory about a
        person is its own harm: without this the only remedy would be to erase
        a true memory that merely got the details wrong.
        """
        text = content.strip()
        if not text:
            raise PrivacyError("A memory cannot be replaced with empty text.")
        current = self.get_memory(identifier)
        if current is None:
            raise PrivacyError(_not_found(identifier))
        try:
            outcome = self._archive.update_memory(
                identifier,
                content=text,
                expected_revision=current.revision,
            )
        except Exception as exc:
            raise PrivacyError(
                f"Memory {identifier} could not be changed: {exc}"
            ) from exc
        if not outcome.succeeded:
            raise PrivacyError(_explain(outcome, identifier))
        if outcome.status is MemoryOperationStatus.UPDATED_PENDING_INDEX:
            raise PrivacyError(
                f"Memory {identifier} was changed, but its local search index "
                "still needs repair."
            )
        updated = self.get_memory(identifier)
        if updated is None:  # archive reported success but the row is gone
            raise PrivacyError(
                f"Memory {identifier} was reported as changed but cannot be read back."
            )
        return updated

    def delete_memory(self, identifier: int) -> None:
        """Remove one memory and its embedding. Raises if it was not removed."""
        memory = self.get_memory(identifier)
        if memory is None:
            raise PrivacyError(_not_found(identifier))
        outcome = self._delete_record(memory)
        if not outcome.succeeded:
            raise PrivacyError(_explain(outcome, identifier))
        if outcome.status is MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP:
            raise PrivacyError(
                f"Memory {identifier} was removed, but its local search-index "
                "cleanup is still pending."
            )

    def delete_all(self) -> int:
        """Remove every stored memory, returning how many were removed.

        Deletes one at a time through the same path as a single deletion, so
        embeddings are cleaned up too rather than leaving vectors behind for
        content the user asked to have forgotten. Stops at the first failure and
        reports how many had already gone, so the count is never overstated.
        """
        removed = 0
        for memory in self.list_memories():
            try:
                outcome = self._delete_record(memory)
            except PrivacyError as exc:
                raise PrivacyError(
                    f"Removed {removed} memories, then stopped: {exc}"
                ) from exc
            if outcome.status is MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP:
                removed += 1
                raise PrivacyError(
                    f"Removed {removed} memories, then stopped: local search-index "
                    "cleanup is still pending."
                )
            if not outcome.succeeded:
                raise PrivacyError(
                    f"Removed {removed} memories, then stopped: "
                    f"{_explain(outcome, memory.identifier)}"
                )
            removed += 1
        return removed

    def export_memories(self) -> list[dict]:
        """Return every memory as plain records, for the user to keep.

        Exporting is part of control, not a convenience: someone deciding
        whether to erase their data should be able to take a copy first.
        """
        return [
            {
                "id": item.identifier,
                "content": item.content,
                "layer": item.layer,
                "created_at": item.created_at,
                "created": item.created_display,
                "topic": item.topic,
                "person": item.person,
                "source_type": item.source_type,
            }
            for item in self.list_memories()
        ]

    def _read_all(self) -> list[MemoryRecord]:
        """Read the archive, turning any backend failure into a PrivacyError."""
        try:
            records = self._archive.get_all_memories()
            if not isinstance(records, list) or any(
                not isinstance(record, MemoryRecord) for record in records
            ):
                raise TypeError("Memory archive returned untyped records.")
            return records
        except PrivacyError:
            raise
        except Exception as exc:  # unknown backend failure; do not leak internals
            raise PrivacyError(f"Stored memories could not be read: {exc}") from exc

    def _delete_record(self, memory: StoredMemory) -> MemoryOperationOutcome:
        """Delete the exact revision the privacy centre reviewed."""

        try:
            return self._archive.delete_memory(
                memory.identifier,
                expected_revision=memory.revision,
            )
        except Exception as exc:
            raise PrivacyError(
                f"Memory {memory.identifier} could not be removed: {exc}"
            ) from exc


def _to_view(record: MemoryRecord) -> StoredMemory:
    """Convert a stored record into the read-only view shown to the user."""
    return StoredMemory(
        identifier=record.id,
        content=record.content,
        layer=record.layer,
        revision=record.revision,
        created_at=record.created_at,
        topic=record.topic,
        person=record.person,
        source_type=record.source_type,
    )


def _explain(outcome: MemoryOperationOutcome, identifier: int) -> str:
    """Turn an archive reason code into something worth reading."""
    if outcome.status is MemoryOperationStatus.MEMORY_NOT_FOUND:
        return _not_found(identifier)
    if outcome.status is MemoryOperationStatus.MEMORY_REVISION_CONFLICT:
        return (
            f"Memory {identifier} changed after it was reviewed; "
            "review it again before retrying."
        )
    return f"Memory {identifier} could not be changed: {outcome.reason}"


def _not_found(identifier: int) -> str:
    return f"No memory with id {identifier} is stored."
