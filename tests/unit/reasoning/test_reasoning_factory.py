"""Tests for the application-facing reasoning runtime factory."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from ollama import ResponseError

from voice_concierge.reasoning import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_REASONING_MODEL,
    LocalModelDetails,
    ModelDownloadProgress,
    OllamaModelManagementError,
    OllamaReasoningEngine,
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningModelSelection,
    ReasoningModelUnavailableError,
    build_reasoning_engine,
    save_model_selection,
)


class RecordingModelManager:
    """Test double that records factory model-management calls."""

    def __init__(self, failure: str | None = None) -> None:
        self.failure = failure
        self.show_calls: list[str] = []
        self.pull_calls: list[str] = []

    def list_models(self) -> tuple[object, ...]:
        return ()

    def show_model(self, model: str) -> LocalModelDetails:
        self.show_calls.append(model)
        if self.failure == "missing":
            try:
                raise ResponseError("model not found", status_code=404)
            except ResponseError as exc:
                raise OllamaModelManagementError("missing model") from exc
        if self.failure == "backend":
            raise OllamaModelManagementError("connection failed") from ConnectionError(
                "refused"
            )
        return LocalModelDetails(model=model)

    def pull_model(
        self,
        model: str,
        *,
        stream: bool = False,
    ) -> tuple[ModelDownloadProgress, ...]:
        self.pull_calls.append(model)
        return ()


def test_factory_uses_default_selection_when_config_file_is_missing(
    tmp_path: Path,
) -> None:
    manager = RecordingModelManager()

    engine = build_reasoning_engine(
        tmp_path / "missing-model-selection.json",
        model_manager=manager,
    )

    assert isinstance(engine, OllamaReasoningEngine)
    assert engine.config.model == DEFAULT_REASONING_MODEL
    assert manager.show_calls == [DEFAULT_REASONING_MODEL]
    assert manager.pull_calls == []


def test_factory_reads_custom_selected_model_and_host(tmp_path: Path) -> None:
    path = tmp_path / "model-selection.json"
    save_model_selection(
        ReasoningModelSelection(
            model="granite-test:latest",
            fallback_model="granite-fallback:latest",
            host="http://localhost:9999",
        ),
        path,
    )
    manager = RecordingModelManager()

    engine = build_reasoning_engine(
        path,
        prompt_version="v1",
        timeout_s=7.5,
        model_manager=manager,
    )

    assert isinstance(engine, OllamaReasoningEngine)
    assert engine.config.model == "granite-test:latest"
    assert engine.config.host == "http://localhost:9999"
    assert engine.config.timeout_s == 7.5
    assert engine.config.prompt_version == "v1"
    assert manager.show_calls == ["granite-test:latest"]
    assert manager.pull_calls == []


def test_factory_rejects_invalid_model_selection_file(tmp_path: Path) -> None:
    path = tmp_path / "model-selection.json"
    path.write_text(json.dumps({"schema_version": 99}), encoding="utf-8")

    with pytest.raises(ReasoningConfigurationError, match="model selection"):
        build_reasoning_engine(path, model_manager=RecordingModelManager())


def test_factory_rejects_unsupported_backend(tmp_path: Path) -> None:
    path = tmp_path / "model-selection.json"
    save_model_selection(ReasoningModelSelection(backend="cloud"), path)
    manager = RecordingModelManager()

    with pytest.raises(ReasoningConfigurationError, match="Unsupported"):
        build_reasoning_engine(path, model_manager=manager)

    assert manager.show_calls == []


def test_factory_rejects_invalid_prompt_version(tmp_path: Path) -> None:
    manager = RecordingModelManager()

    with pytest.raises(ReasoningConfigurationError, match="prompt version"):
        build_reasoning_engine(
            tmp_path / "missing-model-selection.json",
            prompt_version="../bad",
            model_manager=manager,
        )

    assert manager.show_calls == []


def test_factory_checks_selected_primary_model_only(tmp_path: Path) -> None:
    path = tmp_path / "model-selection.json"
    save_model_selection(
        ReasoningModelSelection(
            model="granite-primary:latest",
            fallback_model=DEFAULT_FALLBACK_MODEL,
        ),
        path,
    )
    manager = RecordingModelManager()

    build_reasoning_engine(path, model_manager=manager)

    assert manager.show_calls == ["granite-primary:latest"]
    assert DEFAULT_FALLBACK_MODEL not in manager.show_calls
    assert manager.pull_calls == []


def test_factory_maps_missing_selected_model(tmp_path: Path) -> None:
    manager = RecordingModelManager(failure="missing")

    with pytest.raises(ReasoningModelUnavailableError, match=DEFAULT_REASONING_MODEL):
        build_reasoning_engine(
            tmp_path / "missing-model-selection.json",
            model_manager=manager,
        )


def test_factory_maps_unavailable_backend(tmp_path: Path) -> None:
    manager = RecordingModelManager(failure="backend")

    with pytest.raises(ReasoningBackendUnavailableError, match="Could not verify"):
        build_reasoning_engine(
            tmp_path / "missing-model-selection.json",
            model_manager=manager,
        )
