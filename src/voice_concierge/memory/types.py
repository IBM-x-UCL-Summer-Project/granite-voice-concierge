"""Typed records and operation outcomes owned by the memory subsystem."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum


@dataclass(frozen=True)
class MemoryRecord:
    """One authoritative SQL memory record."""

    id: int
    content: str
    layer: str
    memory_key: str | None
    revision: int
    indexed_revision: int
    deleted_at: int | None
    created_at: int
    event_time: int | None
    last_accessed: int | None
    strength: int
    person: str | None
    source_type: str | None
    topic: str | None

    def __post_init__(self) -> None:
        _require_positive_int(self.id, "Memory ID")
        _require_nonblank_string(self.content, "Memory content")
        _require_nonblank_string(self.layer, "Memory layer")
        _require_optional_nonblank_string(self.memory_key, "Memory key")
        _require_positive_int(self.revision, "Memory revision")
        _require_nonnegative_int(self.indexed_revision, "Indexed revision")
        if self.indexed_revision > self.revision:
            raise ValueError("Indexed revision cannot exceed the memory revision.")
        _require_optional_nonnegative_int(self.deleted_at, "Deletion timestamp")
        _require_nonnegative_int(self.created_at, "Creation timestamp")
        _require_optional_int(self.event_time, "Event timestamp")
        _require_optional_nonnegative_int(self.last_accessed, "Last-access timestamp")
        _require_strength(self.strength)
        _require_optional_nonblank_string(self.person, "Memory person")
        _require_optional_nonblank_string(self.source_type, "Memory source type")
        _require_optional_nonblank_string(self.topic, "Memory topic")

    @classmethod
    def from_mapping(cls, row: Mapping[str, object]) -> MemoryRecord:
        """Validate and convert one storage row at the SQL boundary."""

        return cls(
            id=row["id"],
            content=row["content"],
            layer=row["layer"],
            memory_key=row["memory_key"],
            revision=row["revision"],
            indexed_revision=row["indexed_revision"],
            deleted_at=row["deleted_at"],
            created_at=row["created_at"],
            event_time=row["event_time"],
            last_accessed=row["last_accessed"],
            strength=row["strength"],
            person=row["person"],
            source_type=row["source_type"],
            topic=row["topic"],
        )


@dataclass(frozen=True)
class MemoryWrite:
    """Validated content and metadata accepted by the SQL write boundary."""

    content: str
    layer: str
    memory_key: str | None = None
    event_time: int | None = None
    strength: int = 1
    person: str | None = None
    source_type: str | None = None
    topic: str | None = None

    def __post_init__(self) -> None:
        _require_nonblank_string(self.content, "Memory content")
        _require_nonblank_string(self.layer, "Memory layer")
        _require_optional_nonblank_string(self.memory_key, "Memory key")
        _require_optional_int(self.event_time, "Event timestamp")
        _require_strength(self.strength)
        _require_optional_nonblank_string(self.person, "Memory person")
        _require_optional_nonblank_string(self.source_type, "Memory source type")
        _require_optional_nonblank_string(self.topic, "Memory topic")


@dataclass(frozen=True)
class MemoryUpdate:
    """Validated fields accepted by the SQL update boundary."""

    content: str | None = None
    layer: str | None = None
    event_time: int | None = None
    strength: int | None = None
    person: str | None = None
    source_type: str | None = None
    topic: str | None = None

    def __post_init__(self) -> None:
        _require_optional_nonblank_string(self.content, "Memory content")
        _require_optional_nonblank_string(self.layer, "Memory layer")
        _require_optional_int(self.event_time, "Event timestamp")
        if self.strength is not None:
            _require_strength(self.strength)
        _require_optional_nonblank_string(self.person, "Memory person")
        _require_optional_nonblank_string(self.source_type, "Memory source type")
        _require_optional_nonblank_string(self.topic, "Memory topic")

    @property
    def has_changes(self) -> bool:
        """Return whether at least one field was supplied."""

        return any(
            value is not None
            for value in (
                self.content,
                self.layer,
                self.event_time,
                self.strength,
                self.person,
                self.source_type,
                self.topic,
            )
        )


@dataclass(frozen=True)
class ExtractedMemoryMetadata:
    """Canonical metadata accepted from the validator/model boundary."""

    person: str | None = None
    source_type: str | None = None
    event_time: int | None = None
    strength: int = 1

    def __post_init__(self) -> None:
        _require_optional_nonblank_string(self.person, "Memory person")
        _require_optional_nonblank_string(self.source_type, "Memory source type")
        _require_optional_int(self.event_time, "Event timestamp")
        _require_strength(self.strength)

    @classmethod
    def from_value(cls, value: object) -> ExtractedMemoryMetadata:
        """Normalize an untrusted metadata payload without leaking loose types."""

        if not isinstance(value, Mapping):
            return cls()
        return cls(
            person=_optional_nonblank_text(value.get("person")),
            source_type=_optional_nonblank_text(value.get("source_type")),
            event_time=normalize_event_time(value.get("event_time")),
            strength=normalize_memory_strength(
                value.get("strength"),
                default=1,
            ),
        )


@dataclass(frozen=True)
class VectorSearchResult:
    """One nearest-neighbour result from the derived vector index."""

    memory_id: int
    distance: float

    def __post_init__(self) -> None:
        _require_positive_int(self.memory_id, "Vector memory ID")
        _require_distance(self.distance, "Vector distance")


@dataclass(frozen=True)
class MemorySearchResult:
    """An authoritative memory paired with its semantic distance."""

    memory: MemoryRecord
    distance: float

    def __post_init__(self) -> None:
        if not isinstance(self.memory, MemoryRecord):
            raise TypeError("Memory search results require a MemoryRecord.")
        _require_distance(self.distance, "Memory distance")


class MemoryOperationStatus(StrEnum):
    """Stable machine-readable statuses for memory operations."""

    def __new__(cls, value: str, succeeded: bool) -> MemoryOperationStatus:
        member = str.__new__(cls, value)
        member._value_ = value
        member._succeeded = succeeded
        return member

    @property
    def succeeded(self) -> bool:
        """Return the authoritative success semantics owned by this status."""

        return self._succeeded

    STORED_SUCCESSFULLY = ("stored_successfully", True)
    STORED_PENDING_INDEX = ("stored_pending_index", True)
    DUPLICATE_KEY = ("duplicate_key", False)
    DUPLICATE_FOUND = ("duplicate_found", False)
    VALIDATION_FAILED = ("validation_failed", False)
    STORAGE_ERROR = ("storage_error", False)
    UPDATED_SUCCESSFULLY = ("updated_successfully", True)
    UPDATED_PENDING_INDEX = ("updated_pending_index", True)
    MEMORY_NOT_FOUND = ("memory_not_found", False)
    MEMORY_REVISION_CONFLICT = ("memory_revision_conflict", False)
    NO_CHANGES = ("no_changes", False)
    UPDATE_ERROR = ("update_error", False)
    DELETED_SUCCESSFULLY = ("deleted_successfully", True)
    DELETED_PENDING_INDEX_CLEANUP = ("deleted_pending_index_cleanup", True)
    DELETE_ERROR = ("delete_error", False)
    MEMORY_ACTION_ERROR = ("memory_action_error", False)
    MEMORY_TARGET_NOT_FOUND = ("memory_target_not_found", False)
    MEMORY_TARGET_MISMATCH = ("memory_target_mismatch", False)
    STRUCTURED_LIST_TARGET_MISMATCH = ("structured_list_target_mismatch", False)
    INVALID_STRUCTURED_LIST_CONTENT = ("invalid_structured_list_content", False)
    UNKNOWN_ACTION = ("unknown_action", False)
    MEMORY_NOT_CONFIGURED = ("memory_not_configured", False)
    MEMORY_SCOPE_NONE = ("memory_scope_none", False)
    STRUCTURED_LIST_SCOPE_MISMATCH = ("structured_list_scope_mismatch", False)
    MEMORY_GATEWAY_ERROR = ("memory_gateway_error", False)


@dataclass(frozen=True)
class MemoryOperationOutcome:
    """Typed result of a store, update, delete, or proposed memory action."""

    status: MemoryOperationStatus
    memory_id: int | None = None
    detail: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.status, MemoryOperationStatus):
            raise TypeError("Memory outcome status must be MemoryOperationStatus.")
        if self.memory_id is not None:
            _require_positive_int(self.memory_id, "Outcome memory ID")
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise ValueError("Memory outcome detail must not be blank.")

    @property
    def succeeded(self) -> bool:
        """Return whether the authoritative operation completed successfully."""

        return self.status.succeeded

    @property
    def reason(self) -> str:
        """Return a display value for logs and serialized application output."""

        if self.detail is None:
            return self.status.value
        return f"{self.status.value}: {self.detail}"


def normalize_event_time(value: object) -> int | None:
    """Convert extracted or legacy ISO event times to integer UTC timestamps."""

    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return int(value)
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return int(parsed.timestamp())
    except (OSError, OverflowError, ValueError):
        return None


def normalize_memory_strength(
    value: object,
    *,
    default: int | None = None,
) -> int | None:
    """Normalize model or legacy strength to the documented 1-10 range."""

    if not isinstance(value, int) or isinstance(value, bool):
        return default
    return min(10, max(1, value))


def _require_positive_int(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} must be a positive integer.")


def _require_nonnegative_int(value: object, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer.")


def _require_optional_nonnegative_int(value: object, label: str) -> None:
    if value is not None:
        _require_nonnegative_int(value, label)


def _require_optional_int(value: object, label: str) -> None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool)):
        raise ValueError(f"{label} must be an integer.")


def _require_strength(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 10:
        raise ValueError("Memory strength must be an integer from 1 to 10.")


def _require_nonblank_string(value: object, label: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be blank.")


def _require_optional_nonblank_string(value: object, label: str) -> None:
    if value is not None:
        _require_nonblank_string(value, label)


def _optional_nonblank_text(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def _require_distance(value: object, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or value < 0
    ):
        raise ValueError(f"{label} must be a finite non-negative number.")
