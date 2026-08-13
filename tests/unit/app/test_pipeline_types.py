"""Tests for app pipeline request and state types."""

import pytest

from voice_concierge.app.types import (
    AppPipelineState,
    AppTurnOptions,
    AppTurnRequest,
    ConversationTurn,
    MemoryOperationResult,
)
from voice_concierge.memory import MemoryOperationOutcome, MemoryOperationStatus


def test_app_pipeline_state_defaults_to_home_without_pending_actions() -> None:
    state = AppPipelineState()

    assert state.context.mode == "home"
    assert state.context.pending_mode is None
    assert state.last_spoken_response is None
    assert state.conversation_history == ()
    assert state.pending_memory_action is None
    assert state.pending_memory_scope is None


def test_conversation_turn_stores_one_completed_exchange() -> None:
    turn = ConversationTurn(
        user_transcript="Who is Ada Lovelace?",
        assistant_response="Ada Lovelace was an early computing pioneer.",
    )

    assert turn.user_transcript == "Who is Ada Lovelace?"
    assert turn.assistant_response.startswith("Ada Lovelace")


def test_app_turn_request_defaults_to_no_state_and_no_audio_side_effects() -> None:
    request = AppTurnRequest(transcript="Hello.")

    assert request.transcript == "Hello."
    assert request.state is None
    assert request.options == AppTurnOptions()
    assert request.options.synthesize is False
    assert request.options.play is False


def test_memory_operation_result_defaults_to_not_attempted() -> None:
    result = MemoryOperationResult()

    assert result.attempted is False
    assert result.succeeded is False
    assert result.reason == ""


def test_memory_operation_result_derives_fields_from_typed_outcome() -> None:
    result = MemoryOperationResult(
        attempted=True,
        outcome=MemoryOperationOutcome(MemoryOperationStatus.STORED_PENDING_INDEX),
    )

    assert result.succeeded is True
    assert result.reason == "stored_pending_index"


def test_memory_operation_result_rejects_contradictory_attempt_state() -> None:
    with pytest.raises(ValueError, match="require an outcome"):
        MemoryOperationResult(attempted=True)
