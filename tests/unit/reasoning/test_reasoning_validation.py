"""Tests for reasoning request validation."""

from __future__ import annotations

import pytest

from voice_concierge.reasoning import (
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningRequestError,
    validate_reasoning_request,
)


def test_valid_reasoning_request_passes_validation() -> None:
    request = ReasoningRequest(
        transcript="What is on my shopping list?",
        mode="shopping",
        memories=("Shopping list: milk.",),
        conversation_summary="The user was planning groceries.",
    )

    validate_reasoning_request(request)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("transcript", ""),
        ("transcript", "   "),
        ("transcript", None),
        ("mode", ""),
        ("mode", "   "),
        ("mode", None),
    ),
)
def test_request_validation_rejects_empty_or_non_string_core_fields(
    field: str,
    value: object,
) -> None:
    kwargs = {"transcript": "Hello", "mode": "home", field: value}
    request = ReasoningRequest(**kwargs)

    with pytest.raises(ReasoningRequestError, match=field):
        validate_reasoning_request(request)


def test_request_validation_rejects_non_tuple_memories() -> None:
    request = ReasoningRequest(
        transcript="Hello",
        memories=["User prefers short answers."],
    )

    with pytest.raises(ReasoningRequestError, match="memories must be a tuple"):
        validate_reasoning_request(request)


@pytest.mark.parametrize("memory", ("", "   ", None))
def test_request_validation_rejects_invalid_memory_values(memory: object) -> None:
    request = ReasoningRequest(transcript="Hello", memories=(memory,))

    with pytest.raises(ReasoningRequestError, match=r"memories\[0\]"):
        validate_reasoning_request(request)


@pytest.mark.parametrize("summary", ("", "   ", 123))
def test_request_validation_rejects_invalid_conversation_summary(
    summary: object,
) -> None:
    request = ReasoningRequest(
        transcript="Hello",
        conversation_summary=summary,
    )

    with pytest.raises(ReasoningRequestError, match="conversation_summary"):
        validate_reasoning_request(request)


def test_request_validation_rejects_missing_constraints() -> None:
    request = ReasoningRequest(transcript="Hello", constraints=None)

    with pytest.raises(ReasoningRequestError, match="ReasoningConstraints"):
        validate_reasoning_request(request)


@pytest.mark.parametrize("max_words", (0, -1, True, "60"))
def test_request_validation_rejects_invalid_max_words(max_words: object) -> None:
    request = ReasoningRequest(
        transcript="Hello",
        constraints=ReasoningConstraints(max_words=max_words),
    )

    with pytest.raises(ReasoningRequestError, match="max_words"):
        validate_reasoning_request(request)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("offline", "yes"),
        ("voice_first", 1),
        ("allow_memory_writes", None),
    ),
)
def test_request_validation_rejects_non_boolean_constraint_flags(
    field: str,
    value: object,
) -> None:
    kwargs = {
        "offline": True,
        "voice_first": True,
        "allow_memory_writes": True,
        field: value,
    }
    request = ReasoningRequest(
        transcript="Hello",
        constraints=ReasoningConstraints(**kwargs),
    )

    with pytest.raises(ReasoningRequestError, match=field):
        validate_reasoning_request(request)
