"""Domain behavior for project-owned structured list memories."""

from __future__ import annotations

import re

from voice_concierge.memory.types import StructuredListMutation
from voice_concierge.memory_contracts import StructuredListName


def create_structured_list(mutation: StructuredListMutation) -> str:
    """Render the first persisted value for a typed list operation."""

    return _render(_list_label(mutation), mutation.items)


def apply_structured_list_operation(
    existing_content: str,
    mutation: StructuredListMutation,
) -> str | None:
    """Apply an item operation to canonical persisted list content."""

    existing_items = parse_structured_list(existing_content, mutation)
    if existing_items is None:
        return None

    combined = list(existing_items)
    seen = {item.casefold() for item in existing_items}
    for item in mutation.items:
        comparison_key = item.casefold()
        if comparison_key not in seen:
            combined.append(item)
            seen.add(comparison_key)
    return _render(_list_label(mutation), tuple(combined))


def parse_structured_list(
    content: str,
    mutation: StructuredListMutation,
) -> tuple[str, ...] | None:
    """Parse canonical content for the list targeted by an operation."""

    prefix = f"{_list_label(mutation)}:"
    normalized = content.strip()
    if not normalized.casefold().startswith(prefix.casefold()):
        return None

    item_text = normalized[len(prefix) :].strip().removesuffix(".")
    if not item_text:
        return ()
    items = tuple(item.strip() for item in item_text.split(",") if item.strip())
    if not items:
        return None
    return items


def parse_legacy_structured_list(
    content: str,
    list_name: StructuredListName,
) -> tuple[str, ...] | None:
    """Extract items from list records written before stable keyed storage."""

    text = content.strip()
    name_pattern = (
        r"shopping\s+list" if list_name == "shopping" else r"(?:task|to-do|todo)\s+list"
    )
    canonical = re.fullmatch(
        rf"{list_name}_list:add:(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if canonical:
        return _split_legacy_items(canonical.group(1))

    addition = re.fullmatch(
        rf"add\s+(.+?)\s+to\s+(?:my|the)\s+{name_pattern}\.?",
        text,
        flags=re.IGNORECASE,
    )
    if addition:
        return _split_legacy_items(addition.group(1))

    labelled = re.fullmatch(
        rf"{name_pattern}\s*:\s*(.+)",
        text,
        flags=re.IGNORECASE,
    )
    if labelled:
        return _split_legacy_items(labelled.group(1))

    return None


def _split_legacy_items(value: str) -> tuple[str, ...] | None:
    items: list[str] = []
    seen: set[str] = set()
    for candidate in re.split(r"\s*(?:,|\band\b)\s*", value, flags=re.I):
        item = candidate.strip(" .'\"")
        key = item.casefold()
        if item and key not in seen:
            seen.add(key)
            items.append(item)
    return tuple(items) or None


def _render(label: str, items: tuple[str, ...]) -> str:
    return f"{label}: {', '.join(items)}."


def _list_label(mutation: StructuredListMutation) -> str:
    if mutation.list_name == "shopping":
        return "Shopping list"
    return "Task list"
