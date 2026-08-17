// Wake-word detection, VAD capture, and follow-up listening.

function setWakeWordView(phase, { title, status, detail } = {}) {
  state.wakeWord.phase = phase;
  elements.wakeWordScreen.dataset.state = phase;
  if (title) elements.wakeWordTitle.textContent = title;
  if (status) elements.wakeWordStatus.textContent = status;
  if (detail) elements.wakeWordDetail.textContent = detail;
  const listening = phase === "listening";
  elements.wakePushButton.disabled = !["waiting", "listening"].includes(phase);
  elements.wakePushLabel.textContent = listening ? "Send now" : "Talk now";
  elements.wakePushButton.setAttribute(
    "aria-label",
    listening ? "Send the current spoken request" : "Start push-to-talk",
  );
  elements.wakeCancelButton.hidden = !listening;
}

function resetWakeWordFrameBuffer() {
  state.wakeWord.frameChunks = [];
  state.wakeWord.frameSampleCount = 0;
}

function tearDownWakeWordAudio() {
  const audio = state.wakeWord.audio;
  state.wakeWord.audio = null;
  if (!audio) return;
  audio.processor.onaudioprocess = null;
  for (const node of [audio.processor, audio.source, audio.silentGain]) {
    try {
      node.disconnect();
    } catch {
      // A browser may disconnect audio nodes automatically as the context closes.
    }
  }
  audio.stream.getTracks().forEach((track) => track.stop());
  const closing = audio.context.close();
  if (closing?.catch) closing.catch(() => {});
}

async function startWakeWordMode() {
  if (state.wakeWord.active || state.running || state.recorder) return;
  if (!state.capabilities.wake_word) {
    showToast("Restart the local UI server with --voice-io to enable wake-word mode");
    return;
  }
  const generation = state.wakeWord.generation + 1;
  state.wakeWord.generation = generation;
  state.wakeWord.sendingFrame = false;

  unlockResponsePlayback();
  if (!elements.wakeWordScreen.open) elements.wakeWordScreen.showModal();
  setWakeWordView("starting", {
    title: "Preparing wake mode",
    status: "Opening the local microphone…",
    detail: "Microphone samples remain on this device and are checked by the local wake-word model.",
  });

  const audioConstraint = state.settings.microphone_id === "default"
    ? true
    : { deviceId: { exact: state.settings.microphone_id } };
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraint });
    if (generation !== state.wakeWord.generation) {
      stream.getTracks().forEach((track) => track.stop());
      return;
    }
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContext();
    await context.resume();
    if (generation !== state.wakeWord.generation) {
      stream.getTracks().forEach((track) => track.stop());
      const closing = context.close();
      if (closing?.catch) closing.catch(() => {});
      return;
    }
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    state.wakeWord.audio = {
      stream,
      context,
      source,
      processor,
      silentGain,
      sourceRate: context.sampleRate,
    };
    state.wakeWord.active = true;
    tearDownVoiceCommandAudio();
    state.wakeWord.noiseFloor = 0.004;
    processor.onaudioprocess = handleWakeWordAudio;
    await requestJson(
      "/api/wake-word/start",
      { sensitivity: Number(state.settings.wake_word_sensitivity) },
      { timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS },
    );
    if (generation !== state.wakeWord.generation) return;
    resetWakeWordFrameBuffer();
    setWakeWordView("waiting", {
      title: "Say “Hey Jarvis”",
      status: "Listening for the wake phrase",
      detail: "After the chime-like visual changes, speak your request and pause when finished.",
    });
  } catch (error) {
    if (generation !== state.wakeWord.generation) return;
    state.wakeWord.active = false;
    tearDownWakeWordAudio();
    setWakeWordView("error", {
      title: "Wake mode unavailable",
      status: error.name === "NotAllowedError"
        ? "Microphone permission was not allowed"
        : error.message || "The local wake-word model could not start",
      detail: "Return to the conversation, check the microphone and local server, then try again.",
    });
  } finally {
    updateSendState();
  }
}

function stopWakeWordMode() {
  const wasActive = state.wakeWord.active;
  state.wakeWord.active = false;
  state.wakeWord.generation += 1;
  state.wakeWord.sendingFrame = false;
  state.wakeWord.phase = "inactive";
  resetWakeWordFrameBuffer();
  state.wakeWord.commandChunks = [];
  if (elements.wakeWordScreen.open) elements.wakeWordScreen.close();
  tearDownWakeWordAudio();
  if (voiceCommandContextActive()) {
    state.voiceCommands.serverActive = false;
    startVoiceCommandListening();
  }
  if (wasActive) {
    requestJson(
      "/api/wake-word/stop",
      {},
      {
        updateConnection: false,
        timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
      },
    ).catch(() => {
      // The microphone has already been stopped locally; health polling handles the server.
    });
  }
  updateSendState();
}

function handleWakeWordAudio(event) {
  if (!state.wakeWord.active) return;
  const sourceSamples = new Float32Array(event.inputBuffer.getChannelData(0));
  const samples = resampleAudio(
    sourceSamples,
    state.wakeWord.audio.sourceRate,
    16000,
  );
  const commandControlActive = voiceCommandContextActive();
  if (commandControlActive) enqueueVoiceCommandFrame(samples);
  if (state.wakeWord.phase === "waiting" && !commandControlActive) {
    enqueueWakeWordFrame(samples);
  }
  else if (state.wakeWord.phase === "listening") collectWakeCommand(samples);
}

function enqueueWakeWordFrame(samples) {
  const rms = rootMeanSquare(samples);
  state.wakeWord.noiseFloor = Math.min(
    0.03,
    state.wakeWord.noiseFloor * 0.97 + rms * 0.03,
  );
  state.wakeWord.frameChunks.push(samples);
  state.wakeWord.frameSampleCount += samples.length;
  flushWakeWordFrame();
}

async function flushWakeWordFrame() {
  if (!state.wakeWord.active
      || state.wakeWord.phase !== "waiting"
      || state.wakeWord.sendingFrame
      || state.wakeWord.frameSampleCount < WAKE_WORD_FRAME_SAMPLES) return;

  const samples = mergeAudioChunks(state.wakeWord.frameChunks);
  const generation = state.wakeWord.generation;
  const frame = samples.slice(0, WAKE_WORD_FRAME_SAMPLES);
  const remainder = samples.slice(WAKE_WORD_FRAME_SAMPLES);
  state.wakeWord.frameChunks = remainder.length ? [remainder] : [];
  state.wakeWord.frameSampleCount = remainder.length;
  state.wakeWord.sendingFrame = true;
  const frameSentAt = performance.now();
  try {
    const result = await requestJson(
      "/api/wake-word/frame",
      { pcm_base64: encodePcmBase64(frame) },
      {
        updateConnection: false,
        timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
      },
    );
    const detectionReceivedAt = performance.now();
    if (result.detected
        && state.wakeWord.active
        && generation === state.wakeWord.generation) {
      const preRollChunks = state.wakeWord.frameChunks;
      const bufferedAudioMs = state.wakeWord.frameSampleCount / 16;
      beginWakeCommand({
        preRollChunks,
        timing: {
          detectedAt: detectionReceivedAt,
          frameSentAt,
          wakeFrameMs: frame.length / 16,
          wakeRoundTripMs: detectionReceivedAt - frameSentAt,
          bufferedAudioMs,
        },
      });
    }
  } catch (error) {
    if (state.wakeWord.active && generation === state.wakeWord.generation) {
      state.wakeWord.active = false;
      tearDownWakeWordAudio();
      setWakeWordView("error", {
        title: "Wake mode stopped",
        status: error.message,
        detail: "Another tab may have taken over wake-word listening, or the local server may need attention.",
      });
    }
  } finally {
    if (generation === state.wakeWord.generation) {
      state.wakeWord.sendingFrame = false;
      if (state.wakeWord.phase === "waiting") flushWakeWordFrame();
    }
  }
}

function reportWakeTiming(event, metrics = {}) {
  const payload = { event };
  for (const [name, value] of Object.entries(metrics)) {
    if (Number.isFinite(value) && value >= 0) payload[name] = value;
  }
  console.debug("Granite wake timing", payload);
  requestJson(
    "/api/diagnostics/wake-timing",
    payload,
    {
      updateConnection: false,
      timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
    },
  ).catch(() => {
    // Timing diagnostics must never interfere with wake-word capture.
  });
}

function beginWakeCommand({ followUp = false, timing = null, preRollChunks = [] } = {}) {
  const captureStartedAt = performance.now();
  const capture = prepareWakeCapture({
    chunks: preRollChunks,
    sampleRate: 16000,
    captureStartedAt,
    deferSpeechArm: Boolean(timing) || followUp,
    armDelayMs: WAKE_COMMAND_ARM_DELAY_MILLISECONDS,
  });
  resetWakeWordFrameBuffer();
  state.wakeWord.commandChunks = capture.retainedChunks;
  state.wakeWord.commandStartedAt = capture.commandStartedAt;
  state.wakeWord.lastVoiceAt = captureStartedAt;
  state.wakeWord.speechArmedAt = capture.speechArmedAt;
  // Retain the wake handoff audio, but require speech to continue after the
  // detector responds. Otherwise the tail of “Jarvis” can submit by itself.
  state.wakeWord.voiceDetected = false;
  state.wakeWord.followUp = followUp;
  state.wakeWord.timing = timing;
  setWakeWordView("listening", {
    title: followUp ? "Anything else?" : "I’m listening",
    status: followUp ? "Listening for a follow-up" : "Speak your request",
    detail: followUp
      ? `Speak within ${state.settings.wake_follow_up_seconds} seconds, or cancel to return to the wake phrase.`
      : "Pause when you are finished, or press Send now. Granite responds locally.",
  });
  if (timing) {
    reportWakeTiming("command_capture_started", {
      wake_frame_ms: timing.wakeFrameMs,
      wake_round_trip_ms: timing.wakeRoundTripMs,
      buffered_audio_ms: timing.bufferedAudioMs,
      detection_to_capture_ms: captureStartedAt - timing.detectedAt,
    });
  }
}

function collectWakeCommand(samples) {
  state.wakeWord.commandChunks.push(samples);
  const now = performance.now();
  const rms = rootMeanSquare(samples);
  const speechThreshold = Math.max(0.012, state.wakeWord.noiseFloor * 3);
  if (speechCanStart({
    now,
    speechArmedAt: state.wakeWord.speechArmedAt,
    rms,
    speechThreshold,
  })) {
    if (!state.wakeWord.voiceDetected && state.wakeWord.timing) {
      reportWakeTiming("speech_started", {
        wake_to_speech_ms: now - state.wakeWord.timing.detectedAt,
        capture_elapsed_ms: now - state.wakeWord.commandStartedAt,
      });
    }
    state.wakeWord.voiceDetected = true;
    state.wakeWord.lastVoiceAt = now;
  }
  const elapsed = now - state.wakeWord.commandStartedAt;
  const silenceMilliseconds = state.settings.wake_end_pause_seconds * 1000;
  const maximumMilliseconds = state.settings.wake_max_request_seconds * 1000;
  const startTimeoutMilliseconds = state.wakeWord.followUp
    ? state.settings.wake_follow_up_seconds * 1000
    : WAKE_COMMAND_START_TIMEOUT_MILLISECONDS;
  if (state.wakeWord.voiceDetected
      && now - state.wakeWord.lastVoiceAt >= silenceMilliseconds) {
    finishWakeCommand();
  } else if (elapsed >= maximumMilliseconds) {
    finishWakeCommand();
  } else if (!state.wakeWord.voiceDetected
      && elapsed >= startTimeoutMilliseconds) {
    resumeWakeWordListening(state.wakeWord.followUp
      ? "Follow-up window ended. Listening for “Hey Jarvis”."
      : "I didn’t hear a request. Listening for “Hey Jarvis” again.");
  }
}

function rootMeanSquare(samples) {
  if (!samples.length) return 0;
  let sum = 0;
  for (const sample of samples) sum += sample * sample;
  return Math.sqrt(sum / samples.length);
}

async function finishWakeCommand({ force = false } = {}) {
  if (!state.wakeWord.active || state.wakeWord.phase !== "listening") return;
  const chunks = state.wakeWord.commandChunks;
  state.wakeWord.commandChunks = [];
  if ((!state.wakeWord.voiceDetected && !force) || !chunks.length) {
    resumeWakeWordListening("I didn’t hear a request. Listening for “Hey Jarvis” again.");
    return;
  }

  const timing = state.wakeWord.timing;
  if (timing) {
    const sampleCount = chunks.reduce((total, chunk) => total + chunk.length, 0);
    reportWakeTiming("command_finished", {
      capture_elapsed_ms: performance.now() - state.wakeWord.commandStartedAt,
      captured_audio_ms: sampleCount / 16,
      end_pause_target_ms: state.settings.wake_end_pause_seconds * 1000,
    });
  }

  setWakeWordView("thinking", {
    title: "Working on that",
    status: "Transcribing and thinking locally…",
    detail: "This can take a moment while the on-device models prepare the response.",
  });
  const samples = mergeAudioChunks(chunks);
  const response = await runTurn({ kind: "audio", wavBase64: encodeWavBase64(samples, 16000) });
  await waitForResponsePlayback();
  if (state.wakeWord.active) {
    if (response?.routine?.active) {
      setWakeWordView("routine", {
        title: "Guided routine",
        status: "Routine controls are listening",
        detail: "Say Pause, Continue, Next, Back, Repeat, Slower, Faster, or Stop.",
      });
    } else if (response && state.settings.wake_auto_follow_up) {
      beginWakeCommand({ followUp: true });
    } else if (response) {
      resumeWakeWordListening("Response complete. Listening for “Hey Jarvis”.");
    } else {
      resumeWakeWordListening("I couldn’t complete that. Listening for “Hey Jarvis”.");
    }
  }
}

function resumeWakeWordListening(status) {
  if (!state.wakeWord.active) return;
  state.wakeWord.commandChunks = [];
  state.wakeWord.followUp = false;
  state.wakeWord.timing = null;
  resetWakeWordFrameBuffer();
  setWakeWordView("waiting", {
    title: "Say “Hey Jarvis”",
    status,
    detail: "Granite listens only for the wake phrase until it activates again.",
  });
}

function waitForResponsePlayback() {
  return state.playback?.completion || Promise.resolve();
}


