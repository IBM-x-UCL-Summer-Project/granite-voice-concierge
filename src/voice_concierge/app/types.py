"""Application pipeline request, state, and result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from voice_concierge.app.reasoning import ReasoningTurnResult
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.context.types import (
    ContextDecision,
    ContextState,
    MemoryScope,
    Verbosity,
)
from voice_concierge.memory.types import MemoryOperationOutcome
from voice_concierge.reasoning.types import MemoryAction, RuntimeReference

AppTurnError = Literal[
    "empty_transcript",
    "stt_failed",
    "memory_retrieval_failed",
    "runtime_context_failed",
    "reasoning_failed",
    "memory_action_failed",
    "tts_failed",
    "playback_failed",
]


class TranscriptResult(Protocol):
    """Structural transcript result accepted from an STT backend."""

    text: str
    language: str | None
    language_probability: float | None


class SpeechToTextAdapter(Protocol):
    """Minimal speech-to-text boundary consumed by the app pipeline."""

    def transcribe(self, audio: CapturedAudio) -> TranscriptResult:
        """Return a transcript for captured audio."""


class TextToSpeechAdapter(Protocol):
    """Minimal text-to-speech boundary consumed by the app pipeline."""

    def synthesize(self, text: str) -> CapturedAudio:
        """Return synthesized speech audio for a response."""


class AudioPlayerAdapter(Protocol):
    """Minimal playback boundary consumed by the app pipeline."""

    def play(self, audio: CapturedAudio) -> None:
        """Play synthesized speech audio."""


class RuntimeContextProvider(Protocol):
    """Trusted boundary for current local application or device facts."""

    def snapshot(self) -> tuple[RuntimeReference, ...]:
        """Return identified runtime facts observed for the current turn."""


@dataclass(frozen=True)
class AppTurnOptions:
    """Optional per-turn behavior flags for UI or manual callers."""

    synthesize: bool = False
    play: bool = False
    response_length: Verbosity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.synthesize, bool) or not isinstance(self.play, bool):
            raise TypeError("Turn audio options must be boolean.")
        if self.response_length not in {None, "short", "normal", "detailed"}:
            raise ValueError("Turn response length is invalid.")


@dataclass(frozen=True)
class AppTranscript:
    """App-owned transcript shape returned from a pipeline turn."""

    text: str
    language: str | None = None
    language_probability: float | None = None


@dataclass(frozen=True)
class ConversationTurn:
    """One completed user/assistant exchange retained for short-term context."""

    user_transcript: str
    assistant_response: str
    user_sent_at: str | None = None
    assistant_received_at: str | None = None


@dataclass(frozen=True)
class AppPipelineState:
    """State trusted in-process callers may pass between pipeline turns.

    Network transports must keep this state server-side rather than treating a
    serialized client copy as authoritative for confirmations or mutations.
    """

    context: ContextState = field(default_factory=ContextState)
    last_spoken_response: str | None = None
    conversation_history: tuple[ConversationTurn, ...] = ()
    pending_memory_action: MemoryAction | None = None
    pending_memory_scope: MemoryScope | None = None
    pending_bulk_memory_delete: bool = False


@dataclass(frozen=True)
class AppTurnRequest:
    """Transcript request shape for one app pipeline turn."""

    transcript: str
    state: AppPipelineState | None = None
    options: AppTurnOptions = field(default_factory=AppTurnOptions)


@dataclass(frozen=True)
class MemoryOperationResult:
    """Result of attempting to apply a pending memory action."""

    attempted: bool = False
    outcome: MemoryOperationOutcome | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.attempted, bool):
            raise TypeError("Memory operation attempted must be a boolean.")
        if self.attempted != (self.outcome is not None):
            raise ValueError(
                "Attempted memory results require an outcome and idle results do not."
            )

    @property
    def succeeded(self) -> bool:
        """Return success without duplicating status-owned semantics."""

        return self.outcome.succeeded if self.outcome is not None else False

    @property
    def reason(self) -> str:
        """Return the outcome's compatibility display reason."""

        return self.outcome.reason if self.outcome is not None else ""


@dataclass(frozen=True)
class AppTurnResult:
    """Full app pipeline response for one turn."""

    state: AppPipelineState
    spoken_response: str
    context_decision: ContextDecision
    transcript: AppTranscript | None = None
    reasoning_result: ReasoningTurnResult | None = None
    memory_operation: MemoryOperationResult = field(
        default_factory=MemoryOperationResult
    )
    response_audio: CapturedAudio | None = None
    errors: tuple[AppTurnError, ...] = ()
