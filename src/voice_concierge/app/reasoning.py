"""Application-facing reasoning turn orchestration."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from voice_concierge.reasoning.engine import ReasoningEngine
from voice_concierge.reasoning.errors import (
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningError,
    ReasoningGenerationError,
    ReasoningModelUnavailableError,
    ReasoningRequestError,
    ReasoningTimeoutError,
)
from voice_concierge.reasoning.models import DEFAULT_MODEL_SELECTION_PATH
from voice_concierge.reasoning.prompting import DEFAULT_PROMPT_VERSION
from voice_concierge.reasoning.types import (
    MemoryReference,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningResponse,
    RuntimeReference,
)

ReasoningFailureCategory = Literal[
    "invalid_request",
    "configuration",
    "backend_unavailable",
    "model_unavailable",
    "timeout",
    "generation",
    "unknown",
]


class ReasoningEngineFactory(Protocol):
    """Callable boundary for constructing the selected reasoning engine."""

    def __call__(
        self,
        selection_path: str | Path,
        *,
        prompt_version: str,
        timeout_s: float,
    ) -> ReasoningEngine:
        """Build a reasoning engine from app-level runtime config."""


@dataclass(frozen=True)
class AppReasoningConfig:
    """App-level configuration used to construct the reasoning service."""

    selection_path: str | Path = DEFAULT_MODEL_SELECTION_PATH
    prompt_version: str = DEFAULT_PROMPT_VERSION
    timeout_s: float = 120.0


@dataclass(frozen=True)
class ReasoningTurnContext:
    """Prepared app context for one transcript-in, response-out reasoning turn."""

    mode: str = "home"
    memories: tuple[MemoryReference, ...] = ()
    runtime_context: tuple[RuntimeReference, ...] = ()
    conversation_summary: str | None = None
    max_words: int = 60
    allow_memory_writes: bool = True
    offline: bool = True
    voice_first: bool = True

    def to_request(self, transcript: str) -> ReasoningRequest:
        """Convert app context into the public reasoning request contract."""

        return ReasoningRequest(
            transcript=transcript,
            mode=self.mode,
            memories=self.memories,
            runtime_context=self.runtime_context,
            conversation_summary=self.conversation_summary,
            constraints=ReasoningConstraints(
                offline=self.offline,
                voice_first=self.voice_first,
                max_words=self.max_words,
                allow_memory_writes=self.allow_memory_writes,
            ),
        )


@dataclass(frozen=True)
class ReasoningFailure:
    """Typed app-level failure information safe for orchestration decisions."""

    category: ReasoningFailureCategory
    user_message: str
    exception_type: str


@dataclass(frozen=True)
class ReasoningTurnResult:
    """App-level result for one reasoning turn."""

    response: ReasoningResponse
    failure: ReasoningFailure | None = None

    @property
    def succeeded(self) -> bool:
        """Return whether reasoning completed without a mapped runtime failure."""

        return self.failure is None

    @property
    def spoken_response(self) -> str:
        """Return the user-facing text that should be sent to speech output."""

        return self.response.spoken_response


class ReasoningTurnService:
    """Thin app adapter around the public reasoning engine interface."""

    def __init__(self, engine: ReasoningEngine) -> None:
        self._engine = engine

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        """Generate a safe app-level result from one transcript."""

        turn_context = context or ReasoningTurnContext()
        try:
            response = self._engine.generate(turn_context.to_request(transcript))
        except ReasoningRequestError as exc:
            return _failure_result("invalid_request", exc)
        except ReasoningConfigurationError as exc:
            return _failure_result("configuration", exc)
        except ReasoningBackendUnavailableError as exc:
            return _failure_result("backend_unavailable", exc)
        except ReasoningModelUnavailableError as exc:
            return _failure_result("model_unavailable", exc)
        except ReasoningTimeoutError as exc:
            return _failure_result("timeout", exc)
        except ReasoningGenerationError as exc:
            return _failure_result("generation", exc)
        except ReasoningError as exc:
            return _failure_result("unknown", exc)

        return ReasoningTurnResult(response=response)

    def supports_streaming(self) -> bool:
        """Whether the engine underneath can stream a reply as it writes it."""

        return hasattr(self._engine, "generate_stream_trace")

    def stream_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
        *,
        on_spoken_text: Callable[[str], None],
    ) -> ReasoningTurnResult:
        """Generate with the spoken text delivered as it arrives.

        Returns the same result as process_transcript, including the same
        failure handling, so a caller can fall back to the blocking path
        without special-casing errors. The only difference is that the words
        have already been handed over by the time this returns.
        """

        turn_context = context or ReasoningTurnContext()
        try:
            trace = self._engine.generate_stream_trace(
                turn_context.to_request(transcript),
                on_spoken_text,
            )
        except ReasoningRequestError as exc:
            return _failure_result("invalid_request", exc)
        except ReasoningConfigurationError as exc:
            return _failure_result("configuration", exc)
        except ReasoningBackendUnavailableError as exc:
            return _failure_result("backend_unavailable", exc)
        except ReasoningModelUnavailableError as exc:
            return _failure_result("model_unavailable", exc)
        except ReasoningTimeoutError as exc:
            return _failure_result("timeout", exc)
        except ReasoningGenerationError as exc:
            return _failure_result("generation", exc)
        except ReasoningError as exc:
            return _failure_result("unknown", exc)

        return ReasoningTurnResult(response=trace.guarded_response)


def build_reasoning_turn_service(
    config: AppReasoningConfig | None = None,
    *,
    engine_factory: ReasoningEngineFactory | None = None,
) -> ReasoningTurnService:
    """Construct the app reasoning service from selected local runtime config."""

    runtime_config = config or AppReasoningConfig()
    if engine_factory is None:
        # Keep the Ollama client optional for deterministic/demo pipeline users.
        # The real backend is imported only when it is actually requested.
        from voice_concierge.reasoning.factory import build_reasoning_engine

        engine_factory = build_reasoning_engine
    engine = engine_factory(
        runtime_config.selection_path,
        prompt_version=runtime_config.prompt_version,
        timeout_s=runtime_config.timeout_s,
    )
    return ReasoningTurnService(engine)


def _failure_result(
    category: ReasoningFailureCategory,
    exc: Exception,
) -> ReasoningTurnResult:
    user_message = _failure_message(category)
    failure = ReasoningFailure(
        category=category,
        user_message=user_message,
        exception_type=exc.__class__.__name__,
    )
    response = ReasoningResponse(
        spoken_response=user_message,
        confidence="low",
        metadata={
            "app_failure_category": category,
            "app_failure_exception": exc.__class__.__name__,
        },
    )
    return ReasoningTurnResult(response=response, failure=failure)


def _failure_message(category: ReasoningFailureCategory) -> str:
    messages: dict[ReasoningFailureCategory, str] = {
        "invalid_request": "I did not catch enough to answer. Please say that again.",
        "configuration": "Local reasoning is not configured yet.",
        "backend_unavailable": "I cannot reach the local reasoning service right now.",
        "model_unavailable": "The local reasoning model is not ready yet.",
        "timeout": "Local reasoning took too long. Please try again.",
        "generation": "I could not produce a local response for that.",
        "unknown": "Local reasoning failed unexpectedly.",
    }
    return messages[category]
