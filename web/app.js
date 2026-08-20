// Browser entry point and event wiring.

function showToast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("is-visible");
  window.setTimeout(() => elements.toast.classList.remove("is-visible"), 1600);
}

elements.form.addEventListener("submit", (event) => {
  event.preventDefault();
  runTurn(elements.input.value);
});

elements.input.addEventListener("input", () => {
  autoSizeInput();
  updateSendState();
});

elements.input.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    if (!elements.send.disabled) elements.form.requestSubmit();
  }
});

document.querySelectorAll("[data-prompt]").forEach((button) => {
  button.addEventListener("click", () => {
    elements.input.value = button.dataset.prompt;
    autoSizeInput();
    updateSendState();
    elements.input.focus();
  });
});

elements.conversation.addEventListener("click", (event) => {
  const action = event.target.closest("[data-confirm]");
  if (action) {
    const card = action.closest(".confirmation-card");
    card.remove();
    runTurn(action.dataset.confirm === "yes" ? "yes, confirm" : "cancel");
    return;
  }
  const speak = event.target.closest(".speak-button");
  if (speak) {
    playResponse(speak);
  }
});

elements.modeSelect.addEventListener("change", () => {
  const requestedMode = elements.modeSelect.value;
  if (requestedMode === state.pipeline.context.mode) return;
  runTurn(`Switch to ${requestedMode} mode`);
});

elements.microphoneButton.addEventListener("click", async () => {
  unlockResponsePlayback();
  if (state.recorder) {
    await stopVoiceRecording();
  } else {
    await startVoiceRecording();
    updateSendState();
  }
});

elements.themeButton.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  window.localStorage.setItem("granite-theme", next);
});

elements.newConversation.addEventListener("click", startNewConversation);
elements.exportChat.addEventListener("click", exportChat);
elements.wakeWordButton.addEventListener("click", () => {
  if (elements.wakeWordScreen.open) stopWakeWordMode();
  else startWakeWordMode();
});
elements.wakeConversationToggle.addEventListener("click", () => {
  state.settings.wake_show_conversation = !state.settings.wake_show_conversation;
  window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(state.settings));
  renderWakeConversation();
});
elements.wakePushButton.addEventListener("click", () => {
  if (state.wakeWord.phase === "waiting") beginWakeCommand();
  else if (state.wakeWord.phase === "listening") finishWakeCommand({ force: true });
});
elements.wakeCancelButton.addEventListener("click", () => {
  resumeWakeWordListening("Cancelled. Listening for “Hey Jarvis”.");
});
for (const control of [
  elements.wakeQuickSensitivity,
  elements.wakeQuickPause,
  elements.wakeQuickFollowUp,
  elements.wakeQuickMaximum,
]) {
  control.addEventListener("input", updateWakeQuickOutputs);
  control.addEventListener("change", saveWakeQuickSettings);
}
elements.wakeQuickAutoFollowUp.addEventListener("change", saveWakeQuickSettings);
elements.wakeWordCloseForm.addEventListener("submit", (event) => {
  event.preventDefault();
  stopWakeWordMode();
});
elements.wakeWordScreen.addEventListener("close", stopWakeWordMode);
elements.localDataButton.addEventListener("click", openLocalData);
elements.localDataClose.addEventListener("click", () => elements.localDataDialog.close());
elements.localDataDialog.addEventListener("click", async (event) => {
  const memoryAction = event.target.closest("[data-memory-action]");
  const reminderAction = event.target.closest("[data-reminder-action]");
  if (!memoryAction && !reminderAction) return;
  try {
    if (memoryAction) await handleMemoryAction(memoryAction);
    else await handleReminderAction(reminderAction);
  } catch (error) {
    showToast(error.message);
  }
});
elements.exportMemories.addEventListener("click", exportMemories);
elements.forgetAllMemories.addEventListener("click", async () => {
  const confirmed = await requestAction({
    title: "Forget all memories?",
    description: "Every saved memory will be permanently removed from this device. This cannot be undone.",
    confirmLabel: "Forget all memories",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const result = await requestJson("/api/privacy/memories/forget-all", {
      confirmation: "DELETE",
    });
    showToast(`${result.deleted} ${result.deleted === 1 ? "memory" : "memories"} deleted`);
    await refreshLocalData();
  } catch (error) {
    showToast(error.message);
  }
});
elements.cancelAllReminders.addEventListener("click", async () => {
  const confirmed = await requestAction({
    title: "Cancel all reminders?",
    description: "Every scheduled reminder and timer will be removed and will not be announced.",
    confirmLabel: "Cancel all reminders",
    danger: true,
  });
  if (!confirmed) return;
  try {
    const result = await requestJson("/api/reminders/cancel-all", {
      confirmation: "DELETE",
    });
    showToast(`${result.cancelled} ${result.cancelled === 1 ? "reminder" : "reminders"} cancelled`);
    await refreshLocalData();
  } catch (error) {
    showToast(error.message);
  }
});
elements.actionForm.addEventListener("submit", (event) => {
  event.preventDefault();
  if (!elements.actionInputField.hidden) {
    const value = elements.actionInput.value.trim();
    if (!value) {
      elements.actionInput.setCustomValidity("Enter a value before saving.");
      elements.actionInput.reportValidity();
      return;
    }
    finishActionDialog(value);
    return;
  }
  finishActionDialog(true);
});
elements.actionInput.addEventListener("input", () => {
  elements.actionInput.setCustomValidity("");
});
elements.actionClose.addEventListener("click", () => finishActionDialog(null));
elements.actionCancel.addEventListener("click", () => finishActionDialog(null));
elements.actionDialog.addEventListener("cancel", (event) => {
  event.preventDefault();
  finishActionDialog(null);
});
elements.actionDialog.addEventListener("close", () => finishActionDialog(null));
elements.settingsButton.addEventListener("click", openSetup);
elements.setupClose.addEventListener("click", closeSetup);
elements.setupSkip.addEventListener("click", closeSetup);
elements.setupBack.addEventListener("click", () => {
  collectSettingsDraft();
  state.setupStep = Math.max(0, state.setupStep - 1);
  renderSetupStep();
});
elements.setupNext.addEventListener("click", () => {
  collectSettingsDraft();
  if (state.setupStep === setupSteps.length - 1) {
    savePersonalSettings();
    return;
  }
  state.setupStep += 1;
  renderSetupStep();
});
elements.detectDevices.addEventListener("click", findAudioDevices);
elements.previewVoice.addEventListener("click", previewAssistantVoice);
elements.setupForm.addEventListener("input", () => {
  collectSettingsDraft();
  if (state.setupStep === setupSteps.length - 1) updateSetupReview();
});
elements.setupDialog.addEventListener("cancel", () => {
  state.settingsDraft = null;
});

document.documentElement.dataset.theme = window.localStorage.getItem("granite-theme") || "light";
window.localStorage.removeItem(LEGACY_PIPELINE_STORAGE_KEY);
diagnostics.info("browser_application_starting", {
  location: window.location.href,
  user_agent: navigator.userAgent,
  settings: state.settings,
});
applyPersonalSettings();
restoreConversationHistory();
connectPipeline();
window.setInterval(() => connectPipeline({ silent: true }), HEALTH_POLL_MILLISECONDS);
window.setInterval(pollDueReminders, DUE_POLL_MILLISECONDS);
window.addEventListener("pagehide", () => {
  diagnostics.info("browser_application_stopping", {
    connection: state.connection,
    busy: state.busy,
    wake_word_phase: state.wakeWord.phase,
  });
  tearDownWakeWordAudio();
  tearDownVoiceCommandAudio();
});
