"""Public types and ports for turn-level orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from voice_concierge.app.memory import MemoryGateway as MemoryGateway
from voice_concierge.app.types import MemoryOperationResult
from voice_concierge.context import ContextDecision, SpeechPace
from voice_concierge.reasoning.types import ReasoningResponse

TurnError = Literal[
    "empty_transcript",
    "memory_retrieval_failed",
    "reasoning_failed",
    "speech_failed",
    "memory_action_failed",
]


class SpeechGateway(Protocol):
    """Speech output operations required by the orchestrator."""

    def speak(self, text: str, pace: SpeechPace) -> bool:
        """Speak text at the requested pace."""

    def stop(self) -> bool:
        """Stop current speech output if supported."""


@dataclass(frozen=True)
class TurnResult:
    """Observable result of coordinating one assistant turn."""

    context_decision: ContextDecision
    spoken_response: str
    reasoning_response: ReasoningResponse | None = None
    speech_succeeded: bool = False
    memory_operation: MemoryOperationResult = MemoryOperationResult()
    errors: tuple[TurnError, ...] = ()
