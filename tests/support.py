"""Shared typed test data builders."""

from voice_concierge.reasoning.types import MemoryReference


def memory_reference(
    content: str,
    *,
    memory_id: int = 1,
    layer: str = "profile",
    revision: int = 1,
    memory_key: str | None = None,
    topic: str | None = None,
) -> MemoryReference:
    """Build identified memory evidence with concise test defaults."""

    return MemoryReference(
        memory_id=memory_id,
        content=content,
        layer=layer,
        revision=revision,
        memory_key=memory_key,
        topic=topic,
    )
