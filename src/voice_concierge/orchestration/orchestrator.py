"""Compatibility facade over the canonical application turn pipeline."""

from __future__ import annotations

from typing import cast

from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reasoning import (
    ReasoningTurnContext,
    ReasoningTurnResult,
)
from voice_concierge.app.types import AppPipelineState, AppTurnResult
from voice_concierge.context import ContextManager, ContextState
from voice_concierge.orchestration.types import (
    MemoryGateway,
    SpeechGateway,
    TurnError,
    TurnResult,
)
from voice_concierge.reasoning.engine import ReasoningEngine


class _ReasoningEngineProcessor:
    """Adapt the original reasoning port to the app pipeline's turn port."""

    def __init__(self, engine: ReasoningEngine) -> None:
        self._engine = engine

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        turn_context = context or ReasoningTurnContext()
        response = self._engine.generate(turn_context.to_request(transcript))
        return ReasoningTurnResult(response=response)


class ConciergeOrchestrator:
    """Preserve the original API while delegating turns to the app pipeline.

    ``VoiceConciergePipeline`` is the sole turn-processing implementation. This
    class remains as a compatibility facade for callers that use the original
    text-in/speech-out API.
    """

    def __init__(
        self,
        *,
        memory: MemoryGateway,
        reasoning: ReasoningEngine,
        speech: SpeechGateway,
        context_manager: ContextManager | None = None,
        initial_state: ContextState | None = None,
    ) -> None:
        self._speech = speech
        self._pipeline = VoiceConciergePipeline(
            _ReasoningEngineProcessor(reasoning),
            context_manager=context_manager,
            memory=memory,
        )
        self._state = AppPipelineState(context=initial_state or ContextState())

    def handle_transcript(self, transcript: str) -> TurnResult:
        """Process one transcript through the canonical app pipeline."""

        app_result = self._pipeline.process_transcript(transcript, self._state)
        self._state = app_result.state
        speech_succeeded, speech_failed = self._deliver_speech(app_result)

        errors = list(_legacy_errors(app_result))
        if speech_failed:
            errors.append("speech_failed")

        reasoning_response = (
            app_result.reasoning_result.response
            if app_result.reasoning_result is not None
            else None
        )
        return TurnResult(
            context_decision=app_result.context_decision,
            spoken_response=app_result.spoken_response,
            reasoning_response=reasoning_response,
            speech_succeeded=speech_succeeded,
            memory_operation=app_result.memory_operation,
            errors=tuple(errors),
        )

    def _deliver_speech(self, result: AppTurnResult) -> tuple[bool, bool]:
        try:
            if result.context_decision.command_action == "stop":
                succeeded = self._speech.stop()
            else:
                succeeded = self._speech.speak(
                    result.spoken_response,
                    result.context_decision.policy.speech_pace,
                )
        except Exception:
            return False, True
        return succeeded, not succeeded


def _legacy_errors(result: AppTurnResult) -> tuple[TurnError, ...]:
    supported: set[str] = {
        "empty_transcript",
        "memory_action_failed",
        "memory_retrieval_failed",
        "reasoning_failed",
    }
    errors = tuple(error for error in result.errors if error in supported)
    return cast(tuple[TurnError, ...], errors)
