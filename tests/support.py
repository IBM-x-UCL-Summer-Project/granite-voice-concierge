"""Shared typed test data builders."""

from voice_concierge.reasoning.types import (
    InformationEvidence,
    MemoryReference,
    RuntimeReference,
)


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


def user_input_evidence(quote: str) -> InformationEvidence:
    """Build exact evidence from the current transcript."""

    return InformationEvidence(source="user_input", quote=quote)


def runtime_reference(
    content: str,
    *,
    runtime_id: str = "device.clock",
    observed_at: int = 1_700_000_000,
) -> RuntimeReference:
    """Build identified runtime evidence with concise test defaults."""

    return RuntimeReference(
        runtime_id=runtime_id,
        content=content,
        observed_at=observed_at,
    )
