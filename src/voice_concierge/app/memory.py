"""Memory gateway used by the application pipeline."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Protocol

from voice_concierge.context.types import MemoryScope
from voice_concierge.reasoning.types import MemoryAction

if TYPE_CHECKING:
    from voice_concierge.memory.factory import LocalMemoryConfig


class MemoryGateway(Protocol):
    """Small app-owned boundary over memory retrieval and confirmed writes."""

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        *,
        limit: int = 3,
    ) -> tuple[str, ...]:
        """Return relevant snippets, or the complete owned list for list scope."""

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
        if scope == "list_relevant":
            # A shopping list is an owned collection, not a similarity-ranked
            # context window. Returning every event prevents silent truncation.
            memories = self._manager.retrieve_by_metadata(topic=topic)
        else:
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

        is_shopping_list_addition = scope == "list_relevant" and (
            action.action == "update"
            or (
                action.action == "store"
                and action.content.casefold().startswith("shopping_list:add:")
            )
        )
        if is_shopping_list_addition:
            return self._append_shopping_list_items(action.content)

        if action.action == "store":
            layer, topic = _storage_metadata(scope)
            success, reason, _memory_id = self._manager.store_memory(
                content=action.content,
                layer=layer,
                topic=topic,
                validate=False,
                auto_classify=False,
                auto_extract=False,
            )
            return success, reason

        return self._manager.process_memory_action(action)

    def _append_shopping_list_items(self, content: str) -> tuple[bool, str]:
        requested_items = _split_shopping_list_items(
            _shopping_list_action_payload(content)
        )
        if not requested_items:
            return False, "shopping_list_items_missing"
        memories = self._manager.retrieve_by_metadata(topic="shopping")
        existing_items = {
            item.casefold()
            for memory in memories
            if isinstance(memory, dict) and isinstance(memory.get("content"), str)
            for item in _stored_shopping_list_items(memory["content"])
        }
        missing_items = [
            item for item in requested_items if item.casefold() not in existing_items
        ]
        if not missing_items:
            return True, "shopping_list_unchanged"

        for item in missing_items:
            success, reason, _memory_id = self._manager.store_memory(
                content=f"shopping_list:add:{item}",
                layer="feedback",
                topic="shopping",
                validate=False,
                auto_classify=False,
                auto_extract=False,
                check_duplicates=False,
            )
            if not success:
                return False, reason
        return True, "stored_successfully"

    def close(self) -> None:
        """Close the underlying memory manager."""

        self._manager.close()


def build_local_memory_gateway(
    config: LocalMemoryConfig | None = None,
) -> MemoryManagerGateway:
    """Build the app gateway over persistent local memory components."""

    from voice_concierge.memory.factory import build_memory_manager

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


def _stored_shopping_list_items(content: str) -> tuple[str, ...]:
    normalized = content.strip()
    prefix = "shopping_list:add:"
    if normalized.casefold().startswith(prefix):
        normalized = normalized[len(prefix) :]
    return _split_shopping_list_items(normalized)


def _shopping_list_action_payload(content: str) -> str:
    payload = content.strip()
    prefix = "shopping_list:add:"
    if payload.casefold().startswith(prefix):
        return payload[len(prefix) :]
    payload = re.sub(r"^\s*(?:please\s+)?add\s+", "", payload, flags=re.I)
    return re.sub(
        r"\s+to\s+(?:my|the)\s+(?:shopping\s+)?list\.?\s*$",
        "",
        payload,
        flags=re.I,
    )


def _split_shopping_list_items(content: str) -> tuple[str, ...]:
    items: list[str] = []
    seen: set[str] = set()
    for candidate in re.split(r"\s*(?:,|\band\b)\s*", content, flags=re.IGNORECASE):
        item = candidate.strip(" .'\"")
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            items.append(item)
    return tuple(items)
