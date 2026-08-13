"""Public API smoke tests for the selected local reasoning runtime."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from httpx import ReadTimeout
from ollama import ChatResponse, ResponseError

from voice_concierge.reasoning import (
    LocalModelDetails,
    LocalModelInfo,
    ModelDownloadProgress,
    OllamaModelManagementError,
    ReasoningBackendUnavailableError,
    ReasoningConstraints,
    ReasoningGenerationError,
    ReasoningModelSelection,
    ReasoningModelUnavailableError,
    ReasoningRequest,
    ReasoningTimeoutError,
    TraceableReasoningEngine,
    build_reasoning_engine,
    save_model_selection,
)


class AvailableModelManager:
    """Public model-manager test double for selected-runtime construction."""

    def __init__(self) -> None:
        self.show_calls: list[str] = []
        self.pull_calls: list[str] = []

    def list_models(self) -> tuple[LocalModelInfo, ...]:
        return ()

    def show_model(self, model: str) -> LocalModelDetails:
        self.show_calls.append(model)
        return LocalModelDetails(model=model)

    def pull_model(
        self,
        model: str,
        *,
        stream: bool = False,
    ) -> tuple[ModelDownloadProgress, ...]:
        self.pull_calls.append(model)
        return ()


class MissingModelManager(AvailableModelManager):
    """Model-manager test double that reports a missing selected model."""

    def show_model(self, model: str) -> LocalModelDetails:
        self.show_calls.append(model)
        try:
            raise ResponseError("model not found", status_code=404)
        except ResponseError as exc:
            raise OllamaModelManagementError("missing model") from exc


class RecordingChatClient:
    """Small fake for the official Ollama client used by the public factory."""

    def __init__(
        self,
        content: str | None = None,
        *,
        error: BaseException | None = None,
    ) -> None:
        self.content = content
        self.error = error
        self.chat_calls: list[dict[str, Any]] = []

    def chat(self, **kwargs: Any) -> ChatResponse:
        self.chat_calls.append(kwargs)
        if self.error is not None:
            raise self.error
        if self.content is None:
            raise AssertionError("RecordingChatClient needs content or an error.")
        return ChatResponse(message={"role": "assistant", "content": self.content})


def _structured_content(
    spoken_response: str,
    *,
    needs_confirmation: bool = False,
    proposed_memory_action: dict[str, object] | None = None,
    mode_suggestion: str | None = None,
    confidence: str = "medium",
    required_information_source: str = "none",
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
            "freshness_requirement": freshness_requirement,
        }
    )


def _build_selected_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    client: RecordingChatClient,
    *,
    model_manager: AvailableModelManager | None = None,
) -> tuple[TraceableReasoningEngine, AvailableModelManager, list[dict[str, object]]]:
    selection_path = tmp_path / "reasoning-model-selection.json"
    save_model_selection(
        ReasoningModelSelection(
            model="granite-smoke:latest",
            fallback_model="granite-fallback:latest",
            host="http://localhost:11434",
        ),
        selection_path,
    )
    manager = model_manager or AvailableModelManager()
    client_constructions: list[dict[str, object]] = []

    def fake_client_factory(*, host: str, timeout: float) -> RecordingChatClient:
        client_constructions.append({"host": host, "timeout": timeout})
        return client

    monkeypatch.setattr("voice_concierge.reasoning.ollama.Client", fake_client_factory)

    engine = build_reasoning_engine(
        selection_path,
        timeout_s=9.0,
        model_manager=manager,
    )
    assert isinstance(engine, TraceableReasoningEngine)
    return engine, manager, client_constructions


def test_selected_runtime_bounds_generation_and_exposes_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingChatClient(
        _structured_content(
            "Your appointment is at noon.",
            confidence="high",
            required_information_source="local_context",
        )
    )
    engine, manager, client_constructions = _build_selected_runtime(
        tmp_path,
        monkeypatch,
        client,
    )

    response = engine.generate(
        ReasoningRequest(
            transcript="When is my appointment?",
            mode="home",
            memories=("Appointment is at noon.",),
            conversation_summary="The user asked about lunch earlier.",
            constraints=ReasoningConstraints(
                max_words=25,
                allow_memory_writes=False,
            ),
        )
    )

    assert manager.show_calls == ["granite-smoke:latest"]
    assert manager.pull_calls == []
    assert client_constructions == [{"host": "http://localhost:11434", "timeout": 9.0}]
    assert len(client.chat_calls) == 1

    call = client.chat_calls[0]
    assert call["model"] == "granite-smoke:latest"
    assert call["stream"] is False
    assert call["keep_alive"] == "5m"
    assert call["options"] == {
        "temperature": 0.2,
        "top_p": 0.9,
        "num_ctx": 4096,
        "num_predict": 164,
    }
    assert call["format"]["type"] == "object"
    assert "Maximum spoken response length: 25 words." in call["messages"][0]["content"]
    assert "Memory writes allowed: False." in call["messages"][0]["content"]
    assert "Appointment is at noon." in call["messages"][1]["content"]
    assert "The user asked about lunch earlier." in call["messages"][1]["content"]

    assert response.spoken_response == "Your appointment is at noon."
    assert response.confidence == "high"
    assert response.required_information_source == "local_context"
    assert response.freshness_requirement == "not_required"
    assert response.metadata["num_ctx"] == "4096"
    assert response.metadata["num_predict"] == "164"
    assert response.metadata["max_predict_tokens"] == "512"
    assert response.metadata["keep_alive"] == "5m"
    assert response.metadata["temperature"] == "0.2"
    assert response.metadata["top_p"] == "0.9"


@pytest.mark.parametrize(
    ("error", "expected_error"),
    (
        (
            ConnectionError("connection refused"),
            ReasoningBackendUnavailableError,
        ),
        (
            ReadTimeout("request timed out"),
            ReasoningTimeoutError,
        ),
        (
            ResponseError("model not found", status_code=404),
            ReasoningModelUnavailableError,
        ),
        (
            ResponseError("runner failed", status_code=500),
            ReasoningGenerationError,
        ),
    ),
)
def test_selected_runtime_maps_generation_failures_to_project_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: BaseException,
    expected_error: type[Exception],
) -> None:
    client = RecordingChatClient(error=error)
    engine, _, _ = _build_selected_runtime(tmp_path, monkeypatch, client)

    with pytest.raises(expected_error):
        engine.generate(ReasoningRequest(transcript="Hello."))


@pytest.mark.parametrize(
    ("content", "expected_response", "parse_error"),
    (
        (
            "Plain text instead of JSON.",
            "I could not produce a valid structured response.",
            "invalid_json",
        ),
        (
            _structured_content("", confidence="unknown"),
            "I could not produce a valid structured response.",
            "schema_validation_failed",
        ),
    ),
)
def test_selected_runtime_preserves_structured_output_failures_without_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    content: str,
    expected_response: str,
    parse_error: str,
) -> None:
    client = RecordingChatClient(content)
    engine, _, _ = _build_selected_runtime(tmp_path, monkeypatch, client)

    trace = engine.generate_trace(ReasoningRequest(transcript="Hello."))

    assert len(client.chat_calls) == 1
    assert trace.raw_response.spoken_response == expected_response
    assert trace.raw_response.confidence == "low"
    assert trace.raw_response.metadata["structured_parse_error"] == parse_error
    assert trace.guarded_response.spoken_response == expected_response
    assert trace.guarded_response.confidence == "low"
    assert trace.guarded_response.metadata["structured_parse_error"] == parse_error


def test_selected_runtime_maps_missing_model_at_startup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = RecordingChatClient(_structured_content("Unused."))
    manager = MissingModelManager()

    with pytest.raises(ReasoningModelUnavailableError):
        _build_selected_runtime(
            tmp_path,
            monkeypatch,
            client,
            model_manager=manager,
        )

    assert manager.show_calls == ["granite-smoke:latest"]
    assert client.chat_calls == []
