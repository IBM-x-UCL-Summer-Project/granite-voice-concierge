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
  state.voiceCommands.stream?.drainPendingSamples();
}

function tearDownVoiceCommandAudio() {
  const audio = state.voiceCommands.audio;
  state.voiceCommands.audio = null;
  if (!audio) return;
  audio.stop({ flush: false }).catch(() => {});
}

async function startVoiceCommandListening() {
  if (!voiceCommandContextActive()
      || state.voiceCommands.serverActive
      || state.voiceCommands.starting) return;
  state.voiceCommands.starting = true;
  const generation = state.voiceCommands.generation;
  diagnostics.debug("voice_command_listener_starting", {
    generation,
    routine_active: state.routine.active,
    playback_active: Boolean(state.playback),
    wake_word_active: state.wakeWord.active,
  });
  try {
    const stream = new PcmWebSocketStream({
      mode: "voice_command",
      onResult: handleVoiceCommandStreamResult,
      onError: (error) => {
        if (generation !== state.voiceCommands.generation) return;
        diagnostics.error("voice_command_stream_failed", {
          generation,
          error_message: error.message,
        });
        showToast("Hands-free playback controls stopped");
        stopVoiceCommandListening();
      },
      onDrop: (event) => diagnostics.warning("voice_command_frame_dropped", event),
    });
    state.voiceCommands.stream = stream;
    await stream.start();
    state.voiceCommands.serverActive = true;
    diagnostics.info("voice_command_backend_started", {
      generation,
      transport: "binary_websocket",
    });
    resetVoiceCommandFrameBuffer();
    if (!voiceCommandContextActive()
        || generation !== state.voiceCommands.generation) {
      stopVoiceCommandListening();
      return;
    }
    if (state.wakeWord.active || state.voiceCommands.audio) return;

    const audio = await openMicrophoneCapture({
      microphoneId: state.settings.microphone_id,
      purpose: "voice_command",
      onSamples: enqueueVoiceCommandFrame,
      onEnded: () => {
        if (generation !== state.voiceCommands.generation) return;
        showToast("Hands-free playback controls stopped");
        stopVoiceCommandListening();
      },
      onStateChange: (contextState) => {
        if (contextState === "suspended" && voiceCommandContextActive()) {
          diagnostics.warning("voice_command_microphone_suspended", { generation });
        }
      },
    });
    if (!voiceCommandContextActive()
        || generation !== state.voiceCommands.generation
        || state.wakeWord.active) {
      await audio.stop({ flush: false });
      if (!voiceCommandContextActive()) stopVoiceCommandListening();
      return;
    }
    state.voiceCommands.audio = audio;
    diagnostics.info("voice_command_microphone_started", {
      generation,
      sample_rate: MICROPHONE_TARGET_SAMPLE_RATE,
      microphone_id: state.settings.microphone_id,
      settings: audio.settings,
    });
  } catch (error) {
    const backendWasActive = state.voiceCommands.serverActive;
    stopVoiceCommandListening();
    if (!backendWasActive) state.voiceCommands.serverActive = false;
    diagnostics.error("voice_command_listener_failed", {
      generation,
      error_name: error.name,
      error_message: error.message,
      stack: error.stack || null,
    });
    showToast(error.name === "NotAllowedError"
      ? "Microphone access is needed for hands-free playback controls"
      : "Hands-free playback controls are unavailable");
  } finally {
    state.voiceCommands.starting = false;
  }
}

function stopVoiceCommandListening() {
  const wasServerActive = state.voiceCommands.serverActive;
  const stream = state.voiceCommands.stream;
  state.voiceCommands.generation += 1;
  resetVoiceCommandFrameBuffer();
  tearDownVoiceCommandAudio();
  state.voiceCommands.stream = null;
  stream?.stop();
  state.voiceCommands.serverActive = false;
  diagnostics.info("voice_command_listener_stopped", {
    generation: state.voiceCommands.generation,
    server_was_active: wasServerActive,
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
  state.voiceCommands.stream?.push(samples);
}

async function handleVoiceCommandStreamResult(result) {
  const generation = state.voiceCommands.generation;
  if (!result.command
      || !voiceCommandContextActive()
      || generation !== state.voiceCommands.generation) return;
  diagnostics.info("voice_command_detected", {
    command: result.command,
    phrase: result.phrase,
    confidence: result.confidence,
    server_processing_ms: result.processing_ms,
    target: state.routine.active ? "routine" : "playback",
  });
  if (state.routine.active) await handleRoutineVoiceCommand(result.command);
  else await handlePlaybackVoiceCommand(result.command);
}

async function handlePlaybackVoiceCommand(command) {
  if (!state.playback || !isPlaybackBargeInCommand(command)) return;
  resetVoiceCommandFrameBuffer();
  if (command === "stop") {
    stopPlayback({ reason: "voice_command" });
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
  diagnostics.info("routine_voice_command", {
    command,
    status: state.routine.status,
    awaiting_confirmation: state.routine.awaiting_confirmation,
  });
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
  diagnostics.info("routine_state_updated", {
    previous_active: previousActive,
    routine: next,
  });
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
        await state.voiceCommands.stream?.reset();
        if (generation === state.routine.autoGeneration) {
          state.routine.confirmationReady = true;
        }
      } catch {
        showToast("Say yes through push-to-talk or use the confirmation buttons");
      }
    }, 500);
  });
}
