"""Typed records and operation outcomes owned by the memory subsystem."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Literal

from voice_concierge.memory_contracts import (
    SHOPPING_LIST_MEMORY_KEY,
    STRUCTURED_LIST_MEMORY_KEYS,
    TASK_LIST_MEMORY_KEY,
    StructuredListName,
)


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
class MemoryRecordScope:
    """Metadata boundary that separates independently meaningful memories."""

    layer: str
    person: str | None = None
    source_type: str | None = None
    topic: str | None = None

    def __post_init__(self) -> None:
        _require_nonblank_string(self.layer, "Memory scope layer")
        _require_optional_nonblank_string(self.person, "Memory scope person")
        _require_optional_nonblank_string(
            self.source_type,
            "Memory scope source type",
        )
        _require_optional_nonblank_string(self.topic, "Memory scope topic")

    def contains(self, memory: MemoryRecord) -> bool:
        """Return whether a record belongs to this exact metadata scope."""

        if not isinstance(memory, MemoryRecord):
            raise TypeError("Memory scopes can only match MemoryRecord values.")
        return (
            memory.layer == self.layer
            and memory.person == self.person
            and memory.source_type == self.source_type
            and memory.topic == self.topic
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
class MemoryCommandTarget:
    """Exact identity and optional revision for an executable mutation."""

    memory_id: int | None = None
    memory_key: str | None = None
    expected_revision: int | None = None

    def __post_init__(self) -> None:
        if self.memory_id is None and self.memory_key is None:
            raise ValueError("Memory command target requires an ID or stable key.")
        if self.memory_id is not None:
            _require_positive_int(self.memory_id, "Memory command target ID")
        _require_optional_nonblank_string(
            self.memory_key,
            "Memory command target key",
        )
        if self.expected_revision is not None:
            _require_positive_int(
                self.expected_revision,
                "Memory command expected revision",
            )


@dataclass(frozen=True)
class StructuredListMutation:
    """Memory-owned operation over one project structured list."""

    list_name: StructuredListName
    items: tuple[str, ...]
    operation: Literal["add_items", "remove_items"] = "add_items"

    def __post_init__(self) -> None:
        if self.list_name not in {"shopping", "task"}:
            raise ValueError(f"Unsupported structured list: {self.list_name!r}.")
        if self.operation not in {"add_items", "remove_items"}:
            raise ValueError(
                f"Unsupported structured-list operation: {self.operation!r}."
            )
        if not isinstance(self.items, tuple) or not self.items:
            raise ValueError("Structured-list items must be a non-empty tuple.")
        if any(
            not isinstance(item, str) or not item.strip(" .") for item in self.items
        ):
            raise ValueError("Structured-list items must not be blank.")

        normalized_items: list[str] = []
        seen: set[str] = set()
        for item in self.items:
            normalized = item.strip(" .")
            comparison_key = normalized.casefold()
            if comparison_key in seen:
                continue
            normalized_items.append(normalized)
            seen.add(comparison_key)
        object.__setattr__(self, "items", tuple(normalized_items))

    @property
    def memory_key(self) -> str:
        """Return the stable identity of the target list."""

        if self.list_name == "shopping":
            return SHOPPING_LIST_MEMORY_KEY
        return TASK_LIST_MEMORY_KEY

    @property
    def topic(self) -> str:
        """Return the storage topic for this list."""

        if self.list_name == "shopping":
            return "shopping"
        return "task"


@dataclass(frozen=True)
class StoreMemoryCommand:
    """Executable command to create one memory in an authorized scope."""

    content: str
    layer: str
    memory_key: str | None = None
    topic: str | None = None

    def __post_init__(self) -> None:
        _require_nonblank_string(self.content, "Store command content")
        _require_nonblank_string(self.layer, "Store command layer")
        _require_optional_nonblank_string(self.memory_key, "Store command key")
        _require_optional_nonblank_string(self.topic, "Store command topic")
        if self.memory_key in STRUCTURED_LIST_MEMORY_KEYS:
            raise ValueError(
                "Structured-list writes require ApplyStructuredListCommand."
            )


@dataclass(frozen=True)
class UpdateMemoryCommand:
    """Executable command to update one exact memory."""

    target: MemoryCommandTarget
    content: str

    def __post_init__(self) -> None:
        if not isinstance(self.target, MemoryCommandTarget):
            raise TypeError("Update command target must be MemoryCommandTarget.")
        _require_nonblank_string(self.content, "Update command content")


@dataclass(frozen=True)
class DeleteMemoryCommand:
    """Executable command to delete one exact memory."""

    target: MemoryCommandTarget

    def __post_init__(self) -> None:
        if not isinstance(self.target, MemoryCommandTarget):
            raise TypeError("Delete command target must be MemoryCommandTarget.")


@dataclass(frozen=True)
class ApplyStructuredListCommand:
    """Executable, identity-addressed structured-list mutation."""

    target: MemoryCommandTarget
    mutation: StructuredListMutation

    def __post_init__(self) -> None:
        if not isinstance(self.target, MemoryCommandTarget):
            raise TypeError("Structured-list target must be MemoryCommandTarget.")
        if not isinstance(self.mutation, StructuredListMutation):
            raise TypeError(
                "Structured-list command mutation must be StructuredListMutation."
            )
        if self.target.memory_key not in {None, self.mutation.memory_key}:
            raise ValueError("Structured-list mutation does not match target key.")


MemoryCommand = (
    StoreMemoryCommand
    | UpdateMemoryCommand
    | DeleteMemoryCommand
    | ApplyStructuredListCommand
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
    """An authoritative memory paired with semantic and retention scores."""

    memory: MemoryRecord
    distance: float
    retention_score: float | None = None
    retrieval_score: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.memory, MemoryRecord):
            raise TypeError("Memory search results require a MemoryRecord.")
        _require_distance(self.distance, "Memory distance")
        if self.retention_score is not None:
            _require_unit_interval(
                self.retention_score,
                "Memory retention score",
            )
        if self.retrieval_score is not None:
            _require_distance(self.retrieval_score, "Memory retrieval score")


@dataclass(frozen=True)
class MemorySimilarityAdvisory:
    """Non-blocking evidence that a stored memory resembles an existing one."""

    memory_id: int
    distance: float

    def __post_init__(self) -> None:
        _require_positive_int(self.memory_id, "Advisory memory ID")
        _require_distance(self.distance, "Advisory distance")


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
    NO_CHANGES = ("no_changes", True)
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
    MEMORY_SCOPE_MISMATCH = ("memory_scope_mismatch", False)
    MEMORY_GATEWAY_ERROR = ("memory_gateway_error", False)


@dataclass(frozen=True)
class MemoryOperationOutcome:
    """Typed result of a store, update, delete, or proposed memory action."""

    status: MemoryOperationStatus
    memory_id: int | None = None
    detail: str | None = None
    similarity_advisories: tuple[MemorySimilarityAdvisory, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, MemoryOperationStatus):
            raise TypeError("Memory outcome status must be MemoryOperationStatus.")
        if self.memory_id is not None:
            _require_positive_int(self.memory_id, "Outcome memory ID")
        if self.detail is not None and (
            not isinstance(self.detail, str) or not self.detail.strip()
        ):
            raise ValueError("Memory outcome detail must not be blank.")
        if not isinstance(self.similarity_advisories, tuple) or any(
            not isinstance(advisory, MemorySimilarityAdvisory)
            for advisory in self.similarity_advisories
        ):
            raise TypeError(
                "Memory similarity advisories must be a tuple of "
                "MemorySimilarityAdvisory values."
            )

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


def _require_unit_interval(value: object, label: str) -> None:
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 1
    ):
        raise ValueError(f"{label} must be a finite number between 0 and 1.")
