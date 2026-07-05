"""Validation helpers for application-facing reasoning requests."""

from __future__ import annotations

from voice_concierge.reasoning.errors import ReasoningRequestError
from voice_concierge.reasoning.types import ReasoningConstraints, ReasoningRequest


def validate_reasoning_request(request: ReasoningRequest) -> None:
    """Validate one request before prompt construction or backend calls."""

    if not isinstance(request, ReasoningRequest):
        raise ReasoningRequestError("Reasoning request must be a ReasoningRequest.")

    _require_non_empty_string(request.transcript, "transcript")
    _require_non_empty_string(request.mode, "mode")
    _validate_memories(request.memories)

    if request.conversation_summary is not None:
        _require_non_empty_string(
            request.conversation_summary,
            "conversation_summary",
        )

    _validate_constraints(request.constraints)


def _validate_memories(memories: object) -> None:
    if not isinstance(memories, tuple):
        raise ReasoningRequestError("Reasoning request memories must be a tuple.")

    for index, memory in enumerate(memories):
        try:
            _require_non_empty_string(memory, f"memories[{index}]")
        except ReasoningRequestError as exc:
            raise ReasoningRequestError(str(exc)) from exc


def _validate_constraints(constraints: object) -> None:
    if not isinstance(constraints, ReasoningConstraints):
        raise ReasoningRequestError(
            "Reasoning request constraints must be ReasoningConstraints."
        )

    _require_boolean(constraints.offline, "constraints.offline")
    _require_boolean(constraints.voice_first, "constraints.voice_first")
    _require_boolean(
        constraints.allow_memory_writes,
        "constraints.allow_memory_writes",
    )

    if not isinstance(constraints.max_words, int) or isinstance(
        constraints.max_words,
        bool,
    ):
        raise ReasoningRequestError("constraints.max_words must be an integer.")
    if constraints.max_words <= 0:
        raise ReasoningRequestError("constraints.max_words must be greater than 0.")


def _require_non_empty_string(value: object, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ReasoningRequestError(f"{field_name} must be a non-empty string.")


def _require_boolean(value: object, field_name: str) -> None:
    if not isinstance(value, bool):
        raise ReasoningRequestError(f"{field_name} must be a boolean.")
