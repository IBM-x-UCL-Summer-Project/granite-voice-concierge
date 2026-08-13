"""Tests for app-level memory gateway adapters."""

from __future__ import annotations

from voice_concierge.app.memory import MemoryManagerGateway, NullMemoryGateway
from voice_concierge.memory import (
    MemoryOperationOutcome,
    MemoryOperationStatus,
    MemoryRecord,
    MemorySearchResult,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryReference,
    MemoryTarget,
    StructuredListOperation,
)


class FakeMemoryManager:
    def __init__(self) -> None:
        self.key_calls: list[str] = []
        self.retrieve_calls: list[dict[str, object]] = []
        self.store_calls: list[dict[str, object]] = []
        self.processed_actions: list[MemoryAction] = []
        self.closed = False
        self.keyed_memories: dict[str, MemoryRecord] = {
            "list:shopping": _memory_record(
                memory_id=10,
                content="Shopping list: milk, bread.",
                revision=3,
                memory_key="list:shopping",
                topic="shopping",
            ),
            "list:tasks": _memory_record(
                memory_id=20,
                content="Task list: call the dentist.",
                revision=4,
                memory_key="list:tasks",
                topic="task",
            ),
        }

    def get_memory_by_key(self, memory_key: str) -> MemoryRecord | None:
        self.key_calls.append(memory_key)
        return self.keyed_memories.get(memory_key)

    def retrieve_similar(
        self,
        *,
        query: str,
        top_k: int,
        topic: str | None,
    ) -> list[MemorySearchResult]:
        self.retrieve_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "topic": topic,
            }
        )
        content = (
            "Remembered task context."
            if topic == "task"
            else "Remembered personal context."
        )
        return [
            MemorySearchResult(
                memory=_memory_record(
                    memory_id=1,
                    content=content,
                    revision=2,
                    topic=topic,
                ),
                distance=0.1,
            ),
            MemorySearchResult(
                memory=_memory_record(
                    memory_id=2,
                    content="Remembered bread.",
                    revision=1,
                    topic=topic,
                ),
                distance=0.2,
            ),
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
    ) -> MemoryOperationOutcome:
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
        return MemoryOperationOutcome(
            MemoryOperationStatus.STORED_SUCCESSFULLY,
            memory_id=42,
        )

    def process_memory_action(self, action: MemoryAction) -> MemoryOperationOutcome:
        self.processed_actions.append(action)
        return MemoryOperationOutcome(MemoryOperationStatus.UPDATED_SUCCESSFULLY)

    def close(self) -> None:
        self.closed = True


def _memory_record(
    *,
    memory_id: int,
    content: str,
    revision: int,
    memory_key: str | None = None,
    topic: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        content=content,
        layer="feedback",
        memory_key=memory_key,
        revision=revision,
        indexed_revision=revision,
        deleted_at=None,
        created_at=1,
        event_time=None,
        last_accessed=None,
        strength=1,
        person=None,
        source_type=None,
        topic=topic,
    )


def test_null_memory_gateway_returns_no_memories_and_blocks_writes() -> None:
    gateway = NullMemoryGateway()
    action = MemoryAction(
        action="store",
        content="User likes tea.",
        rationale="User asked the assistant to remember it.",
    )

    assert gateway.retrieve("tea", "personal_relevant") == ()
    outcome = gateway.apply(action, "personal_relevant")
    assert outcome.status is MemoryOperationStatus.MEMORY_NOT_CONFIGURED
    assert outcome.succeeded is False


def test_memory_manager_gateway_semantically_retrieves_personal_context() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    memories = gateway.retrieve("What should I drink?", "personal_relevant", limit=2)

    assert memories == (
        MemoryReference(
            memory_id=1,
            content="Remembered personal context.",
            layer="feedback",
            revision=2,
        ),
        MemoryReference(
            memory_id=2,
            content="Remembered bread.",
            layer="feedback",
            revision=1,
        ),
    )
    assert manager.retrieve_calls == [
        {
            "query": "What should I drink?",
            "top_k": 2,
            "topic": None,
        }
    ]
    assert manager.key_calls == []


def test_memory_manager_gateway_retrieves_shopping_list_by_stable_key() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    memories = gateway.retrieve(
        "Semantically unrelated wording", "list_relevant", limit=3
    )

    assert memories == (
        MemoryReference(
            memory_id=10,
            content="Shopping list: milk, bread.",
            layer="feedback",
            revision=3,
            memory_key="list:shopping",
            topic="shopping",
        ),
    )
    assert manager.key_calls == ["list:shopping"]
    assert manager.retrieve_calls == []


def test_memory_manager_gateway_does_not_semantically_substitute_missing_list() -> None:
    manager = FakeMemoryManager()
    manager.keyed_memories.pop("list:shopping")
    gateway = MemoryManagerGateway(manager)

    memories = gateway.retrieve("milk", "list_relevant", limit=3)

    assert memories == ()
    assert manager.key_calls == ["list:shopping"]
    assert manager.retrieve_calls == []


def test_memory_manager_gateway_keeps_task_list_ahead_of_semantic_context() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    memories = gateway.retrieve("What is the next step?", "task_relevant_only", limit=2)

    assert memories == (
        MemoryReference(
            memory_id=20,
            content="Task list: call the dentist.",
            layer="feedback",
            revision=4,
            memory_key="list:tasks",
            topic="task",
        ),
        MemoryReference(
            memory_id=1,
            content="Remembered task context.",
            layer="feedback",
            revision=2,
            topic="task",
        ),
    )
    assert manager.key_calls == ["list:tasks"]
    assert manager.retrieve_calls == [
        {
            "query": "What is the next step?",
            "top_k": 1,
            "topic": "task",
        }
    ]


def test_memory_manager_gateway_skips_retrieval_when_scope_is_none() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    assert gateway.retrieve("Do I need fuel?", "none") == ()
    assert manager.retrieve_calls == []
    assert manager.key_calls == []


def test_memory_manager_gateway_applies_store_with_scope_metadata() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content="Shopping list includes milk.",
        rationale="User added milk to the list.",
    )

    outcome = gateway.apply(action, "list_relevant")
    assert outcome.status is MemoryOperationStatus.STORED_SUCCESSFULLY
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

    outcome = gateway.apply(action, "personal_relevant")
    assert outcome.status is MemoryOperationStatus.UPDATED_SUCCESSFULLY
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

    outcome = gateway.apply(action, "list_relevant")
    assert outcome.status is MemoryOperationStatus.UPDATED_SUCCESSFULLY
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

    assert gateway.apply(action, "list_relevant").status is (
        MemoryOperationStatus.STRUCTURED_LIST_SCOPE_MISMATCH
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

    assert (
        gateway.apply(action, "none").status is MemoryOperationStatus.MEMORY_SCOPE_NONE
    )
    assert manager.store_calls == []
    assert manager.processed_actions == []


def test_memory_manager_gateway_closes_manager() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    gateway.close()

    assert manager.closed is True
