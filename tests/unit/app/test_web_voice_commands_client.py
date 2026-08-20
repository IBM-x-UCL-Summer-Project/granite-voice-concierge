"""Regression tests for browser barge-in command coordination."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
VOICE_COMMANDS_PATH = REPOSITORY_ROOT / "web" / "voice-commands.js"


def run_voice_command_probe() -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute browser command coordination.")
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");

let releaseTurn;
const turnGate = new Promise((resolve) => { releaseTurn = resolve; });
const turnCalls = [];
const diagnosticEvents = [];
let resetCount = 0;
let pushedFrames = 0;

global.state = {
  capabilities: { playback_barge_in: true, routine_barge_in: true },
  playback: { kind: "audio" },
  running: false,
  routine: {
    active: true,
    status: "running",
    awaiting_confirmation: false,
    confirmationReady: false,
    autoGeneration: 0,
    autoTimer: null,
    confirmationTimer: null,
  },
  voiceCommands: {
    serverActive: true,
    starting: false,
    processingCommand: false,
    generation: 7,
    audio: null,
    stream: {
      drainPendingSamples() { return []; },
      push() { pushedFrames += 1; },
      async reset() { resetCount += 1; },
    },
  },
  wakeWord: { active: false },
};
global.window = { clearTimeout };
global.shouldListenForVoiceCommands = ({
  capabilityEnabled,
  routineActive,
  playbackActive,
}) => Boolean(capabilityEnabled && (routineActive || playbackActive));
global.isPlaybackBargeInCommand = () => true;
global.diagnostics = {
  debug() {},
  info(event) { diagnosticEvents.push(event); },
  warning() {},
  error() {},
};
global.stopPlayback = () => { state.playback = null; };
global.delay = () => Promise.resolve();
global.showToast = () => {};
global.runTurn = async (command) => {
  turnCalls.push(command);
  await turnGate;
};

vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"), {
  filename: process.argv[1],
});

(async () => {
  await handleVoiceCommandStreamResult(
    { command: "stop", phrase: "stop" },
    6,
  );

  const first = handleVoiceCommandStreamResult(
    { command: "stop", phrase: "stop" },
    7,
  );
  await new Promise((resolve) => setImmediate(resolve));
  enqueueVoiceCommandFrame(new Float32Array(1600));
  const duplicate = handleVoiceCommandStreamResult(
    { command: "stop", phrase: "stop" },
    7,
  );
  await new Promise((resolve) => setImmediate(resolve));
  releaseTurn();
  await Promise.all([first, duplicate]);

  enqueueVoiceCommandFrame(new Float32Array(1600));
  process.stdout.write(JSON.stringify({
    turnCalls,
    resetCount,
    pushedFrames,
    processingCommand: state.voiceCommands.processingCommand,
    detectedEvents: diagnosticEvents.filter(
      (event) => event === "voice_command_detected",
    ).length,
  }));
})().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        [node, "-e", script, str(VOICE_COMMANDS_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        pytest.fail(completed.stderr)
    return json.loads(completed.stdout)


def test_stale_and_concurrent_voice_commands_are_not_handled_twice() -> None:
    result = run_voice_command_probe()

    assert result == {
        "turnCalls": ["stop"],
        "resetCount": 1,
        "pushedFrames": 1,
        "processingCommand": False,
        "detectedEvents": 1,
    }
