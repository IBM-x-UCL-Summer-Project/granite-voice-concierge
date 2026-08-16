"""Tests for the stateful app turn pipeline."""

from __future__ import annotations

import numpy as np
import pytest

from tests.support import memory_reference, runtime_reference
from voice_concierge.app.pipeline import VoiceConciergePipeline
from voice_concierge.app.reasoning import (
    ReasoningFailure,
    ReasoningTurnContext,
    ReasoningTurnResult,
)
from voice_concierge.app.types import (
    AppPipelineState,
    AppTranscript,
    AppTurnOptions,
    AppTurnRequest,
    ConversationTurn,
)
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.context.types import ContextState
from voice_concierge.memory import MemoryOperationOutcome, MemoryOperationStatus
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryReference,
    MemoryTarget,
    ReasoningResponse,
    RuntimeReference,
    StructuredListOperation,
)


class FakeReasoning:
    def __init__(
        self,
        response: ReasoningResponse | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.response = response or ReasoningResponse(
            spoken_response="Reasoned response.",
            confidence="high",
        )
        self.error = error
        self.calls: list[dict[str, object]] = []

    def process_transcript(
        self,
        transcript: str,
        context: ReasoningTurnContext | None = None,
    ) -> ReasoningTurnResult:
        self.calls.append({"transcript": transcript, "context": context})
        if self.error is not None:
            raise self.error
        return ReasoningTurnResult(response=self.response)


class FakeMemory:
    def __init__(
        self,
        memories: tuple[MemoryReference, ...] = (),
        *,
        retrieve_error: Exception | None = None,
        apply_result: MemoryOperationOutcome = MemoryOperationOutcome(
            MemoryOperationStatus.STORED_SUCCESSFULLY
        ),
    ) -> None:
        self.memories = memories
        self.retrieve_error = retrieve_error
        self.apply_result = apply_result
        self.retrieve_calls: list[dict[str, object]] = []
        self.apply_calls: list[dict[str, object]] = []
        self.closed = False

    def retrieve(
        self,
        query: str,
        scope: str,
        *,
        limit: int = 3,
    ) -> tuple[MemoryReference, ...]:
        self.retrieve_calls.append({"query": query, "scope": scope, "limit": limit})
        if self.retrieve_error is not None:
            raise self.retrieve_error
        return self.memories

    def apply(self, action: MemoryAction, scope: str) -> MemoryOperationOutcome:
        self.apply_calls.append({"action": action, "scope": scope})
        return self.apply_result

    def close(self) -> None:
        self.closed = True


class FakeSpeechToText:
    def __init__(
        self,
        transcript: AppTranscript | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.transcript = transcript or AppTranscript(text="audio transcript")
        self.error = error
        self.calls: list[CapturedAudio] = []

    def transcribe(self, audio: CapturedAudio) -> AppTranscript:
        self.calls.append(audio)
        if self.error is not None:
            raise self.error
        return self.transcript


class FakeTextToSpeech:
    def __init__(
        self,
        audio: CapturedAudio | None = None,
        *,
        error: Exception | None = None,
    ) -> None:
        self.audio = audio or _audio()
        self.error = error
        self.calls: list[str] = []

    def synthesize(self, text: str) -> CapturedAudio:
        self.calls.append(text)
        if self.error is not None:
            raise self.error
        return self.audio


class FakeAudioPlayer:
    def __init__(self, *, error: Exception | None = None) -> None:
        self.error = error
        self.played: list[CapturedAudio] = []

    def play(self, audio: CapturedAudio) -> None:
        self.played.append(audio)
        if self.error is not None:
            raise self.error


class FakeRuntimeContext:
    def __init__(
        self,
        *,
        error: Exception | None = None,
    ) -> None:
        self.reference = runtime_reference("Local device time: 15:05.")
        self.error = error
        self.calls = 0

    def snapshot(self) -> tuple[RuntimeReference, ...]:
        self.calls += 1
        if self.error is not None:
            raise self.error
        return (self.reference,)


def test_process_transcript_calls_memory_and_reasoning_with_context_policy() -> None:
    reasoning = FakeReasoning(
        ReasoningResponse(spoken_response="Tea sounds good.", confidence="high")
    )
    remembered_preference = memory_reference("User prefers tea.")
    memory = FakeMemory(memories=(remembered_preference,))
    pipeline = VoiceConciergePipeline(reasoning, memory=memory)

    result = pipeline.process_transcript("  What should I drink?  ")

    assert result.spoken_response == "Tea sounds good."
    assert result.transcript == AppTranscript(text="What should I drink?")
    assert result.state.context.mode == "home"
    assert result.state.last_spoken_response == "Tea sounds good."
    assert result.errors == ()
    assert memory.retrieve_calls == [
        {
            "query": "What should I drink?",
            "scope": "personal_relevant",
            "limit": 3,
        }
    ]

    reasoning_context = reasoning.calls[0]["context"]
    assert isinstance(reasoning_context, ReasoningTurnContext)
    assert reasoning.calls[0]["transcript"] == "What should I drink?"
    assert reasoning_context.mode == "home"
    assert reasoning_context.memories == (remembered_preference,)
    assert reasoning_context.conversation_summary is None
    assert reasoning_context.max_words == 60
    assert reasoning_context.allow_memory_writes is True
    assert result.state.conversation_history == (
        ConversationTurn(
            user_transcript="What should I drink?",
            assistant_response="Tea sounds good.",
        ),
    )


@pytest.mark.parametrize(
    ("response_length", "expected_max_words"),
    (
        ("short", 45),
        ("normal", 60),
        ("detailed", 90),
    ),
)
def test_request_response_length_controls_reasoning_policy(
    response_length: str,
    expected_max_words: int,
) -> None:
    reasoning = FakeReasoning()
    pipeline = VoiceConciergePipeline(reasoning, memory=FakeMemory())

    result = pipeline.process_request(
        AppTurnRequest(
            transcript="Explain this.",
            options=AppTurnOptions(response_length=response_length),
        )
    )

    context = reasoning.calls[0]["context"]
    assert isinstance(context, ReasoningTurnContext)
    assert context.max_words == expected_max_words
    assert result.state.context.accessibility.verbosity == response_length


def test_detailed_preference_does_not_relax_driving_safety_limit() -> None:
    reasoning = FakeReasoning()
    pipeline = VoiceConciergePipeline(reasoning, memory=FakeMemory())

    pipeline.process_request(
        AppTurnRequest(
            transcript="Explain this.",
            state=AppPipelineState(context=ContextState(mode="driving")),
            options=AppTurnOptions(response_length="detailed"),
        )
    )

    context = reasoning.calls[0]["context"]
    assert isinstance(context, ReasoningTurnContext)
    assert context.max_words == 25


@pytest.mark.parametrize(
    ("transcript", "expected_scope"),
    (
        ("What is on my shopping list?", "list_relevant"),
        ("Read my to-do list", "task_relevant_only"),
        ("Please update the task list", "task_relevant_only"),
    ),
)
def test_explicit_structured_list_routes_retrieval_outside_list_mode(
    transcript: str,
    expected_scope: str,
) -> None:
    memory = FakeMemory()
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=memory)

    pipeline.process_transcript(transcript)

    assert memory.retrieve_calls == [
        {"query": transcript, "scope": expected_scope, "limit": 3}
    ]


def test_driving_mode_still_blocks_explicit_list_retrieval() -> None:
    memory = FakeMemory()
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=memory)

    pipeline.process_transcript(
        "What is on my shopping list?",
        AppPipelineState(context=ContextState(mode="driving")),
    )

    assert memory.retrieve_calls == []


def test_prior_conversation_turns_are_passed_to_reasoning() -> None:
    reasoning = FakeReasoning(
        ReasoningResponse(spoken_response="Follow-up response.", confidence="high")
    )
    pipeline = VoiceConciergePipeline(reasoning, memory=FakeMemory())

    first = pipeline.process_transcript("Who is Ada Lovelace?")
    second = pipeline.process_transcript("When was she born?", first.state)

    second_context = reasoning.calls[1]["context"]
    assert isinstance(second_context, ReasoningTurnContext)
    assert second_context.conversation_summary == (
        "Previous turn 1:\n"
        "User transcript: Who is Ada Lovelace?\n"
        "Assistant response: Follow-up response."
    )
    assert second.state.conversation_history == (
        ConversationTurn(
            user_transcript="Who is Ada Lovelace?",
            assistant_response="Follow-up response.",
        ),
        ConversationTurn(
            user_transcript="When was she born?",
            assistant_response="Follow-up response.",
        ),
    )


def test_conversation_history_is_bounded_before_and_after_reasoning() -> None:
    reasoning = FakeReasoning()
    state = AppPipelineState(
        conversation_history=(
            ConversationTurn("oldest question", "oldest answer"),
            ConversationTurn("recent question", "recent answer"),
            ConversationTurn("latest question", "latest answer"),
        )
    )
    pipeline = VoiceConciergePipeline(
        reasoning,
        memory=FakeMemory(),
        conversation_history_limit=2,
    )

    result = pipeline.process_transcript("new question", state)

    context = reasoning.calls[0]["context"]
    assert isinstance(context, ReasoningTurnContext)
    assert "oldest question" not in context.conversation_summary
    assert "recent question" in context.conversation_summary
    assert "latest question" in context.conversation_summary
    assert result.state.conversation_history == (
        ConversationTurn("latest question", "latest answer"),
        ConversationTurn("new question", "Reasoned response."),
    )


def test_negative_conversation_history_limit_is_rejected() -> None:
    with pytest.raises(ValueError, match="must not be negative"):
        VoiceConciergePipeline(
            FakeReasoning(),
            conversation_history_limit=-1,
        )


def test_process_transcript_returns_empty_transcript_without_reasoning() -> None:
    reasoning = FakeReasoning()
    memory = FakeMemory()
    pipeline = VoiceConciergePipeline(reasoning, memory=memory)

    result = pipeline.process_transcript("   ")

    assert result.spoken_response == "I didn't catch that. Could you say it again?"
    assert result.errors == ("empty_transcript",)
    assert result.reasoning_result is None
    assert reasoning.calls == []
    assert memory.retrieve_calls == []


def test_context_confirmation_short_circuits_reasoning() -> None:
    reasoning = FakeReasoning()
    memory = FakeMemory()
    pipeline = VoiceConciergePipeline(reasoning, memory=memory)

    result = pipeline.process_transcript("switch to driving mode")

    assert result.context_decision.needs_confirmation is True
    assert result.state.context.mode == "home"
    assert result.state.context.pending_mode == "driving"
    assert result.spoken_response.startswith("Driving mode uses very short")
    assert result.reasoning_result is None
    assert reasoning.calls == []
    assert memory.retrieve_calls == []


def test_context_confirmation_can_be_accepted_on_next_turn() -> None:
    reasoning = FakeReasoning()
    pipeline = VoiceConciergePipeline(reasoning, memory=FakeMemory())

    first = pipeline.process_transcript("switch to driving mode")
    second = pipeline.process_transcript("yes", first.state)

    assert second.state.context.mode == "driving"
    assert second.context_decision.mode_changed is True
    assert second.spoken_response == (
        "Driving mode activated. I'll keep responses very short and safety-aware."
    )
    assert second.reasoning_result is None
    assert second.errors == ()
    assert reasoning.calls == []


@pytest.mark.parametrize(
    ("transcript", "state", "expected_mode", "expected_response"),
    (
        (
            "switch to cooking mode",
            AppPipelineState(),
            "cooking",
            "Cooking mode activated. I'll give one step at a time.",
        ),
        (
            "switch to shopping mode",
            AppPipelineState(),
            "shopping",
            "Shopping mode activated. I'll keep responses list-focused.",
        ),
        (
            "switch back to home mdoe",
            AppPipelineState(context=ContextState(mode="driving")),
            "home",
            "Home mode activated.",
        ),
    ),
)
def test_completed_mode_changes_use_deterministic_app_response(
    transcript: str,
    state: AppPipelineState,
    expected_mode: str,
    expected_response: str,
) -> None:
    reasoning = FakeReasoning(
        ReasoningResponse(
            spoken_response="Model claimed a different state.",
            confidence="high",
        )
    )
    memory = FakeMemory()
    pipeline = VoiceConciergePipeline(reasoning, memory=memory)

    result = pipeline.process_transcript(transcript, state)

    assert result.state.context.mode == expected_mode
    assert result.context_decision.mode_changed is True
    assert result.spoken_response == expected_response
    assert result.reasoning_result is None
    assert reasoning.calls == []
    assert memory.retrieve_calls == []


def test_repeat_command_returns_previous_spoken_response_without_reasoning() -> None:
    reasoning = FakeReasoning()
    state = AppPipelineState(last_spoken_response="Previous answer.")
    pipeline = VoiceConciergePipeline(reasoning, memory=FakeMemory())

    result = pipeline.process_transcript("repeat that", state)

    assert result.spoken_response == "Previous answer."
    assert result.context_decision.command_action == "repeat"
    assert reasoning.calls == []


def test_reasoning_memory_proposal_becomes_pending_state() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers tea.",
        rationale="User asked the assistant to remember it.",
    )
    reasoning = FakeReasoning(
        ReasoningResponse(
            spoken_response="I can remember that. Please confirm before I save it.",
            needs_confirmation=True,
            proposed_memory_action=action,
            confidence="high",
        )
    )
    pipeline = VoiceConciergePipeline(reasoning, memory=FakeMemory())

    result = pipeline.process_transcript("remember that I prefer tea")

    assert result.state.pending_memory_action == action
    assert result.state.pending_memory_scope == "personal_relevant"
    assert result.spoken_response == (
        "I can remember that. Please confirm before I save it."
    )


def test_structured_list_proposal_uses_typed_scope_outside_list_mode() -> None:
    action = MemoryAction(
        action="store",
        content=None,
        rationale="User asked to add the first shopping item.",
        target=MemoryTarget(memory_key="list:shopping"),
        list_operation=StructuredListOperation(
            list_name="shopping",
            operation="add_items",
            items=("milk",),
        ),
    )
    reasoning = FakeReasoning(
        ReasoningResponse(
            spoken_response="Please confirm before I add milk.",
            needs_confirmation=True,
            proposed_memory_action=action,
            confidence="high",
        )
    )
    pipeline = VoiceConciergePipeline(reasoning, memory=FakeMemory())

    result = pipeline.process_transcript("add milk to my shopping list")

    assert result.state.context.mode == "home"
    assert result.state.pending_memory_action == action
    assert result.state.pending_memory_scope == "list_relevant"


def test_pending_memory_confirmation_applies_and_clears_action() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers tea.",
        rationale="User asked the assistant to remember it.",
    )
    state = AppPipelineState(
        pending_memory_action=action,
        pending_memory_scope="personal_relevant",
    )
    memory = FakeMemory(
        apply_result=MemoryOperationOutcome(MemoryOperationStatus.STORED_SUCCESSFULLY)
    )
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=memory)

    result = pipeline.process_transcript("yes please", state)

    assert result.spoken_response == "I've saved that."
    assert result.memory_operation.attempted is True
    assert result.memory_operation.succeeded is True
    assert result.memory_operation.reason == "stored_successfully"
    assert result.state.pending_memory_action is None
    assert result.state.pending_memory_scope is None
    assert memory.apply_calls == [{"action": action, "scope": "personal_relevant"}]


@pytest.mark.parametrize(
    ("action", "status", "expected"),
    (
        (
            MemoryAction(
                action="update",
                content="User prefers peppermint tea.",
                rationale="User corrected a memory.",
                target=MemoryTarget(memory_id=4, expected_revision=2),
            ),
            MemoryOperationStatus.UPDATED_SUCCESSFULLY,
            "I've updated that memory.",
        ),
        (
            MemoryAction(
                action="delete",
                content="User prefers tea.",
                rationale="User asked to forget it.",
                target=MemoryTarget(memory_id=4, expected_revision=2),
            ),
            MemoryOperationStatus.DELETED_SUCCESSFULLY,
            "I've deleted that memory.",
        ),
        (
            MemoryAction(
                action="update",
                content=None,
                rationale="User removed a list item.",
                target=MemoryTarget(
                    memory_id=9,
                    memory_key="list:shopping",
                    expected_revision=3,
                ),
                list_operation=StructuredListOperation(
                    list_name="shopping",
                    operation="remove_items",
                    items=("bread",),
                ),
            ),
            MemoryOperationStatus.UPDATED_SUCCESSFULLY,
            "I've removed bread from your shopping list.",
        ),
    ),
)
def test_confirmation_copy_names_the_completed_operation(
    action, status, expected
) -> None:
    state = AppPipelineState(
        pending_memory_action=action,
        pending_memory_scope=(
            "list_relevant"
            if action.list_operation is not None
            else "personal_relevant"
        ),
    )
    memory = FakeMemory(apply_result=MemoryOperationOutcome(status))
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=memory)

    result = pipeline.process_transcript("yes", state)

    assert result.spoken_response == expected


def test_duplicate_confirmation_is_an_idempotent_completed_request() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers tea.",
        rationale="User asked the assistant to remember it.",
    )
    state = AppPipelineState(
        pending_memory_action=action,
        pending_memory_scope="personal_relevant",
    )
    memory = FakeMemory(
        apply_result=MemoryOperationOutcome(MemoryOperationStatus.DUPLICATE_FOUND)
    )
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=memory)

    result = pipeline.process_transcript("yes", state)

    assert result.spoken_response == "I already had that saved."
    assert result.memory_operation.succeeded is False
    assert result.errors == ()
    assert result.state.pending_memory_action is None
    assert result.state.pending_memory_scope is None


def test_failed_confirmation_clears_pending_action_for_the_next_turn() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers tea.",
        rationale="User asked the assistant to remember it.",
    )
    state = AppPipelineState(
        pending_memory_action=action,
        pending_memory_scope="personal_relevant",
    )
    memory = FakeMemory(
        apply_result=MemoryOperationOutcome(
            MemoryOperationStatus.MEMORY_GATEWAY_ERROR,
            detail="store unavailable",
        )
    )
    reasoning = FakeReasoning()
    pipeline = VoiceConciergePipeline(reasoning, memory=memory)

    failed = pipeline.process_transcript("yes", state)
    next_turn = pipeline.process_transcript("what drink do I prefer?", failed.state)

    assert failed.errors == ("memory_action_failed",)
    assert failed.state.pending_memory_action is None
    assert failed.state.pending_memory_scope is None
    assert next_turn.spoken_response == "Reasoned response."
    assert reasoning.calls[-1]["transcript"] == "what drink do I prefer?"


def test_memory_confirmation_does_not_also_confirm_pending_mode() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers tea.",
        rationale="User asked the assistant to remember it.",
    )
    state = AppPipelineState(
        context=ContextState(mode="home", pending_mode="driving"),
        pending_memory_action=action,
        pending_memory_scope="personal_relevant",
    )
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=FakeMemory())

    result = pipeline.process_transcript("yes", state)

    assert result.memory_operation.succeeded is True
    assert result.state.context.mode == "home"
    assert result.state.context.pending_mode == "driving"


def test_pending_memory_cancel_clears_action_without_apply() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers tea.",
        rationale="User asked the assistant to remember it.",
    )
    state = AppPipelineState(
        pending_memory_action=action,
        pending_memory_scope="personal_relevant",
    )
    memory = FakeMemory()
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=memory)

    result = pipeline.process_transcript("no", state)

    assert result.spoken_response == "Okay, I won't save that."
    assert result.state.pending_memory_action is None
    assert result.state.pending_memory_scope is None
    assert memory.apply_calls == []


@pytest.mark.parametrize("transcript", ("yesterday", "I know", "not yet", "yes, no"))
def test_ambiguous_memory_confirmation_preserves_pending_action(
    transcript: str,
) -> None:
    action = MemoryAction(
        action="delete",
        content="shopping list",
        rationale="User asked to delete it.",
        target=MemoryTarget(memory_key="list:shopping"),
    )
    state = AppPipelineState(
        pending_memory_action=action,
        pending_memory_scope="list_relevant",
    )
    memory = FakeMemory()
    reasoning = FakeReasoning()
    pipeline = VoiceConciergePipeline(reasoning, memory=memory)

    result = pipeline.process_transcript(transcript, state)

    assert result.spoken_response == "Sorry, was that a yes or a no?"
    assert result.state.pending_memory_action == action
    assert result.state.pending_memory_scope == "list_relevant"
    assert result.memory_operation.attempted is False
    assert memory.apply_calls == []
    assert reasoning.calls == []


def test_memory_retrieval_failure_still_allows_reasoning() -> None:
    reasoning = FakeReasoning(
        ReasoningResponse(spoken_response="Fallback response.", confidence="medium")
    )
    memory = FakeMemory(retrieve_error=RuntimeError("memory down"))
    pipeline = VoiceConciergePipeline(reasoning, memory=memory)

    result = pipeline.process_transcript("what should I do")

    assert result.spoken_response == "Fallback response."
    assert result.errors == ("memory_retrieval_failed",)

    reasoning_context = reasoning.calls[0]["context"]
    assert isinstance(reasoning_context, ReasoningTurnContext)
    assert reasoning_context.memories == ()


def test_runtime_context_snapshot_is_passed_to_reasoning() -> None:
    reasoning = FakeReasoning()
    runtime_context = FakeRuntimeContext()
    pipeline = VoiceConciergePipeline(
        reasoning,
        memory=FakeMemory(),
        runtime_context=runtime_context,
    )

    result = pipeline.process_transcript("what time is it")

    reasoning_context = reasoning.calls[0]["context"]
    assert isinstance(reasoning_context, ReasoningTurnContext)
    assert reasoning_context.runtime_context == (runtime_context.reference,)
    assert runtime_context.calls == 1
    assert result.errors == ()


def test_runtime_context_failure_is_recoverable() -> None:
    reasoning = FakeReasoning()
    runtime_context = FakeRuntimeContext(error=RuntimeError("clock unavailable"))
    pipeline = VoiceConciergePipeline(
        reasoning,
        memory=FakeMemory(),
        runtime_context=runtime_context,
    )

    result = pipeline.process_transcript("hello")

    reasoning_context = reasoning.calls[0]["context"]
    assert isinstance(reasoning_context, ReasoningTurnContext)
    assert reasoning_context.runtime_context == ()
    assert result.errors == ("runtime_context_failed",)


def test_reasoning_exception_returns_stable_failure_result() -> None:
    pipeline = VoiceConciergePipeline(
        FakeReasoning(error=RuntimeError("bad state")),
        memory=FakeMemory(),
    )

    result = pipeline.process_transcript("hello")

    assert result.spoken_response == "Local reasoning failed unexpectedly."
    assert result.errors == ("reasoning_failed",)
    assert result.reasoning_result is not None
    assert result.reasoning_result.succeeded is False
    assert isinstance(result.reasoning_result.failure, ReasoningFailure)
    assert result.reasoning_result.failure.exception_type == "RuntimeError"


def test_process_audio_transcribes_synthesizes_and_plays_response() -> None:
    input_audio = _audio()
    response_audio = _audio(value=1)
    speech_to_text = FakeSpeechToText(
        AppTranscript(text="hello from audio", language="en", language_probability=0.9)
    )
    text_to_speech = FakeTextToSpeech(response_audio)
    audio_player = FakeAudioPlayer()
    pipeline = VoiceConciergePipeline(
        FakeReasoning(ReasoningResponse(spoken_response="Hello.", confidence="high")),
        memory=FakeMemory(),
        speech_to_text=speech_to_text,
        text_to_speech=text_to_speech,
        audio_player=audio_player,
    )

    result = pipeline.process_audio(input_audio, synthesize=True, play=True)

    assert speech_to_text.calls == [input_audio]
    assert result.transcript == AppTranscript(
        text="hello from audio",
        language="en",
        language_probability=0.9,
    )
    assert text_to_speech.calls == ["Hello."]
    assert audio_player.played == [response_audio]
    assert result.response_audio is response_audio
    assert result.errors == ()


def test_process_audio_returns_stt_failure_without_reasoning() -> None:
    reasoning = FakeReasoning()
    pipeline = VoiceConciergePipeline(
        reasoning,
        memory=FakeMemory(),
        speech_to_text=FakeSpeechToText(error=RuntimeError("stt unavailable")),
    )

    result = pipeline.process_audio(_audio())

    assert result.spoken_response == "I couldn't transcribe that. Please try again."
    assert result.errors == ("stt_failed",)
    assert result.transcript is None
    assert reasoning.calls == []


def test_close_releases_memory_gateway() -> None:
    memory = FakeMemory()
    pipeline = VoiceConciergePipeline(FakeReasoning(), memory=memory)

    pipeline.close()

    assert memory.closed is True


def test_synthesize_without_tts_reports_recoverable_error() -> None:
    pipeline = VoiceConciergePipeline(
        FakeReasoning(ReasoningResponse(spoken_response="Hello.", confidence="high")),
        memory=FakeMemory(),
    )

    result = pipeline.process_transcript("hello", synthesize=True)

    assert result.spoken_response == "Hello."
    assert result.response_audio is None
    assert result.errors == ("tts_failed",)


def _audio(value: int = 0) -> CapturedAudio:
    return CapturedAudio(samples=np.full(160, value, dtype=np.int16))
