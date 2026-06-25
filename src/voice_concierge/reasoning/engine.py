"""Reasoning engine protocols and a small deterministic fake."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from voice_concierge.reasoning.types import (
    ReasoningRequest,
    ReasoningResponse,
    ReasoningTrace,
)


class ReasoningEngine(Protocol):
    """Callable interface that all local reasoning backends must implement."""

    def generate(self, request: ReasoningRequest) -> ReasoningResponse:
        """Generate a voice-ready response from a transcript and local context."""


@runtime_checkable
class TraceableReasoningEngine(ReasoningEngine, Protocol):
    """Reasoning engine that exposes one generation before and after policy."""

    def generate_trace(self, request: ReasoningRequest) -> ReasoningTrace:
        """Generate raw and guarded responses without a second inference."""


class DeterministicReasoningFake:
    """Configurable fake for exercising reasoning component boundaries."""

    def __init__(self, response: ReasoningResponse | None = None) -> None:
        self.response = (
            response
            if response is not None
            else ReasoningResponse(
                spoken_response="Deterministic reasoning response.",
                confidence="high",
                metadata={"backend": "deterministic_fake"},
            )
        )
        self.requests: list[ReasoningRequest] = []

    def generate(self, request: ReasoningRequest) -> ReasoningResponse:
        """Record the request and return the configured response unchanged."""

        self.requests.append(request)
        return self.response
