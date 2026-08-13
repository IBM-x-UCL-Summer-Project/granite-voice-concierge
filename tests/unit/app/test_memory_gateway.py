"""Tests for app-level memory gateway adapters."""

from __future__ import annotations

from voice_concierge.app.memory import MemoryManagerGateway, NullMemoryGateway
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryReference,
    MemoryTarget,
    StructuredListOperation,
)


class FakeMemoryManager:
    def __init__(self) -> None:
        self.retrieve_calls: list[dict[str, object]] = []
        self.store_calls: list[dict[str, object]] = []
        self.processed_actions: list[MemoryAction] = []
        self.closed = False

    def retrieve_similar(
        self,
        *,
        query: str,
        top_k: int,
        topic: str | None,
    ) -> list[dict[str, object]]:
        self.retrieve_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "topic": topic,
            }
        )
        return [
            {
                "id": 1,
                "content": "Remembered milk.",
                "layer": "feedback",
                "revision": 2,
                "memory_key": "list:shopping",
                "topic": "shopping",
            },
            {"content": 123},
            {
                "id": 2,
                "content": "Remembered bread.",
                "layer": "feedback",
                "revision": 1,
                "memory_key": None,
                "topic": "shopping",
            },
        ]

    def store_memory(
        self,
        *,
        content: str,
        layer: str,
        memory_key: str | None,
        topic: str | None,
        validate: bool,
        auto_classify: bool,
        auto_extract: bool,
    ) -> tuple[bool, str, int]:
        self.store_calls.append(
            {
                "content": content,
                "layer": layer,
                "memory_key": memory_key,
                "topic": topic,
                "validate": validate,
                "auto_classify": auto_classify,
                "auto_extract": auto_extract,
            }
        )
        return True, "stored_successfully", 42

    def process_memory_action(self, action: MemoryAction) -> tuple[bool, str]:
        self.processed_actions.append(action)
        return True, "processed"

    def close(self) -> None:
        self.closed = True


def test_null_memory_gateway_returns_no_memories_and_blocks_writes() -> None:
    gateway = NullMemoryGateway()
    action = MemoryAction(
        action="store",
        content="User likes tea.",
        rationale="User asked the assistant to remember it.",
    )

    assert gateway.retrieve("tea", "personal_relevant") == ()
    assert gateway.apply(action, "personal_relevant") == (
        False,
        "memory_not_configured",
    )


def test_memory_manager_gateway_retrieves_content_for_scoped_query() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    memories = gateway.retrieve(
        "What is on my shopping list?", "list_relevant", limit=2
    )

    assert memories == (
        MemoryReference(
            memory_id=1,
            content="Remembered milk.",
            layer="feedback",
            revision=2,
            memory_key="list:shopping",
            topic="shopping",
        ),
        MemoryReference(
            memory_id=2,
            content="Remembered bread.",
            layer="feedback",
            revision=1,
            topic="shopping",
        ),
    )
    assert manager.retrieve_calls == [
        {
            "query": "What is on my shopping list?",
            "top_k": 2,
            "topic": "shopping",
        }
    ]


def test_memory_manager_gateway_skips_retrieval_when_scope_is_none() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    assert gateway.retrieve("Do I need fuel?", "none") == ()
    assert manager.retrieve_calls == []


def test_memory_manager_gateway_applies_store_with_scope_metadata() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content="Shopping list includes milk.",
        rationale="User added milk to the list.",
    )

    assert gateway.apply(action, "list_relevant") == (True, "stored_successfully")
    assert manager.store_calls == [
        {
            "content": "Shopping list includes milk.",
            "layer": "feedback",
            "memory_key": None,
            "topic": "shopping",
            "validate": False,
            "auto_classify": False,
            "auto_extract": False,
        }
    ]


def test_memory_manager_gateway_delegates_update_and_delete_actions() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="delete",
        content="Remove old appointment.",
        rationale="User asked to forget it.",
        target=MemoryTarget(memory_id=42, expected_revision=3),
    )

    assert gateway.apply(action, "personal_relevant") == (True, "processed")
    assert manager.processed_actions == [action]


def test_memory_manager_gateway_delegates_typed_list_store() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content=None,
        rationale="User added the first shopping item.",
        target=MemoryTarget(memory_key="list:shopping"),
        list_operation=StructuredListOperation(
            list_name="shopping",
            operation="add_items",
            items=("milk",),
        ),
    )

    assert gateway.apply(action, "list_relevant") == (True, "processed")
    assert manager.processed_actions == [action]
    assert manager.store_calls == []


def test_memory_manager_gateway_rejects_list_scope_mismatch() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content=None,
        rationale="User added the first task.",
        target=MemoryTarget(memory_key="list:tasks"),
        list_operation=StructuredListOperation(
            list_name="task",
            operation="add_items",
            items=("call the dentist",),
        ),
    )

    assert gateway.apply(action, "list_relevant") == (
        False,
        "structured_list_scope_mismatch",
    )
    assert manager.processed_actions == []


def test_memory_manager_gateway_blocks_apply_when_scope_is_none() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content="User likes tea.",
        rationale="User asked the assistant to remember it.",
    )

    assert gateway.apply(action, "none") == (False, "memory_scope_none")
    assert manager.store_calls == []
    assert manager.processed_actions == []


def test_memory_manager_gateway_closes_manager() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    gateway.close()

    assert manager.closed is True
