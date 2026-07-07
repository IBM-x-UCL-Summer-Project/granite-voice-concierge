"""Tests for reasoning engine protocols and the deterministic fake."""

from __future__ import annotations

import pytest

from voice_concierge.reasoning import (
    DeterministicReasoningFake,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningRequestError,
    ReasoningResponse,
)


def test_deterministic_fake_returns_default_response_and_records_request() -> None:
    engine = DeterministicReasoningFake()
    request = ReasoningRequest(transcript="Exercise the reasoning boundary.")

    response = engine.generate(request)

    assert response.spoken_response == "Deterministic reasoning response."
    assert response.confidence == "high"
    assert response.metadata == {"backend": "deterministic_fake"}
    assert engine.requests == [request]


def test_deterministic_fake_returns_configured_response_unchanged() -> None:
    configured_response = ReasoningResponse(
        spoken_response="Configured response.",
        needs_confirmation=True,
        confidence="low",
        metadata={"test_case": "configured"},
    )
    engine = DeterministicReasoningFake(configured_response)

    response = engine.generate(ReasoningRequest(transcript="Anything"))

    assert response is configured_response


def test_deterministic_fake_does_not_apply_intent_policy_or_word_limits() -> None:
    engine = DeterministicReasoningFake()
    request = ReasoningRequest(
        transcript="Remember milk and add it to my shopping list.",
        mode="shopping",
        constraints=ReasoningConstraints(
            max_words=1,
            allow_memory_writes=False,
        ),
    )

    response = engine.generate(request)

    assert response.spoken_response == "Deterministic reasoning response."
    assert len(response.spoken_response.split()) > request.constraints.max_words
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None


def test_deterministic_fake_validates_requests_before_recording() -> None:
    engine = DeterministicReasoningFake()

    with pytest.raises(ReasoningRequestError, match="transcript"):
        engine.generate(ReasoningRequest(transcript="   "))

    assert engine.requests == []
