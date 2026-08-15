"""Deterministic fakes for the privacy package."""

# Local
from voice_concierge.memory.types import (
    MemoryOperationOutcome,
    MemoryOperationStatus,
    MemoryRecord,
)
from voice_concierge.privacy.errors import PrivacyError


class FakeMemoryArchive:
    """In-memory MemoryArchive so tests never touch a database."""

    def __init__(
        self, records: list[dict] | None = None, *, failing: bool = False
    ) -> None:
        self.records = list(records or [])
        self._failing = failing

    def get_all_memories(self) -> list[MemoryRecord]:
        if self._failing:
            raise PrivacyError("archive unavailable")
        return [_to_memory_record(record) for record in self.records]

    def update_memory(
        self,
        memory_id: int,
        content: str | None = None,
        expected_revision: int | None = None,
    ) -> MemoryOperationOutcome:
        for record in self.records:
            if record["id"] == memory_id:
                revision = record.get("revision", 1)
                if expected_revision is not None and revision != expected_revision:
                    return MemoryOperationOutcome(
                        MemoryOperationStatus.MEMORY_REVISION_CONFLICT,
                        memory_id=memory_id,
                    )
                record["content"] = content
                record["revision"] = revision + 1
                record["indexed_revision"] = revision + 1
                return MemoryOperationOutcome(
                    MemoryOperationStatus.UPDATED_SUCCESSFULLY,
                    memory_id=memory_id,
                )
        return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_NOT_FOUND)

    def delete_memory(
        self,
        memory_id: int,
        expected_revision: int | None = None,
    ) -> MemoryOperationOutcome:
        for index, record in enumerate(self.records):
            if record["id"] == memory_id:
                if (
                    expected_revision is not None
                    and record.get("revision", 1) != expected_revision
                ):
                    return MemoryOperationOutcome(
                        MemoryOperationStatus.MEMORY_REVISION_CONFLICT,
                        memory_id=memory_id,
                    )
                del self.records[index]
                return MemoryOperationOutcome(
                    MemoryOperationStatus.DELETED_SUCCESSFULLY,
                    memory_id=memory_id,
                )
        return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_NOT_FOUND)


def _to_memory_record(record: dict) -> MemoryRecord:
    """Build the same typed record returned by the real memory manager."""

    revision = record.get("revision", 1)
    return MemoryRecord(
        id=record["id"],
        content=record["content"],
        layer=record.get("layer", "unknown"),
        memory_key=record.get("memory_key"),
        revision=revision,
        indexed_revision=record.get("indexed_revision", revision),
        deleted_at=None,
        created_at=record.get("created_at", 0),
        event_time=record.get("event_time"),
        last_accessed=record.get("last_accessed"),
        strength=record.get("strength", 1),
        person=record.get("person"),
        source_type=record.get("source_type"),
        topic=record.get("topic"),
    )
