"""Lightweight shared identities for memory-related component contracts."""

from typing import Literal

SHOPPING_LIST_MEMORY_KEY = "list:shopping"
TASK_LIST_MEMORY_KEY = "list:tasks"
STRUCTURED_LIST_MEMORY_KEYS = frozenset(
    {SHOPPING_LIST_MEMORY_KEY, TASK_LIST_MEMORY_KEY}
)
StructuredListName = Literal["shopping", "task"]
