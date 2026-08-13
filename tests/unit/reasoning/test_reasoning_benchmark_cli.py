"""Tests for the consolidated reasoning benchmark command."""

from __future__ import annotations

import json
import subprocess
import sys
from argparse import Namespace
from pathlib import Path

import pytest

from benchmarks.reasoning.benchmark import _run_single, build_engine
from voice_concierge.reasoning import (
    DeterministicReasoningFake,
    OllamaReasoningEngine,
    ReasoningBackendUnavailableError,
    ReasoningConfigurationError,
    ReasoningModelSelection,
    ReasoningModelUnavailableError,
    save_model_selection,
)

BENCHMARK_MODULE = "benchmarks.reasoning.benchmark"


def test_benchmark_cli_runs_fake(tmp_path: Path) -> None:
    output_path = tmp_path / "fake-report.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            BENCHMARK_MODULE,
            "run",
            "--output",
            str(output_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["engine"] == "DeterministicReasoningFake"
    assert report["total_cases"] == 20


def test_benchmark_cli_compare_requires_two_models() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            BENCHMARK_MODULE,
            "compare",
            "--models",
            "granite4.1:8b",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "compare requires at least two models" in result.stderr


def test_benchmark_ollama_engine_uses_persisted_model_selection(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "model-selection.json"
    save_model_selection(
        ReasoningModelSelection(
            model="selected-model:latest",
            host="http://127.0.0.1:11500",
        ),
        config_path,
    )

    engine = build_engine(
        Namespace(
            engine="ollama",
            config=config_path,
            model=None,
            host=None,
            prompt_version="v1",
            timeout_s=7.0,
        )
    )

    assert isinstance(engine, OllamaReasoningEngine)
    assert engine.config.model == "selected-model:latest"
    assert engine.config.host == "http://127.0.0.1:11500"
    assert engine.config.timeout_s == 7.0
    assert engine.config.prompt_version == "v1"


def test_benchmark_ollama_engine_cli_values_override_selection(
    tmp_path: Path,
) -> None:
    engine = build_engine(
        Namespace(
            engine="ollama",
            config=tmp_path / "missing.json",
            model="override-model:latest",
            host="http://localhost:11600",
            prompt_version="v1",
            timeout_s=4.0,
        )
    )

    assert isinstance(engine, OllamaReasoningEngine)
    assert engine.config.model == "override-model:latest"
    assert engine.config.host == "http://localhost:11600"


def test_benchmark_selected_engine_uses_runtime_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}
    fake_engine = DeterministicReasoningFake()

    def fake_factory(
        selection_path: str | Path,
        *,
        prompt_version: str,
        timeout_s: float,
    ) -> DeterministicReasoningFake:
        captured.update(
            selection_path=selection_path,
            prompt_version=prompt_version,
            timeout_s=timeout_s,
        )
        return fake_engine

    monkeypatch.setattr(
        "benchmarks.reasoning.benchmark.build_reasoning_engine",
        fake_factory,
    )

    config_path = tmp_path / "model-selection.json"
    engine = build_engine(
        Namespace(
            engine="selected",
            config=config_path,
            model=None,
            host=None,
            prompt_version="v1",
            timeout_s=9.0,
        )
    )

    assert engine is fake_engine
    assert captured == {
        "selection_path": config_path,
        "prompt_version": "v1",
        "timeout_s": 9.0,
    }


def test_benchmark_cli_selected_rejects_model_or_host_override() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            BENCHMARK_MODULE,
            "run",
            "--engine",
            "selected",
            "--model",
            "granite-test",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "--engine selected uses --config" in result.stderr


@pytest.mark.parametrize(
    ("error", "expected_returncode"),
    (
        (ReasoningConfigurationError("bad config"), 2),
        (ReasoningBackendUnavailableError("backend down"), 1),
        (ReasoningModelUnavailableError("model missing"), 1),
    ),
)
def test_benchmark_cli_maps_selected_factory_errors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_returncode: int,
) -> None:
    def failing_build_engine(args: Namespace) -> DeterministicReasoningFake:
        raise error

    monkeypatch.setattr(
        "benchmarks.reasoning.benchmark.build_engine",
        failing_build_engine,
    )

    result = _run_single(
        Namespace(
            prompts=Path("benchmarks/reasoning/prompts/v0.json"),
            output=tmp_path / "report.json",
            max_words=60,
            evaluation_mode="guarded",
        )
    )

    assert result == expected_returncode


def test_benchmark_rejects_selected_non_ollama_backend(tmp_path: Path) -> None:
    config_path = tmp_path / "model-selection.json"
    save_model_selection(
        ReasoningModelSelection(
            backend="llama_cpp",
            model="local-model.gguf",
        ),
        config_path,
    )

    with pytest.raises(ValueError, match="not supported by the Ollama benchmark"):
        build_engine(
            Namespace(
                engine="ollama",
                config=config_path,
                model=None,
                host=None,
                prompt_version="v1",
                timeout_s=4.0,
            )
        )


def test_benchmark_cli_rejects_unknown_prompt_version() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            BENCHMARK_MODULE,
            "run",
            "--engine",
            "ollama",
            "--model",
            "granite-test",
            "--host",
            "http://localhost:11434",
            "--prompt-version",
            "missing-version",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "Prompt template version 'missing-version' is not available" in result.stderr
