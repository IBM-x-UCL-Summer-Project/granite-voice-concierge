"""Tests for app-level reasoning turn orchestration."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support import memory_reference
from voice_concierge.app import (
    AppReasoningConfig,
    ReasoningTurnContext,
    ReasoningTurnService,
    build_reasoning_turn_service,
)
from voice_concierge.reasoning import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningError,
    ReasoningGenerationError,
    ReasoningModelUnavailableError,
    ReasoningRequest,
    ReasoningRequestError,
    ReasoningResponse,
    ReasoningTimeoutError,
)


class FakeReasoningEngine:
    """Small app-test fake for the public reasoning engine protocol."""

    def __init__(
        self,
        response: ReasoningResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response or ReasoningResponse(
            spoken_response="Fake app response.",
            confidence="high",
            metadata={"backend": "fake"},
        )
        self.error = error
        self.requests: list[ReasoningRequest] = []

    def generate(self, request: ReasoningRequest) -> ReasoningResponse:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def test_build_reasoning_turn_service_uses_runtime_config() -> None:
    engine = FakeReasoningEngine()
    calls: list[dict[str, object]] = []

    def fake_factory(
        selection_path: str | Path,
        *,
        prompt_version: str,
        timeout_s: float,
        policy_profile: str,
    ) -> FakeReasoningEngine:
        calls.append(
            {
                "selection_path": selection_path,
                "prompt_version": prompt_version,
                "timeout_s": timeout_s,
                "policy_profile": policy_profile,
            }
        )
        return engine

    service = build_reasoning_turn_service(
        AppReasoningConfig(
            selection_path=Path(".local/custom-selection.json"),
            prompt_version="v1",
            timeout_s=8.5,
            policy_profile="uat_relaxed",
        ),
        engine_factory=fake_factory,
    )

    result = service.process_transcript("Hello.")

    assert result.succeeded is True
    assert result.spoken_response == "Fake app response."
    assert calls == [
        {
            "selection_path": Path(".local/custom-selection.json"),
            "prompt_version": "v1",
            "timeout_s": 8.5,
            "policy_profile": "uat_relaxed",
        }
    ]
    assert len(engine.requests) == 1


def test_process_transcript_builds_reasoning_request_from_app_context() -> None:
    response = ReasoningResponse(
        spoken_response="The apples are on your list.",
        confidence="high",
        metadata={"source": "unit"},
    )
    engine = FakeReasoningEngine(response)
    service = ReasoningTurnService(engine)

    result = service.process_transcript(
        "What is on my shopping list?",
        ReasoningTurnContext(
            mode="shopping",
            memories=(
                memory_reference(
                    "Shopping list includes apples.",
                    layer="feedback",
                    memory_key="list:shopping",
                ),
            ),
            conversation_summary="The user asked about groceries.",
            max_words=25,
            allow_memory_writes=False,
            offline=True,
            voice_first=True,
        ),
    )

    assert result.succeeded is True
    assert result.failure is None
    assert result.response is response
    assert result.spoken_response == "The apples are on your list."

    request = engine.requests[0]
    assert request.transcript == "What is on my shopping list?"
    assert request.mode == "shopping"
    assert request.memories == (
        memory_reference(
            "Shopping list includes apples.",
            layer="feedback",
            memory_key="list:shopping",
        ),
    )
    assert request.conversation_summary == "The user asked about groceries."
    assert request.constraints.max_words == 25
    assert request.constraints.allow_memory_writes is False
    assert request.constraints.offline is True
    assert request.constraints.voice_first is True


def test_process_transcript_uses_default_context() -> None:
    engine = FakeReasoningEngine()
    service = ReasoningTurnService(engine)

    result = service.process_transcript("What time is lunch?")

    assert result.succeeded is True
    request = engine.requests[0]
    assert request.mode == "home"
    assert request.memories == ()
    assert request.conversation_summary is None
    assert request.constraints.max_words == 60
    assert request.constraints.allow_memory_writes is True


@pytest.mark.parametrize(
    ("error", "category", "message"),
    (
        (
            ReasoningRequestError("blank transcript"),
            "invalid_request",
            "I did not catch enough to answer. Please say that again.",
        ),
        (
            ReasoningConfigurationError("bad config"),
            "configuration",
            "Local reasoning is not configured yet.",
        ),
        (
            ReasoningBackendUnavailableError("runner unavailable"),
            "backend_unavailable",
            "I cannot reach the local reasoning service right now.",
        ),
        (
            ReasoningModelUnavailableError("missing model"),
            "model_unavailable",
            "The local reasoning model is not ready yet.",
        ),
        (
            ReasoningTimeoutError("timeout"),
            "timeout",
            "Local reasoning took too long. Please try again.",
        ),
        (
            ReasoningGenerationError("runner failed"),
            "generation",
            "I could not produce a local response for that.",
        ),
        (
            ReasoningError("unknown reasoning failure"),
            "unknown",
            "Local reasoning failed unexpectedly.",
        ),
    ),
)
def test_process_transcript_maps_reasoning_failures_to_safe_results(
    error: Exception,
    category: str,
    message: str,
) -> None:
    engine = FakeReasoningEngine(error=error)
    service = ReasoningTurnService(engine)

    result = service.process_transcript("Hello.")

    assert result.succeeded is False
    assert result.spoken_response == message
    assert result.response.confidence == "low"
    assert result.response.metadata == {
        "app_failure_category": category,
        "app_failure_exception": error.__class__.__name__,
    }
    assert result.failure is not None
    assert result.failure.category == category
    assert result.failure.user_message == message
    assert result.failure.exception_type == error.__class__.__name__
    assert len(engine.requests) == 1


def test_process_transcript_does_not_swallow_unexpected_errors() -> None:
    class BrokenEngine:
        def generate(self, request: ReasoningRequest) -> ReasoningResponse:
            raise RuntimeError("programming error")

    service = ReasoningTurnService(BrokenEngine())

    with pytest.raises(RuntimeError, match="programming error"):
        service.process_transcript("Hello.")
