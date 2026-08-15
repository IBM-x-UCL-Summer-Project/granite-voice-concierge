"""Tests for app-level memory gateway adapters."""

from __future__ import annotations

from voice_concierge.app.memory import MemoryManagerGateway, NullMemoryGateway
from voice_concierge.reasoning.types import MemoryAction


class FakeMemoryManager:
    def __init__(self) -> None:
        self.retrieve_calls: list[dict[str, object]] = []
        self.store_calls: list[dict[str, object]] = []
        self.processed_actions: list[MemoryAction] = []
        self.metadata_memories: list[dict[str, object]] = [
            {"content": "shopping_list:add:cookies"},
            {"content": "shopping_list:add:milk"},
            {"content": "shopping_list:add:tea"},
            {"content": "shopping_list:add:meat"},
            {"content": "shopping_list:add:onions"},
        ]
        self.closed = False

    def retrieve_by_metadata(
        self,
        *,
        topic: str | None,
        person: str | None = None,
        layer: str | None = None,
    ) -> list[dict[str, object]]:
        self.retrieve_calls.append(
            {"topic": topic, "person": person, "layer": layer, "metadata": True}
        )
        return self.metadata_memories

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
            {"content": "Remembered milk."},
            {"content": 123},
            {"content": "Remembered bread."},
        ]

    def store_memory(
        self,
        *,
        content: str,
        layer: str,
        topic: str | None,
        validate: bool,
        auto_classify: bool,
        auto_extract: bool,
        check_duplicates: bool = True,
    ) -> tuple[bool, str, int]:
        self.store_calls.append(
            {
                "content": content,
                "layer": layer,
                "topic": topic,
                "validate": validate,
                "auto_classify": auto_classify,
                "auto_extract": auto_extract,
                "check_duplicates": check_duplicates,
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
        "shopping_list:add:cookies",
        "shopping_list:add:milk",
        "shopping_list:add:tea",
        "shopping_list:add:meat",
        "shopping_list:add:onions",
    )
    assert manager.retrieve_calls == [
        {
            "topic": "shopping",
            "person": None,
            "layer": None,
            "metadata": True,
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
            "topic": "shopping",
            "validate": False,
            "auto_classify": False,
            "auto_extract": False,
            "check_duplicates": True,
        }
    ]


def test_memory_manager_gateway_appends_owned_shopping_list_event() -> None:
    manager = FakeMemoryManager()
    manager.metadata_memories = []
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="update",
        content="shopping_list:add:ice cream and onions",
        rationale="User asked to add an item.",
    )

    assert gateway.apply(action, "list_relevant") == (True, "stored_successfully")
    assert manager.store_calls == [
        {
            "content": "shopping_list:add:ice cream",
            "layer": "feedback",
            "topic": "shopping",
            "validate": False,
            "auto_classify": False,
            "auto_extract": False,
            "check_duplicates": False,
        },
        {
            "content": "shopping_list:add:onions",
            "layer": "feedback",
            "topic": "shopping",
            "validate": False,
            "auto_classify": False,
            "auto_extract": False,
            "check_duplicates": False,
        },
    ]
    assert manager.processed_actions == []


def test_memory_manager_gateway_treats_existing_list_items_as_success() -> None:
    manager = FakeMemoryManager()
    manager.metadata_memories = [
        {"content": "ice cream"},
        {"content": "shopping_list:add:onions"},
    ]
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="update",
        content="shopping_list:add:ice cream and onions",
        rationale="User asked to add items.",
    )

    assert gateway.apply(action, "list_relevant") == (
        True,
        "shopping_list_unchanged",
    )
    assert manager.store_calls == []


def test_memory_manager_gateway_treats_canonical_store_of_legacy_item_as_success() -> (
    None
):
    manager = FakeMemoryManager()
    manager.metadata_memories = [{"content": "ice cream"}]
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="store",
        content="shopping_list:add:ice cream",
        rationale="User asked to add an item already stored in the legacy format.",
    )

    assert gateway.apply(action, "list_relevant") == (
        True,
        "shopping_list_unchanged",
    )
    assert manager.store_calls == []


def test_memory_manager_gateway_normalizes_model_generated_list_update() -> None:
    manager = FakeMemoryManager()
    manager.metadata_memories = []
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="update",
        content="Add mouth to the list",
        rationale="Model proposed a non-canonical list update.",
    )

    assert gateway.apply(action, "list_relevant") == (True, "stored_successfully")
    assert manager.store_calls[0]["content"] == "shopping_list:add:mouth"
    assert manager.processed_actions == []


def test_memory_manager_gateway_delegates_update_and_delete_actions() -> None:
    manager = FakeMemoryManager()
    gateway = MemoryManagerGateway(manager)
    action = MemoryAction(
        action="delete",
        content="Remove old appointment.",
        rationale="User asked to forget it.",
    )

    assert gateway.apply(action, "personal_relevant") == (True, "processed")
    assert manager.processed_actions == [action]


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
