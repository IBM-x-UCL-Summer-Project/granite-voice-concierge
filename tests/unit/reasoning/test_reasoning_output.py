"""Tests for backend-neutral reasoning output shaping."""

from __future__ import annotations

from voice_concierge.reasoning import (
    MemoryAction,
    ReasoningResponse,
    apply_spoken_word_limit,
)


def test_word_limit_returns_original_response_when_already_within_limit() -> None:
    response = ReasoningResponse(spoken_response="Already concise.")

    assert apply_spoken_word_limit(response, 2) is response


def test_word_limit_truncates_text_and_preserves_response_fields() -> None:
    response = ReasoningResponse(
        spoken_response="one two three four five",
        mode_suggestion="shopping",
        confidence="low",
        metadata={"source": "test"},
    )

    shaped = apply_spoken_word_limit(response, 3)

    assert shaped.spoken_response == "one two three."
    assert shaped.mode_suggestion == "shopping"
    assert shaped.confidence == "low"
    assert shaped.metadata == {"source": "test", "truncated": "true"}
    assert response.spoken_response == "one two three four five"
    assert response.metadata == {"source": "test"}


def test_word_limit_preserves_confirmation_for_memory_action() -> None:
    action = MemoryAction(
        action="update",
        content="shopping_list:add:milk and bread",
        rationale="User asked to add shopping items.",
    )
    response = ReasoningResponse(
        spoken_response=(
            "I can add milk and bread to your shopping list. Please confirm."
        ),
        needs_confirmation=True,
        proposed_memory_action=action,
    )

    shaped = apply_spoken_word_limit(response, 2)

    assert shaped.spoken_response == "Please confirm."
    assert shaped.needs_confirmation is True
    assert shaped.proposed_memory_action is action
    assert shaped.metadata["truncated"] == "true"
    assert apply_spoken_word_limit(response, 1).spoken_response == "Confirm."


def test_word_limit_clamps_non_positive_limit_to_one_word() -> None:
    response = ReasoningResponse(spoken_response="one two three")

    shaped = apply_spoken_word_limit(response, 0)

    assert shaped.spoken_response == "one."
