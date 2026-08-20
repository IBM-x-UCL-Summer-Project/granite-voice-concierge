// Shared permission, constraint, AudioWorklet, and microphone lifecycle logic.

const MICROPHONE_TARGET_SAMPLE_RATE = 16000;
const MICROPHONE_WORKLET_CHUNK_SAMPLES = 320;
const MICROPHONE_FLUSH_TIMEOUT_MILLISECONDS = 1000;
const MICROPHONE_WORKLET_URL = "./audio-capture-worklet.mjs?v=20260820-1";

function buildMicrophoneConstraints(microphoneId) {
  const supported = navigator.mediaDevices.getSupportedConstraints?.() || null;
  const recognizes = (name) => supported === null || supported[name] === true;
  const audio = {};
  if (microphoneId !== "default" && recognizes("deviceId")) {
    audio.deviceId = { exact: microphoneId };
  }
  for (const [name, value] of Object.entries({
    channelCount: { ideal: 1 },
    echoCancellation: true,
    noiseSuppression: true,
    autoGainControl: true,
  })) {
    if (recognizes(name)) audio[name] = value;
  }
  return { audio };
}

function microphoneSettings(track, context, requestedConstraints) {
  const settings = track.getSettings?.() || {};
  return {
    requested_constraints: requestedConstraints.audio,
    device_id: settings.deviceId || null,
    channel_count: settings.channelCount || null,
    track_sample_rate: settings.sampleRate || null,
    context_sample_rate: context.sampleRate,
    echo_cancellation: settings.echoCancellation ?? null,
    noise_suppression: settings.noiseSuppression ?? null,
    auto_gain_control: settings.autoGainControl ?? null,
  };
}

async function openMicrophoneCapture({
  microphoneId,
  purpose,
  onSamples,
  onEnded = () => {},
  onStateChange = () => {},
}) {
  if (!navigator.mediaDevices?.getUserMedia) {
    throw new DOMException(
      "Microphone capture is unavailable in this browser or origin.",
      "NotSupportedError",
    );
  }
  const resources = {
    stream: null,
    context: null,
    source: null,
    worklet: null,
    silentGain: null,
  };
  let stopping = false;
  let acceptingSamples = true;
  let stopPromise = null;
  const constraints = buildMicrophoneConstraints(microphoneId);

  const disconnect = () => {
    for (const node of [resources.source, resources.worklet, resources.silentGain]) {
      try {
        node?.disconnect();
      } catch {
        // Context shutdown may disconnect graph nodes first.
      }
    }
  };

  const closeResources = async () => {
    disconnect();
    resources.stream?.getTracks().forEach((track) => track.stop());
    if (resources.context && resources.context.state !== "closed") {
      try {
        await resources.context.close();
      } catch {
        // The browser may close an interrupted context itself.
      }
    }
  };

  const flushWorklet = () => new Promise((resolve) => {
    if (!resources.worklet) {
      resolve();
      return;
    }
    const token = crypto.randomUUID?.() || `${Date.now()}-${Math.random()}`;
    const timeout = window.setTimeout(() => {
      resources.worklet.port.removeEventListener("message", handleFlush);
      diagnostics.warning("microphone_capture_flush_timeout", { purpose });
      resolve();
    }, MICROPHONE_FLUSH_TIMEOUT_MILLISECONDS);
    const handleFlush = (event) => {
      if (event.data?.type !== "flushed" || event.data.token !== token) return;
      window.clearTimeout(timeout);
      resources.worklet.port.removeEventListener("message", handleFlush);
      resolve();
    };
    resources.worklet.port.addEventListener("message", handleFlush);
    resources.worklet.port.postMessage({ type: "flush", token });
  });

  const capture = {
    get contextState() {
      return resources.context?.state || "closed";
    },
    get settings() {
      const track = resources.stream?.getAudioTracks()[0];
      return track && resources.context
        ? microphoneSettings(track, resources.context, constraints)
        : null;
    },
    async resume() {
      if (!stopping && resources.context?.state === "suspended") {
        await resources.context.resume();
      }
    },
    stop({ flush = true } = {}) {
      if (stopPromise) return stopPromise;
      stopping = true;
      stopPromise = (async () => {
        if (flush) await flushWorklet();
        acceptingSamples = false;
        await closeResources();
        diagnostics.info("microphone_capture_stopped", { purpose });
      })();
      return stopPromise;
    },
  };

  try {
    diagnostics.info("microphone_capture_starting", {
      purpose,
      microphone_id: microphoneId,
      requested_constraints: constraints.audio,
    });
    resources.stream = await navigator.mediaDevices.getUserMedia(constraints);
    const [track] = resources.stream.getAudioTracks();
    if (!track) throw new DOMException("No microphone track was returned.", "NotFoundError");

    const AudioContext = window.AudioContext || window.webkitAudioContext;
    if (!AudioContext || !window.AudioWorkletNode) {
      throw new DOMException(
        "AudioWorklet microphone capture is unavailable in this browser.",
        "NotSupportedError",
      );
    }
    resources.context = new AudioContext({ latencyHint: "interactive" });
    await resources.context.audioWorklet.addModule(
      new URL(MICROPHONE_WORKLET_URL, window.location.href),
    );
    resources.source = resources.context.createMediaStreamSource(resources.stream);
    resources.worklet = new AudioWorkletNode(
      resources.context,
      "granite-pcm-capture",
      {
        channelCount: 1,
        channelCountMode: "explicit",
        numberOfInputs: 1,
        numberOfOutputs: 1,
        outputChannelCount: [1],
        processorOptions: {
          targetSampleRate: MICROPHONE_TARGET_SAMPLE_RATE,
          outputChunkSamples: MICROPHONE_WORKLET_CHUNK_SAMPLES,
        },
      },
    );
    resources.silentGain = resources.context.createGain();
    resources.silentGain.gain.value = 0;
    resources.worklet.port.addEventListener("message", (event) => {
      if (event.data?.type !== "samples" || !acceptingSamples) return;
      try {
        onSamples(event.data.samples);
      } catch (error) {
        diagnostics.error("microphone_capture_consumer_failed", {
          purpose,
          error_name: error.name,
          error_message: error.message,
        });
      }
    });
    resources.worklet.port.start();
    track.addEventListener("ended", () => {
      if (stopping) return;
      diagnostics.warning("microphone_track_ended", { purpose });
      onEnded();
      capture.stop({ flush: false });
    });
    resources.context.addEventListener("statechange", () => {
      const contextState = resources.context.state;
      diagnostics.info("microphone_context_state_changed", {
        purpose,
        state: contextState,
      });
      if (!stopping) onStateChange(contextState);
    });
    resources.source.connect(resources.worklet);
    resources.worklet.connect(resources.silentGain);
    resources.silentGain.connect(resources.context.destination);
    await resources.context.resume();
    diagnostics.info("microphone_capture_started", {
      purpose,
      ...microphoneSettings(track, resources.context, constraints),
    });
    return capture;
  } catch (error) {
    stopping = true;
    acceptingSamples = false;
    await closeResources();
    diagnostics.error("microphone_capture_failed", {
      purpose,
      error_name: error.name,
      error_message: error.message,
    });
    throw error;
  }
}

function resumeActiveMicrophoneCaptures() {
  const captures = [
    state.recorder?.capture,
    state.wakeWord.audio,
    state.voiceCommands.audio,
  ].filter(Boolean);
  return Promise.allSettled(captures.map((capture) => capture.resume()));
}
