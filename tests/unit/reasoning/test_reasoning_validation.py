"""Tests for reasoning request validation."""

from __future__ import annotations

import pytest

from tests.support import memory_reference, runtime_reference
from voice_concierge.reasoning import (
    MemoryAction,
    MemoryReference,
    MemoryTarget,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningRequestError,
    validate_reasoning_request,
)


def test_valid_reasoning_request_passes_validation() -> None:
    request = ReasoningRequest(
        transcript="What is on my shopping list?",
        mode="shopping",
        memories=(
            memory_reference(
                "Shopping list: milk.",
                layer="feedback",
                memory_key="list:shopping",
            ),
        ),
        conversation_summary="The user was planning groceries.",
        runtime_context=(runtime_reference("Local device time: 15:05."),),
    )

    validate_reasoning_request(request)


def test_memory_reference_produces_revision_checked_mutation_target() -> None:
    memory = MemoryReference(
        memory_id=12,
        content="User prefers tea.",
        layer="profile",
        revision=3,
        memory_key="preference:drink",
    )

    assert memory.mutation_target() == MemoryTarget(
        memory_id=12,
        memory_key="preference:drink",
        expected_revision=3,
    )


@pytest.mark.parametrize("action", ("update", "delete"))
def test_memory_mutation_action_requires_exact_target(action: str) -> None:
    with pytest.raises(ValueError, match="requires an exact target"):
        MemoryAction(
            action=action,
            content="Unsafe mutation",
            rationale="Test invalid model output.",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("action", "replace", "Unsupported memory action"),
        ("content", " ", "content must not be blank"),
        ("rationale", "", "rationale must not be blank"),
        ("requires_confirmation", "yes", "flag must be boolean"),
    ),
)
def test_memory_action_rejects_malformed_payload_fields(
    field: str,
    value: object,
    message: str,
) -> None:
    values = {
        "action": "store",
        "content": "User prefers tea.",
        "rationale": "User supplied a preference.",
        "requires_confirmation": True,
        field: value,
    }

    with pytest.raises(ValueError, match=message):
        MemoryAction(**values)


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


def test_request_validation_rejects_non_tuple_runtime_context() -> None:
    request = ReasoningRequest(
        transcript="Hello",
        runtime_context=[runtime_reference("Local device time: 15:05.")],
    )

    with pytest.raises(ReasoningRequestError, match="runtime context must be a tuple"):
        validate_reasoning_request(request)


def test_request_validation_rejects_invalid_runtime_reference() -> None:
    request = ReasoningRequest(transcript="Hello", runtime_context=(object(),))

    with pytest.raises(ReasoningRequestError, match=r"runtime_context\[0\]"):
        validate_reasoning_request(request)


@pytest.mark.parametrize("memory", ("", "   ", None, object()))
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
