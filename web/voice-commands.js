// Barge-in command streaming and guided-routine controls.

function voiceCommandCapabilityEnabled() {
  return Boolean(
    state.capabilities.playback_barge_in || state.capabilities.routine_barge_in,
  );
}

function voiceCommandContextActive() {
  return shouldListenForVoiceCommands({
    capabilityEnabled: voiceCommandCapabilityEnabled(),
    routineActive: state.routine.active,
    playbackActive: Boolean(state.playback),
  });
}

function resetVoiceCommandFrameBuffer() {
  state.voiceCommands.frameChunks = [];
  state.voiceCommands.frameSampleCount = 0;
}

function tearDownVoiceCommandAudio() {
  const audio = state.voiceCommands.audio;
  state.voiceCommands.audio = null;
  if (!audio) return;
  audio.processor.onaudioprocess = null;
  for (const node of [audio.processor, audio.source, audio.silentGain]) {
    try {
      node.disconnect();
    } catch {
      // Browsers may disconnect audio nodes while their context is closing.
    }
  }
  audio.stream.getTracks().forEach((track) => track.stop());
  const closing = audio.context.close();
  if (closing?.catch) closing.catch(() => {});
}

async function startVoiceCommandListening() {
  if (!voiceCommandContextActive()
      || state.voiceCommands.serverActive
      || state.voiceCommands.starting) return;
  state.voiceCommands.starting = true;
  const generation = state.voiceCommands.generation;
  try {
    await requestJson(
      "/api/routine-command/start",
      {},
      {
        updateConnection: false,
        timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
      },
    );
    state.voiceCommands.serverActive = true;
    resetVoiceCommandFrameBuffer();
    if (!voiceCommandContextActive()
        || generation !== state.voiceCommands.generation) {
      stopVoiceCommandListening();
      return;
    }
    if (state.wakeWord.active || state.voiceCommands.audio) return;

    const selectedDevice = state.settings.microphone_id === "default"
      ? {}
      : { deviceId: { exact: state.settings.microphone_id } };
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        ...selectedDevice,
        echoCancellation: true,
        noiseSuppression: true,
        autoGainControl: true,
      },
    });
    if (!voiceCommandContextActive()
        || generation !== state.voiceCommands.generation
        || state.wakeWord.active) {
      stream.getTracks().forEach((track) => track.stop());
      if (!voiceCommandContextActive()) stopVoiceCommandListening();
      return;
    }
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContext();
    await context.resume();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    state.voiceCommands.audio = {
      stream,
      context,
      source,
      processor,
      silentGain,
      sourceRate: context.sampleRate,
    };
    processor.onaudioprocess = (event) => {
      const samples = resampleAudio(
        new Float32Array(event.inputBuffer.getChannelData(0)),
        context.sampleRate,
        16000,
      );
      enqueueVoiceCommandFrame(samples);
    };
  } catch (error) {
    state.voiceCommands.serverActive = false;
    tearDownVoiceCommandAudio();
    showToast(error.name === "NotAllowedError"
      ? "Microphone access is needed for hands-free playback controls"
      : "Hands-free playback controls are unavailable");
  } finally {
    state.voiceCommands.starting = false;
  }
}

function stopVoiceCommandListening() {
  const wasServerActive = state.voiceCommands.serverActive;
  state.voiceCommands.generation += 1;
  state.voiceCommands.sendingFrame = false;
  resetVoiceCommandFrameBuffer();
  tearDownVoiceCommandAudio();
  state.voiceCommands.serverActive = false;
  if (!wasServerActive) return;
  requestJson(
    "/api/routine-command/stop",
    {},
    {
      updateConnection: false,
      timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
    },
  ).catch(() => {
    // Local state is already stopped; the server expires with the session.
  });
}

function syncVoiceCommandListening() {
  if (voiceCommandContextActive()) startVoiceCommandListening();
  else stopVoiceCommandListening();
}

function enqueueVoiceCommandFrame(samples) {
  if (!voiceCommandContextActive() || !state.voiceCommands.serverActive) return;
  if (state.routine.awaiting_confirmation
      && !state.routine.confirmationReady
      && !state.playback) return;
  state.voiceCommands.frameChunks.push(samples);
  state.voiceCommands.frameSampleCount += samples.length;
  flushVoiceCommandFrame();
}

async function flushVoiceCommandFrame() {
  if (!voiceCommandContextActive()
      || !state.voiceCommands.serverActive
      || state.voiceCommands.sendingFrame
      || state.voiceCommands.frameSampleCount < VOICE_COMMAND_FRAME_SAMPLES) return;
  const samples = mergeAudioChunks(state.voiceCommands.frameChunks);
  const generation = state.voiceCommands.generation;
  const frame = samples.slice(0, VOICE_COMMAND_FRAME_SAMPLES);
  const remainder = samples.slice(VOICE_COMMAND_FRAME_SAMPLES);
  state.voiceCommands.frameChunks = remainder.length ? [remainder] : [];
  state.voiceCommands.frameSampleCount = remainder.length;
  state.voiceCommands.sendingFrame = true;
  try {
    const result = await requestJson(
      "/api/routine-command/frame",
      { pcm_base64: encodePcmBase64(frame) },
      {
        updateConnection: false,
        timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
      },
    );
    if (result.command
        && voiceCommandContextActive()
        && generation === state.voiceCommands.generation) {
      if (state.routine.active) await handleRoutineVoiceCommand(result.command);
      else await handlePlaybackVoiceCommand(result.command);
    }
  } catch {
    if (generation === state.voiceCommands.generation) {
      state.voiceCommands.serverActive = false;
      tearDownVoiceCommandAudio();
      showToast("Hands-free playback controls stopped");
    }
  } finally {
    if (generation === state.voiceCommands.generation) {
      state.voiceCommands.sendingFrame = false;
      flushVoiceCommandFrame();
    }
  }
}

async function handlePlaybackVoiceCommand(command) {
  if (!state.playback || !isPlaybackBargeInCommand(command)) return;
  resetVoiceCommandFrameBuffer();
  if (command === "stop") {
    stopPlayback();
    showToast("Response stopped");
  } else if (command === "pause") {
    if (pausePlayback()) showToast("Response paused — say Continue to resume");
  } else if (await resumePlayback()) {
    showToast("Response resumed");
  }
}

async function handleRoutineVoiceCommand(command) {
  if (state.routine.awaiting_confirmation) {
    if (!state.routine.confirmationReady || !["yes", "no"].includes(command)) {
      return;
    }
  } else if (["yes", "no"].includes(command)) {
    return;
  }
  resetVoiceCommandFrameBuffer();
  cancelRoutineAutoAdvance();
  stopPlayback();
  const deadline = performance.now() + 1500;
  while (state.running && performance.now() < deadline) await delay(20);
  if (state.running) {
    showToast("Routine control is still processing; please try again");
    return;
  }
  await runTurn(command, {
    routineControl: true,
    suppressPlayback: command === "pause",
  });
}

function cancelRoutineAutoAdvance() {
  state.routine.autoGeneration += 1;
  if (state.routine.autoTimer !== null) {
    window.clearTimeout(state.routine.autoTimer);
    state.routine.autoTimer = null;
  }
  if (state.routine.confirmationTimer !== null) {
    window.clearTimeout(state.routine.confirmationTimer);
    state.routine.confirmationTimer = null;
  }
  state.routine.confirmationReady = false;
}

function syncRoutineState(routine) {
  cancelRoutineAutoAdvance();
  const previousActive = state.routine.active;
  const next = routine || { active: false };
  state.routine = {
    ...state.routine,
    ...next,
    active: Boolean(next.active),
  };
  if (Number.isFinite(next.pace_delta)) {
    state.settings.speech_rate = Math.max(
      0.6,
      Math.min(1.6, Number(state.settings.speech_rate) + Number(next.pace_delta)),
    );
    window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(state.settings));
    showToast(`Routine speech rate ${state.settings.speech_rate.toFixed(1)}×`);
  }
  if (state.routine.active) {
    syncVoiceCommandListening();
    if (state.wakeWord.active) {
      setWakeWordView("routine", {
        title: "Guided routine",
        status: state.routine.status === "paused"
          ? "Paused — say Continue when ready"
          : "Say Pause, Next, Back, Repeat, Slower, Faster, or Stop",
        detail: "Routine control words work without saying the wake word.",
      });
    }
  } else if (previousActive || state.voiceCommands.serverActive) {
    syncVoiceCommandListening();
    if (state.wakeWord.active) {
      resumeWakeWordListening("Routine finished. Listening for “Hey Jarvis”.");
    }
  }
}

function scheduleRoutineAutoAdvance() {
  if (!state.routine.active
      || state.routine.status !== "running"
      || state.routine.awaiting_choice
      || state.routine.awaiting_confirmation) return;
  const generation = state.routine.autoGeneration;
  const delayMilliseconds = Number(state.routine.auto_advance_seconds || 6) * 1000;
  waitForResponsePlayback().then(() => {
    if (generation !== state.routine.autoGeneration
        || !state.routine.active
        || state.routine.status !== "running") return;
    state.routine.autoTimer = window.setTimeout(() => {
      state.routine.autoTimer = null;
      if (generation === state.routine.autoGeneration && !state.running) {
        runTurn("next", { routineControl: true, automatic: true });
      }
    }, delayMilliseconds);
  });
}

function armRoutineConfirmationWindow() {
  if (!state.capabilities.routine_barge_in
      || !state.routine.active
      || !state.routine.awaiting_confirmation) return;
  const generation = state.routine.autoGeneration;
  waitForResponsePlayback().then(() => {
    if (generation !== state.routine.autoGeneration
        || !state.routine.awaiting_confirmation) return;
    state.routine.confirmationTimer = window.setTimeout(async () => {
      state.routine.confirmationTimer = null;
      if (generation !== state.routine.autoGeneration) return;
      resetVoiceCommandFrameBuffer();
      try {
        await requestJson(
          "/api/routine-command/reset",
          {},
          {
            updateConnection: false,
            timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
          },
        );
        if (generation === state.routine.autoGeneration) {
          state.routine.confirmationReady = true;
        }
      } catch {
        showToast("Say yes through push-to-talk or use the confirmation buttons");
      }
    }, 500);
  });
}


