"""Tests for the Ollama reasoning backend."""

from __future__ import annotations

import json
from unittest.mock import Mock

import pytest
from httpx import ReadTimeout
from ollama import ChatResponse, ResponseError

from tests.support import memory_reference, runtime_reference
from voice_concierge.reasoning import (
    MemoryTarget,
    OllamaBackendUnavailableError,
    OllamaConfig,
    OllamaGenerationError,
    OllamaModelUnavailableError,
    OllamaReasoningEngine,
    OllamaReasoningError,
    OllamaTimeoutError,
    ReasoningConfigurationError,
    ReasoningConstraints,
    ReasoningRequest,
    ReasoningRequestError,
    StructuredListOperation,
)


def _chat_response(content: str, **metrics: int) -> ChatResponse:
    return ChatResponse(
        message={"role": "assistant", "content": content},
        **metrics,
    )


def _structured_content(
    spoken_response: str,
    *,
    needs_confirmation: bool = False,
    proposed_memory_action: dict[str, object] | None = None,
    mode_suggestion: str | None = None,
    confidence: str = "medium",
    required_information_source: str = "none",
    information_evidence: list[dict[str, object]] | None = None,
    freshness_requirement: str = "not_required",
) -> str:
    return json.dumps(
        {
            "spoken_response": spoken_response,
            "needs_confirmation": needs_confirmation,
            "proposed_memory_action": proposed_memory_action,
            "mode_suggestion": mode_suggestion,
            "confidence": confidence,
            "required_information_source": required_information_source,
            "information_evidence": information_evidence or [],
            "freshness_requirement": freshness_requirement,
        }
    )


def _engine_with_response(
    content: str,
    **metrics: int,
) -> tuple[OllamaReasoningEngine, Mock]:
    client = Mock()
    client.chat.return_value = _chat_response(content, **metrics)
    engine = OllamaReasoningEngine(
        OllamaConfig(model="granite-local-test"),
        client=client,
    )
    return engine, client


@pytest.mark.parametrize(
    ("field", "value", "message"),
    (
        ("model", "", "model"),
        ("host", "   ", "host"),
        ("prompt_version", "", "prompt_version"),
        ("timeout_s", 0, "timeout_s"),
        ("timeout_s", True, "timeout_s"),
        ("temperature", -0.1, "temperature"),
        ("temperature", 2.1, "temperature"),
        ("temperature", "cold", "temperature"),
        ("top_p", 0, "top_p"),
        ("top_p", 1.1, "top_p"),
        ("top_p", False, "top_p"),
        ("num_ctx", 0, "num_ctx"),
        ("num_ctx", True, "num_ctx"),
        ("num_ctx", "4096", "num_ctx"),
        ("max_predict_tokens", 0, "max_predict_tokens"),
        ("max_predict_tokens", False, "max_predict_tokens"),
        ("max_predict_tokens", "512", "max_predict_tokens"),
        ("keep_alive", "", "keep_alive"),
        ("keep_alive", 0, "keep_alive"),
        ("keep_alive", True, "keep_alive"),
        ("model_role", "emergency", "model_role"),
        ("policy_profile", "unsafe", "policy profile"),
    ),
)
def test_ollama_config_rejects_invalid_values(
    field: str,
    value: object,
    message: str,
) -> None:
    kwargs = {
        "model": "granite-local-test",
        "host": "http://localhost:11434",
        "prompt_version": "v1",
        "timeout_s": 120.0,
        "temperature": 0.2,
        "top_p": 0.9,
        "num_ctx": 4096,
        "max_predict_tokens": 512,
        "keep_alive": "5m",
        field: value,
    }

    with pytest.raises(ReasoningConfigurationError, match=message):
        OllamaConfig(**kwargs)


def test_ollama_engine_configures_official_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    client = Mock()

    def fake_client(*, host: str, timeout: float) -> Mock:
        captured.update(host=host, timeout=timeout)
        return client

    monkeypatch.setattr("voice_concierge.reasoning.ollama.Client", fake_client)

    engine = OllamaReasoningEngine(
        OllamaConfig(
            model="granite-local-test",
            host="http://localhost:11434",
            timeout_s=3.0,
        )
    )

    assert engine.config.model == "granite-local-test"
    assert captured == {"host": "http://localhost:11434", "timeout": 3.0}


def test_ollama_engine_sends_chat_messages_and_generated_schema() -> None:
    engine, client = _engine_with_response(
        _structured_content("Local model response."),
        total_duration=1000,
        eval_count=5,
    )

    response = engine.generate(
        ReasoningRequest(
            transcript="How do I like you to answer?",
            memories=(memory_reference("User prefers short answers."),),
        )
    )

    call = client.chat.call_args.kwargs
    assert call["model"] == "granite-local-test"
    assert call["stream"] is False
    assert call["format"]["type"] == "object"
    assert call["format"]["additionalProperties"] is False
    assert "required_information_source" in call["format"]["required"]
    assert "information_evidence" in call["format"]["required"]
    assert "freshness_requirement" in call["format"]["required"]
    assert call["keep_alive"] == "5m"
    assert call["options"] == {
        "temperature": 0.2,
        "top_p": 0.9,
        "num_ctx": 4096,
        "num_predict": 304,
    }
    assert call["messages"][0]["role"] == "system"
    assert call["messages"][1]["role"] == "user"
    assert "User prefers short answers." in call["messages"][1]["content"]
    assert response.spoken_response == "Local model response."
    assert response.needs_confirmation is False
    assert response.proposed_memory_action is None
    assert response.metadata["backend"] == "ollama"
    assert response.metadata["model"] == "granite-local-test"
    assert response.metadata["model_role"] == "primary"
    assert response.metadata["output_format"] == "structured_json"
    assert response.metadata["prompt_id"] == "local-reasoning"
    assert response.metadata["prompt_version"] == "v3"
    assert response.metadata["policy_profile"] == "strict"
    assert response.metadata["temperature"] == "0.2"
    assert response.metadata["top_p"] == "0.9"
    assert response.metadata["num_ctx"] == "4096"
    assert response.metadata["num_predict"] == "304"
    assert response.metadata["max_predict_tokens"] == "512"
    assert response.metadata["keep_alive"] == "5m"
    assert response.metadata["total_duration"] == "1000"
    assert response.metadata["eval_count"] == "5"


def test_ollama_engine_applies_relaxed_uat_prompt_and_policy() -> None:
    client = Mock()
    client.chat.return_value = _chat_response(
        _structured_content(
            "Plants use light energy to make sugars.",
            required_information_source="runtime_live",
        )
    )
    engine = OllamaReasoningEngine(
        OllamaConfig(
            model="granite-local-test",
            policy_profile="uat_relaxed",
        ),
        client=client,
    )

    response = engine.generate(ReasoningRequest(transcript="Explain photosynthesis."))

    system_prompt = client.chat.call_args.kwargs["messages"][0]["content"]
    assert "UAT behavior profile" in system_prompt
    assert response.spoken_response == "Plants use light energy to make sugars."
    assert response.required_information_source == "stable_knowledge"
    assert response.metadata["policy_profile"] == "uat_relaxed"


def test_ollama_engine_derives_generation_limit_from_request_word_limit() -> None:
    engine, client = _engine_with_response(_structured_content("Short response."))

    response = engine.generate(
        ReasoningRequest(
            transcript="Hello",
            constraints=ReasoningConstraints(max_words=25),
        )
    )

    call = client.chat.call_args.kwargs
    assert call["options"]["num_predict"] == 164
    assert response.metadata["num_predict"] == "164"


def test_ollama_engine_caps_generation_limit_at_configured_maximum() -> None:
    client = Mock()
    client.chat.return_value = _chat_response(_structured_content("Short response."))
    engine = OllamaReasoningEngine(
        OllamaConfig(model="granite-local-test", max_predict_tokens=120),
        client=client,
    )

    response = engine.generate(
        ReasoningRequest(
            transcript="Hello",
            constraints=ReasoningConstraints(max_words=100),
        )
    )

    call = client.chat.call_args.kwargs
    assert call["options"]["num_predict"] == 120
    assert response.metadata["max_predict_tokens"] == "120"
    assert response.metadata["num_predict"] == "120"


def test_ollama_engine_validates_request_before_client_call() -> None:
    engine, client = _engine_with_response(_structured_content("Unused."))

    with pytest.raises(ReasoningRequestError, match="transcript"):
        engine.generate(ReasoningRequest(transcript="   "))

    client.chat.assert_not_called()


def test_ollama_engine_parses_memory_action() -> None:
    engine, _ = _engine_with_response(
        _structured_content(
            "I can remember that. Please confirm before I save it.",
            proposed_memory_action={
                "action": "store",
                "content": "User prefers short answers.",
                "rationale": "User explicitly asked to remember it.",
                "target": {"memory_key": "preference:answer_length"},
                "requires_confirmation": True,
            },
            confidence="high",
            required_information_source="user_input",
            information_evidence=[{"source": "user_input", "quote": "Please help."}],
        )
    )

    response = engine.generate(ReasoningRequest(transcript="Please help."))

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "User prefers short answers."
    assert response.proposed_memory_action.target == MemoryTarget(
        memory_key="preference:answer_length"
    )
    assert response.required_information_source == "user_input"
    assert response.freshness_requirement == "not_required"
    assert "confirm" in response.spoken_response.lower()
    assert response.confidence == "high"


def test_ollama_engine_rejects_mutation_without_exact_target() -> None:
    engine, _ = _engine_with_response(
        _structured_content(
            "I updated that.",
            proposed_memory_action={
                "action": "update",
                "content": "User prefers tea.",
                "rationale": "Model selected a memory without identity.",
                "requires_confirmation": True,
            },
        )
    )

    response = engine.generate(ReasoningRequest(transcript="Please help."))

    assert response.proposed_memory_action is None
    assert response.metadata["structured_parse_error"] == ("schema_validation_failed")


def test_ollama_engine_parses_typed_structured_list_operation() -> None:
    engine, _ = _engine_with_response(
        _structured_content(
            "I can add milk and bread. Please confirm before I save it.",
            needs_confirmation=True,
            proposed_memory_action={
                "action": "store",
                "content": None,
                "rationale": "User asked to add shopping items.",
                "target": {"memory_key": "list:shopping"},
                "list_operation": {
                    "list_name": "shopping",
                    "operation": "add_items",
                    "items": ["milk", "bread"],
                },
                "requires_confirmation": True,
            },
            required_information_source="user_input",
            information_evidence=[
                {
                    "source": "user_input",
                    "quote": "Add milk and bread to my shopping list.",
                }
            ],
        )
    )

    response = engine.generate(
        ReasoningRequest(
            transcript="Add milk and bread to my shopping list.",
            mode="shopping",
        )
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.content is None
    assert response.proposed_memory_action.list_operation == (
        StructuredListOperation(
            list_name="shopping",
            operation="add_items",
            items=("milk", "bread"),
        )
    )


def test_ollama_engine_parses_and_verifies_runtime_evidence() -> None:
    clock = runtime_reference("Local device time: 15:05.")
    engine, _ = _engine_with_response(
        _structured_content(
            "It is 15:05.",
            confidence="high",
            required_information_source="runtime_live",
            information_evidence=[
                {
                    "source": "runtime_context",
                    "quote": clock.content,
                    "runtime_id": clock.runtime_id,
                    "observed_at": clock.observed_at,
                }
            ],
            freshness_requirement="current",
        )
    )

    response = engine.generate(
        ReasoningRequest(
            transcript="What time is it?",
            runtime_context=(clock,),
        )
    )

    assert response.spoken_response == "It is 15:05."
    assert response.information_evidence == (clock.information_evidence(),)


def test_ollama_engine_maps_connection_errors() -> None:
    client = Mock()
    client.chat.side_effect = ConnectionError("connection refused")
    engine = OllamaReasoningEngine(
        OllamaConfig(model="granite-local-test"),
        client=client,
    )

    with pytest.raises(OllamaBackendUnavailableError, match="Could not reach"):
        engine.generate(ReasoningRequest(transcript="Hello"))


def test_ollama_engine_maps_client_timeouts() -> None:
    client = Mock()
    client.chat.side_effect = ReadTimeout("request timed out")
    engine = OllamaReasoningEngine(
        OllamaConfig(model="granite-local-test"),
        client=client,
    )

    with pytest.raises(OllamaTimeoutError, match="Could not complete local Ollama"):
        engine.generate(ReasoningRequest(transcript="Hello"))


def test_ollama_engine_maps_missing_model_during_generation() -> None:
    client = Mock()
    client.chat.side_effect = ResponseError("model not found", status_code=404)
    engine = OllamaReasoningEngine(
        OllamaConfig(model="missing-model"),
        client=client,
    )

    with pytest.raises(OllamaModelUnavailableError, match="Ollama request failed"):
        engine.generate(ReasoningRequest(transcript="Hello"))


def test_ollama_engine_maps_general_generation_failures() -> None:
    client = Mock()
    client.chat.side_effect = ResponseError("runner failed", status_code=500)
    engine = OllamaReasoningEngine(
        OllamaConfig(model="granite-local-test"),
        client=client,
    )

    with pytest.raises(OllamaGenerationError, match="Ollama request failed"):
        engine.generate(ReasoningRequest(transcript="Hello"))


def test_ollama_specific_errors_preserve_reasoning_error_compatibility() -> None:
    assert issubclass(OllamaBackendUnavailableError, OllamaReasoningError)
    assert issubclass(OllamaModelUnavailableError, OllamaReasoningError)
    assert issubclass(OllamaTimeoutError, OllamaReasoningError)
    assert issubclass(OllamaGenerationError, OllamaReasoningError)


def test_ollama_engine_rejects_empty_message() -> None:
    engine, _ = _engine_with_response("   ")

    with pytest.raises(OllamaGenerationError, match="message was empty"):
        engine.generate(ReasoningRequest(transcript="Hello"))


def test_ollama_engine_falls_back_on_invalid_json() -> None:
    engine, _ = _engine_with_response("Plain text response.")

    response = engine.generate(ReasoningRequest(transcript="Hello"))

    assert (
        response.spoken_response == "I could not produce a valid structured response."
    )
    assert response.confidence == "low"
    assert response.metadata["structured_parse_error"] == "invalid_json"


def test_ollama_engine_falls_back_on_invalid_schema() -> None:
    engine, _ = _engine_with_response(
        _structured_content(
            "",
            needs_confirmation=False,
            confidence="unknown",
        )
    )

    response = engine.generate(ReasoningRequest(transcript="Hello"))

    assert (
        response.spoken_response == "I could not produce a valid structured response."
    )
    assert response.confidence == "low"
    assert response.metadata["structured_parse_error"] == "schema_validation_failed"


def test_ollama_engine_enforces_request_word_limit() -> None:
    engine, _ = _engine_with_response(_structured_content("one two three four five"))

    response = engine.generate(
        ReasoningRequest(
            transcript="Hello",
            constraints=ReasoningConstraints(max_words=3),
        )
    )

    assert response.spoken_response == "one two three."
    assert response.metadata["truncated"] == "true"


def test_ollama_engine_applies_policy_guards() -> None:
    engine, _ = _engine_with_response(_structured_content("Okay, short answers."))

    response = engine.generate(ReasoningRequest(transcript="Keep answers short."))

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "accessibility.verbosity=short"
    assert response.metadata["policy_guard"] == "accessibility_preference_confirmation"


def test_ollama_engine_blocks_declared_live_source_without_phrase_matching() -> None:
    engine, _ = _engine_with_response(
        _structured_content(
            "The pharmacy is open.",
            required_information_source="external_live",
            freshness_requirement="current",
        )
    )

    response = engine.generate(
        ReasoningRequest(transcript="Is the pharmacy open at the moment?")
    )

    assert response.spoken_response == "I cannot verify up-to-date information offline."
    assert response.metadata["policy_guard"] == ("external_source_unavailable_offline")


def test_ollama_engine_stores_declared_user_fact_with_temporal_language() -> None:
    engine, _ = _engine_with_response(
        _structured_content(
            "I can remember that. Please confirm before I save it.",
            required_information_source="user_input",
            information_evidence=[
                {
                    "source": "user_input",
                    "quote": "Remember my appointment this afternoon.",
                }
            ],
        )
    )

    response = engine.generate(
        ReasoningRequest(transcript="Remember my appointment this afternoon.")
    )

    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "store"
    assert response.proposed_memory_action.content == "my appointment this afternoon"


def test_ollama_engine_trace_preserves_raw_and_guarded_response() -> None:
    engine, client = _engine_with_response(_structured_content("Okay, short answers."))

    trace = engine.generate_trace(ReasoningRequest(transcript="Keep answers short."))

    client.chat.assert_called_once()
    assert trace.raw_response.spoken_response == "Okay, short answers."
    assert trace.raw_response.needs_confirmation is False
    assert trace.raw_response.proposed_memory_action is None
    assert trace.guarded_response.needs_confirmation is True
    assert trace.guarded_response.proposed_memory_action is not None
    assert trace.guarded_response.metadata["policy_guard"] == (
        "accessibility_preference_confirmation"
    )


def test_ollama_engine_repairs_paraphrased_quote_for_exact_memory_identity() -> None:
    engine, _ = _engine_with_response(
        _structured_content(
            "You prefer tea.",
            confidence="high",
            required_information_source="local_context",
            information_evidence=[
                {
                    "source": "memory",
                    "quote": "You prefer tea.",
                    "memory_id": 1,
                    "memory_revision": 1,
                }
            ],
        )
    )
    memory = memory_reference(
        "You remember that I prefer tea",
        memory_id=1,
        revision=1,
    )

    trace = engine.generate_trace(
        ReasoningRequest(
            transcript="What drink do I prefer?",
            memories=(memory,),
        )
    )

    assert trace.raw_response.information_evidence[0].quote == "You prefer tea."
    assert trace.guarded_response.spoken_response == "You prefer tea."
    assert trace.guarded_response.information_evidence == (
        memory.information_evidence(),
    )


def test_ollama_engine_applies_delete_confirmation_guard() -> None:
    engine, _ = _engine_with_response(_structured_content("Okay, forgotten."))

    response = engine.generate(
        ReasoningRequest(transcript="Forget my old shopping list.")
    )

    assert response.needs_confirmation is True
    assert response.proposed_memory_action is not None
    assert response.proposed_memory_action.action == "delete"
    assert response.proposed_memory_action.content == "my old shopping list"
    assert response.metadata["policy_guard"] == "memory_delete_confirmation"
