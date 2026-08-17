// Personal setup, device selection, and browser settings.

function saveState() {
  renderState();
}

const setupSteps = [
  {
    title: "Choose your audio devices",
    description: "Select the microphone Granite listens to and the speaker it uses.",
  },
  {
    title: "Make the voice comfortable",
    description: "Adjust speech pace and volume, then preview the result on this device.",
  },
  {
    title: "Choose how you interact",
    description: "Choose when local Piper responses play automatically in this browser.",
  },
  {
    title: "Shape every response",
    description: "Set your preferred answer length, review the setup, and save it locally.",
  },
];

function openSetup() {
  state.settingsDraft = structuredClone(state.settings);
  state.setupStep = 0;
  populateSetupForm(state.settingsDraft);
  renderSetupStep();
  if (!elements.setupDialog.open) elements.setupDialog.showModal();
}

function closeSetup() {
  if (elements.setupDialog.open) elements.setupDialog.close();
}

function renderSetupStep() {
  const step = setupSteps[state.setupStep];
  document.querySelectorAll("[data-setup-step]").forEach((section) => {
    section.hidden = Number(section.dataset.setupStep) !== state.setupStep;
  });
  document.querySelectorAll("[data-progress-step]").forEach((item) => {
    const itemStep = Number(item.dataset.progressStep);
    item.classList.toggle("is-current", itemStep === state.setupStep);
    item.classList.toggle("is-complete", itemStep < state.setupStep);
  });
  elements.setupStepLabel.textContent = `Step ${state.setupStep + 1} of ${setupSteps.length}`;
  elements.setupTitle.textContent = step.title;
  elements.setupDescription.textContent = step.description;
  elements.setupBack.hidden = state.setupStep === 0;
  elements.setupNext.textContent = state.setupStep === setupSteps.length - 1
    ? "Save settings"
    : "Continue";
  elements.setupSkip.textContent = state.settings.setup_complete ? "Cancel" : "Skip for now";
  if (state.setupStep === setupSteps.length - 1) updateSetupReview();
}

function populateSetupForm(settings) {
  ensureSelectedDeviceOption(
    elements.microphoneSelect,
    settings.microphone_id,
    "Previously selected microphone",
  );
  ensureSelectedDeviceOption(
    elements.speakerSelect,
    settings.speaker_id,
    "Previously selected speaker",
  );
  elements.microphoneSelect.value = settings.microphone_id;
  elements.speakerSelect.value = settings.speaker_id;
  elements.speechRate.value = settings.speech_rate;
  elements.voiceVolume.value = settings.volume;
  elements.wakeSensitivity.value = settings.wake_word_sensitivity;
  elements.wakeEndPause.value = settings.wake_end_pause_seconds;
  elements.wakeFollowUp.value = settings.wake_follow_up_seconds;
  elements.wakeMaximumRequest.value = settings.wake_max_request_seconds;
  elements.wakeAutoFollowUp.checked = settings.wake_auto_follow_up;
  const interaction = elements.setupForm.querySelector(
    `[name="interaction_mode"][value="${settings.interaction_mode}"]`,
  );
  if (interaction) interaction.checked = true;
  const responseLength = elements.setupForm.querySelector(
    `[name="response_length"][value="${settings.response_length}"]`,
  );
  if (responseLength) responseLength.checked = true;
  elements.setupForm.elements.speak_confirmations.checked = settings.speak_confirmations;
  updateRangeOutputs();
  populateWakeQuickSettings(settings);
}

function ensureSelectedDeviceOption(select, value, label) {
  if (!value || value === "default") return;
  const exists = [...select.options].some((option) => option.value === value);
  if (!exists) select.add(new Option(label, value));
}

function collectSettingsDraft() {
  const checkedInteraction = elements.setupForm.querySelector(
    '[name="interaction_mode"]:checked',
  );
  const checkedLength = elements.setupForm.querySelector(
    '[name="response_length"]:checked',
  );
  state.settingsDraft = {
    ...state.settingsDraft,
    microphone_id: elements.microphoneSelect.value,
    speaker_id: elements.speakerSelect.value,
    speech_rate: Number(elements.speechRate.value),
    volume: Number(elements.voiceVolume.value),
    response_length: checkedLength?.value || "normal",
    wake_word_sensitivity: Number(elements.wakeSensitivity.value),
    wake_end_pause_seconds: Number(elements.wakeEndPause.value),
    wake_follow_up_seconds: Number(elements.wakeFollowUp.value),
    wake_max_request_seconds: Number(elements.wakeMaximumRequest.value),
    wake_auto_follow_up: elements.wakeAutoFollowUp.checked,
    interaction_mode: checkedInteraction?.value || "voice_first",
    speak_confirmations: elements.setupForm.elements.speak_confirmations.checked,
  };
  updateRangeOutputs();
}

async function savePersonalSettings() {
  collectSettingsDraft();
  state.settings = {
    ...state.settingsDraft,
    version: defaultSettings.version,
    setup_complete: true,
  };
  window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(state.settings));
  applyPersonalSettings();
  closeSetup();
  showToast("Personal settings saved on this device");
  if (state.settings.interaction_mode === "wake_word") {
    if (state.capabilities.wake_word) await startWakeWordMode();
    else showToast("Restart the server with --voice-io to use wake-word mode");
  }
}

function applyPersonalSettings() {
  const { response_length: responseLength } = state.settings;
  populateWakeQuickSettings(state.settings);
  const interactionLabels = {
    wake_word: "Hands-free wake word",
    voice_first: "Automatic voice playback",
    push_to_talk: "Voice after microphone turns",
    text_first: "Manual playback",
  };
  elements.interactionLabel.textContent = interactionLabels[state.settings.interaction_mode];
  elements.settingsButton.classList.toggle("is-configured", state.settings.setup_complete);
  elements.settingsButton.setAttribute(
    "aria-label",
    state.settings.setup_complete
      ? `Personal settings: ${responseLength} responses, ${interactionLabels[state.settings.interaction_mode]}`
      : "Open personal setup",
  );
  renderState();
}

function updateRangeOutputs() {
  const speechRate = Number(elements.speechRate.value);
  const speechLabel = speechRate < 0.9 ? "Slow" : speechRate > 1.1 ? "Fast" : "Normal";
  elements.speechRateOutput.textContent = `${speechLabel} · ${speechRate.toFixed(1)}×`;
  elements.volumeOutput.textContent = `${elements.voiceVolume.value}%`;
  const sensitivity = Number(elements.wakeSensitivity.value);
  const sensitivityLabel = sensitivity < 50
    ? "Conservative"
    : sensitivity > 70 ? "Responsive" : "Balanced";
  elements.sensitivityOutput.textContent = `${sensitivityLabel} · ${sensitivity}%`;
  elements.wakeEndPauseOutput.textContent = `${Number(elements.wakeEndPause.value).toFixed(1)} sec`;
  elements.wakeFollowUpOutput.textContent = `${elements.wakeFollowUp.value} sec`;
  elements.wakeMaximumRequestOutput.textContent = `${elements.wakeMaximumRequest.value} sec`;
}

function populateWakeQuickSettings(settings) {
  elements.wakeQuickSensitivity.value = settings.wake_word_sensitivity;
  elements.wakeQuickPause.value = settings.wake_end_pause_seconds;
  elements.wakeQuickFollowUp.value = settings.wake_follow_up_seconds;
  elements.wakeQuickMaximum.value = settings.wake_max_request_seconds;
  elements.wakeQuickAutoFollowUp.checked = settings.wake_auto_follow_up;
  updateWakeQuickOutputs();
}

function updateWakeQuickOutputs() {
  elements.wakeQuickSensitivityOutput.textContent = `${elements.wakeQuickSensitivity.value}%`;
  elements.wakeQuickPauseOutput.textContent = `${Number(elements.wakeQuickPause.value).toFixed(1)} sec`;
  elements.wakeQuickFollowUpOutput.textContent = `${elements.wakeQuickFollowUp.value} sec`;
  elements.wakeQuickMaximumOutput.textContent = `${elements.wakeQuickMaximum.value} sec`;
}

async function saveWakeQuickSettings() {
  const previousSensitivity = state.settings.wake_word_sensitivity;
  state.settings = {
    ...state.settings,
    wake_word_sensitivity: Number(elements.wakeQuickSensitivity.value),
    wake_end_pause_seconds: Number(elements.wakeQuickPause.value),
    wake_follow_up_seconds: Number(elements.wakeQuickFollowUp.value),
    wake_max_request_seconds: Number(elements.wakeQuickMaximum.value),
    wake_auto_follow_up: elements.wakeQuickAutoFollowUp.checked,
  };
  window.localStorage.setItem(SETTINGS_STORAGE_KEY, JSON.stringify(state.settings));
  elements.wakeSensitivity.value = state.settings.wake_word_sensitivity;
  elements.wakeEndPause.value = state.settings.wake_end_pause_seconds;
  elements.wakeFollowUp.value = state.settings.wake_follow_up_seconds;
  elements.wakeMaximumRequest.value = state.settings.wake_max_request_seconds;
  elements.wakeAutoFollowUp.checked = state.settings.wake_auto_follow_up;
  updateWakeQuickOutputs();
  updateRangeOutputs();
  if (state.wakeWord.active
      && previousSensitivity !== state.settings.wake_word_sensitivity) {
    try {
      await requestJson(
        "/api/wake-word/start",
        { sensitivity: state.settings.wake_word_sensitivity },
        {
          updateConnection: false,
          timeoutMilliseconds: WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS,
        },
      );
      resetWakeWordFrameBuffer();
    } catch (error) {
      showToast(error.message);
    }
  }
}

function updateSetupReview() {
  collectSettingsDraft();
  const microphone = elements.microphoneSelect.selectedOptions[0]?.textContent;
  const speaker = elements.speakerSelect.selectedOptions[0]?.textContent;
  const audioLabel = microphone === "System default microphone"
    && speaker === "System default speaker"
    ? "System defaults"
    : "Custom devices";
  const interactionLabels = {
    wake_word: "Wake word",
    voice_first: "Voice first",
    push_to_talk: "Push to talk",
    text_first: "Text first",
  };
  setText("#review-audio", audioLabel);
  setText(
    "#review-voice",
    `${Number(state.settingsDraft.speech_rate).toFixed(1)}× · ${state.settingsDraft.volume}%`,
  );
  setText("#review-interaction", interactionLabels[state.settingsDraft.interaction_mode]);
}

async function findAudioDevices() {
  elements.detectDevices.disabled = true;
  elements.deviceStatus.textContent = "Checking microphones and speakers…";
  try {
    if (!navigator.mediaDevices?.enumerateDevices) {
      throw new Error("Device selection is unavailable in this browser.");
    }
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    stream.getTracks().forEach((track) => track.stop());
    const devices = await navigator.mediaDevices.enumerateDevices();
    populateDeviceSelect(
      elements.microphoneSelect,
      devices.filter((device) => device.kind === "audioinput"),
      "System default microphone",
      "Microphone",
    );
    populateDeviceSelect(
      elements.speakerSelect,
      devices.filter((device) => device.kind === "audiooutput"),
      "System default speaker",
      "Speaker",
    );
    const microphones = devices.filter((device) => device.kind === "audioinput").length;
    const speakers = devices.filter((device) => device.kind === "audiooutput").length;
    const pipelineStatus = state.capabilities.voice_input
      ? " Local Whisper and Piper are enabled."
      : " Restart the server with --voice-io to use local Whisper and Piper.";
    elements.deviceStatus.textContent = `Found ${microphones} microphone${microphones === 1 ? "" : "s"} and ${speakers} speaker${speakers === 1 ? "" : "s"}.${pipelineStatus}`;
  } catch (error) {
    elements.deviceStatus.textContent = error.name === "NotAllowedError"
      ? "Microphone access was not allowed. You can keep the system defaults."
      : error.message || "Devices could not be listed. System defaults remain available.";
  } finally {
    elements.detectDevices.disabled = false;
  }
}

function populateDeviceSelect(select, devices, defaultLabel, fallbackLabel) {
  const selectedValue = select.value;
  select.replaceChildren(new Option(defaultLabel, "default"));
  devices.forEach((device, index) => {
    if (device.deviceId === "default") return;
    select.add(new Option(device.label || `${fallbackLabel} ${index + 1}`, device.deviceId));
  });
  ensureSelectedDeviceOption(select, selectedValue, `Previously selected ${fallbackLabel.toLowerCase()}`);
  select.value = [...select.options].some((option) => option.value === selectedValue)
    ? selectedValue
    : "default";
}


