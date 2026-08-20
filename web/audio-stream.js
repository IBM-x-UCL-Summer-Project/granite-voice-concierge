// Bounded, acknowledged binary PCM transport for continuous local listening.

const AUDIO_STREAM_FRAME_SAMPLES = 3200;
const AUDIO_STREAM_HEADER_BYTES = 4;
const AUDIO_STREAM_MAX_QUEUED_FRAMES = 3;
const AUDIO_STREAM_MAX_BUFFERED_BYTES = 64 * 1024;
const AUDIO_STREAM_TIMEOUT_MILLISECONDS = 5000;

function audioStreamUrl(configuration) {
  const scheme = window.location.protocol === "https:" ? "wss:" : "ws:";
  const host = configuration.port
    ? `${window.location.hostname}:${configuration.port}`
    : window.location.host;
  return `${scheme}//${host}${configuration.path}`;
}

function encodePcmStreamFrame(samples, sequence) {
  const buffer = new ArrayBuffer(AUDIO_STREAM_HEADER_BYTES + samples.length * 2);
  const view = new DataView(buffer);
  view.setUint32(0, sequence, false);
  samples.forEach((sample, index) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(
      AUDIO_STREAM_HEADER_BYTES + index * 2,
      clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff,
      true,
    );
  });
  return buffer;
}

class PcmWebSocketStreamImplementation {
  constructor({ mode, onResult, onError, onDrop = () => {} }) {
    this.mode = mode;
    this.onResult = onResult;
    this.onError = onError;
    this.onDrop = onDrop;
    this.socket = null;
    this.started = false;
    this.stopping = false;
    this.failed = false;
    this.sequence = 0;
    this.audioEpoch = 0;
    this.frameQueue = [];
    this.partialChunks = [];
    this.partialSampleCount = 0;
    this.inFlight = null;
    this.processingResult = false;
    this.pumpTimer = null;
    this.startTimeout = null;
    this.startResolve = null;
    this.startReject = null;
    this.resetWaiters = new Map();
  }

  start(options = {}) {
    if (!state.audioStream) {
      return Promise.reject(new Error("Binary microphone streaming is unavailable."));
    }
    const startPromise = new Promise((resolve, reject) => {
      this.startResolve = resolve;
      this.startReject = reject;
    });
    this.socket = new WebSocket(
      audioStreamUrl(state.audioStream),
      state.audioStream.subprotocol,
    );
    this.socket.binaryType = "arraybuffer";
    this.socket.addEventListener("open", () => {
      this.socket.send(JSON.stringify({ type: "start", mode: this.mode, ...options }));
    });
    this.socket.addEventListener("message", (event) => this.#handleMessage(event));
    this.socket.addEventListener("error", () => {
      this.#fail(new Error("The local microphone stream could not connect."));
    });
    this.socket.addEventListener("close", (event) => {
      if (this.stopping) return;
      const detail = event.reason || `stream closed (${event.code})`;
      this.#fail(new Error(`The local microphone ${detail}.`));
    });
    this.startTimeout = window.setTimeout(() => {
      this.#fail(new Error("The local microphone stream did not start in time."));
    }, AUDIO_STREAM_TIMEOUT_MILLISECONDS);
    return startPromise;
  }

  push(samples) {
    if (this.stopping || this.failed || !(samples instanceof Float32Array)) return;
    if (samples.length) {
      this.partialChunks.push(samples);
      this.partialSampleCount += samples.length;
    }
    while (this.partialSampleCount >= AUDIO_STREAM_FRAME_SAMPLES) {
      this.#queueFrame(this.#takeSamples(AUDIO_STREAM_FRAME_SAMPLES));
    }
    this.#pump();
  }

  async reset(options = {}) {
    this.audioEpoch += 1;
    this.#clearPendingAudio();
    if (!this.started || this.stopping || this.failed) return;
    const token = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const acknowledgement = new Promise((resolve, reject) => {
      const timeout = window.setTimeout(() => {
        this.resetWaiters.delete(token);
        reject(new Error("The microphone stream reset timed out."));
      }, AUDIO_STREAM_TIMEOUT_MILLISECONDS);
      this.resetWaiters.set(token, { resolve, reject, timeout });
    });
    this.socket.send(JSON.stringify({ type: "reset", token, ...options }));
    await acknowledgement;
  }

  drainPendingSamples() {
    const chunks = this.frameQueue.map((frame) => frame.samples);
    chunks.push(...this.partialChunks);
    this.frameQueue = [];
    this.partialChunks = [];
    this.partialSampleCount = 0;
    return chunks.filter((chunk) => chunk.length);
  }

  stop() {
    if (this.stopping) return;
    this.stopping = true;
    window.clearTimeout(this.startTimeout);
    window.clearTimeout(this.inFlight?.timeout);
    window.clearTimeout(this.pumpTimer);
    this.#clearPendingAudio();
    for (const waiter of this.resetWaiters.values()) {
      window.clearTimeout(waiter.timeout);
      waiter.reject(new Error("The microphone stream stopped."));
    }
    this.resetWaiters.clear();
    this.startReject?.(new Error("The microphone stream stopped."));
    this.startResolve = null;
    this.startReject = null;
    if (this.socket
        && [WebSocket.CONNECTING, WebSocket.OPEN].includes(this.socket.readyState)) {
      this.socket.close(1000, "stopped");
    }
  }

  get queuedSampleCount() {
    return this.partialSampleCount
      + this.frameQueue.reduce((total, frame) => total + frame.samples.length, 0);
  }

  #queueFrame(samples) {
    if (this.frameQueue.length >= AUDIO_STREAM_MAX_QUEUED_FRAMES) {
      const [dropped] = this.frameQueue.splice(0, 1);
      this.onDrop({
        sequence: dropped.sequence,
        samples: dropped.samples.length,
        queuedFrames: this.frameQueue.length,
      });
    }
    this.frameQueue.push({
      sequence: this.sequence,
      audioEpoch: this.audioEpoch,
      samples,
      encoded: encodePcmStreamFrame(samples, this.sequence),
    });
    this.sequence = (this.sequence + 1) >>> 0;
  }

  #takeSamples(sampleCount) {
    const samples = new Float32Array(sampleCount);
    let written = 0;
    while (written < sampleCount) {
      const chunk = this.partialChunks[0];
      const copied = Math.min(chunk.length, sampleCount - written);
      samples.set(chunk.subarray(0, copied), written);
      written += copied;
      if (copied === chunk.length) this.partialChunks.shift();
      else this.partialChunks[0] = chunk.slice(copied);
    }
    this.partialSampleCount -= sampleCount;
    return samples;
  }

  #pump() {
    if (!this.started
        || this.stopping
        || this.failed
        || this.processingResult
        || this.inFlight
        || !this.frameQueue.length) return;
    if (this.socket.bufferedAmount > AUDIO_STREAM_MAX_BUFFERED_BYTES) {
      if (this.pumpTimer === null) {
        this.pumpTimer = window.setTimeout(() => {
          this.pumpTimer = null;
          this.#pump();
        }, 20);
      }
      return;
    }
    const frame = this.frameQueue.shift();
    frame.sentAt = performance.now();
    frame.timeout = window.setTimeout(() => {
      this.#fail(new Error("The local microphone stream stopped acknowledging audio."));
    }, AUDIO_STREAM_TIMEOUT_MILLISECONDS);
    this.inFlight = frame;
    this.socket.send(frame.encoded);
  }

  #handleMessage(event) {
    if (typeof event.data !== "string") {
      this.#fail(new Error("The local microphone stream returned invalid data."));
      return;
    }
    let message;
    try {
      message = JSON.parse(event.data);
    } catch {
      this.#fail(new Error("The local microphone stream returned invalid JSON."));
      return;
    }
    if (message.type === "started") {
      if (message.mode !== this.mode || message.sample_rate !== 16000) {
        this.#fail(new Error("The local microphone stream negotiated invalid settings."));
        return;
      }
      this.started = true;
      window.clearTimeout(this.startTimeout);
      this.startResolve?.(message);
      this.startResolve = null;
      this.startReject = null;
      this.#pump();
      return;
    }
    if (message.type === "reset") {
      const waiter = this.resetWaiters.get(message.token);
      if (!waiter) return;
      window.clearTimeout(waiter.timeout);
      this.resetWaiters.delete(message.token);
      waiter.resolve();
      return;
    }
    if (message.type !== "frame"
        || !this.inFlight
        || message.sequence !== this.inFlight.sequence) {
      this.#fail(new Error("The local microphone stream lost frame synchronization."));
      return;
    }
    const frame = this.inFlight;
    window.clearTimeout(frame.timeout);
    this.inFlight = null;
    this.processingResult = true;
    let result;
    try {
      result = frame.audioEpoch === this.audioEpoch
        ? this.onResult(message, {
          roundTripMilliseconds: performance.now() - frame.sentAt,
          queuedAudioMilliseconds: this.queuedSampleCount / 16,
        })
        : undefined;
    } catch (error) {
      this.#fail(error);
      return;
    }
    Promise.resolve(result).then(() => {
      this.processingResult = false;
      this.#pump();
    }).catch((error) => this.#fail(error));
  }

  #clearPendingAudio() {
    this.frameQueue = [];
    this.partialChunks = [];
    this.partialSampleCount = 0;
  }

  #fail(error) {
    if (this.failed || this.stopping) return;
    const hadStarted = this.started;
    this.failed = true;
    window.clearTimeout(this.startTimeout);
    window.clearTimeout(this.inFlight?.timeout);
    window.clearTimeout(this.pumpTimer);
    this.startReject?.(error);
    this.startResolve = null;
    this.startReject = null;
    if (this.socket
        && [WebSocket.CONNECTING, WebSocket.OPEN].includes(this.socket.readyState)) {
      this.socket.close(1011, "stream failed");
    }
    if (hadStarted) this.onError(error);
  }
}

window.GraniteAudioStreaming = {
  PcmWebSocketStream: PcmWebSocketStreamImplementation,
  encodePcmStreamFrame,
};
