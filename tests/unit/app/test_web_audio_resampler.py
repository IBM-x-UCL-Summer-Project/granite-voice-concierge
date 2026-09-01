"""Tests for the browser's stateful band-limited microphone resampler."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
RESAMPLER_PATH = REPOSITORY_ROOT / "web" / "audio-resampler.mjs"


def run_resampler_probe() -> list[dict[str, float | int]]:
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is required to execute the browser resampler.")
    script = r"""
import { pathToFileURL } from "node:url";
const { StreamingSincResampler } = await import(pathToFileURL(process.argv[1]));

function probe(frequency) {
  const sourceRate = 48000;
  const targetRate = 16000;
  const input = Float32Array.from(
    { length: sourceRate },
    (_, index) => Math.sin(2 * Math.PI * frequency * index / sourceRate),
  );
  const resampler = new StreamingSincResampler(sourceRate, targetRate);
  const chunks = [];
  let length = 0;
  for (let offset = 0; offset < input.length; offset += 128) {
    const chunk = resampler.process(input.slice(offset, offset + 128));
    chunks.push(chunk);
    length += chunk.length;
  }
  const tail = resampler.flush();
  chunks.push(tail);
  length += tail.length;
  const output = new Float32Array(length);
  let outputOffset = 0;
  for (const chunk of chunks) {
    output.set(chunk, outputOffset);
    outputOffset += chunk.length;
  }
  const stable = output.slice(500, -500);
  const rms = Math.sqrt(
    stable.reduce((total, sample) => total + sample * sample, 0) / stable.length,
  );
  return { frequency, length: output.length, rms };
}

process.stdout.write(JSON.stringify([probe(1000), probe(12000)]));
"""
    completed = subprocess.run(
        [node, "--input-type=module", "-e", script, str(RESAMPLER_PATH)],
        cwd=REPOSITORY_ROOT,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


def test_streaming_resampler_preserves_duration_and_passband() -> None:
    passband, _ = run_resampler_probe()

    assert passband["length"] == 16000
    assert passband["rms"] == pytest.approx(2**-0.5, abs=0.01)


def test_streaming_resampler_attenuates_aliases_above_target_nyquist() -> None:
    _, stopband = run_resampler_probe()

    assert stopband["length"] == 16000
    assert stopband["rms"] < 0.01
