"""Tests for structured-list domain operations."""

import pytest

from voice_concierge.memory.structured_lists import (
    apply_structured_list_operation,
    create_structured_list,
    parse_structured_list,
    structured_list_topic,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryTarget,
    StructuredListOperation,
)


def _shopping_add(*items: str) -> StructuredListOperation:
    return StructuredListOperation(
        list_name="shopping",
        operation="add_items",
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
    assert structured_list_topic(operation) == "shopping"


@pytest.mark.parametrize("items", ((), ("",), (" . ",)))
def test_structured_list_operation_rejects_missing_items(items) -> None:
    with pytest.raises(ValueError, match="items"):
        StructuredListOperation(
            list_name="shopping",
            operation="add_items",
            items=items,
        )


def test_structured_list_write_rejects_content_encoded_command() -> None:
    with pytest.raises(ValueError, match="typed list operation"):
        MemoryAction(
            action="update",
            content="shopping_list:add:milk",
            rationale="Legacy command encoding.",
            target=MemoryTarget(memory_key="list:shopping"),
        )


def test_structured_list_operation_must_match_target_key() -> None:
    with pytest.raises(ValueError, match="does not match target key"):
        MemoryAction(
            action="update",
            content=None,
            rationale="Mismatched list operation.",
            target=MemoryTarget(memory_key="list:tasks"),
            list_operation=_shopping_add("milk"),
        )


def test_structured_list_operation_must_not_duplicate_content() -> None:
    with pytest.raises(ValueError, match="must not duplicate"):
        MemoryAction(
            action="store",
            content="Shopping list: milk.",
            rationale="Duplicated structured-list payload.",
            target=MemoryTarget(memory_key="list:shopping"),
            list_operation=_shopping_add("milk"),
        )
