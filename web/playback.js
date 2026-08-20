// Speech playback, automatic-playback policy, and playback controls.

function effectiveSpeechRate(settings, includePipelinePace = true) {
  const pipelineFactor = includePipelinePace
    && state.pipeline.context.accessibility.speech_pace === "slow"
    ? 0.8
    : 1;
  return Number(settings.speech_rate) * pipelineFactor;
}

let cachedLocalBrowserVoice = null;

function localBrowserSpeechVoice() {
  if (!("speechSynthesis" in window)
      || typeof window.SpeechSynthesisUtterance !== "function") {
    return null;
  }
  const localVoices = window.speechSynthesis.getVoices()
    .filter((voice) => voice.localService);
  cachedLocalBrowserVoice = localVoices.find(
    (voice) => voice.default && voice.lang.toLowerCase().startsWith("en"),
  ) || localVoices.find((voice) => voice.lang.toLowerCase().startsWith("en"))
    || localVoices.find((voice) => voice.default)
    || localVoices[0]
    || null;
  return cachedLocalBrowserVoice;
}

function browserSpeechAvailable() {
  return Boolean(localBrowserSpeechVoice());
}

function playbackIdleLabel(button) {
  return button?.dataset.playbackIdleLabel || (state.capabilities.voice_output
    ? "Play response"
    : "Play browser voice");
}

function playbackActiveLabel(button) {
  return button?.dataset.playbackActiveLabel || "Stop response";
}

function setPlaybackButtonLabel(button, label) {
  if (!button) return;
  button.setAttribute("aria-label", label);
  button.lastChild.textContent = ` ${label}`;
}

if ("speechSynthesis" in window) {
  localBrowserSpeechVoice();
  window.speechSynthesis.addEventListener?.("voiceschanged", localBrowserSpeechVoice);
}

async function speakText(
  text,
  settings = state.settings,
  includePipelinePace = settings === state.settings,
  button = null,
) {
  const browserVoice = localBrowserSpeechVoice();
  if (!browserVoice) {
    showToast("No offline browser voice is available on this device");
    return;
  }
  stopPlayback({ preserveVoiceCommands: true });
  const utterance = new window.SpeechSynthesisUtterance(text);
  utterance.voice = browserVoice;
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
  diagnostics.info("playback_prepared", {
    kind: "browser_speech",
    text,
    voice: browserVoice.name,
    language: browserVoice.lang,
    speech_rate: utterance.rate,
    volume: utterance.volume,
  });
  if (button) {
    button.classList.add("is-playing");
    setPlaybackButtonLabel(button, playbackActiveLabel(button));
  }
  utterance.onend = () => {
    if (state.playback === playback) stopPlayback({ reason: "natural_completion" });
  };
  utterance.onerror = (event) => {
    diagnostics.error("browser_speech_failed", {
      error: event.error || "unknown",
    });
    showToast("Browser voice playback failed; the response is still available as text");
    if (state.playback === playback) stopPlayback({ reason: "browser_speech_error" });
  };
  await startVoiceCommandListening();
  window.speechSynthesis.speak(utterance);
  diagnostics.info("playback_started", { kind: "browser_speech" });
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

function stopPlayback({ preserveVoiceCommands = false, reason = "requested" } = {}) {
  const playback = state.playback;
  if (!playback) {
    window.speechSynthesis?.cancel();
    return;
  }
  state.playback = null;
  const positionSeconds = playback.kind === "audio"
    ? playback.audio.currentTime
    : null;
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
  setPlaybackButtonLabel(playback.button, playbackIdleLabel(playback.button));
  playback.resolveCompletion?.();
  diagnostics.info("playback_stopped", {
    kind: playback.kind,
    reason,
    position_seconds: positionSeconds,
  });
  if (!preserveVoiceCommands) syncVoiceCommandListening();
}

function pausePlayback() {
  const playback = state.playback;
  if (!playback || playback.paused) return false;
  if (playback.kind === "speech") window.speechSynthesis.pause();
  else playback.audio.pause();
  playback.paused = true;
  setPlaybackButtonLabel(playback.button, "Resume response");
  diagnostics.info("playback_paused", {
    kind: playback.kind,
    position_seconds: playback.kind === "audio" ? playback.audio.currentTime : null,
  });
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
  setPlaybackButtonLabel(playback.button, playbackActiveLabel(playback.button));
  diagnostics.info("playback_resumed", {
    kind: playback.kind,
    position_seconds: playback.kind === "audio" ? playback.audio.currentTime : null,
  });
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

async function playResponse(
  button,
  settings = state.settings,
  includePipelinePace = settings === state.settings,
) {
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
    await speakText(
      button.fallbackText || "",
      settings,
      includePipelinePace,
      button,
    );
    return;
  }

  const binary = window.atob(audioPayload.wav_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  const audio = state.responseAudioElement || new Audio();
  state.responseAudioElement = audio;
  audio.muted = false;
  audio.src = url;
  audio.volume = Number(settings.volume) / 100;
  audio.playbackRate = effectiveSpeechRate(settings, includePipelinePace);
  if (settings.speaker_id !== "default" && typeof audio.setSinkId === "function") {
    try {
      await audio.setSinkId(settings.speaker_id);
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
  diagnostics.info("playback_prepared", {
    kind: "piper_audio",
    wav_base64_characters: audioPayload.wav_base64.length,
    volume: audio.volume,
    playback_rate: audio.playbackRate,
  });
  button.classList.add("is-playing");
  setPlaybackButtonLabel(button, playbackActiveLabel(button));
  audio.onended = () => {
    if (state.playback === playback) stopPlayback({ reason: "natural_completion" });
  };
  audio.onerror = () => {
    if (state.playback === playback) stopPlayback({ reason: "audio_error" });
  };
  try {
    await startVoiceCommandListening();
    await audio.play();
    diagnostics.info("playback_started", { kind: "piper_audio" });
  } catch {
    stopPlayback({ reason: "autoplay_blocked" });
    showToast("Automatic playback was blocked; choose Play response to retry");
  }
}

function shouldAutoPlayResponse(response, isAudioTurn) {
  const ttsFailed = Array.isArray(response?.errors)
    && response.errors.includes("tts_failed");
  return playbackPolicyAllows({
    voiceOutput: state.capabilities.voice_output,
    audioAvailable: Boolean(response?.audio?.wav_base64),
    browserFallbackAvailable: ttsFailed && browserSpeechAvailable(),
    confirmationRequired: Boolean(confirmationKind(response)),
    speakConfirmations: state.settings.speak_confirmations,
    interactionMode: state.wakeWord.active
      ? "wake_word"
      : state.settings.interaction_mode,
    isAudioTurn,
  });
}
