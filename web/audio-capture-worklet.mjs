// Audio rendering-thread processor that emits stable 16 kHz mono chunks.

import { StreamingSincResampler } from "./audio-resampler.mjs";

class GranitePcmCaptureProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const processorOptions = options.processorOptions || {};
    this.outputChunkSamples = processorOptions.outputChunkSamples || 320;
    this.resampler = new StreamingSincResampler(
      sampleRate,
      processorOptions.targetSampleRate || 16000,
    );
    this.pendingChunks = [];
    this.pendingSampleCount = 0;
    this.pendingOffset = 0;
    this.port.onmessage = (event) => {
      if (event.data?.type !== "flush") return;
      this.#enqueue(this.resampler.flush());
      this.#emitAvailable(true);
      this.port.postMessage({ type: "flushed", token: event.data.token });
    };
  }

  process(inputs, outputs) {
    const channel = inputs[0]?.[0];
    if (channel?.length) {
      this.#enqueue(this.resampler.process(channel));
      this.#emitAvailable(false);
    }
    // This capture node must remain connected to the graph to be pulled, but
    // it never emits audible output.
    for (const output of outputs[0] || []) output.fill(0);
    return true;
  }

  #enqueue(samples) {
    if (!samples.length) return;
    this.pendingChunks.push(samples);
    this.pendingSampleCount += samples.length;
  }

  #emitAvailable(flush) {
    while (this.pendingSampleCount >= this.outputChunkSamples) {
      this.#emit(this.outputChunkSamples);
    }
    if (flush && this.pendingSampleCount) this.#emit(this.pendingSampleCount);
  }

  #emit(sampleCount) {
    const samples = new Float32Array(sampleCount);
    let written = 0;
    while (written < sampleCount) {
      const chunk = this.pendingChunks[0];
      const available = chunk.length - this.pendingOffset;
      const copied = Math.min(available, sampleCount - written);
      samples.set(
        chunk.subarray(this.pendingOffset, this.pendingOffset + copied),
        written,
      );
      written += copied;
      this.pendingOffset += copied;
      if (this.pendingOffset === chunk.length) {
        this.pendingChunks.shift();
        this.pendingOffset = 0;
      }
    }
    this.pendingSampleCount -= sampleCount;
    this.port.postMessage({ type: "samples", samples }, [samples.buffer]);
  }
}

registerProcessor("granite-pcm-capture", GranitePcmCaptureProcessor);
