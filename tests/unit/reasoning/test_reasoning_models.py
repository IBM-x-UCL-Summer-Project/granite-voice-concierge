"""Tests for local reasoning model management."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock

import pytest
from ollama import ListResponse, ProgressResponse, ShowResponse

from voice_concierge.reasoning import (
    DEFAULT_FALLBACK_MODEL,
    DEFAULT_MODEL_BACKEND,
    DEFAULT_MODEL_FALLBACK_POLICY,
    DEFAULT_MODEL_SELECTION_PATH,
    DEFAULT_OLLAMA_HOST,
    DEFAULT_REASONING_MODEL,
    OllamaModelManager,
    OllamaModelManagerConfig,
    ReasoningModelSelection,
    default_model_selection,
    load_model_selection,
    save_model_selection,
)


def test_default_model_selection_uses_granite_4_1_8b() -> None:
    selection = default_model_selection()

    assert selection.backend == DEFAULT_MODEL_BACKEND
    assert selection.model == DEFAULT_REASONING_MODEL
    assert selection.model == "granite4.1:8b"
    assert selection.fallback_model == DEFAULT_FALLBACK_MODEL
    assert selection.fallback_policy == DEFAULT_MODEL_FALLBACK_POLICY
    assert selection.host == DEFAULT_OLLAMA_HOST
    assert DEFAULT_MODEL_SELECTION_PATH == Path(".local/reasoning-model-selection.json")


def test_model_selection_round_trips_to_json(tmp_path: Path) -> None:
    path = tmp_path / "model-selection.json"
    selection = ReasoningModelSelection(
        backend="ollama",
        model="granite4.1:8b",
        fallback_model="granite3.3:2b",
        fallback_policy="startup_missing_primary",
        host="http://localhost:11434",
    )

    save_model_selection(selection, path)

    assert load_model_selection(path) == selection
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == 2


def test_legacy_model_selection_preserves_disabled_fallback(tmp_path: Path) -> None:
    path = tmp_path / "legacy-model-selection.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "backend": "ollama",
                "model": "granite-primary:latest",
                "fallback_model": "granite-fallback:latest",
                "host": "http://localhost:11434",
            }
        ),
        encoding="utf-8",
    )

    selection = load_model_selection(path)

    assert selection.fallback_policy == "disabled"


@pytest.mark.parametrize(
    "selection",
    (
        {
            "fallback_model": None,
            "fallback_policy": "startup_missing_primary",
        },
        {
            "model": "same-model",
            "fallback_model": "same-model",
            "fallback_policy": "startup_missing_primary",
        },
        {"fallback_policy": "always"},
    ),
)
def test_model_selection_rejects_invalid_fallback_configuration(
    selection: dict[str, object],
) -> None:
    with pytest.raises(ValueError, match="fallback"):
        ReasoningModelSelection(**selection)


def test_model_selection_loads_defaults_when_missing(tmp_path: Path) -> None:
    assert load_model_selection(tmp_path / "missing.json") == default_model_selection()


def test_model_selection_rejects_empty_fields(tmp_path: Path) -> None:
    path = tmp_path / "model-selection.json"
    path.write_text(
        json.dumps({"schema_version": 1, "model": "   "}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="non-empty strings"):
        load_model_selection(path)


@pytest.mark.parametrize("version", (True, "2", [], {}))
def test_model_selection_rejects_invalid_schema_version(
    tmp_path: Path,
    version: object,
) -> None:
    path = tmp_path / "model-selection.json"
    path.write_text(
        json.dumps({"schema_version": version}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="schema version"):
        load_model_selection(path)


def test_ollama_model_manager_configures_official_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    client = Mock()

    def fake_client(*, host: str, timeout: float) -> Mock:
        captured.update(host=host, timeout=timeout)
        return client

    monkeypatch.setattr("voice_concierge.reasoning.ollama.Client", fake_client)

    manager = OllamaModelManager(
        OllamaModelManagerConfig(host="http://localhost:11434", timeout_s=5.0)
    )

    assert manager.config.timeout_s == 5.0
    assert captured == {"host": "http://localhost:11434", "timeout": 5.0}


def test_ollama_model_manager_lists_installed_models() -> None:
    client = Mock()
    client.list.return_value = ListResponse(
        models=[
            {
                "model": "granite4.1:8b",
                "modified_at": "2026-06-17T12:00:00Z",
                "size": 5300000000,
                "digest": "abc123",
                "details": {
                    "format": "gguf",
                    "family": "granite",
                    "families": ["granite"],
                    "parameter_size": "8.79B",
                    "quantization_level": "Q4_K_M",
                },
            }
        ]
    )
    manager = OllamaModelManager(client=client)

    models = manager.list_models()

    client.list.assert_called_once_with()
    assert len(models) == 1
    assert models[0].model == "granite4.1:8b"
    assert models[0].size_bytes == 5300000000
    assert models[0].parameter_size == "8.79B"
    assert models[0].quantization_level == "Q4_K_M"


def test_ollama_model_manager_shows_model_details() -> None:
    client = Mock()
    client.show.return_value = ShowResponse(
        model_info={},
        parameters="temperature 0.2",
        license="Apache 2.0",
        capabilities=["completion", "tools"],
        modified_at="2026-06-17T12:00:00Z",
        details={
            "format": "gguf",
            "family": "granite",
            "families": ["granite"],
            "parameter_size": "8.79B",
            "quantization_level": "Q4_K_M",
        },
    )
    manager = OllamaModelManager(client=client)

    details = manager.show_model("granite4.1:8b")

    client.show.assert_called_once_with("granite4.1:8b")
    assert details.model == "granite4.1:8b"
    assert details.capabilities == ("completion", "tools")
    assert details.license == "Apache 2.0"
    assert details.quantization_level == "Q4_K_M"


def test_ollama_model_manager_pulls_model_without_streaming() -> None:
    client = Mock()
    client.pull.return_value = ProgressResponse(status="success")
    manager = OllamaModelManager(client=client)

    progress = manager.pull_model("granite4.1:8b")

    client.pull.assert_called_once_with("granite4.1:8b", stream=False)
    assert len(progress) == 1
    assert progress[0].status == "success"


def test_ollama_model_manager_streams_pull_progress() -> None:
    client = Mock()
    client.pull.return_value = iter(
        [
            ProgressResponse(status="pulling manifest"),
            ProgressResponse(
                status="downloading",
                digest="abc123",
                total=100,
                completed=50,
            ),
            ProgressResponse(status="success"),
        ]
    )
    manager = OllamaModelManager(client=client)

    progress = manager.pull_model("granite4.1:8b", stream=True)

    client.pull.assert_called_once_with("granite4.1:8b", stream=True)
    assert [update.status for update in progress] == [
        "pulling manifest",
        "downloading",
        "success",
    ]
    assert progress[1].digest == "abc123"
    assert progress[1].total == 100
    assert progress[1].completed == 50
