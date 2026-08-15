"""Deterministic fakes for the privacy package."""

# Local
from voice_concierge.privacy.errors import PrivacyError


class FakeMemoryArchive:
    """In-memory MemoryArchive so tests never touch a database."""

    def __init__(
        self, records: list[dict] | None = None, *, failing: bool = False
    ) -> None:
        self.records = list(records or [])
        self._failing = failing

    def get_all_memories(self) -> list[dict]:
        if self._failing:
            raise PrivacyError("archive unavailable")
        return list(self.records)

    def update_memory(self, memory_id: int, content: str | None = None) -> tuple:
        for record in self.records:
            if record["id"] == memory_id:
                record["content"] = content
                return True, "updated_successfully"
        return False, "memory_not_found"

    def delete_memory(self, memory_id: int) -> tuple:
        for index, record in enumerate(self.records):
            if record["id"] == memory_id:
                del self.records[index]
                return True, "deleted_successfully"
        return False, "memory_not_found"
