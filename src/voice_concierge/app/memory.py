"""Memory gateway used by the application pipeline."""

from __future__ import annotations

from typing import Any, Protocol

from voice_concierge.context.types import MemoryScope
from voice_concierge.memory import LocalMemoryConfig, build_memory_manager
from voice_concierge.reasoning.types import MemoryAction


class MemoryGateway(Protocol):
    """Small app-owned boundary over memory retrieval and confirmed writes."""

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        """Return memory snippets relevant to one user query."""

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
    ) -> tuple[str, ...]:
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
    ) -> tuple[str, ...]:
        if scope == "none":
            return ()

        topic = _retrieval_topic(scope)
        memories = self._manager.retrieve_similar(
            query=query,
            top_k=limit,
            topic=topic,
        )
        return tuple(
            memory["content"]
            for memory in memories
            if isinstance(memory, dict) and isinstance(memory.get("content"), str)
        )

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        if scope == "none":
            return False, "memory_scope_none"

        if action.action == "store":
            layer, topic = _storage_metadata(scope)
            success, reason, _memory_id = self._manager.store_memory(
                content=action.content,
                layer=layer,
                memory_key=action.target_key,
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
