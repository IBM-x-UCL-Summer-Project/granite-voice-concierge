// Push-to-talk capture and browser audio encoding.

async function startVoiceRecording() {
  if (state.recorderStarting || state.recorder) return;
  if (!state.capabilities.voice_input) {
    showToast("Restart the local UI server with --voice-io to enable speech input");
    return;
  }
  state.recorderStarting = true;
  updateSendState();
  const recorder = {
    capture: null,
    chunks: [],
    startedAt: performance.now(),
    maximumTimer: null,
  };
  try {
    diagnostics.info("push_to_talk_capture_starting", {
      microphone_id: state.settings.microphone_id,
    });
    recorder.capture = await openMicrophoneCapture({
      microphoneId: state.settings.microphone_id,
      purpose: "push_to_talk",
      onSamples: (samples) => recorder.chunks.push(samples),
      onEnded: () => {
        if (state.recorder === recorder) {
          showToast("Microphone input stopped");
          stopVoiceRecording({ submit: false, reason: "track_ended" });
        }
      },
    });
    state.recorder = recorder;
    recorder.maximumTimer = window.setTimeout(() => {
      if (state.recorder !== recorder) return;
      showToast("Maximum recording length reached; sending now");
      stopVoiceRecording({ reason: "maximum_duration" });
    }, PUSH_TO_TALK_MAXIMUM_MILLISECONDS);
    diagnostics.info("push_to_talk_capture_started", {
      sample_rate: MICROPHONE_TARGET_SAMPLE_RATE,
      maximum_duration_ms: PUSH_TO_TALK_MAXIMUM_MILLISECONDS,
    });
    elements.microphoneButton.classList.add("is-recording");
    elements.microphoneButton.setAttribute("aria-label", "Stop and send voice input");
    elements.microphoneButton.title = "Stop and send";
  } catch (error) {
    diagnostics.error("push_to_talk_capture_failed", {
      error_name: error.name,
      error_message: error.message,
    });
    showToast(error.name === "NotAllowedError"
      ? "Microphone permission was not allowed"
      : "The selected microphone is unavailable");
  } finally {
    state.recorderStarting = false;
    updateSendState();
  }
}

async function stopVoiceRecording({ submit = true, reason = "user" } = {}) {
  const recorder = state.recorder;
  if (!recorder) return;
  state.recorder = null;
  window.clearTimeout(recorder.maximumTimer);
  elements.microphoneButton.classList.remove("is-recording");
  elements.microphoneButton.setAttribute("aria-label", "Start voice input");
  elements.microphoneButton.title = "Start voice input";
  await recorder.capture.stop({ flush: submit });
  updateSendState();

  const samples = mergeAudioChunks(recorder.chunks);
  diagnostics.info("push_to_talk_capture_stopped", {
    capture_elapsed_ms: Math.round(performance.now() - recorder.startedAt),
    sample_rate: MICROPHONE_TARGET_SAMPLE_RATE,
    samples: samples.length,
    audio_seconds: Number(
      (samples.length / MICROPHONE_TARGET_SAMPLE_RATE).toFixed(3),
    ),
    reason,
    submitted: submit,
  });
  if (!submit) return;
  if (samples.length < MICROPHONE_TARGET_SAMPLE_RATE / 5) {
    diagnostics.warning("push_to_talk_capture_rejected", {
      reason: "too_short",
      samples: samples.length,
      minimum_samples: MICROPHONE_TARGET_SAMPLE_RATE / 5,
    });
    showToast("That recording was too short");
    return;
  }
  await runTurn({
    kind: "audio",
    wavBase64: encodeWavBase64(samples, MICROPHONE_TARGET_SAMPLE_RATE),
  });
}

function mergeAudioChunks(chunks) {
  const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
  const merged = new Float32Array(length);
  let offset = 0;
  chunks.forEach((chunk) => {
    merged.set(chunk, offset);
    offset += chunk.length;
  });
  return merged;
}

function encodeWavBase64(samples, sampleRate) {
  const buffer = new ArrayBuffer(44 + samples.length * 2);
  const view = new DataView(buffer);
  const writeString = (offset, value) => {
    for (let index = 0; index < value.length; index += 1) {
      view.setUint8(offset + index, value.charCodeAt(index));
    }
  };
  writeString(0, "RIFF");
  view.setUint32(4, 36 + samples.length * 2, true);
  writeString(8, "WAVE");
  writeString(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeString(36, "data");
  view.setUint32(40, samples.length * 2, true);
  samples.forEach((sample, index) => {
    const clipped = Math.max(-1, Math.min(1, sample));
    view.setInt16(44 + index * 2, clipped < 0 ? clipped * 0x8000 : clipped * 0x7fff, true);
  });
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let offset = 0; offset < bytes.length; offset += 0x8000) {
    binary += String.fromCharCode(...bytes.subarray(offset, offset + 0x8000));
  }
  return window.btoa(binary);
}
