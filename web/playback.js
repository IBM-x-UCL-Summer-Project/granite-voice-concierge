// Speech playback, automatic-playback policy, and playback controls.

function effectiveSpeechRate(settings, includePipelinePace = true) {
  const pipelineFactor = includePipelinePace
    && state.pipeline.context.accessibility.speech_pace === "slow"
    ? 0.8
    : 1;
  return Number(settings.speech_rate) * pipelineFactor;
}

async function speakText(
  text,
  settings = state.settings,
  includePipelinePace = settings === state.settings,
  button = null,
) {
  if (!("speechSynthesis" in window)) {
    showToast("Voice preview is unavailable in this browser");
    return;
  }
  stopPlayback({ preserveVoiceCommands: true });
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = effectiveSpeechRate(settings, includePipelinePace);
  utterance.volume = Number(settings.volume) / 100;
  let resolveCompletion;
  const completion = new Promise((resolve) => {
    resolveCompletion = resolve;
  });
  const playback = {
    kind: "speech",
    utterance,
    button,
    completion,
    resolveCompletion,
    paused: false,
  };
  state.playback = playback;
  if (button) {
    button.classList.add("is-playing");
    button.setAttribute("aria-label", "Stop assistant response");
    button.lastChild.textContent = " Stop response";
  }
  utterance.onend = () => {
    if (state.playback === playback) stopPlayback();
  };
  utterance.onerror = () => {
    if (state.playback === playback) stopPlayback();
  };
  await startVoiceCommandListening();
  window.speechSynthesis.speak(utterance);
}


function confirmationKind(response) {
  if (response.state?.pending_bulk_memory_delete) return "bulk-memory-delete";
  if (response.routine?.awaiting_confirmation) return "routine";
  if (response.context?.needs_confirmation || response.state?.context?.pending_mode) {
    return "mode";
  }
  if (response.reasoning?.proposed_memory_action?.requires_confirmation) return "memory";
  if (response.state?.pending_memory_action) return "memory";
  return null;
}

function stopPlayback({ preserveVoiceCommands = false } = {}) {
  const playback = state.playback;
  if (!playback) {
    window.speechSynthesis?.cancel();
    return;
  }
  state.playback = null;
  if (playback.kind === "speech") {
    playback.utterance.onend = null;
    playback.utterance.onerror = null;
    window.speechSynthesis?.cancel();
  } else {
    playback.audio.onended = null;
    playback.audio.onerror = null;
    playback.audio.pause();
    playback.audio.currentTime = 0;
    URL.revokeObjectURL(playback.url);
  }
  playback.button?.classList.remove("is-playing");
  if (playback.button) {
    playback.button.setAttribute("aria-label", "Play assistant response");
    playback.button.lastChild.textContent = state.capabilities.voice_output
      ? " Play response"
      : " Play browser voice";
  }
  playback.resolveCompletion?.();
  if (!preserveVoiceCommands) syncVoiceCommandListening();
}

function pausePlayback() {
  const playback = state.playback;
  if (!playback || playback.paused) return false;
  if (playback.kind === "speech") window.speechSynthesis.pause();
  else playback.audio.pause();
  playback.paused = true;
  if (playback.button) {
    playback.button.setAttribute("aria-label", "Resume assistant response");
    playback.button.lastChild.textContent = " Resume response";
  }
  return true;
}

async function resumePlayback() {
  const playback = state.playback;
  if (!playback || !playback.paused) return false;
  if (playback.kind === "speech") {
    window.speechSynthesis.resume();
  } else {
    try {
      await playback.audio.play();
    } catch {
      stopPlayback();
      showToast("Playback could not resume; choose Play response to retry");
      return false;
    }
  }
  playback.paused = false;
  if (playback.button) {
    playback.button.setAttribute("aria-label", "Stop assistant response");
    playback.button.lastChild.textContent = " Stop response";
  }
  return true;
}

function unlockResponsePlayback() {
  if (!state.capabilities.voice_output || state.responseAudioElement) return;

  const audio = new Audio(SILENT_WAV_URL);
  audio.muted = true;
  state.responseAudioElement = audio;
  const unlock = audio.play();
  if (!unlock?.then) {
    audio.muted = false;
    return;
  }
  unlock.then(() => {
    if (state.playback?.audio === audio) return;
    audio.pause();
    audio.currentTime = 0;
    audio.muted = false;
  }).catch(() => {
    if (state.playback?.audio === audio) return;
    if (state.responseAudioElement === audio) state.responseAudioElement = null;
  });
}

async function playResponse(button) {
  if (state.playback?.button === button) {
    if (state.playback.paused) {
      await resumePlayback();
      return;
    }
    stopPlayback();
    return;
  }
  stopPlayback({ preserveVoiceCommands: true });
  const audioPayload = button.responseAudio;
  if (!audioPayload?.wav_base64) {
    showToast(state.capabilities.voice_output
      ? "Piper audio is unavailable for this response; using the browser voice"
      : "Using the browser voice; start the server with --voice-io for Piper");
    await speakText(button.fallbackText || "", state.settings, true, button);
    return;
  }

  const binary = window.atob(audioPayload.wav_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  const audio = state.responseAudioElement || new Audio();
  state.responseAudioElement = audio;
  audio.muted = false;
  audio.src = url;
  audio.volume = Number(state.settings.volume) / 100;
  audio.playbackRate = effectiveSpeechRate(state.settings);
  if (state.settings.speaker_id !== "default" && typeof audio.setSinkId === "function") {
    try {
      await audio.setSinkId(state.settings.speaker_id);
    } catch {
      showToast("The selected speaker is unavailable; using the system default");
    }
  }
  let resolveCompletion;
  const completion = new Promise((resolve) => {
    resolveCompletion = resolve;
  });
  const playback = {
    kind: "audio",
    audio,
    button,
    url,
    completion,
    resolveCompletion,
    paused: false,
  };
  state.playback = playback;
  button.classList.add("is-playing");
  button.setAttribute("aria-label", "Stop assistant response");
  button.lastChild.textContent = " Stop response";
  audio.onended = () => {
    if (state.playback === playback) stopPlayback();
  };
  audio.onerror = () => {
    if (state.playback === playback) stopPlayback();
  };
  try {
    await startVoiceCommandListening();
    await audio.play();
  } catch {
    stopPlayback();
    showToast("Automatic playback was blocked; choose Play response to retry");
  }
}

function shouldAutoPlayResponse(response, isAudioTurn) {
  return playbackPolicyAllows({
    voiceOutput: state.capabilities.voice_output,
    audioAvailable: Boolean(response?.audio?.wav_base64),
    confirmationRequired: Boolean(confirmationKind(response)),
    speakConfirmations: state.settings.speak_confirmations,
    interactionMode: state.wakeWord.active
      ? "wake_word"
      : state.settings.interaction_mode,
    isAudioTurn,
  });
}


