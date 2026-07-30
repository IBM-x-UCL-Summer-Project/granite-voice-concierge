"""Public types and ports for turn-level orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol

from voice_concierge.context import ContextDecision, MemoryScope, SpeechPace
from voice_concierge.reasoning.types import MemoryAction, ReasoningResponse

TurnError = Literal[
    "empty_transcript",
    "memory_retrieval_failed",
    "reasoning_failed",
    "speech_failed",
    "memory_action_failed",
]


class MemoryGateway(Protocol):
    """Memory operations required by a single assistant turn."""

    def retrieve(
        self,
        query: str,
        scope: MemoryScope,
        limit: int = 3,
    ) -> tuple[str, ...]:
        """Return memory snippets relevant to the query and context scope."""

    def apply(self, action: MemoryAction, scope: MemoryScope) -> tuple[bool, str]:
        """Apply a confirmed memory action under the active context scope."""


class SpeechGateway(Protocol):
    """Speech output operations required by the orchestrator."""

    def speak(self, text: str, pace: SpeechPace) -> bool:
        """Speak text at the requested pace."""

    def stop(self) -> bool:
        """Stop current speech output if supported."""


@dataclass(frozen=True)
class MemoryOperationResult:
    """Observable result for a memory action attempted by the orchestrator."""

    attempted: bool = False
    succeeded: bool = False
    reason: str = ""


@dataclass(frozen=True)
class TurnResult:
    """Observable result of coordinating one assistant turn."""

    context_decision: ContextDecision
    spoken_response: str
    reasoning_response: ReasoningResponse | None = None
    speech_succeeded: bool = False
    memory_operation: MemoryOperationResult = MemoryOperationResult()
    errors: tuple[TurnError, ...] = ()
