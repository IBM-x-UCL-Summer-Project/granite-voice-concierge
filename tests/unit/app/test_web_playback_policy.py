"""Tests for browser automatic-playback policy without a DOM dependency."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
POLICY_PATH = REPOSITORY_ROOT / "web" / "playback-policy.js"


@pytest.mark.parametrize(
    ("changes", "expected"),
    (
        ({}, True),
        ({"voiceOutput": False}, False),
        ({"audioAvailable": False}, False),
        ({"confirmationRequired": True, "speakConfirmations": False}, False),
        ({"interactionMode": "text_first"}, False),
        ({"interactionMode": "push_to_talk", "isAudioTurn": False}, False),
        ({"interactionMode": "push_to_talk", "isAudioTurn": True}, True),
        ({"interactionMode": "wake_word", "isAudioTurn": True}, True),
    ),
)
def test_automatic_playback_policy(changes: dict[str, object], expected: bool) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the browser policy.")

    values = {
        "voiceOutput": True,
        "audioAvailable": True,
        "confirmationRequired": False,
        "speakConfirmations": True,
        "interactionMode": "voice_first",
        "isAudioTurn": False,
        **changes,
    }
    script = """
require(process.argv[1]);
const input = JSON.parse(process.argv[2]);
const result = globalThis.GranitePlaybackPolicy.shouldAutoPlayResponse(input);
process.stdout.write(JSON.stringify(result));
"""

    completed = subprocess.run(
        [node, "-e", script, str(POLICY_PATH), json.dumps(values)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=5,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert json.loads(completed.stdout) is expected
