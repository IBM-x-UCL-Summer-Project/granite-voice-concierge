"""Turn-level orchestration for the voice concierge."""

from __future__ import annotations

from voice_concierge.context import (
    ContextDecision,
    ContextManager,
    ContextState,
    MemoryScope,
    detect_confirmation_intent,
)
from voice_concierge.orchestration.types import (
    MemoryGateway,
    MemoryOperationResult,
    SpeechGateway,
    TurnError,
    TurnResult,
)
from voice_concierge.reasoning.engine import ReasoningEngine
from voice_concierge.reasoning.types import (
    MemoryAction,
    ReasoningConstraints,
    ReasoningRequest,
)

_EMPTY_TRANSCRIPT_RESPONSE = "I didn't catch that. Could you say it again?"
_REASONING_FALLBACK_RESPONSE = "Sorry, I had trouble thinking that through."
_CANCEL_RESPONSE = "Okay, cancelled."
_DRIVING_MODE_ON_RESPONSE = "Driving mode is on."
_MEMORY_CANCELLED_RESPONSE = "Okay, I won't save that."
_MEMORY_CONFIRMATION_PREFIX = "Should I remember: "
_MEMORY_FAILED_RESPONSE = "I couldn't save that yet."
_MEMORY_SAVED_RESPONSE = "I've saved that."
_NOTHING_TO_REPEAT_RESPONSE = "I don't have anything to repeat yet."
_STOP_RESPONSE = "Okay, I'll stop speaking."


class ConciergeOrchestrator:
    """Coordinate context, memory, reasoning, and speech for one text turn."""

    def __init__(
        self,
        *,
        memory: MemoryGateway,
        reasoning: ReasoningEngine,
        speech: SpeechGateway,
        context_manager: ContextManager | None = None,
        initial_state: ContextState | None = None,
    ) -> None:
        self._memory = memory
        self._reasoning = reasoning
        self._speech = speech
        self._context_manager = context_manager or ContextManager()
        self._state = initial_state or ContextState()
        self._last_spoken_response: str | None = None
        self._pending_memory_action: MemoryAction | None = None
        self._pending_memory_scope: MemoryScope | None = None

    def handle_transcript(self, transcript: str) -> TurnResult:
        """Handle one transcribed user utterance."""

        errors: list[TurnError] = []
        if not transcript.strip():
            errors.append("empty_transcript")
            decision = self._context_manager.handle("", self._state)
            self._state = decision.state
            speech_succeeded = self._speak(_EMPTY_TRANSCRIPT_RESPONSE, decision, errors)
            return TurnResult(
                context_decision=decision,
                spoken_response=_EMPTY_TRANSCRIPT_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        pending_result = self._handle_pending_memory_confirmation(transcript, errors)
        if pending_result is not None:
            return pending_result

        decision = self._context_manager.handle(transcript, self._state)
        self._state = decision.state

        if decision.needs_confirmation:
            spoken_response = decision.confirmation_prompt
            speech_succeeded = self._speak(spoken_response, decision, errors)
            self._last_spoken_response = spoken_response
            return TurnResult(
                context_decision=decision,
                spoken_response=spoken_response,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if (
            decision.mode_changed
            and detect_confirmation_intent(transcript) == "confirm"
        ):
            spoken_response = _DRIVING_MODE_ON_RESPONSE
            speech_succeeded = self._speak(spoken_response, decision, errors)
            self._last_spoken_response = spoken_response
            return TurnResult(
                context_decision=decision,
                spoken_response=spoken_response,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if decision.command_action == "repeat":
            spoken_response = self._last_spoken_response or _NOTHING_TO_REPEAT_RESPONSE
            speech_succeeded = self._speak(spoken_response, decision, errors)
            return TurnResult(
                context_decision=decision,
                spoken_response=spoken_response,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if decision.command_action == "stop":
            try:
                speech_succeeded = self._speech.stop()
            except Exception:
                errors.append("speech_failed")
                speech_succeeded = False
            return TurnResult(
                context_decision=decision,
                spoken_response=_STOP_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        if decision.command_action == "cancel":
            speech_succeeded = self._speak(_CANCEL_RESPONSE, decision, errors)
            self._last_spoken_response = _CANCEL_RESPONSE
            return TurnResult(
                context_decision=decision,
                spoken_response=_CANCEL_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        memories: tuple[str, ...] = ()
        if decision.policy.memory_scope != "none":
            try:
                memories = self._memory.retrieve(
                    transcript,
                    decision.policy.memory_scope,
                    limit=3,
                )
            except Exception:
                errors.append("memory_retrieval_failed")

        try:
            reasoning_response = self._reasoning.generate(
                ReasoningRequest(
                    transcript=transcript,
                    mode=decision.policy.mode,
                    memories=memories,
                    constraints=ReasoningConstraints(
                        max_words=decision.policy.max_words,
                        allow_memory_writes=decision.policy.memory_scope != "none",
                    ),
                )
            )
            spoken_response = reasoning_response.spoken_response
        except Exception:
            errors.append("reasoning_failed")
            reasoning_response = None
            spoken_response = _REASONING_FALLBACK_RESPONSE

        if (
            reasoning_response is not None
            and reasoning_response.proposed_memory_action is not None
            and reasoning_response.proposed_memory_action.requires_confirmation
        ):
            self._pending_memory_action = reasoning_response.proposed_memory_action
            self._pending_memory_scope = decision.policy.memory_scope
            spoken_response = (
                f"{_MEMORY_CONFIRMATION_PREFIX}"
                f"{reasoning_response.proposed_memory_action.content}?"
            )

        speech_succeeded = self._speak(spoken_response, decision, errors)
        self._last_spoken_response = spoken_response
        return TurnResult(
            context_decision=decision,
            spoken_response=spoken_response,
            reasoning_response=reasoning_response,
            speech_succeeded=speech_succeeded,
            memory_operation=MemoryOperationResult(),
            errors=tuple(errors),
        )

    def _handle_pending_memory_confirmation(
        self,
        transcript: str,
        errors: list[TurnError],
    ) -> TurnResult | None:
        if self._pending_memory_action is None or self._pending_memory_scope is None:
            return None

        intent = detect_confirmation_intent(transcript)
        if intent is None:
            self._pending_memory_action = None
            self._pending_memory_scope = None
            return None

        decision = self._context_manager.handle(transcript, self._state)
        self._state = decision.state

        if intent == "cancel":
            self._pending_memory_action = None
            self._pending_memory_scope = None
            speech_succeeded = self._speak(_MEMORY_CANCELLED_RESPONSE, decision, errors)
            self._last_spoken_response = _MEMORY_CANCELLED_RESPONSE
            return TurnResult(
                context_decision=decision,
                spoken_response=_MEMORY_CANCELLED_RESPONSE,
                speech_succeeded=speech_succeeded,
                errors=tuple(errors),
            )

        try:
            succeeded, reason = self._memory.apply(
                self._pending_memory_action,
                self._pending_memory_scope,
            )
        except Exception:
            succeeded = False
            reason = "exception"

        if succeeded:
            self._pending_memory_action = None
            self._pending_memory_scope = None
            spoken_response = _MEMORY_SAVED_RESPONSE
        else:
            errors.append("memory_action_failed")
            spoken_response = _MEMORY_FAILED_RESPONSE

        speech_succeeded = self._speak(spoken_response, decision, errors)
        self._last_spoken_response = spoken_response
        return TurnResult(
            context_decision=decision,
            spoken_response=spoken_response,
            speech_succeeded=speech_succeeded,
            memory_operation=MemoryOperationResult(
                attempted=True,
                succeeded=succeeded,
                reason=reason,
            ),
            errors=tuple(errors),
        )

    def _speak(
        self,
        text: str,
        decision: ContextDecision,
        errors: list[TurnError],
    ) -> bool:
        try:
            succeeded = self._speech.speak(text, decision.policy.speech_pace)
        except Exception:
            errors.append("speech_failed")
            return False
        if not succeeded:
            errors.append("speech_failed")
        return succeeded
