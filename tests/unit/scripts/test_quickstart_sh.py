"""Regression tests for the macOS quick-start readiness gate."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
QUICKSTART_SCRIPT = REPOSITORY_ROOT / "scripts" / "quickstart.sh"


def _write_executable(directory: Path, name: str, body: str) -> None:
    path = directory / name
    path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
    path.chmod(0o755)


def test_quickstart_waits_for_web_health_before_reporting_ready(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    health_attempts = tmp_path / "health-attempts"

    _write_executable(
        fake_bin,
        "docker",
        """
if [ "$1" = "inspect" ]; then
    printf 'running\\n'
fi
exit 0
""".strip(),
    )
    _write_executable(fake_bin, "ollama", "exit 0")
    _write_executable(fake_bin, "sleep", "exit 0")
    _write_executable(
        fake_bin,
        "curl",
        """
case "$*" in
    *127.0.0.1:11434/api/tags*)
        exit 0
        ;;
    *127.0.0.1:4173/api/health*)
        attempts=0
        if [ -f "$HEALTH_ATTEMPTS_FILE" ]; then
            attempts=$(cat "$HEALTH_ATTEMPTS_FILE")
        fi
        attempts=$((attempts + 1))
        printf '%s' "$attempts" > "$HEALTH_ATTEMPTS_FILE"
        if [ "$attempts" -lt 2 ]; then
            exit 7
        fi
        printf '{"status":"ready"}'
        exit 0
        ;;
esac
exit 1
""".strip(),
    )
    (tmp_path / ".env").write_text(
        "OLLAMA_MODEL=granite4.1:8b\n"
        "OLLAMA_EMBEDDING_MODEL=granite-embedding:278m\n",
        encoding="utf-8",
    )
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}{os.pathsep}{environment['PATH']}"
    environment["HEALTH_ATTEMPTS_FILE"] = str(health_attempts)

    result = subprocess.run(
        ["bash", str(QUICKSTART_SCRIPT)],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert health_attempts.read_text(encoding="utf-8") == "2"
    waiting_position = result.stdout.index("Waiting up to")
    ready_position = result.stdout.index("Granite Voice Concierge is ready.")
    ui_position = result.stdout.index("Access Web UI:")
    assert waiting_position < ready_position < ui_position
