"""Tests for browser-side binary framing and bounded backpressure."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
AUDIO_STREAM_PATH = REPOSITORY_ROOT / "web" / "audio-stream.js"


def run_client_probe() -> dict[str, object]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the browser stream client.")
    script = r"""
const fs = require("node:fs");
const vm = require("node:vm");

class FakeWebSocket {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static instances = [];

  constructor(url, protocol) {
    this.url = url;
    this.protocol = protocol;
    this.readyState = FakeWebSocket.CONNECTING;
    this.binaryType = "";
    this.bufferedAmount = 0;
    this.sent = [];
    this.listeners = new Map();
    FakeWebSocket.instances.push(this);
  }

  addEventListener(name, listener) {
    const listeners = this.listeners.get(name) || [];
    listeners.push(listener);
    this.listeners.set(name, listeners);
  }

  emit(name, event = {}) {
    for (const listener of this.listeners.get(name) || []) listener(event);
  }

  open() {
    this.readyState = FakeWebSocket.OPEN;
    this.emit("open");
  }

  receive(payload) {
    this.emit("message", { data: JSON.stringify(payload) });
  }

  send(payload) {
    this.sent.push(payload);
  }

  close(code, reason) {
    this.closeCode = code;
    this.closeReason = reason;
    this.readyState = FakeWebSocket.CLOSED;
  }
}

global.WebSocket = FakeWebSocket;
global.state = {
  audioStream: {
    path: "/api/audio-stream",
    port: 4174,
    subprotocol: "granite-audio-v1",
  },
};
global.window = {
  location: {
    protocol: "http:",
    hostname: "127.0.0.1",
    host: "127.0.0.1:4173",
  },
  setTimeout,
  clearTimeout,
};

vm.runInThisContext(fs.readFileSync(process.argv[1], "utf8"), {
  filename: process.argv[1],
});

const StreamClient = window.GraniteAudioStreaming.PcmWebSocketStream;
const encodeFrame = window.GraniteAudioStreaming.encodePcmStreamFrame;

(async () => {
  const dropped = [];
  const results = [];
  const stream = new StreamClient({
    mode: "wake_word",
    onResult: (result) => results.push(result.sequence),
    onError: (error) => { throw error; },
    onDrop: (event) => dropped.push(event.sequence),
  });
  const started = stream.start({ sensitivity: 60 });
  const socket = FakeWebSocket.instances[0];
  socket.open();
  const startMessage = JSON.parse(socket.sent[0]);
  socket.receive({
    type: "started",
    mode: "wake_word",
    sample_rate: 16000,
    confidence_threshold: 0.3,
  });
  await started;

  for (let index = 0; index < 5; index += 1) {
    stream.push(new Float32Array(3200).fill(index / 10));
  }
  const firstFrame = new DataView(socket.sent[1]);
  socket.receive({ type: "frame", sequence: 0, detected: false });
  await new Promise((resolve) => setImmediate(resolve));
  const secondFrame = new DataView(socket.sent[2]);

  const staleResults = [];
  const resetting = new StreamClient({
    mode: "wake_word",
    onResult: (result) => staleResults.push(result.sequence),
    onError: (error) => { throw error; },
  });
  const resettingStart = resetting.start();
  const resetSocket = FakeWebSocket.instances[1];
  resetSocket.open();
  resetSocket.receive({ type: "started", mode: "wake_word", sample_rate: 16000 });
  await resettingStart;
  resetting.push(new Float32Array(3200));
  const resetPromise = resetting.reset();
  resetSocket.receive({ type: "frame", sequence: 0, detected: true });
  const resetControl = JSON.parse(resetSocket.sent[2]);
  resetSocket.receive({ type: "reset", token: resetControl.token });
  await resetPromise;
  await new Promise((resolve) => setImmediate(resolve));
  resetting.stop();

  const encoded = new DataView(
    encodeFrame(new Float32Array([-1, -0.5, 0, 0.5, 1]), 99),
  );
  stream.stop();

  const connecting = new StreamClient({
    mode: "wake_word",
    onResult: () => {},
    onError: () => {},
  });
  const connectingStart = connecting.start();
  connecting.stop();
  let connectingError = null;
  try {
    await connectingStart;
  } catch (error) {
    connectingError = error.message;
  }

  process.stdout.write(JSON.stringify({
    url: socket.url,
    protocol: socket.protocol,
    binaryType: socket.binaryType,
    startMessage,
    firstSequence: firstFrame.getUint32(0, false),
    secondSequence: secondFrame.getUint32(0, false),
    dropped,
    results,
    staleResults,
    encodedSequence: encoded.getUint32(0, false),
    encodedSamples: Array.from(
      { length: 5 },
      (_, index) => encoded.getInt16(4 + index * 2, true),
    ),
    connectingError,
  }));
})().catch((error) => {
  process.stderr.write(error.stack || String(error));
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        [node, "-e", script, str(AUDIO_STREAM_PATH)],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        pytest.fail(completed.stderr)
    return json.loads(completed.stdout)


def test_stream_client_uses_binary_protocol_and_bounded_queue() -> None:
    result = run_client_probe()

    assert result["url"] == "ws://127.0.0.1:4174/api/audio-stream"
    assert result["protocol"] == "granite-audio-v1"
    assert result["binaryType"] == "arraybuffer"
    assert result["startMessage"] == {
        "type": "start",
        "mode": "wake_word",
        "sensitivity": 60,
    }
    assert result["firstSequence"] == 0
    assert result["secondSequence"] == 2
    assert result["dropped"] == [1]
    assert result["results"] == [0]
    assert result["staleResults"] == []


def test_stream_client_encodes_little_endian_pcm_and_aborts_pending_start() -> None:
    result = run_client_probe()

    assert result["encodedSequence"] == 99
    assert result["encodedSamples"] == [-32768, -16384, 0, 16383, 32767]
    assert result["connectingError"] == "The microphone stream stopped."
