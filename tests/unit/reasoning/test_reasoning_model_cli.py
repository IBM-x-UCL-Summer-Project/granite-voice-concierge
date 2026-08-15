"""Tests for the local reasoning model-management command."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

MODEL_MANAGER_MODULE = "benchmarks.reasoning.manage_models"


def test_model_manager_cli_runs_as_module(tmp_path: Path) -> None:
    config_path = tmp_path / "missing-model-selection.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            MODEL_MANAGER_MODULE,
            "--config",
            str(config_path),
            "current",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    selection = json.loads(result.stdout)
    assert selection["backend"] == "ollama"
    assert selection["model"] == "granite4.1:8b"
    assert selection["fallback_policy"] == "startup_missing_primary"


def test_model_manager_cli_persists_explicit_fallback_policy(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "model-selection.json"

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            MODEL_MANAGER_MODULE,
            "--config",
            str(config_path),
            "select",
            "granite-primary:latest",
            "--fallback-model",
            "granite-fallback:latest",
            "--fallback-policy",
            "disabled",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    selection = json.loads(config_path.read_text(encoding="utf-8"))
    assert selection["schema_version"] == 2
    assert selection["fallback_policy"] == "disabled"
