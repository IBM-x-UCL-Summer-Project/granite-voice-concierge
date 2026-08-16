"""Tests for app-level memory gateway adapters."""

from __future__ import annotations

from voice_concierge.app.memory import MemoryManagerGateway, NullMemoryGateway
from voice_concierge.memory import (
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
        self.id_calls: list[int] = []
        self.retrieve_calls: list[dict[str, object]] = []
        self.processed_commands: list[MemoryCommand] = []
        self.deleted: list[tuple[int, int | None]] = []
        self.delete_outcomes: dict[int, MemoryOperationOutcome] = {}
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
        self.id_memories: dict[int, MemoryRecord] = {
            42: _memory_record(
                memory_id=42,
                content="Old appointment.",
                revision=3,
                layer="profile",
            )
        }

    def get_memory_by_key(self, memory_key: str) -> MemoryRecord | None:
        self.key_calls.append(memory_key)
        return self.keyed_memories.get(memory_key)

    def get_memory_by_id(self, memory_id: int) -> MemoryRecord | None:
        self.id_calls.append(memory_id)
        keyed_memory = next(
            (
                memory
                for memory in self.keyed_memories.values()
                if memory.id == memory_id
            ),
            None,
        )
        return keyed_memory or self.id_memories.get(memory_id)

    def retrieve_similar(
        self,
        *,
        query: str,
        top_k: int,
        topic: str | None,
        layer: str | None,
    ) -> list[MemorySearchResult]:
        self.retrieve_calls.append(
            {
                "query": query,
                "top_k": top_k,
                "topic": topic,
                "layer": layer,
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
                    layer=layer or "feedback",
                ),
                distance=0.1,
            ),
            MemorySearchResult(
                memory=_memory_record(
                    memory_id=2,
                    content="Remembered bread.",
                    revision=1,
                    topic=topic,
                    layer=layer or "feedback",
                ),
                distance=0.2,
            ),
        ]

    def execute_memory_command(
        self,
        command: MemoryCommand,
    ) -> MemoryOperationOutcome:
        self.processed_commands.append(command)
        if isinstance(command, StoreMemoryCommand):
            return MemoryOperationOutcome(
                MemoryOperationStatus.STORED_SUCCESSFULLY,
                memory_id=42,
            )
        return MemoryOperationOutcome(MemoryOperationStatus.UPDATED_SUCCESSFULLY)

    def get_all_memories(self) -> list[MemoryRecord]:
        return [*self.keyed_memories.values(), *self.id_memories.values()]

    def delete_memory(
        self,
        memory_id: int,
        expected_revision: int | None = None,
    ) -> MemoryOperationOutcome:
        self.deleted.append((memory_id, expected_revision))
        return self.delete_outcomes.get(
            memory_id,
            MemoryOperationOutcome(
                MemoryOperationStatus.DELETED_SUCCESSFULLY,
                memory_id=memory_id,
            ),
        )

    def close(self) -> None:
        self.closed = True


def _memory_record(
    *,
    memory_id: int,
    content: str,
    revision: int,
    layer: str = "feedback",
    memory_key: str | None = None,
    topic: str | None = None,
) -> MemoryRecord:
    return MemoryRecord(
        id=memory_id,
        content=content,
        layer=layer,
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
    bulk = gateway.delete_all()
    assert bulk.deleted_count == 0
    assert bulk.outcome.status is MemoryOperationStatus.MEMORY_NOT_CONFIGURED


def test_memory_manager_gateway_deletes_snapshot_with_exact_revisions() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    result = gateway.delete_all()

    assert result.deleted_count == 3
    assert result.outcome.status is MemoryOperationStatus.DELETED_SUCCESSFULLY
    assert manager.deleted == [(10, 3), (20, 4), (42, 3)]


def test_memory_manager_gateway_reports_partial_bulk_delete() -> None:
    manager = FakeMemoryManager()
    manager.delete_outcomes[20] = MemoryOperationOutcome(
        MemoryOperationStatus.MEMORY_REVISION_CONFLICT,
        memory_id=20,
    )
    gateway = MemoryManagerGateway(manager)

    result = gateway.delete_all()

    assert result.deleted_count == 2
    assert result.outcome.status is MemoryOperationStatus.DELETE_ERROR
    assert result.outcome.detail == "Could not delete memory IDs 20"


def test_memory_manager_gateway_semantically_retrieves_personal_context() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    memories = gateway.retrieve("What should I drink?", "personal_relevant", limit=2)

    assert memories == (
        MemoryReference(
            memory_id=1,
            content="Remembered personal context.",
            layer="profile",
            revision=2,
        ),
        MemoryReference(
            memory_id=2,
            content="Remembered bread.",
            layer="profile",
            revision=1,
        ),
    )
    assert manager.retrieve_calls == [
        {
            "query": "What should I drink?",
            "top_k": 2,
            "topic": None,
            "layer": "profile",
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


def test_memory_manager_gateway_repairs_legacy_list_wrapper_for_reasoning() -> None:
    manager = FakeMemoryManager()
    manager.keyed_memories["list:shopping"] = _memory_record(
        memory_id=10,
        content="Shopping list: I'll add milk, bread.",
        revision=3,
        memory_key="list:shopping",
        topic="shopping",
    )
    gateway = MemoryManagerGateway(manager)

    memories = gateway.retrieve("What is on my shopping list?", "list_relevant")

    assert memories[0].content == "Shopping list: milk, bread."
    assert memories[0].memory_id == 10
    assert memories[0].revision == 3


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
            "layer": "feedback",
        }
    ]


def test_memory_manager_gateway_skips_retrieval_when_scope_is_none() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    assert gateway.retrieve("Do I need fuel?", "none") == ()
    assert manager.retrieve_calls == []
    assert manager.key_calls == []


def test_memory_manager_gateway_rejects_untyped_shopping_list_store() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content="Shopping list includes milk.",
        rationale="User added milk to the list.",
    )

    outcome = gateway.apply(action, "list_relevant")
    assert outcome.status is MemoryOperationStatus.MEMORY_SCOPE_MISMATCH
    assert manager.processed_commands == []


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
    assert manager.processed_commands == [
        DeleteMemoryCommand(
            target=MemoryCommandTarget(memory_id=42, expected_revision=3),
        )
    ]


def test_memory_manager_gateway_rejects_target_outside_active_scope() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="delete",
        content="Delete the shopping list.",
        rationale="User requested deletion.",
        target=MemoryTarget(
            memory_id=10,
            memory_key="list:shopping",
            expected_revision=3,
        ),
    )

    outcome = gateway.apply(action, "personal_relevant")

    assert outcome.status is MemoryOperationStatus.MEMORY_SCOPE_MISMATCH
    assert outcome.memory_id is None
    assert manager.processed_commands == []


def test_memory_manager_gateway_rejects_same_topic_non_list_target() -> None:
    manager = FakeMemoryManager()
    manager.id_memories[50] = _memory_record(
        memory_id=50,
        content="Shopping note: compare prices.",
        revision=2,
        topic="shopping",
    )
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="delete",
        content="Shopping note: compare prices.",
        rationale="Attempted same-topic deletion.",
        target=MemoryTarget(memory_id=50, expected_revision=2),
    )

    outcome = gateway.apply(action, "list_relevant")

    assert outcome.status is MemoryOperationStatus.MEMORY_SCOPE_MISMATCH
    assert outcome.memory_id == 50
    assert manager.processed_commands == []


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
    assert manager.processed_commands == [
        ApplyStructuredListCommand(
            target=MemoryCommandTarget(memory_key="list:shopping"),
            mutation=StructuredListMutation(
                list_name="shopping",
                items=("milk",),
            ),
        )
    ]


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
    assert manager.processed_commands == []


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
    assert manager.processed_commands == []


def test_memory_manager_gateway_closes_manager() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)

    gateway.close()

    assert manager.closed is True
