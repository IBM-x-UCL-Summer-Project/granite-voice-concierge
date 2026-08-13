"""Tests for app pipeline plain-dict serialization."""

from __future__ import annotations

import base64

import numpy as np
import pytest

from voice_concierge.app.reasoning import ReasoningTurnResult
from voice_concierge.app.serialization import (
    PayloadValidationError,
    app_pipeline_state_from_dict,
    app_pipeline_state_to_dict,
    app_turn_request_from_dict,
    app_turn_request_to_dict,
    app_turn_result_to_dict,
    captured_audio_to_dict,
)
from voice_concierge.app.types import (
    AppPipelineState,
    AppTranscript,
    AppTurnOptions,
    AppTurnRequest,
    AppTurnResult,
    ConversationTurn,
    MemoryOperationResult,
)
from voice_concierge.audio.types import CapturedAudio
from voice_concierge.context.policies import policy_for_mode
from voice_concierge.context.types import (
    AccessibilityProfile,
    ContextDecision,
    ContextState,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryTarget,
    ReasoningResponse,
    StructuredListOperation,
)


def test_app_pipeline_state_round_trips_through_plain_dict() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers short answers.",
        rationale="User asked for this to be remembered.",
        target=MemoryTarget(memory_key="preference:accessibility.verbosity"),
    )
    state = AppPipelineState(
        context=ContextState(
            mode="shopping",
            pending_mode="driving",
            last_topic="groceries",
            accessibility=AccessibilityProfile(
                verbosity="short",
                speech_pace="slow",
            ),
        ),
        last_spoken_response="I added milk.",
        conversation_history=(
            ConversationTurn(
                user_transcript="Add milk to my shopping list.",
                assistant_response="I added milk.",
            ),
        ),
        pending_memory_action=action,
        pending_memory_scope="list_relevant",
    )

    payload = app_pipeline_state_to_dict(state)
    parsed = app_pipeline_state_from_dict(payload)

    assert payload == {
        "context": {
            "mode": "shopping",
            "pending_mode": "driving",
            "last_topic": "groceries",
            "accessibility": {
                "verbosity": "short",
                "speech_pace": "slow",
            },
        },
        "last_spoken_response": "I added milk.",
        "conversation_history": [
            {
                "user_transcript": "Add milk to my shopping list.",
                "assistant_response": "I added milk.",
            }
        ],
        "pending_memory_action": {
            "action": "store",
            "content": "User prefers short answers.",
            "rationale": "User asked for this to be remembered.",
            "target": {
                "memory_key": "preference:accessibility.verbosity",
            },
            "requires_confirmation": True,
        },
        "pending_memory_scope": "list_relevant",
    }
    assert parsed == state


def test_exact_memory_target_round_trips_with_pending_mutation() -> None:
    state = AppPipelineState(
        pending_memory_action=MemoryAction(
            action="update",
            content=None,
            rationale="User confirmed an exact list update.",
            target=MemoryTarget(
                memory_id=8,
                memory_key="list:shopping",
                expected_revision=3,
            ),
            list_operation=StructuredListOperation(
                list_name="shopping",
                operation="add_items",
                items=("bread",),
            ),
        ),
        pending_memory_scope="list_relevant",
    )

    payload = app_pipeline_state_to_dict(state)

    assert payload["pending_memory_action"]["target"] == {
        "memory_id": 8,
        "memory_key": "list:shopping",
        "expected_revision": 3,
    }
    assert payload["pending_memory_action"]["list_operation"] == {
        "list_name": "shopping",
        "operation": "add_items",
        "items": ["bread"],
    }
    assert app_pipeline_state_from_dict(payload) == state


def test_pending_mutation_without_target_is_rejected() -> None:
    payload = app_pipeline_state_to_dict(AppPipelineState())
    payload["pending_memory_action"] = {
        "action": "delete",
        "content": "User prefers tea.",
        "rationale": "Delete a memory.",
        "requires_confirmation": True,
    }

    with pytest.raises(PayloadValidationError, match="requires an exact target"):
        app_pipeline_state_from_dict(payload)


def test_app_turn_request_from_dict_parses_state_and_options() -> None:
    state = AppPipelineState(last_spoken_response="Previous answer.")
    payload = {
        "transcript": "repeat that",
        "state": app_pipeline_state_to_dict(state),
        "options": {
            "synthesize": True,
            "play": False,
        },
    }

    request = app_turn_request_from_dict(payload)

    assert request == AppTurnRequest(
        transcript="repeat that",
        state=state,
        options=AppTurnOptions(synthesize=True, play=False),
    )
    assert app_turn_request_to_dict(request) == payload


def test_app_turn_request_from_dict_defaults_missing_state_and_options() -> None:
    request = app_turn_request_from_dict({"transcript": "hello"})

    assert request == AppTurnRequest(transcript="hello")


def test_app_turn_result_to_dict_matches_frontend_shape() -> None:
    action = MemoryAction(
        action="store",
        content="User prefers tea.",
        rationale="User asked the assistant to remember it.",
    )
    state = AppPipelineState(
        context=ContextState(mode="home"),
        last_spoken_response="I can remember that.",
        pending_memory_action=action,
        pending_memory_scope="personal_relevant",
    )
    decision = ContextDecision(
        state=state.context,
        policy=policy_for_mode("home", state.context.accessibility),
        command_action=None,
    )
    reasoning_response = ReasoningResponse(
        spoken_response="I can remember that.",
        needs_confirmation=True,
        proposed_memory_action=action,
        mode_suggestion="home",
        confidence="high",
    )
    result = AppTurnResult(
        state=state,
        spoken_response="I can remember that.",
        context_decision=decision,
        transcript=AppTranscript(text="remember tea", language="en"),
        reasoning_result=ReasoningTurnResult(response=reasoning_response),
        memory_operation=MemoryOperationResult(),
        errors=("tts_failed",),
    )

    assert app_turn_result_to_dict(result) == {
        "state": app_pipeline_state_to_dict(state),
        "transcript": {
            "text": "remember tea",
            "language": "en",
            "language_probability": None,
        },
        "spoken_response": "I can remember that.",
        "context": {
            "mode": "home",
            "mode_changed": False,
            "needs_confirmation": False,
            "command_action": None,
            "confirmation_prompt": "",
        },
        "reasoning": {
            "confidence": "high",
            "required_information_source": "none",
            "information_evidence": [],
            "freshness_requirement": "not_required",
            "needs_confirmation": True,
            "proposed_memory_action": {
                "action": "store",
                "content": "User prefers tea.",
                "rationale": "User asked the assistant to remember it.",
                "requires_confirmation": True,
            },
            "mode_suggestion": "home",
        },
        "memory_operation": {
            "attempted": False,
            "succeeded": False,
            "reason": "",
        },
        "errors": ["tts_failed"],
        "audio": None,
    }


def test_captured_audio_to_dict_serializes_wav_audio() -> None:
    audio = CapturedAudio(samples=np.zeros(160, dtype=np.int16))

    payload = captured_audio_to_dict(audio)

    assert payload is not None
    assert payload["sample_rate"] == 16000
    assert payload["duration_seconds"] == 0.01
    assert base64.b64decode(payload["wav_base64"]).startswith(b"RIFF")


def test_invalid_context_mode_raises_payload_validation_error() -> None:
    state_payload = app_pipeline_state_to_dict(AppPipelineState())
    state_payload["context"]["mode"] = "party"

    with pytest.raises(PayloadValidationError, match="mode must be a valid"):
        app_pipeline_state_from_dict(state_payload)


def test_invalid_option_type_raises_payload_validation_error() -> None:
    payload = {
        "transcript": "hello",
        "options": {
            "synthesize": "yes",
        },
    }

    with pytest.raises(PayloadValidationError, match="synthesize must be a boolean"):
        app_turn_request_from_dict(payload)


def test_missing_conversation_history_parses_as_empty_for_compatibility() -> None:
    payload = app_pipeline_state_to_dict(AppPipelineState())
    del payload["conversation_history"]

    state = app_pipeline_state_from_dict(payload)

    assert state is not None
    assert state.conversation_history == ()


def test_invalid_conversation_history_raises_payload_validation_error() -> None:
    payload = app_pipeline_state_to_dict(AppPipelineState())
    payload["conversation_history"] = "not-an-array"

    with pytest.raises(
        PayloadValidationError,
        match="conversation_history must be an array",
    ):
        app_pipeline_state_from_dict(payload)
