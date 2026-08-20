"""Lifecycle tests for the shared browser microphone capture boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
CAPTURE_PATH = REPOSITORY_ROOT / "web" / "audio-capture.js"


def run_capture_probe() -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute browser capture lifecycle tests.")
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class EventTargetFake {
  constructor() {
    this.listeners = new Map();
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  removeEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    this.listeners.set(name, listeners.filter((item) => item !== listener));
  }

  emit(name, data = {}) {
    for (const listener of this.listeners.get(name) || []) listener({ data });
  }
}

class FakeTrack extends EventTargetFake {
  constructor() {
    super();
    this.stopCount = 0;
  }

  getSettings() {
    return {
      deviceId: "selected-device",
      channelCount: 1,
      sampleRate: 48000,
      echoCancellation: true,
      noiseSuppression: false,
      autoGainControl: true,
    };
  }

  stop() {
    this.stopCount += 1;
  }
}

class FakeNode {
  constructor() {
    this.disconnectCount = 0;
    this.connections = [];
  }

  connect(node) {
    this.connections.push(node);
    return node;
  }

  disconnect() {
    this.disconnectCount += 1;
  }
}

class FakePort extends EventTargetFake {
  start() {}

  postMessage(message) {
    if (message.type === "flush") {
      queueMicrotask(() => this.emit("message", {
        type: "flushed",
        token: message.token,
      }));
    }
  }
}

class FakeAudioWorkletNode extends FakeNode {
  constructor(context, name, options) {
    super();
    this.context = context;
    this.name = name;
    this.options = options;
    this.port = new FakePort();
    FakeAudioWorkletNode.instances.push(this);
  }
}
FakeAudioWorkletNode.instances = [];

class FakeAudioContext extends EventTargetFake {
  constructor(options) {
    super();
    this.options = options;
    this.state = "suspended";
    this.sampleRate = 48000;
    this.audioWorklet = {
      addModule: async (url) => { this.moduleUrl = String(url); },
    };
    this.destination = new FakeNode();
    this.resumeCount = 0;
    this.closeCount = 0;
    FakeAudioContext.instances.push(this);
  }

  createMediaStreamSource(stream) {
    this.stream = stream;
    return new FakeNode();
  }

  createGain() {
    const node = new FakeNode();
    node.gain = { value: 1 };
    return node;
  }

  async resume() {
    this.resumeCount += 1;
    this.state = "running";
  }

  async close() {
    this.closeCount += 1;
    this.state = "closed";
  }
}
FakeAudioContext.instances = [];

const track = new FakeTrack();
const mediaStream = {
  getAudioTracks: () => [track],
  getTracks: () => [track],
};
const requested = [];
const diagnosticEvents = [];
Object.defineProperty(global, "navigator", { configurable: true, value: {
  mediaDevices: {
    getSupportedConstraints: () => ({
      deviceId: true,
      channelCount: true,
      echoCancellation: true,
      noiseSuppression: false,
      autoGainControl: true,
    }),
    getUserMedia: async (constraints) => {
      requested.push(constraints);
      return mediaStream;
    },
  },
} });
global.diagnostics = {
  info: (name, details) => diagnosticEvents.push({ level: "info", name, details }),
  warning: (name, details) => diagnosticEvents.push(
    { level: "warning", name, details },
  ),
  error: (name, details) => diagnosticEvents.push({ level: "error", name, details }),
};
global.state = { recorder: null, wakeWord: {}, voiceCommands: {} };
global.window = {
  AudioContext: FakeAudioContext,
  AudioWorkletNode: FakeAudioWorkletNode,
  location: { href: "http://127.0.0.1:4173/" },
  setTimeout,
  clearTimeout,
};
global.AudioWorkletNode = FakeAudioWorkletNode;

const source = fs.readFileSync(process.argv[1], "utf8")
  + "\n;globalThis.captureBoundary = { openMicrophoneCapture };";
vm.runInThisContext(source, { filename: process.argv[1] });

(async () => {
  let endedCount = 0;
  const contextStates = [];
  const capture = await captureBoundary.openMicrophoneCapture({
    microphoneId: "selected-device",
    purpose: "test",
    onSamples: () => {},
    onEnded: () => { endedCount += 1; },
    onStateChange: (value) => contextStates.push(value),
  });
  const context = FakeAudioContext.instances[0];
  const worklet = FakeAudioWorkletNode.instances[0];
  const settings = capture.settings;

  context.state = "suspended";
  context.emit("statechange");
  await capture.resume();
  track.emit("ended");
  await new Promise((resolve) => setImmediate(resolve));
  await capture.stop();

  navigator.mediaDevices.getUserMedia = async () => {
    throw new DOMException("permission denied", "NotAllowedError");
  };
  let deniedName = null;
  try {
    await captureBoundary.openMicrophoneCapture({
      microphoneId: "default",
      purpose: "denied",
      onSamples: () => {},
    });
  } catch (error) {
    deniedName = error.name;
  }

  process.stdout.write(JSON.stringify({
    requested: requested[0],
    settings,
    contextStates,
    resumeCount: context.resumeCount,
    closeCount: context.closeCount,
    trackStopCount: track.stopCount,
    endedCount,
    workletName: worklet.name,
    workletOptions: worklet.options,
    moduleUrl: context.moduleUrl,
    deniedName,
    deniedLogged: diagnosticEvents.some(
      (event) => event.name === "microphone_capture_failed"
        && event.details.error_name === "NotAllowedError",
    ),
  }));
})().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        [node, "-e", script, str(CAPTURE_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        pytest.fail(completed.stderr)
    return json.loads(completed.stdout)


def test_capture_applies_supported_constraints_and_reports_actual_settings() -> None:
    result = run_capture_probe()

    assert result["requested"] == {
        "audio": {
            "deviceId": {"exact": "selected-device"},
            "channelCount": {"ideal": 1},
            "echoCancellation": True,
            "autoGainControl": True,
        }
    }
    assert result["settings"] == {
        "requested_constraints": result["requested"]["audio"],
        "device_id": "selected-device",
        "channel_count": 1,
        "track_sample_rate": 48000,
        "context_sample_rate": 48000,
        "echo_cancellation": True,
        "noise_suppression": False,
        "auto_gain_control": True,
    }
    assert result["workletName"] == "granite-pcm-capture"
    assert result["workletOptions"]["processorOptions"] == {
        "targetSampleRate": 16000,
        "outputChunkSamples": 320,
    }
    assert "audio-capture-worklet.mjs" in result["moduleUrl"]


def test_capture_resumes_and_releases_resources_on_track_end() -> None:
    result = run_capture_probe()

    assert result["contextStates"] == ["suspended"]
    assert result["resumeCount"] == 2
    assert result["endedCount"] == 1
    assert result["trackStopCount"] == 1
    assert result["closeCount"] == 1


def test_capture_propagates_denied_permission_without_leaking_resources() -> None:
    result = run_capture_probe()

    assert result["deniedName"] == "NotAllowedError"
    assert result["deniedLogged"] is True
