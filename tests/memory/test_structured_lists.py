"""Tests for structured-list domain operations."""

import pytest

from voice_concierge.memory.structured_lists import (
    apply_structured_list_operation,
    create_structured_list,
    parse_legacy_structured_list,
    parse_structured_list,
)
from voice_concierge.memory.types import (
    ApplyStructuredListCommand,
    MemoryCommandTarget,
    StoreMemoryCommand,
    StructuredListMutation,
)


def _shopping_add(*items: str) -> StructuredListMutation:
    return StructuredListMutation(
        list_name="shopping",
        items=items,
    )


def test_create_structured_list_renders_canonical_content() -> None:
    operation = _shopping_add("milk", "bread")

    assert create_structured_list(operation) == "Shopping list: milk, bread."


def test_apply_structured_list_operation_deduplicates_case_insensitively() -> None:
    operation = _shopping_add("Milk", "eggs", "eggs")

    assert (
        apply_structured_list_operation(
            "Shopping list: bread, milk.",
            operation,
        )
        == "Shopping list: bread, milk, eggs."
    )


def test_apply_structured_list_operation_rejects_wrong_list_content() -> None:
    operation = _shopping_add("milk")

    assert apply_structured_list_operation("Task list: call Mum.", operation) is None


def test_parse_structured_list_supports_an_empty_canonical_list() -> None:
    assert parse_structured_list("Shopping list:.", _shopping_add("milk")) == ()


def test_structured_list_operation_normalizes_and_deduplicates_items() -> None:
    operation = _shopping_add(" milk. ", "MILK", "bread")

    assert operation.items == ("milk", "bread")
    assert operation.memory_key == "list:shopping"
    assert operation.topic == "shopping"


@pytest.mark.parametrize("items", ((), ("",), (" . ",)))
def test_structured_list_operation_rejects_missing_items(items) -> None:
    with pytest.raises(ValueError, match="items"):
        StructuredListMutation(
            list_name="shopping",
            items=items,
        )


def test_structured_list_write_rejects_content_encoded_command() -> None:
    with pytest.raises(ValueError, match="ApplyStructuredListCommand"):
        StoreMemoryCommand(
            content="shopping_list:add:milk",
            layer="feedback",
            memory_key="list:shopping",
        )


def test_structured_list_operation_must_match_target_key() -> None:
    with pytest.raises(ValueError, match="does not match target key"):
        ApplyStructuredListCommand(
            target=MemoryCommandTarget(memory_key="list:tasks"),
            mutation=_shopping_add("milk"),
        )


@pytest.mark.parametrize(
    ("content", "list_name", "expected"),
    (
        ("shopping_list:add:milk and bread", "shopping", ("milk", "bread")),
        ("Add milk to my shopping list.", "shopping", ("milk",)),
        ("Shopping list: milk, bread.", "shopping", ("milk", "bread")),
        ("task_list:add:call Mum", "task", ("call Mum",)),
        ("Task list: call Mum, book dentist.", "task", ("call Mum", "book dentist")),
    ),
)
def test_legacy_structured_list_parser_accepts_identifiable_list_records(
    content: str,
    list_name: str,
    expected: tuple[str, ...],
) -> None:
    assert parse_legacy_structured_list(content, list_name) == expected


@pytest.mark.parametrize(
    "content",
    (
        "milk",
        "compare shopping prices",
        "User prefers tea",
    ),
)
def test_legacy_structured_list_parser_preserves_ambiguous_topic_records(
    content: str,
) -> None:
    assert parse_legacy_structured_list(content, "shopping") is None
