"""Memory gateway used by the application pipeline."""

from __future__ import annotations

from typing import Any, Protocol

from voice_concierge.context.types import MemoryScope
from voice_concierge.memory import LocalMemoryConfig, build_memory_manager
from voice_concierge.reasoning.types import (
    SHOPPING_LIST_MEMORY_KEY,
    TASK_LIST_MEMORY_KEY,
    MemoryAction,
    MemoryReference,
)


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

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        """Apply a previously confirmed memory action."""

    def close(self) -> None:
        """Release persistent memory resources."""


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

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        return False, "memory_not_configured"

    def close(self) -> None:
        """Release no resources for the no-op gateway."""


class MemoryManagerGateway:
    """Adapter from the app pipeline boundary to the current MemoryManager."""

    def __init__(self, manager: Any) -> None:
        self._manager = manager

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 3,
    ) -> tuple[MemoryReference, ...]:
        if scope == "none" or limit <= 0:
            return ()

        if scope == "list_relevant":
            shopping_list = _memory_reference(
                self._manager.get_memory_by_key(SHOPPING_LIST_MEMORY_KEY)
            )
            return (shopping_list,) if shopping_list is not None else ()

        exact_memories: tuple[MemoryReference, ...] = ()
        if scope == "task_relevant_only":
            task_list = _memory_reference(
                self._manager.get_memory_by_key(TASK_LIST_MEMORY_KEY)
            )
            if task_list is not None:
                exact_memories = (task_list,)

        semantic_limit = limit - len(exact_memories)
        if semantic_limit <= 0:
            return exact_memories

        topic = _retrieval_topic(scope)
        memories = self._manager.retrieve_similar(
            query=query,
            top_k=semantic_limit,
            topic=topic,
        )
        semantic_memories = tuple(
            reference
            for memory in memories
            if (reference := _memory_reference(memory)) is not None
            and all(exact.memory_id != reference.memory_id for exact in exact_memories)
        )
        return (*exact_memories, *semantic_memories[:semantic_limit])

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        if scope == "none":
            return False, "memory_scope_none"

        if action.list_operation is not None:
            expected_scope: MemoryScope = (
                "list_relevant"
                if action.list_operation.list_name == "shopping"
                else "task_relevant_only"
            )
            if scope != expected_scope:
                return False, "structured_list_scope_mismatch"
            return self._manager.process_memory_action(action)

        if action.action == "store":
            assert action.content is not None
            layer, topic = _storage_metadata(scope)
            memory_key = action.target.memory_key if action.target is not None else None
            success, reason, _memory_id = self._manager.store_memory(
                content=action.content,
                layer=layer,
                memory_key=memory_key,
                topic=topic,
                validate=False,
                auto_classify=False,
                auto_extract=False,
            )
            return success, reason

        return self._manager.process_memory_action(action)

    def close(self) -> None:
        """Close the underlying memory manager."""

        self._manager.close()


def build_local_memory_gateway(
    config: LocalMemoryConfig | None = None,
) -> MemoryManagerGateway:
    """Build the app gateway over persistent local memory components."""

    return MemoryManagerGateway(build_memory_manager(config))


def _retrieval_topic(scope: MemoryScope) -> str | None:
    topics: dict[MemoryScope, str | None] = {
        "none": None,
        "personal_relevant": None,
        "task_relevant_only": "task",
        "list_relevant": "shopping",
    }
    return topics[scope]


def _storage_metadata(scope: MemoryScope) -> tuple[str, str | None]:
    metadata: dict[MemoryScope, tuple[str, str | None]] = {
        "none": ("feedback", None),
        "personal_relevant": ("profile", None),
        "task_relevant_only": ("feedback", "task"),
        "list_relevant": ("feedback", "shopping"),
    }
    return metadata[scope]


def _memory_reference(value: object) -> MemoryReference | None:
    if not isinstance(value, dict):
        return None
    memory_id = value.get("id")
    content = value.get("content")
    layer = value.get("layer")
    revision = value.get("revision")
    memory_key = value.get("memory_key")
    topic = value.get("topic")
    if (
        not isinstance(memory_id, int)
        or isinstance(memory_id, bool)
        or not isinstance(content, str)
        or not isinstance(layer, str)
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or (memory_key is not None and not isinstance(memory_key, str))
        or (topic is not None and not isinstance(topic, str))
    ):
        return None
    try:
        return MemoryReference(
            memory_id=memory_id,
            content=content,
            layer=layer,
            revision=revision,
            memory_key=memory_key,
            topic=topic,
        )
    except ValueError:
        return None
