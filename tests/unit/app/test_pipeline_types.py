"""Tests for app pipeline request and state types."""

from voice_concierge.app.types import (
    AppPipelineState,
    AppTurnOptions,
    AppTurnRequest,
    MemoryOperationResult,
)


def test_app_pipeline_state_defaults_to_home_without_pending_actions() -> None:
    state = AppPipelineState()

    assert state.context.mode == "home"
    assert state.context.pending_mode is None
    assert state.last_spoken_response is None
    assert state.pending_memory_action is None
    assert state.pending_memory_scope is None


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
