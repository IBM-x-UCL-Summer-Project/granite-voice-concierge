"""Backend-neutral shaping for reasoning responses."""

from __future__ import annotations

from dataclasses import replace

from voice_concierge.reasoning.types import ReasoningResponse


def apply_spoken_word_limit(
    response: ReasoningResponse,
    max_words: int,
) -> ReasoningResponse:
    """Limit spoken output while preserving structured response fields."""

    limit = max(1, max_words)
    words = response.spoken_response.split()
    if len(words) <= limit:
        return response

    if response.needs_confirmation and response.proposed_memory_action:
        spoken_response = _confirmation_truncation_text(limit)
    else:
        shortened = " ".join(words[:limit]).rstrip(".,;:")
        spoken_response = f"{shortened}."

    return replace(
        response,
        spoken_response=spoken_response,
        metadata={**response.metadata, "truncated": "true"},
    )


def _confirmation_truncation_text(max_words: int) -> str:
    if max_words == 1:
        return "Confirm."

    words = ("Please", "confirm", "this", "change")
    return f"{' '.join(words[:max_words])}."
