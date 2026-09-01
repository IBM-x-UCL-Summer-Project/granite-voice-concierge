// Turn orchestration, session state, and backend connection lifecycle.

async function runTurn(
  input,
  { routineControl = false, automatic = false, suppressPlayback = false } = {},
) {
  if (state.running) return;
  const isAudio = typeof input === "object" && input.kind === "audio";
  const transcript = isAudio ? "" : String(input || "").trim();
  if (!isAudio && !transcript) return;

  const turnStartedAt = performance.now();
  diagnostics.info("turn_started", {
    input_kind: isAudio ? "audio" : "text",
    transcript: isAudio ? null : transcript,
    audio_base64_characters: isAudio ? input.wavBase64.length : 0,
    routine_control: routineControl,
    automatic,
    suppress_playback: suppressPlayback,
  });

  unlockResponsePlayback();
  state.running = true;
  if (!isAudio && !automatic) {
    elements.input.value = "";
    autoSizeInput();
    appendMessage("user", transcript);
  }
  appendPendingMessage(isAudio ? "Transcribing and thinking locally" : "Thinking locally");
  updateSendState();

  let completedResponse = null;
  try {
    const response = isAudio
      ? await requestAudioTurn(input.wavBase64)
      : await requestTextTurn(transcript, { automaticRoutine: automatic });
    if (!response?.state || !response?.context || !Array.isArray(response.errors)) {
      throw new Error("The local pipeline returned an incomplete response.");
    }

    diagnostics.info("turn_response_received", {
      duration_ms: Math.round(performance.now() - turnStartedAt),
      transcript: response.transcript?.text || null,
      spoken_response: response.spoken_response || null,
      errors: response.errors,
      memory_operation: response.memory_operation || null,
      routine: response.routine || null,
      context: response.context,
    });

    if (response.context.command_action === "stop") stopPlayback();

    state.pipeline = response.state;
    state.sessionHistory = Array.isArray(response.session_history)
      ? response.session_history
      : response.state.conversation_history;
    completedResponse = response;
    syncRoutineState(response.routine);
    saveState();

    const currentSpeakButton = renderConversationHistory(response);
    if (!suppressPlayback
        && currentSpeakButton
        && shouldAutoPlayResponse(response, isAudio)) {
      await playResponse(currentSpeakButton);
    }
    scheduleRoutineAutoAdvance();
    armRoutineConfirmationWindow();
  } catch (error) {
    diagnostics.error("turn_failed", {
      duration_ms: Math.round(performance.now() - turnStartedAt),
      transcript: isAudio ? null : transcript,
      error_name: error.name,
      error_message: error.message,
      stack: error.stack || null,
    });
    removePendingMessage();
    appendPipelineError(error.message);
  } finally {
    state.running = false;
    updateSendState();
    diagnostics.debug("turn_finished", {
      duration_ms: Math.round(performance.now() - turnStartedAt),
      succeeded: Boolean(completedResponse),
    });
  }
  return completedResponse;
}

function autoSizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 140)}px`;
}

function updateSendState() {
  const wakeModeOpen = elements.wakeWordScreen.open;
  elements.send.disabled = state.running
    || Boolean(state.recorder)
    || state.recorderStarting
    || state.connection !== "ready"
    || !state.capabilities.text_input
    || !elements.input.value.trim();
  elements.modeSelect.disabled = state.running
    || Boolean(state.recorder)
    || state.recorderStarting
    || state.connection !== "ready"
    || !state.capabilities.text_input;
  elements.microphoneButton.disabled = state.running
    || state.recorderStarting
    || state.connection !== "ready"
    || !state.capabilities.voice_input;
  elements.newConversation.disabled = state.running || state.connection !== "ready";
  elements.exportChat.disabled = state.running
    || state.sessionHistory.length === 0;
  elements.wakeWordButton.disabled = !wakeModeOpen && (
    state.running
    || Boolean(state.recorder)
    || state.recorderStarting
    || state.connection !== "ready"
    || !state.capabilities.wake_word
  );
  elements.wakeWordButton.setAttribute("aria-pressed", String(wakeModeOpen));
  elements.wakeWordButton.setAttribute(
    "aria-label",
    wakeModeOpen ? "Close hands-free wake mode" : "Open hands-free wake mode",
  );
  elements.wakeWordButton.title = wakeModeOpen
    ? "Close hands-free wake-word mode"
    : state.capabilities.wake_word
      ? "Open hands-free wake-word mode"
      : "Run the server with --voice-io to enable wake-word mode";
}

function renderConversationHistory(response = null) {
  let currentSpeakButton = null;
  elements.conversation
    .querySelectorAll(":scope > :not(.date-rule):not([data-welcome])")
    .forEach((node) => node.remove());
  state.sessionHistory.forEach((turn) => {
    if (turn.user_transcript) {
      appendMessage("user", turn.user_transcript, { timestamp: turn.user_sent_at });
    }
    const isCurrent = response
      && turn === state.sessionHistory.at(-1)
      && turn.assistant_response === response.spoken_response;
    const speakButton = appendMessage("assistant", turn.assistant_response, isCurrent ? {
      confirmation: confirmationKind(response),
      errors: response.errors,
      audio: response.audio,
      timestamp: turn.assistant_received_at,
    } : { timestamp: turn.assistant_received_at });
    if (isCurrent) currentSpeakButton = speakButton;
  });
  const responseWasRecorded = response
    && state.sessionHistory.at(-1)?.assistant_response
      === response.spoken_response;
  if (response?.spoken_response && !responseWasRecorded) {
    currentSpeakButton = appendMessage("assistant", response.spoken_response, {
      confirmation: confirmationKind(response),
      errors: response.errors,
      audio: response.audio,
    });
  } else if (response?.errors.length && !responseWasRecorded) {
    appendPipelineError(`Recoverable pipeline error: ${response.errors.join(", ")}.`);
  }
  if (!response) {
    if (state.pipeline.context.pending_mode) appendConfirmation("mode");
    else if (state.pipeline.pending_bulk_memory_delete) appendConfirmation("bulk-memory-delete");
    else if (state.pipeline.pending_memory_action) appendConfirmation("memory");
  }
  updateSendState();
  renderWakeConversation();
  return currentSpeakButton;
}

function appendWakeTranscriptTurn(role, text, timestamp) {
  if (!text) return;
  const turn = document.createElement("article");
  turn.className = `wake-transcript-turn ${role === "user" ? "is-user" : "is-assistant"}`;
  const speaker = document.createElement("strong");
  const speakerLabel = document.createElement("span");
  speakerLabel.textContent = role === "user" ? "You" : "Granite";
  const time = document.createElement("time");
  time.textContent = messageTime(timestamp);
  if (timestamp) time.dateTime = timestamp;
  speaker.append(speakerLabel, time);
  const content = document.createElement("p");
  content.textContent = text;
  turn.append(speaker, content);
  elements.wakeConversationList.appendChild(turn);
}

function renderWakeConversation() {
  const visible = Boolean(state.settings.wake_show_conversation);
  elements.wakeWordScreen.classList.toggle("show-conversation", visible);
  elements.wakeConversationToggle.setAttribute("aria-pressed", String(visible));
  elements.wakeConversationToggle.textContent = visible
    ? "Hide conversation"
    : "Show conversation";
  elements.wakeConversationPanel.setAttribute("aria-hidden", String(!visible));
  elements.wakeConversationList.replaceChildren();
  if (!state.sessionHistory.length) {
    const empty = document.createElement("p");
    empty.className = "wake-conversation-empty";
    empty.textContent = "Your current conversation will appear here while wake mode stays active.";
    elements.wakeConversationList.appendChild(empty);
    return;
  }
  for (const turn of state.sessionHistory) {
    appendWakeTranscriptTurn("user", turn.user_transcript, turn.user_sent_at);
    appendWakeTranscriptTurn(
      "assistant",
      turn.assistant_response,
      turn.assistant_received_at,
    );
  }
  elements.wakeConversationList.scrollTop = elements.wakeConversationList.scrollHeight;
}

function restoreConversationHistory() {
  renderConversationHistory();
}

function setConnectionStatus(status, health = null) {
  const previous = state.connection;
  state.connection = status;
  if (previous !== status) {
    diagnostics.info("connection_state_changed", {
      previous,
      current: status,
      health,
    });
  }
  elements.runtimeDot.classList.toggle("is-offline", status === "offline");
  elements.runtimeDot.classList.toggle(
    "is-connecting",
    status === "connecting" || status === "starting",
  );
  elements.startupScreen.classList.toggle("is-hidden", status === "ready");
  elements.startupScreen.classList.toggle("is-error", status === "error");
  if (status === "ready") {
    elements.runtimeLabel.textContent = "Local pipeline";
    if (health?.runtime?.model) {
      const policyLabel = health.runtime.policy_profile === "uat_relaxed"
        ? " · relaxed UAT"
        : " · strict policy";
      elements.runtimeModel.textContent = `${health.runtime.model}${policyLabel}`;
    }
    elements.startupTitle.textContent = "Granite is ready";
    elements.startupMessage.textContent = health?.message || "Local engine is ready.";
    if (!state.settings.setup_complete && !state.setupPrompted) {
      state.setupPrompted = true;
      window.setTimeout(openSetup, 180);
    }
  } else if (status === "starting") {
    elements.runtimeLabel.textContent = "Starting local engine…";
    elements.startupTitle.textContent = "Starting Granite";
    elements.startupMessage.textContent = health?.message || "Loading local models…";
    if (health?.runtime?.model) {
      elements.runtimeModel.textContent = health.runtime.model;
    }
  } else if (status === "error") {
    elements.runtimeLabel.textContent = "Engine needs attention";
    elements.runtimeModel.textContent = "check local server";
    elements.startupTitle.textContent = "Granite could not start";
    elements.startupMessage.textContent = health?.message || "Check the local server log, then retry.";
  } else if (status === "connecting") {
    elements.runtimeLabel.textContent = "Reconnecting…";
    elements.startupTitle.textContent = "Connecting to Granite";
    elements.startupMessage.textContent = "Waiting for the local application server…";
  } else {
    elements.runtimeLabel.textContent = "Assistant disconnected";
    elements.runtimeModel.textContent = "retrying locally";
    elements.startupTitle.textContent = "Waiting for the local backend";
    elements.startupMessage.textContent = "Granite will reconnect automatically when the local server is available.";
  }
  if (status !== "ready" && state.wakeWord.active) {
    state.wakeWord.active = false;
    tearDownWakeWordAudio();
    setWakeWordView("error", {
      title: "Wake mode stopped",
      status: "The local assistant disconnected",
      detail: "Wake-word listening can be started again after the local engine reconnects.",
    });
  }
  if (status !== "ready" && state.routine.active) {
    syncRoutineState({ active: false });
  }
  if (previous === "offline" && status === "ready") showToast("Local assistant reconnected");
  if (status === "offline" && previous === "ready") state.sessionLoaded = false;
  updateSendState();
}

async function restoreServerSession() {
  const session = await getJson("/api/session", {
    updateConnection: false,
    timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
  });
  state.pipeline = session.state || structuredClone(defaultState);
  state.sessionHistory = Array.isArray(session.session_history)
    ? session.session_history
    : [];
  syncRoutineState(session.routine);
  state.sessionLoaded = true;
  renderConversationHistory();
  saveState();
  diagnostics.info("session_restored", {
    turns: state.sessionHistory.length,
    mode: state.pipeline.context.mode,
    routine: session.routine,
  });
}

async function connectPipeline({ silent = false } = {}) {
  if (!silent && state.connection !== "offline") setConnectionStatus("connecting");
  try {
    const health = await getJson("/api/health", {
      updateConnection: false,
      timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
      diagnostic: !silent,
    });
    state.capabilities = { ...state.capabilities, ...health.capabilities };
    state.audioStream = health.audio_stream || null;
    diagnostics.setEnabled(Boolean(state.capabilities.diagnostics));
    if (!silent) diagnostics.debug("health_received", health);
    const healthStatus = ["ready", "starting", "error"].includes(health.status)
      ? health.status
      : "error";
    setConnectionStatus(healthStatus, health);
    if (healthStatus === "ready" && !state.sessionLoaded) {
      await restoreServerSession();
    }
    if (state.capabilities.voice_input) applyPersonalSettings();
    else elements.interactionLabel.textContent = "Transcript input · voice I/O disabled";
    if (!state.capabilities.voice_input) {
      elements.deviceStatus.textContent = (
        "Browser devices can be selected, but local STT/TTS is disabled. "
        + "Restart the server with --voice-io."
      );
    }
    elements.microphoneButton.title = state.capabilities.voice_input
      ? "Start voice input"
      : "Run the server with --voice-io to enable voice input";
    const wakeChoice = elements.setupForm.querySelector(
      '[name="interaction_mode"][value="wake_word"]',
    );
    wakeChoice.disabled = !state.capabilities.wake_word;
    document.querySelector("#wake-word-choice").classList.toggle(
      "is-disabled",
      !state.capabilities.wake_word,
    );
    renderState();
  } catch (error) {
    diagnostics.error("health_check_failed", {
      error_name: error.name,
      error_message: error.message,
    });
    state.capabilities = {
      text_input: false,
      voice_input: false,
      voice_output: false,
      wake_word: false,
      reminders: false,
      guided_routines: false,
      routine_barge_in: false,
      playback_barge_in: false,
      diagnostics: false,
      privacy_centre: false,
    };
    state.audioStream = null;
    diagnostics.setEnabled(false);
    setConnectionStatus("offline");
  }
}

async function startNewConversation() {
  if (state.running) return;
  elements.newConversation.disabled = true;
  try {
    const response = await requestJson("/api/session/reset", {});
    state.pipeline = response.state || structuredClone(defaultState);
    state.sessionHistory = response.session_history || [];
    syncRoutineState({ active: false });
    state.sessionLoaded = true;
    stopPlayback();
    renderConversationHistory();
    saveState();
    showToast("Started a new private conversation");
  } catch (error) {
    appendPipelineError(error.message);
  } finally {
    updateSendState();
  }
}
