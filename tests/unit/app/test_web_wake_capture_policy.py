"""Tests for browser wake handoff policy without a DOM dependency."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPOSITORY_ROOT / "web" / "wake-capture-policy.js"


def run_policy(function: str, values: dict[str, object]) -> dict[str, object] | bool:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the browser policy.")
    script = """
require(process.argv[1]);
const input = JSON.parse(process.argv[3]);
if (Array.isArray(input.chunks)) {
  input.chunks = input.chunks.map((length) => new Float32Array(length));
}
const result = globalThis.GraniteWakeCapturePolicy[process.argv[2]](input);
if (result && Array.isArray(result.retainedChunks)) {
  result.retainedChunks = result.retainedChunks.map((chunk) => chunk.length);
}
process.stdout.write(JSON.stringify(result));
"""
    completed = subprocess.run(
        [node, "-e", script, str(POLICY_PATH), function, json.dumps(values)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_wake_capture_retains_and_backdates_pre_roll() -> None:
    result = run_policy(
        "prepareWakeCapture",
        {
            "chunks": [0, 800, 1600],
            "sampleRate": 16000,
            "captureStartedAt": 1000,
            "deferSpeechArm": True,
            "armDelayMs": 350,
        },
    )

    assert result == {
        "retainedChunks": [800, 1600],
        "preRollMs": 150,
        "commandStartedAt": 850,
        "speechArmedAt": 1350,
    }


def test_push_to_talk_capture_arms_immediately() -> None:
    result = run_policy(
        "prepareWakeCapture",
        {
            "chunks": [],
            "sampleRate": 16000,
            "captureStartedAt": 1000,
            "deferSpeechArm": False,
            "armDelayMs": 350,
        },
    )

    assert result["speechArmedAt"] == 1000


@pytest.mark.parametrize(
    ("values", "expected"),
    (
        (
            {"now": 1349, "speechArmedAt": 1350, "rms": 0.2, "speechThreshold": 0.1},
            False,
        ),
        (
            {"now": 1350, "speechArmedAt": 1350, "rms": 0.09, "speechThreshold": 0.1},
            False,
        ),
        (
            {"now": 1350, "speechArmedAt": 1350, "rms": 0.2, "speechThreshold": 0.1},
            True,
        ),
    ),
)
def test_wake_tail_cannot_start_speech_before_arm_time(
    values: dict[str, object], expected: bool
) -> None:
    assert run_policy("speechCanStart", values) is expected
