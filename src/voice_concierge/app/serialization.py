"""Plain-dict serialization helpers for app pipeline contracts."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from typing import Any

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
from voice_concierge.context.types import (
    AccessibilityProfile,
    ContextState,
)
from voice_concierge.reasoning.types import (
    MemoryAction,
    MemoryTarget,
    StructuredListOperation,
)

JsonDict = dict[str, Any]

_CONTEXT_MODES = {"home", "cooking", "shopping", "driving"}
_COMMAND_ACTIONS = {"repeat", "next_step", "stop", "cancel"}
_MEMORY_SCOPES = {
    "none",
    "personal_relevant",
    "task_relevant_only",
    "list_relevant",
}
_MEMORY_ACTIONS = {"store", "delete", "update"}
_VERBOSITY = {"short", "normal"}
_SPEECH_PACE = {"slow", "normal"}


class PayloadValidationError(ValueError):
    """Raised when a plain-dict app payload cannot be parsed safely."""


def app_turn_request_from_dict(payload: Mapping[str, Any]) -> AppTurnRequest:
    """Parse a frontend/backend payload into an app turn request."""

    request_payload = _mapping(payload, "request")
    transcript = _required_string(request_payload, "transcript")
    state = app_pipeline_state_from_dict(request_payload.get("state"))
    options = app_turn_options_from_dict(request_payload.get("options"))
    return AppTurnRequest(transcript=transcript, state=state, options=options)


def app_turn_request_to_dict(request: AppTurnRequest) -> JsonDict:
    """Serialize an app turn request into the frontend/backend shape."""

    return {
        "transcript": request.transcript,
        "state": (
            app_pipeline_state_to_dict(request.state)
            if request.state is not None
            else None
        ),
        "options": app_turn_options_to_dict(request.options),
    }


def app_turn_options_from_dict(payload: object) -> AppTurnOptions:
    """Parse optional per-turn pipeline flags."""

    if payload is None:
        return AppTurnOptions()

    options_payload = _mapping(payload, "options")
    return AppTurnOptions(
        synthesize=_optional_bool(options_payload, "synthesize", default=False),
        play=_optional_bool(options_payload, "play", default=False),
    )


def app_turn_options_to_dict(options: AppTurnOptions) -> JsonDict:
    """Serialize per-turn pipeline flags."""

    return {
        "synthesize": options.synthesize,
        "play": options.play,
    }


def app_pipeline_state_from_dict(payload: object) -> AppPipelineState | None:
    """Parse optional app state returned by an earlier pipeline turn."""

    if payload is None:
        return None

    state_payload = _mapping(payload, "state")
    context = context_state_from_dict(_required(state_payload, "context"))
    return AppPipelineState(
        context=context,
        last_spoken_response=_optional_string(state_payload, "last_spoken_response"),
        conversation_history=conversation_history_from_dict(
            state_payload.get("conversation_history")
        ),
        pending_memory_action=memory_action_from_dict(
            state_payload.get("pending_memory_action")
        ),
        pending_memory_scope=_optional_literal(
            state_payload,
            "pending_memory_scope",
            _MEMORY_SCOPES,
            "memory scope",
        ),
    )


def app_pipeline_state_to_dict(state: AppPipelineState) -> JsonDict:
    """Serialize app state that callers should round-trip between turns."""

    return {
        "context": context_state_to_dict(state.context),
        "last_spoken_response": state.last_spoken_response,
        "conversation_history": [
            conversation_turn_to_dict(turn) for turn in state.conversation_history
        ],
        "pending_memory_action": memory_action_to_dict(state.pending_memory_action),
        "pending_memory_scope": state.pending_memory_scope,
    }


def conversation_history_from_dict(payload: object) -> tuple[ConversationTurn, ...]:
    """Parse optional short-term conversation history from app state."""

    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise PayloadValidationError("conversation_history must be an array.")

    return tuple(
        conversation_turn_from_dict(turn_payload, index=index)
        for index, turn_payload in enumerate(payload)
    )


def conversation_turn_from_dict(
    payload: object,
    *,
    index: int = 0,
) -> ConversationTurn:
    """Parse one completed conversation exchange."""

    turn_payload = _mapping(payload, f"conversation_history[{index}]")
    return ConversationTurn(
        user_transcript=_required_string(turn_payload, "user_transcript"),
        assistant_response=_required_string(turn_payload, "assistant_response"),
    )


def conversation_turn_to_dict(turn: ConversationTurn) -> JsonDict:
    """Serialize one completed conversation exchange."""

    return {
        "user_transcript": turn.user_transcript,
        "assistant_response": turn.assistant_response,
    }


def context_state_from_dict(payload: object) -> ContextState:
    """Parse persisted context state."""

    context_payload = _mapping(payload, "context")
    accessibility_payload = _mapping(
        _required(context_payload, "accessibility"),
        "context.accessibility",
    )
    return ContextState(
        mode=_required_literal(context_payload, "mode", _CONTEXT_MODES, "context mode"),
        pending_mode=_optional_literal(
            context_payload,
            "pending_mode",
            _CONTEXT_MODES,
            "pending context mode",
        ),
        last_topic=_optional_string(context_payload, "last_topic"),
        accessibility=AccessibilityProfile(
            verbosity=_required_literal(
                accessibility_payload,
                "verbosity",
                _VERBOSITY,
                "verbosity",
            ),
            speech_pace=_required_literal(
                accessibility_payload,
                "speech_pace",
                _SPEECH_PACE,
                "speech pace",
            ),
        ),
    )


def context_state_to_dict(state: ContextState) -> JsonDict:
    """Serialize context state."""

    return {
        "mode": state.mode,
        "pending_mode": state.pending_mode,
        "last_topic": state.last_topic,
        "accessibility": {
            "verbosity": state.accessibility.verbosity,
            "speech_pace": state.accessibility.speech_pace,
        },
    }


def app_turn_result_to_dict(result: AppTurnResult) -> JsonDict:
    """Serialize one app pipeline result into the frontend/backend shape."""

    return {
        "state": app_pipeline_state_to_dict(result.state),
        "transcript": app_transcript_to_dict(result.transcript),
        "spoken_response": result.spoken_response,
        "context": {
            "mode": result.context_decision.state.mode,
            "mode_changed": result.context_decision.mode_changed,
            "needs_confirmation": result.context_decision.needs_confirmation,
            "command_action": result.context_decision.command_action,
            "confirmation_prompt": result.context_decision.confirmation_prompt,
        },
        "reasoning": reasoning_result_to_dict(result),
        "memory_operation": memory_operation_to_dict(result.memory_operation),
        "errors": list(result.errors),
        "audio": captured_audio_to_dict(result.response_audio),
    }


def app_transcript_to_dict(transcript: AppTranscript | None) -> JsonDict | None:
    """Serialize transcript metadata."""

    if transcript is None:
        return None

    return {
        "text": transcript.text,
        "language": transcript.language,
        "language_probability": transcript.language_probability,
    }


def reasoning_result_to_dict(result: AppTurnResult) -> JsonDict | None:
    """Serialize the reasoning response section of an app result."""

    if result.reasoning_result is None:
        return None

    response = result.reasoning_result.response
    return {
        "confidence": response.confidence,
        "required_information_source": response.required_information_source,
        "information_evidence": [
            {
                "source": evidence.source,
                "quote": evidence.quote,
                **(
                    {
                        "memory_id": evidence.memory_id,
                        "memory_revision": evidence.memory_revision,
                    }
                    if evidence.source == "memory"
                    else {}
                ),
            }
            for evidence in response.information_evidence
        ],
        "freshness_requirement": response.freshness_requirement,
        "needs_confirmation": response.needs_confirmation,
        "proposed_memory_action": memory_action_to_dict(
            response.proposed_memory_action
        ),
        "mode_suggestion": response.mode_suggestion,
    }


def memory_operation_to_dict(operation: MemoryOperationResult) -> JsonDict:
    """Serialize the result of a pending memory operation."""

    return {
        "attempted": operation.attempted,
        "succeeded": operation.succeeded,
        "reason": operation.reason,
    }


def memory_action_from_dict(payload: object) -> MemoryAction | None:
    """Parse an optional memory action from state."""

    if payload is None:
        return None

    action_payload = _mapping(payload, "pending_memory_action")
    try:
        return MemoryAction(
            action=_required_literal(
                action_payload,
                "action",
                _MEMORY_ACTIONS,
                "memory action",
            ),
            content=_optional_string(action_payload, "content"),
            rationale=_required_string(action_payload, "rationale"),
            target=_memory_target_from_dict(action_payload.get("target")),
            list_operation=_structured_list_operation_from_dict(
                action_payload.get("list_operation")
            ),
            requires_confirmation=_optional_bool(
                action_payload,
                "requires_confirmation",
                default=True,
            ),
        )
    except ValueError as exc:
        raise PayloadValidationError(str(exc)) from exc


def memory_action_to_dict(action: MemoryAction | None) -> JsonDict | None:
    """Serialize an optional memory action."""

    if action is None:
        return None

    payload = {
        "action": action.action,
        "content": action.content,
        "rationale": action.rationale,
        "requires_confirmation": action.requires_confirmation,
    }
    if action.target is not None:
        payload["target"] = _memory_target_to_dict(action.target)
    if action.list_operation is not None:
        payload["list_operation"] = _structured_list_operation_to_dict(
            action.list_operation
        )
    return payload


def _memory_target_from_dict(payload: object) -> MemoryTarget | None:
    if payload is None:
        return None
    target_payload = _mapping(payload, "memory target")
    try:
        return MemoryTarget(
            memory_id=_optional_int(target_payload, "memory_id"),
            memory_key=_optional_string(target_payload, "memory_key"),
            expected_revision=_optional_int(
                target_payload,
                "expected_revision",
            ),
        )
    except ValueError as exc:
        raise PayloadValidationError(str(exc)) from exc


def _memory_target_to_dict(target: MemoryTarget) -> JsonDict:
    payload: JsonDict = {}
    if target.memory_id is not None:
        payload["memory_id"] = target.memory_id
    if target.memory_key is not None:
        payload["memory_key"] = target.memory_key
    if target.expected_revision is not None:
        payload["expected_revision"] = target.expected_revision
    return payload


def _structured_list_operation_from_dict(
    payload: object,
) -> StructuredListOperation | None:
    if payload is None:
        return None
    operation_payload = _mapping(payload, "structured-list operation")
    items = _required(operation_payload, "items")
    if not isinstance(items, list) or not all(isinstance(item, str) for item in items):
        raise PayloadValidationError("items must be an array of strings.")
    try:
        return StructuredListOperation(
            list_name=_required_literal(
                operation_payload,
                "list_name",
                {"shopping", "task"},
                "structured list",
            ),
            operation=_required_literal(
                operation_payload,
                "operation",
                {"add_items"},
                "structured-list operation",
            ),
            items=tuple(items),
        )
    except ValueError as exc:
        raise PayloadValidationError(str(exc)) from exc


def _structured_list_operation_to_dict(
    operation: StructuredListOperation,
) -> JsonDict:
    return {
        "list_name": operation.list_name,
        "operation": operation.operation,
        "items": list(operation.items),
    }


def captured_audio_to_dict(audio: CapturedAudio | None) -> JsonDict | None:
    """Serialize optional response audio for a web backend."""

    if audio is None:
        return None

    return {
        "wav_base64": base64.b64encode(audio.to_wav_bytes()).decode("ascii"),
        "sample_rate": audio.sample_rate,
        "duration_seconds": audio.duration_seconds,
    }


def _mapping(payload: object, label: str) -> Mapping[str, Any]:
    if not isinstance(payload, Mapping):
        raise PayloadValidationError(f"{label} must be an object.")
    return payload


def _required(payload: Mapping[str, Any], field: str) -> object:
    if field not in payload:
        raise PayloadValidationError(f"{field} is required.")
    return payload[field]


def _required_string(payload: Mapping[str, Any], field: str) -> str:
    value = _required(payload, field)
    if not isinstance(value, str):
        raise PayloadValidationError(f"{field} must be a string.")
    return value


def _optional_string(payload: Mapping[str, Any], field: str) -> str | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise PayloadValidationError(f"{field} must be a string or null.")
    return value


def _optional_int(payload: Mapping[str, Any], field: str) -> int | None:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool):
        raise PayloadValidationError(f"{field} must be an integer or null.")
    return value


def _optional_bool(
    payload: Mapping[str, Any],
    field: str,
    *,
    default: bool,
) -> bool:
    value = payload.get(field, default)
    if not isinstance(value, bool):
        raise PayloadValidationError(f"{field} must be a boolean.")
    return value


def _required_literal(
    payload: Mapping[str, Any],
    field: str,
    allowed: set[str],
    label: str,
) -> Any:
    value = _required(payload, field)
    if not isinstance(value, str) or value not in allowed:
        raise PayloadValidationError(
            f"{field} must be a valid {label}: {', '.join(sorted(allowed))}."
        )
    return value


def _optional_literal(
    payload: Mapping[str, Any],
    field: str,
    allowed: set[str],
    label: str,
) -> Any:
    value = payload.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or value not in allowed:
        raise PayloadValidationError(
            f"{field} must be a valid {label} or null: "
            f"{', '.join(sorted(allowed))}."
        )
    return value
