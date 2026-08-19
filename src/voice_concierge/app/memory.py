"""Memory gateway used by the application pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from threading import RLock
from typing import TYPE_CHECKING, Protocol

from voice_concierge.context.types import MemoryScope
from voice_concierge.memory.structured_lists import (
    canonicalize_structured_list_content,
)
from voice_concierge.memory.types import (
    ApplyStructuredListCommand,
    DeleteMemoryCommand,
    MemoryCommand,
    MemoryCommandTarget,
    MemoryOperationOutcome,
    MemoryOperationStatus,
    MemoryRecord,
    MemorySearchResult,
    StoreMemoryCommand,
    StructuredListMutation,
    UpdateMemoryCommand,
)
from voice_concierge.memory_contracts import (
    SHOPPING_LIST_MEMORY_KEY,
    TASK_LIST_MEMORY_KEY,
)
from voice_concierge.reasoning.list_intents import shopping_purchase_remainder
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryReference,
    MemoryTarget,
)

if TYPE_CHECKING:
    from voice_concierge.memory.factory import LocalMemoryConfig


@dataclass(frozen=True)
class BulkMemoryDeleteResult:
    """Outcome and count for one confirmed all-memory deletion."""

    deleted_count: int
    outcome: MemoryOperationOutcome

    def __post_init__(self) -> None:
        if self.deleted_count < 0:
            raise ValueError("Deleted memory count must not be negative.")


class MemoryGateway(Protocol):
    """Small app-owned boundary over memory retrieval and confirmed writes."""

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 3,
    ) -> tuple[MemoryReference, ...]:
        """Return identified memory evidence relevant to one user query."""

    def apply(
        self,
        action: MemoryAction,
        scope: MemoryScope,
    ) -> MemoryOperationOutcome:
        """Apply a previously confirmed memory action."""

    def delete_all(self) -> BulkMemoryDeleteResult:
        """Delete every saved memory after app-level confirmation."""

    def close(self) -> None:
        """Release persistent memory resources."""


def retrieval_scope_for_turn(
    transcript: str,
    fallback: MemoryScope,
) -> MemoryScope:
    """Route explicitly named structured records independently of UI mode."""

    if fallback == "none":
        return "none"
    normalized = " ".join(transcript.casefold().split())
    if "shopping list" in normalized:
        return "list_relevant"
    if shopping_purchase_remainder(normalized) is not None:
        return "list_relevant"
    if re.search(r"\b(?:task|to-do|todo)\s+list\b", normalized):
        return "task_relevant_only"
    return fallback


class NullMemoryGateway:
    """No-op memory gateway for tests and installations without memory wiring."""

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 3,
    ) -> tuple[MemoryReference, ...]:
        return ()

    def apply(
        self,
        action: MemoryAction,
        scope: MemoryScope,
    ) -> MemoryOperationOutcome:
        return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_NOT_CONFIGURED)

    def delete_all(self) -> BulkMemoryDeleteResult:
        return BulkMemoryDeleteResult(
            0,
            MemoryOperationOutcome(MemoryOperationStatus.MEMORY_NOT_CONFIGURED),
        )

    def close(self) -> None:
        """Release no resources for the no-op gateway."""


class MemoryManagerGateway:
    """Adapter from the app pipeline boundary to the current MemoryManager."""

    def __init__(self, manager: MemoryManagerPort) -> None:
        self._manager = manager
        self._operation_lock = RLock()

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 3,
    ) -> tuple[MemoryReference, ...]:
        with self._operation_lock:
            return self._retrieve(query, scope, limit=limit)

    def _retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int,
    ) -> tuple[MemoryReference, ...]:
        if scope == "none" or limit <= 0:
            return ()

        if scope == "list_relevant":
            shopping_list = _memory_reference(
                self._manager.get_memory_by_key(SHOPPING_LIST_MEMORY_KEY)
            )
            return (shopping_list,) if shopping_list is not None else ()

        exact_memories: tuple[MemoryReference, ...] = ()
        preference_key = _accessibility_preference_key(query)
        if preference_key is not None and _scope_allows_key(scope, preference_key):
            preference = _memory_reference(
                self._manager.get_memory_by_key(preference_key)
            )
            if preference is not None:
                exact_memories = (preference,)
        if scope == "task_relevant_only":
            task_list = _memory_reference(
                self._manager.get_memory_by_key(TASK_LIST_MEMORY_KEY)
            )
            if task_list is not None:
                exact_memories = (task_list,)

        semantic_limit = limit - len(exact_memories)
        if semantic_limit <= 0:
            return exact_memories

        layer, topic = _retrieval_metadata(scope)
        memories = self._manager.retrieve_similar(
            query=query,
            top_k=semantic_limit,
            topic=topic,
            layer=layer,
        )
        semantic_memories = tuple(
            reference
            for memory in memories
            if (reference := _memory_reference(memory)) is not None
            and all(exact.memory_id != reference.memory_id for exact in exact_memories)
        )
        return (*exact_memories, *semantic_memories[:semantic_limit])

    def apply(
        self,
        action: MemoryAction,
        scope: MemoryScope,
    ) -> MemoryOperationOutcome:
        with self._operation_lock:
            return self._apply(action, scope)

    def _apply(
        self,
        action: MemoryAction,
        scope: MemoryScope,
    ) -> MemoryOperationOutcome:
        if scope == "none":
            return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_SCOPE_NONE)

        if action.list_operation is not None:
            expected_scope: MemoryScope = (
                "list_relevant"
                if action.list_operation.list_name == "shopping"
                else "task_relevant_only"
            )
            if scope != expected_scope:
                return MemoryOperationOutcome(
                    MemoryOperationStatus.STRUCTURED_LIST_SCOPE_MISMATCH
                )
        elif scope == "list_relevant" and action.action in {"store", "update"}:
            return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_SCOPE_MISMATCH)
        target_outcome = self._authorize_target(action, scope)
        if target_outcome is not None:
            return target_outcome
        command = _memory_command_from_action(action, scope)
        return self._manager.execute_memory_command(command)

    def delete_all(self) -> BulkMemoryDeleteResult:
        """Delete the current snapshot with revision-safe manager operations."""

        with self._operation_lock:
            memories = self._manager.get_all_memories()
            if not memories:
                return BulkMemoryDeleteResult(
                    0,
                    MemoryOperationOutcome(MemoryOperationStatus.NO_CHANGES),
                )

            deleted_count = 0
            pending_cleanup = False
            failed_ids: list[int] = []
            for memory in memories:
                outcome = self._manager.delete_memory(
                    memory.id,
                    expected_revision=memory.revision,
                )
                if outcome.succeeded:
                    deleted_count += 1
                    pending_cleanup = pending_cleanup or (
                        outcome.status
                        is MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP
                    )
                else:
                    failed_ids.append(memory.id)

            if failed_ids:
                return BulkMemoryDeleteResult(
                    deleted_count,
                    MemoryOperationOutcome(
                        MemoryOperationStatus.DELETE_ERROR,
                        detail=(
                            "Could not delete memory IDs "
                            + ", ".join(str(memory_id) for memory_id in failed_ids)
                        ),
                    ),
                )
            status = (
                MemoryOperationStatus.DELETED_PENDING_INDEX_CLEANUP
                if pending_cleanup
                else MemoryOperationStatus.DELETED_SUCCESSFULLY
            )
            return BulkMemoryDeleteResult(
                deleted_count,
                MemoryOperationOutcome(status),
            )

    def _authorize_target(
        self,
        action: MemoryAction,
        scope: MemoryScope,
    ) -> MemoryOperationOutcome | None:
        """Reject exact targets outside the current app-owned memory scope."""

        target = action.target
        if target is None:
            return None
        if target.memory_key is not None and not _scope_allows_key(
            scope,
            target.memory_key,
        ):
            return MemoryOperationOutcome(MemoryOperationStatus.MEMORY_SCOPE_MISMATCH)

        memory: MemoryRecord | None
        if target.memory_id is not None:
            memory = self._manager.get_memory_by_id(target.memory_id)
        elif target.memory_key is not None:
            memory = self._manager.get_memory_by_key(target.memory_key)
        else:
            memory = None
        if memory is not None and not _scope_contains_memory(scope, memory):
            return MemoryOperationOutcome(
                MemoryOperationStatus.MEMORY_SCOPE_MISMATCH,
                memory_id=memory.id,
            )
        return None

    def close(self) -> None:
        """Close the underlying memory manager."""

        with self._operation_lock:
            self._manager.close()


def build_local_memory_gateway(
    config: LocalMemoryConfig | None = None,
) -> MemoryManagerGateway:
    """Build the app gateway over persistent local memory components."""

    from voice_concierge.memory.factory import build_memory_manager

    return MemoryManagerGateway(build_memory_manager(config))


def _retrieval_metadata(scope: MemoryScope) -> tuple[str | None, str | None]:
    metadata: dict[MemoryScope, tuple[str | None, str | None]] = {
        "none": (None, None),
        "personal_relevant": ("profile", None),
        "task_relevant_only": ("feedback", "task"),
        "list_relevant": ("feedback", "shopping"),
    }
    return metadata[scope]


def _storage_metadata(scope: MemoryScope) -> tuple[str, str | None]:
    metadata: dict[MemoryScope, tuple[str, str | None]] = {
        "none": ("feedback", None),
        "personal_relevant": ("profile", None),
        "task_relevant_only": ("feedback", "task"),
        "list_relevant": ("feedback", "shopping"),
    }
    return metadata[scope]


def _accessibility_preference_key(query: str) -> str | None:
    normalized = " ".join(query.casefold().split())
    if re.search(
        r"\b(?:speak|talk|answer)\s+"
        r"(?:(?:a|one)\s+)?(?:(?:little|bit)\s+)?"
        r"(?:more\s+slowly|slower)\b",
        normalized,
    ):
        return "preference:accessibility.preferred_pace"
    if "keep answers short" in normalized or "short answers" in normalized:
        return "preference:accessibility.verbosity"
    return None


def _memory_command_from_action(
    action: MemoryAction,
    scope: MemoryScope,
) -> MemoryCommand:
    """Translate an untrusted reasoning proposal into a memory-owned command."""

    if action.list_operation is not None:
        assert action.target is not None
        return ApplyStructuredListCommand(
            target=_command_target(action.target),
            mutation=StructuredListMutation(
                list_name=action.list_operation.list_name,
                items=action.list_operation.items,
                operation=action.list_operation.operation,
            ),
        )

    if action.action == "store":
        assert action.content is not None
        layer, topic = _storage_metadata(scope)
        return StoreMemoryCommand(
            content=action.content,
            layer=layer,
            memory_key=(
                action.target.memory_key if action.target is not None else None
            ),
            topic=topic,
        )

    assert action.target is not None
    if action.action == "update":
        assert action.content is not None
        return UpdateMemoryCommand(
            target=_command_target(action.target),
            content=action.content,
        )
    return DeleteMemoryCommand(target=_command_target(action.target))


def _command_target(target: object) -> MemoryCommandTarget:
    if not isinstance(target, MemoryTarget):
        raise TypeError("Memory proposal target must be MemoryTarget.")
    return MemoryCommandTarget(
        memory_id=target.memory_id,
        memory_key=target.memory_key,
        expected_revision=target.expected_revision,
    )


def _scope_allows_key(scope: MemoryScope, memory_key: str) -> bool:
    if scope == "personal_relevant":
        return memory_key.startswith("preference:")
    if scope == "task_relevant_only":
        return memory_key == TASK_LIST_MEMORY_KEY
    if scope == "list_relevant":
        return memory_key == SHOPPING_LIST_MEMORY_KEY
    return False


def _scope_contains_memory(scope: MemoryScope, memory: MemoryRecord) -> bool:
    if scope == "personal_relevant":
        return memory.layer == "profile"
    if scope == "task_relevant_only":
        return memory.layer == "feedback" and memory.topic == "task"
    if scope == "list_relevant":
        return memory.memory_key == SHOPPING_LIST_MEMORY_KEY
    return False


def _memory_reference(
    value: MemoryRecord | MemorySearchResult | None,
) -> MemoryReference | None:
    if isinstance(value, MemorySearchResult):
        memory = value.memory
    elif isinstance(value, MemoryRecord):
        memory = value
    else:
        return None
    content = memory.content
    list_name = None
    if memory.memory_key == SHOPPING_LIST_MEMORY_KEY:
        list_name = "shopping"
    elif memory.memory_key == TASK_LIST_MEMORY_KEY:
        list_name = "task"
    if list_name is not None:
        content = canonicalize_structured_list_content(content, list_name) or content
    return MemoryReference(
        memory_id=memory.id,
        content=content,
        layer=memory.layer,
        revision=memory.revision,
        memory_key=memory.memory_key,
        topic=memory.topic,
    )


class MemoryManagerPort(Protocol):
    """Typed manager operations consumed by the app memory gateway."""

    def get_memory_by_key(self, memory_key: str) -> MemoryRecord | None: ...

    def get_memory_by_id(self, memory_id: int) -> MemoryRecord | None: ...

    def retrieve_similar(
        self,
        *,
        query: str,
        top_k: int,
        topic: str | None,
        layer: str | None,
    ) -> list[MemorySearchResult]: ...

    def execute_memory_command(
        self,
        command: MemoryCommand,
    ) -> MemoryOperationOutcome: ...

    def get_all_memories(self) -> list[MemoryRecord]: ...

    def delete_memory(
        self,
        memory_id: int,
        expected_revision: int | None = None,
    ) -> MemoryOperationOutcome: ...

    def close(self) -> None: ...
