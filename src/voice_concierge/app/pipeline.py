"""Stateful turn-level application pipeline."""

from __future__ import annotations

from dataclasses import replace
from typing import Protocol

from voice_concierge.app.memory import (
    MemoryGateway,
    NullMemoryGateway,
    retrieval_scope_for_turn,
)
from voice_concierge.app.reasoning import (
    ReasoningFailure,
    ReasoningTurnContext,
    ReasoningTurnResult,
    ReasoningTurnService,
)
from voice_concierge.app.types import (
    AppPipelineState,
    AppTranscript,
    AppTurnError,
    AppTurnOptions,
    AppTurnRequest,
    AppTurnResult,
    AudioPlayerAdapter,
    ConversationTurn,
    MemoryOperationResult,
    RuntimeContextProvider,
    SpeechToTextAdapter,
    TextToSpeechAdapter,
    TranscriptResult,
)
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.context.manager import (
    CONFIRMATION_CLARIFICATION_PROMPT,
    ContextManager,
    detect_confirmation_intent,
)
from voice_concierge.context.policies import policy_for_mode
from voice_concierge.context.types import (
    ConfirmationIntent,
    ContextDecision,
    ContextMode,
    ContextState,
    MemoryScope,
    Verbosity,
)
from voice_concierge.memory.types import (
    MemoryOperationOutcome,
    MemoryOperationStatus,
)
from voice_concierge.memory_contracts import (
    SHOPPING_LIST_MEMORY_KEY,
    TASK_LIST_MEMORY_KEY,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryReference,
    ReasoningResponse,
    RuntimeReference,
)

_EMPTY_TRANSCRIPT_RESPONSE = "I didn't catch that. Could you say it again?"
_STT_FAILED_RESPONSE = "I couldn't transcribe that. Please try again."
_MEMORY_CANCELLED_RESPONSE = "Okay, I won't save that."
_MEMORY_SAVED_RESPONSE = "I've saved that."
_MEMORY_ALREADY_SAVED_RESPONSE = "I already had that saved."
_MEMORY_FAILED_RESPONSE = "I couldn't save that yet."
_NOTHING_TO_REPEAT_RESPONSE = "I don't have anything to repeat yet."
_STOP_RESPONSE = "Okay, I'll stop."
_CANCEL_RESPONSE = "Okay, cancelled."
_REASONING_FAILED_RESPONSE = "Local reasoning failed unexpectedly."
_MODE_CHANGED_RESPONSES: dict[ContextMode, str] = {
    "home": "Home mode activated.",
    "cooking": "Cooking mode activated. I'll give one step at a time.",
    "shopping": "Shopping mode activated. I'll keep responses list-focused.",
    "driving": (
        "Driving mode activated. I'll keep responses very short and safety-aware."
    ),
}

DEFAULT_CONVERSATION_HISTORY_LIMIT = 6


class ReasoningTurnProcessor(Protocol):
    """Reasoning boundary consumed by the app pipeline."""

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        """Return a reasoning result for one transcript and prepared context."""


class VoiceConciergePipeline:
    """Coordinate context, memory, reasoning, STT, TTS, and playback per turn."""

    def __init__(
        self,
        reasoning: ReasoningTurnProcessor | ReasoningTurnService,
        *,
        context_manager: ContextManager | None = None,
        memory: MemoryGateway | None = None,
        speech_to_text: SpeechToTextAdapter | None = None,
        text_to_speech: TextToSpeechAdapter | None = None,
        audio_player: AudioPlayerAdapter | None = None,
        runtime_context: RuntimeContextProvider | None = None,
        memory_context_limit: int = 3,
        conversation_history_limit: int = DEFAULT_CONVERSATION_HISTORY_LIMIT,
    ) -> None:
        if conversation_history_limit < 0:
            raise ValueError("conversation_history_limit must not be negative.")

        self._reasoning = reasoning
        self._context_manager = context_manager or ContextManager()
        self._memory = memory or NullMemoryGateway()
        self._speech_to_text = speech_to_text
        self._text_to_speech = text_to_speech
        self._audio_player = audio_player
        self._runtime_context = runtime_context
        self._memory_context_limit = memory_context_limit
        self._conversation_history_limit = conversation_history_limit

    @property
    def speech_to_text(self) -> SpeechToTextAdapter | None:
        """The configured speech-to-text backend, if any.

        Exposed so a caller that must inspect a transcript before the turn is
        reasoned about (the live app routes guided routines this way) can reuse
        this backend instead of loading a second copy of the model.
        """
        return self._speech_to_text

    @property
    def text_to_speech(self) -> TextToSpeechAdapter | None:
        """The configured speech synthesiser, if any.

        Exposed alongside speech_to_text so a caller that must speak outside a
        turn (a reminder falling due) reuses this backend instead of loading a
        second copy of the voice.
        """
        return self._text_to_speech

    @property
    def audio_player(self) -> AudioPlayerAdapter | None:
        """The configured audio player, if any."""
        return self._audio_player

    def process_request(self, request: AppTurnRequest) -> AppTurnResult:
        """Process a typed transcript request."""

        return self.process_transcript(
            request.transcript,
            request.state,
            synthesize=request.options.synthesize,
            play=request.options.play,
            response_length=request.options.response_length,
        )

    def close(self) -> None:
        """Release resources owned by configured pipeline adapters."""

        close_memory = getattr(self._memory, "close", None)
        if callable(close_memory):
            close_memory()

    def process_transcript(
        self,
        transcript: str,
        state: AppPipelineState | None = None,
        *,
        synthesize: bool = False,
        play: bool = False,
        response_length: Verbosity | None = None,
    ) -> AppTurnResult:
        """Process one transcript turn and return response plus next state."""

        current_state = self._with_response_length(
            self._bounded_state(state or AppPipelineState()),
            response_length,
        )
        app_transcript = AppTranscript(text=transcript.strip())
        return self._process_app_transcript(
            app_transcript,
            current_state,
            options=AppTurnOptions(
                synthesize=synthesize,
                play=play,
                response_length=response_length,
            ),
        )

    def process_audio(
        self,
        audio: CapturedAudio,
        state: AppPipelineState | None = None,
        *,
        synthesize: bool = False,
        play: bool = False,
        response_length: Verbosity | None = None,
    ) -> AppTurnResult:
        """Transcribe captured audio, then process it through the same turn path."""

        current_state = self._with_response_length(
            self._bounded_state(state or AppPipelineState()),
            response_length,
        )
        options = AppTurnOptions(
            synthesize=synthesize,
            play=play,
            response_length=response_length,
        )
        if self._speech_to_text is None:
            return self._finalize_result(
                state=current_state,
                spoken_response=_STT_FAILED_RESPONSE,
                context_decision=_decision_for_state(current_state.context),
                transcript=None,
                errors=("stt_failed",),
                options=options,
            )

        try:
            transcript_result = self._speech_to_text.transcribe(audio)
        except Exception:
            return self._finalize_result(
                state=current_state,
                spoken_response=_STT_FAILED_RESPONSE,
                context_decision=_decision_for_state(current_state.context),
                transcript=None,
                errors=("stt_failed",),
                options=options,
            )

        return self._process_app_transcript(
            _to_app_transcript(transcript_result),
            current_state,
            options=options,
        )

    def _process_app_transcript(
        self,
        transcript: AppTranscript,
        current_state: AppPipelineState,
        *,
        options: AppTurnOptions,
    ) -> AppTurnResult:
        normalized_text = _normalize(transcript.text)
        if not normalized_text:
            next_state = replace(
                current_state,
                last_spoken_response=_EMPTY_TRANSCRIPT_RESPONSE,
            )
            return self._finalize_result(
                state=next_state,
                spoken_response=_EMPTY_TRANSCRIPT_RESPONSE,
                context_decision=_decision_for_state(current_state.context),
                transcript=transcript,
                errors=("empty_transcript",),
                options=options,
            )

        if current_state.pending_memory_action is not None:
            return self._handle_pending_memory_action(
                transcript,
                current_state,
                intent=detect_confirmation_intent(normalized_text),
                options=options,
            )

        context_decision = self._context_manager.handle(
            normalized_text,
            current_state.context,
        )

        if context_decision.needs_confirmation:
            return self._context_response(
                current_state,
                context_decision,
                transcript=transcript,
                spoken_response=context_decision.confirmation_prompt,
                options=options,
            )

        if context_decision.mode_changed:
            return self._context_response(
                current_state,
                context_decision,
                transcript=transcript,
                spoken_response=_MODE_CHANGED_RESPONSES[context_decision.state.mode],
                options=options,
            )

        command_result = self._command_response(
            current_state,
            context_decision,
            transcript=transcript,
            options=options,
        )
        if command_result is not None:
            return command_result

        memories: tuple[MemoryReference, ...] = ()
        runtime_context: tuple[RuntimeReference, ...] = ()
        errors: list[AppTurnError] = []
        retrieval_scope = retrieval_scope_for_turn(
            normalized_text,
            context_decision.policy.memory_scope,
        )
        if retrieval_scope != "none":
            try:
                memories = self._memory.retrieve(
                    normalized_text,
                    retrieval_scope,
                    limit=self._memory_context_limit,
                )
            except Exception:
                errors.append("memory_retrieval_failed")

        if self._runtime_context is not None:
            try:
                candidate_runtime_context = self._runtime_context.snapshot()
                if not isinstance(candidate_runtime_context, tuple) or not all(
                    isinstance(reference, RuntimeReference)
                    for reference in candidate_runtime_context
                ):
                    raise TypeError(
                        "Runtime context must be a tuple of RuntimeReference values."
                    )
                runtime_context = candidate_runtime_context
            except Exception:
                errors.append("runtime_context_failed")

        reasoning_context = ReasoningTurnContext(
            mode=context_decision.policy.mode,
            memories=memories,
            runtime_context=runtime_context,
            conversation_summary=_conversation_summary(
                current_state.conversation_history
            ),
            max_words=context_decision.policy.max_words,
            allow_memory_writes=context_decision.policy.memory_scope != "none",
        )
        try:
            reasoning_result = self._reasoning.process_transcript(
                normalized_text,
                reasoning_context,
            )
        except Exception as exc:
            reasoning_result = _unexpected_reasoning_failure(exc)
            errors.append("reasoning_failed")

        if not reasoning_result.succeeded and "reasoning_failed" not in errors:
            errors.append("reasoning_failed")

        proposed_memory_action = reasoning_result.response.proposed_memory_action
        pending_memory_scope = None
        if (
            proposed_memory_action is not None
            and context_decision.policy.memory_scope != "none"
        ):
            pending_memory_scope = _memory_action_scope(
                proposed_memory_action,
                fallback=context_decision.policy.memory_scope,
            )

        next_state = AppPipelineState(
            context=context_decision.state,
            last_spoken_response=reasoning_result.spoken_response,
            conversation_history=self._record_conversation(
                current_state,
                transcript,
                reasoning_result.spoken_response,
            ),
            pending_memory_action=(
                proposed_memory_action if pending_memory_scope is not None else None
            ),
            pending_memory_scope=pending_memory_scope,
        )
        return self._finalize_result(
            state=next_state,
            spoken_response=reasoning_result.spoken_response,
            context_decision=context_decision,
            transcript=transcript,
            reasoning_result=reasoning_result,
            errors=tuple(errors),
            options=options,
        )

    def _handle_pending_memory_action(
        self,
        transcript: AppTranscript,
        current_state: AppPipelineState,
        *,
        intent: ConfirmationIntent,
        options: AppTurnOptions,
    ) -> AppTurnResult:
        context_decision = _decision_for_state(current_state.context)
        pending_action = current_state.pending_memory_action
        pending_scope = current_state.pending_memory_scope

        if intent == "ambiguous":
            next_state = replace(
                current_state,
                context=context_decision.state,
                last_spoken_response=CONFIRMATION_CLARIFICATION_PROMPT,
                conversation_history=self._record_conversation(
                    current_state,
                    transcript,
                    CONFIRMATION_CLARIFICATION_PROMPT,
                ),
            )
            return self._finalize_result(
                state=next_state,
                spoken_response=CONFIRMATION_CLARIFICATION_PROMPT,
                context_decision=context_decision,
                transcript=transcript,
                options=options,
            )

        if intent == "cancel" or pending_action is None or pending_scope is None:
            next_state = AppPipelineState(
                context=context_decision.state,
                last_spoken_response=_MEMORY_CANCELLED_RESPONSE,
                conversation_history=self._record_conversation(
                    current_state,
                    transcript,
                    _MEMORY_CANCELLED_RESPONSE,
                ),
            )
            return self._finalize_result(
                state=next_state,
                spoken_response=_MEMORY_CANCELLED_RESPONSE,
                context_decision=context_decision,
                transcript=transcript,
                options=options,
            )

        try:
            outcome = self._memory.apply(pending_action, pending_scope)
        except Exception as exc:
            outcome = MemoryOperationOutcome(
                MemoryOperationStatus.MEMORY_GATEWAY_ERROR,
                detail=exc.__class__.__name__,
            )

        memory_operation = MemoryOperationResult(
            attempted=True,
            outcome=outcome,
        )
        already_stored = outcome.status is MemoryOperationStatus.DUPLICATE_FOUND
        if outcome.succeeded:
            spoken_response = _MEMORY_SAVED_RESPONSE
        elif already_stored:
            spoken_response = _MEMORY_ALREADY_SAVED_RESPONSE
        else:
            spoken_response = _MEMORY_FAILED_RESPONSE
        errors: tuple[AppTurnError, ...] = (
            () if outcome.succeeded or already_stored else ("memory_action_failed",)
        )
        next_state = AppPipelineState(
            context=context_decision.state,
            last_spoken_response=spoken_response,
            conversation_history=self._record_conversation(
                current_state,
                transcript,
                spoken_response,
            ),
            # A confirmation is one transaction attempt. Retaining a failed
            # action traps every later utterance in the yes/no branch even
            # though repeating "yes" cannot repair a stale target, invalid
            # scope, or unavailable store. The user can restate the mutation
            # after the failure has been reported.
            pending_memory_action=None,
            pending_memory_scope=None,
        )
        return self._finalize_result(
            state=next_state,
            spoken_response=spoken_response,
            context_decision=context_decision,
            transcript=transcript,
            memory_operation=memory_operation,
            errors=errors,
            options=options,
        )

    def _context_response(
        self,
        current_state: AppPipelineState,
        context_decision: ContextDecision,
        *,
        transcript: AppTranscript,
        spoken_response: str,
        options: AppTurnOptions,
    ) -> AppTurnResult:
        next_state = AppPipelineState(
            context=context_decision.state,
            last_spoken_response=spoken_response,
            conversation_history=self._record_conversation(
                current_state,
                transcript,
                spoken_response,
            ),
            pending_memory_action=current_state.pending_memory_action,
            pending_memory_scope=current_state.pending_memory_scope,
        )
        return self._finalize_result(
            state=next_state,
            spoken_response=spoken_response,
            context_decision=context_decision,
            transcript=transcript,
            options=options,
        )

    def _command_response(
        self,
        current_state: AppPipelineState,
        context_decision: ContextDecision,
        *,
        transcript: AppTranscript,
        options: AppTurnOptions,
    ) -> AppTurnResult | None:
        command_action = context_decision.command_action
        if command_action == "repeat":
            spoken_response = (
                current_state.last_spoken_response or _NOTHING_TO_REPEAT_RESPONSE
            )
        elif command_action == "stop":
            spoken_response = _STOP_RESPONSE
        elif command_action == "cancel":
            spoken_response = _CANCEL_RESPONSE
        else:
            return None

        next_state = AppPipelineState(
            context=context_decision.state,
            last_spoken_response=spoken_response,
            conversation_history=self._record_conversation(
                current_state,
                transcript,
                spoken_response,
            ),
        )
        return self._finalize_result(
            state=next_state,
            spoken_response=spoken_response,
            context_decision=context_decision,
            transcript=transcript,
            options=options,
        )

    def _bounded_state(self, state: AppPipelineState) -> AppPipelineState:
        return replace(
            state,
            conversation_history=self._bounded_history(state.conversation_history),
        )

    def _with_response_length(
        self,
        state: AppPipelineState,
        response_length: Verbosity | None,
    ) -> AppPipelineState:
        """Apply an explicit caller preference without trusting posted state."""

        if response_length is None:
            return state
        accessibility = replace(
            state.context.accessibility,
            verbosity=response_length,
        )
        return replace(
            state,
            context=replace(state.context, accessibility=accessibility),
        )

    def _record_conversation(
        self,
        state: AppPipelineState,
        transcript: AppTranscript,
        spoken_response: str,
    ) -> tuple[ConversationTurn, ...]:
        history = (
            *state.conversation_history,
            ConversationTurn(
                user_transcript=_normalize(transcript.text),
                assistant_response=spoken_response,
            ),
        )
        return self._bounded_history(history)

    def _bounded_history(
        self,
        history: tuple[ConversationTurn, ...],
    ) -> tuple[ConversationTurn, ...]:
        if self._conversation_history_limit == 0:
            return ()
        return history[-self._conversation_history_limit :]

    def _finalize_result(
        self,
        *,
        state: AppPipelineState,
        spoken_response: str,
        context_decision: ContextDecision,
        options: AppTurnOptions,
        transcript: AppTranscript | None = None,
        reasoning_result: ReasoningTurnResult | None = None,
        memory_operation: MemoryOperationResult | None = None,
        errors: tuple[AppTurnError, ...] = (),
    ) -> AppTurnResult:
        response_audio = None
        updated_errors = list(errors)

        if options.synthesize or options.play:
            if self._text_to_speech is None:
                updated_errors.append("tts_failed")
            else:
                try:
                    response_audio = self._text_to_speech.synthesize(spoken_response)
                except Exception:
                    updated_errors.append("tts_failed")

        if options.play and response_audio is not None:
            if self._audio_player is None:
                updated_errors.append("playback_failed")
            else:
                try:
                    self._audio_player.play(response_audio)
                except Exception:
                    updated_errors.append("playback_failed")

        return AppTurnResult(
            state=state,
            spoken_response=spoken_response,
            context_decision=context_decision,
            transcript=transcript,
            reasoning_result=reasoning_result,
            memory_operation=memory_operation or MemoryOperationResult(),
            response_audio=response_audio,
            errors=tuple(updated_errors),
        )


def _to_app_transcript(transcript: TranscriptResult) -> AppTranscript:
    return AppTranscript(
        text=transcript.text.strip(),
        language=getattr(transcript, "language", None),
        language_probability=getattr(transcript, "language_probability", None),
    )


def _normalize(text: str) -> str:
    return " ".join(text.strip().split())


def _memory_action_scope(
    action: MemoryAction,
    *,
    fallback: MemoryScope,
) -> MemoryScope:
    """Resolve mutation authority from the typed target, not the UI mode.

    Mode policy controls what is retrieved for a turn. An explicit shopping or
    task-list mutation remains that mutation when spoken from home or cooking
    mode; treating the current mode as its write scope makes valid operations
    fail after confirmation. Driving mode is filtered before this helper.
    """

    if action.list_operation is not None:
        return (
            "list_relevant"
            if action.list_operation.list_name == "shopping"
            else "task_relevant_only"
        )

    target_key = action.target.memory_key if action.target is not None else None
    if target_key == SHOPPING_LIST_MEMORY_KEY:
        return "list_relevant"
    if target_key == TASK_LIST_MEMORY_KEY:
        return "task_relevant_only"
    if action.action == "store":
        return "personal_relevant"
    return fallback


def _conversation_summary(history: tuple[ConversationTurn, ...]) -> str | None:
    if not history:
        return None

    return "\n\n".join(
        (
            f"Previous turn {index}:\n"
            f"User transcript: {turn.user_transcript}\n"
            f"Assistant response: {turn.assistant_response}"
        )
        for index, turn in enumerate(history, start=1)
    )


def _decision_for_state(state: ContextState) -> ContextDecision:
    return ContextDecision(
        state=state,
        policy=policy_for_mode(state.mode, state.accessibility),
    )


def _unexpected_reasoning_failure(exc: Exception) -> ReasoningTurnResult:
    category = "unknown"
    failure = ReasoningFailure(
        category=category,
        user_message=_REASONING_FAILED_RESPONSE,
        exception_type=exc.__class__.__name__,
    )
    response = ReasoningResponse(
        spoken_response=_REASONING_FAILED_RESPONSE,
        confidence="low",
        metadata={
            "app_failure_category": category,
            "app_failure_exception": exc.__class__.__name__,
        },
    )
    return ReasoningTurnResult(response=response, failure=failure)
