const LEGACY_PIPELINE_STORAGE_KEY = "granite-pipeline-state-v1";
const SETTINGS_STORAGE_KEY = "granite-personal-settings-v1";
const HEALTH_POLL_MILLISECONDS = 5000;
const DUE_POLL_MILLISECONDS = 5000;
const REQUEST_TIMEOUT_MILLISECONDS = 12000;
const SILENT_WAV_URL = "data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAAAAA==";
const { shouldAutoPlayResponse: playbackPolicyAllows } = window.GranitePlaybackPolicy;

const defaultSettings = {
  version: 1,
  setup_complete: false,
  microphone_id: "default",
  speaker_id: "default",
  speech_rate: 1,
  volume: 80,
  response_length: "normal",
  wake_word_sensitivity: 60,
  interaction_mode: "voice_first",
  speak_confirmations: true,
};

const defaultState = {
  context: {
    mode: "home",
    pending_mode: null,
    last_topic: null,
    accessibility: {
      verbosity: "normal",
      speech_pace: "normal",
    },
  },
  last_spoken_response: null,
  conversation_history: [],
  pending_memory_action: null,
  pending_memory_scope: null,
};

const state = {
  pipeline: structuredClone(defaultState),
  settings: loadSettings(),
  settingsDraft: null,
  setupStep: 0,
  running: false,
  capabilities: {
    text_input: false,
    voice_input: false,
    voice_output: false,
    wake_word: false,
    reminders: false,
    guided_routines: false,
    privacy_centre: false,
  },
  connection: "connecting",
  recorder: null,
  playback: null,
  responseAudioElement: null,
  actionDialogResolve: null,
};

const elements = {
  form: document.querySelector("#turn-form"),
  input: document.querySelector("#transcript-input"),
  send: document.querySelector("#send-button"),
  conversation: document.querySelector("#conversation"),
  modeSelect: document.querySelector("#mode-select"),
  microphoneButton: document.querySelector("#mic-button"),
  runtimeLabel: document.querySelector("#runtime-label"),
  runtimeDot: document.querySelector("#runtime-dot"),
  runtimeModel: document.querySelector("#runtime-model"),
  toast: document.querySelector("#toast"),
  themeButton: document.querySelector("#theme-button"),
  settingsButton: document.querySelector("#settings-button"),
  setupDialog: document.querySelector("#setup-dialog"),
  setupForm: document.querySelector("#setup-form"),
  setupClose: document.querySelector("#setup-close"),
  setupSkip: document.querySelector("#setup-skip"),
  setupBack: document.querySelector("#setup-back"),
  setupNext: document.querySelector("#setup-next"),
  setupStepLabel: document.querySelector("#setup-step-label"),
  setupTitle: document.querySelector("#setup-title"),
  setupDescription: document.querySelector("#setup-description"),
  microphoneSelect: document.querySelector("#microphone-select"),
  speakerSelect: document.querySelector("#speaker-select"),
  deviceStatus: document.querySelector("#device-status"),
  detectDevices: document.querySelector("#detect-devices"),
  speechRate: document.querySelector("#speech-rate"),
  speechRateOutput: document.querySelector("#speech-rate-output"),
  voiceVolume: document.querySelector("#voice-volume"),
  volumeOutput: document.querySelector("#volume-output"),
  wakeSensitivity: document.querySelector("#wake-sensitivity"),
  sensitivityOutput: document.querySelector("#sensitivity-output"),
  previewVoice: document.querySelector("#preview-voice"),
  interactionLabel: document.querySelector("#interaction-label"),
  localDataButton: document.querySelector("#local-data-button"),
  localDataDialog: document.querySelector("#local-data-dialog"),
  localDataClose: document.querySelector("#local-data-close"),
  memorySummary: document.querySelector("#memory-summary"),
  memoryList: document.querySelector("#memory-list"),
  reminderSummary: document.querySelector("#reminder-summary"),
  reminderList: document.querySelector("#reminder-list"),
  storageList: document.querySelector("#storage-list"),
  exportMemories: document.querySelector("#export-memories"),
  forgetAllMemories: document.querySelector("#forget-all-memories"),
  cancelAllReminders: document.querySelector("#cancel-all-reminders"),
  newConversation: document.querySelector("#new-conversation-button"),
  actionDialog: document.querySelector("#action-dialog"),
  actionForm: document.querySelector("#action-form"),
  actionClose: document.querySelector("#action-close"),
  actionTitle: document.querySelector("#action-title"),
  actionDescription: document.querySelector("#action-description"),
  actionInputField: document.querySelector("#action-input-field"),
  actionInputLabel: document.querySelector("#action-input-label"),
  actionInput: document.querySelector("#action-input"),
  actionCancel: document.querySelector("#action-cancel"),
  actionConfirm: document.querySelector("#action-confirm"),
};

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function loadSettings() {
  try {
    const persisted = window.localStorage.getItem(SETTINGS_STORAGE_KEY);
    return persisted
      ? { ...defaultSettings, ...JSON.parse(persisted) }
      : structuredClone(defaultSettings);
  } catch {
    return structuredClone(defaultSettings);
  }
}

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
    interaction_mode: checkedInteraction?.value || "voice_first",
    speak_confirmations: elements.setupForm.elements.speak_confirmations.checked,
  };
  updateRangeOutputs();
}

function savePersonalSettings() {
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
}

function applyPersonalSettings() {
  const { response_length: responseLength } = state.settings;
  const interactionLabels = {
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
  elements.sensitivityOutput.textContent = "Live runner only";
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

function effectiveSpeechRate(settings, includePipelinePace = true) {
  const pipelineFactor = includePipelinePace
    && state.pipeline.context.accessibility.speech_pace === "slow"
    ? 0.8
    : 1;
  return Number(settings.speech_rate) * pipelineFactor;
}

function speakText(
  text,
  settings = state.settings,
  includePipelinePace = settings === state.settings,
) {
  if (!("speechSynthesis" in window)) {
    showToast("Voice preview is unavailable in this browser");
    return;
  }
  stopPlayback();
  const utterance = new SpeechSynthesisUtterance(text);
  utterance.rate = effectiveSpeechRate(settings, includePipelinePace);
  utterance.volume = Number(settings.volume) / 100;
  window.speechSynthesis.speak(utterance);
}

function renderState() {
  elements.modeSelect.value = state.pipeline.context.mode;
  document.querySelectorAll("[data-capability]").forEach((element) => {
    element.hidden = !state.capabilities[element.dataset.capability];
  });
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = String(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function appendMessage(role, text, options = {}) {
  const article = document.createElement("article");
  article.className = `message message-${role}`;
  const isAssistant = role === "assistant";
  article.innerHTML = `
    <div class="avatar" aria-hidden="true">${isAssistant ? "G" : "Y"}</div>
    <div class="message-body">
      <div class="message-meta"><strong>${isAssistant ? "Granite" : "You"}</strong><span>Now</span></div>
      <div class="bubble">${escapeHtml(text)}</div>
      ${isAssistant ? `
        <button class="speak-button" type="button" aria-label="Play assistant response">
          <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M11 5 6 9H3v6h3l5 4V5Z" /><path d="M15 9.5c.7.7 1 1.5 1 2.5s-.3 1.8-1 2.5M18 7c1.4 1.4 2 3 2 5s-.6 3.6-2 5" /></svg>
          ${state.capabilities.voice_output ? "Play response" : "Play browser voice"}
        </button>` : ""}
    </div>`;
  elements.conversation.appendChild(article);
  const speakButton = article.querySelector(".speak-button");
  if (speakButton) {
    speakButton.responseAudio = options.audio || null;
    speakButton.fallbackText = text;
  }

  if (options.confirmation) {
    appendConfirmation(options.confirmation);
  }
  if (options.errors?.length) {
    const error = document.createElement("div");
    error.className = "error-card";
    error.textContent = `Recoverable pipeline error: ${options.errors.join(", ")}. The spoken response remains available.`;
    elements.conversation.appendChild(error);
  }
  article.scrollIntoView({ behavior: "smooth", block: "nearest" });
  return speakButton;
}

function appendPipelineError(message) {
  const error = document.createElement("div");
  error.className = "error-card";
  error.textContent = message;
  elements.conversation.appendChild(error);
  error.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function appendConfirmation(kind) {
  const card = document.createElement("div");
  card.className = "confirmation-card";
  const isMode = kind === "mode";
  card.innerHTML = `
    <div>
      <strong>${isMode ? "Mode change requires confirmation" : "Memory change requires confirmation"}</strong>
      <span>${isMode ? "Driving mode changes response policy." : "No memory is changed until you approve."}</span>
    </div>
    <div class="confirmation-actions">
      <button type="button" data-confirm="cancel">Cancel</button>
      <button class="confirm" type="button" data-confirm="yes">Confirm</button>
    </div>`;
  elements.conversation.appendChild(card);
}

async function requestJson(path, payload = null, { method = "POST" } = {}) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MILLISECONDS);
  let response;
  try {
    response = await fetch(path, {
      method,
      cache: "no-store",
      credentials: "same-origin",
      headers: payload === null ? {} : { "Content-Type": "application/json" },
      body: payload === null ? undefined : JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (error) {
    setConnectionStatus("offline");
    throw new Error(error.name === "AbortError"
      ? "The local assistant did not respond. Reconnecting…"
      : "The local assistant is disconnected. Reconnecting…");
  } finally {
    window.clearTimeout(timeout);
  }
  let body = null;
  try {
    body = await response.json();
  } catch {
    throw new Error("The local pipeline returned an unreadable response.");
  }
  if (!response.ok) {
    throw new Error(body?.error?.message || `Local request failed (${response.status}).`);
  }
  setConnectionStatus("ready");
  return body;
}

function getJson(path) {
  return requestJson(path, null, { method: "GET" });
}

function turnOptions() {
  return {
    synthesize: Boolean(state.capabilities.voice_output),
    play: false,
    response_length: state.settings.response_length,
  };
}

function requestTextTurn(transcript) {
  return requestJson("/api/turn", {
    transcript,
    options: turnOptions(),
  });
}

function requestAudioTurn(wavBase64) {
  return requestJson("/api/audio", {
    wav_base64: wavBase64,
    options: turnOptions(),
  });
}

function confirmationKind(response) {
  if (response.context?.needs_confirmation || response.state?.context?.pending_mode) {
    return "mode";
  }
  if (response.reasoning?.proposed_memory_action?.requires_confirmation) return "memory";
  if (response.state?.pending_memory_action) return "memory";
  return null;
}

function stopPlayback() {
  window.speechSynthesis?.cancel();
  if (!state.playback) return;
  const playback = state.playback;
  state.playback = null;
  playback.audio.onended = null;
  playback.audio.pause();
  playback.audio.currentTime = 0;
  playback.button?.classList.remove("is-playing");
  if (playback.button) playback.button.lastChild.textContent = " Play response";
  URL.revokeObjectURL(playback.url);
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
    stopPlayback();
    return;
  }
  stopPlayback();
  const audioPayload = button.responseAudio;
  if (!audioPayload?.wav_base64) {
    showToast(state.capabilities.voice_output
      ? "Piper audio is unavailable for this response; using the browser voice"
      : "Using the browser voice; start the server with --voice-io for Piper");
    speakText(button.fallbackText || "");
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
  state.playback = { audio, button, url };
  button.classList.add("is-playing");
  button.lastChild.textContent = " Stop response";
  audio.onended = stopPlayback;
  try {
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
    interactionMode: state.settings.interaction_mode,
    isAudioTurn,
  });
}

async function startVoiceRecording() {
  if (!state.capabilities.voice_input) {
    showToast("Restart the local UI server with --voice-io to enable speech input");
    return;
  }
  const audioConstraint = state.settings.microphone_id === "default"
    ? true
    : { deviceId: { exact: state.settings.microphone_id } };
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraint });
    const AudioContext = window.AudioContext || window.webkitAudioContext;
    const context = new AudioContext();
    const source = context.createMediaStreamSource(stream);
    const processor = context.createScriptProcessor(4096, 1, 1);
    const silentGain = context.createGain();
    silentGain.gain.value = 0;
    const chunks = [];
    processor.onaudioprocess = (event) => {
      chunks.push(new Float32Array(event.inputBuffer.getChannelData(0)));
    };
    source.connect(processor);
    processor.connect(silentGain);
    silentGain.connect(context.destination);
    state.recorder = { stream, context, source, processor, silentGain, chunks };
    elements.microphoneButton.classList.add("is-recording");
    elements.microphoneButton.setAttribute("aria-label", "Stop and send voice input");
    elements.microphoneButton.title = "Stop and send";
  } catch (error) {
    showToast(error.name === "NotAllowedError"
      ? "Microphone permission was not allowed"
      : "The selected microphone is unavailable");
  }
}

async function stopVoiceRecording() {
  const recorder = state.recorder;
  if (!recorder) return;
  state.recorder = null;
  recorder.processor.disconnect();
  recorder.source.disconnect();
  recorder.silentGain.disconnect();
  recorder.stream.getTracks().forEach((track) => track.stop());
  const sourceRate = recorder.context.sampleRate;
  await recorder.context.close();
  elements.microphoneButton.classList.remove("is-recording");
  elements.microphoneButton.setAttribute("aria-label", "Start voice input");
  elements.microphoneButton.title = "Start voice input";

  const samples = mergeAudioChunks(recorder.chunks);
  if (samples.length < sourceRate / 5) {
    showToast("That recording was too short");
    return;
  }
  const resampled = resampleAudio(samples, sourceRate, 16000);
  await runTurn({ kind: "audio", wavBase64: encodeWavBase64(resampled, 16000) });
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

function resampleAudio(samples, sourceRate, targetRate) {
  if (sourceRate === targetRate) return samples;
  const targetLength = Math.max(1, Math.round(samples.length * targetRate / sourceRate));
  const output = new Float32Array(targetLength);
  const ratio = sourceRate / targetRate;
  for (let index = 0; index < targetLength; index += 1) {
    const position = index * ratio;
    const left = Math.floor(position);
    const right = Math.min(left + 1, samples.length - 1);
    const fraction = position - left;
    output[index] = samples[left] * (1 - fraction) + samples[right] * fraction;
  }
  return output;
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

async function runTurn(input) {
  if (state.running) return;
  const isAudio = typeof input === "object" && input.kind === "audio";
  const transcript = isAudio ? "" : String(input || "").trim();
  if (!isAudio && !transcript) return;

  unlockResponsePlayback();
  state.running = true;
  if (!isAudio) {
    elements.input.value = "";
    autoSizeInput();
    appendMessage("user", transcript);
  }
  updateSendState();

  try {
    const response = isAudio
      ? await requestAudioTurn(input.wavBase64)
      : await requestTextTurn(transcript);
    if (!response?.state || !response?.context || !Array.isArray(response.errors)) {
      throw new Error("The local pipeline returned an incomplete response.");
    }

    if (response.context.command_action === "stop") stopPlayback();

    state.pipeline = response.state;
    saveState();

    const currentSpeakButton = renderConversationHistory(response);
    if (currentSpeakButton && shouldAutoPlayResponse(response, isAudio)) {
      await playResponse(currentSpeakButton);
    }
  } catch (error) {
    appendPipelineError(error.message);
  } finally {
    state.running = false;
    updateSendState();
  }
}

function autoSizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 140)}px`;
}

function updateSendState() {
  elements.send.disabled = state.running
    || Boolean(state.recorder)
    || state.connection !== "ready"
    || !state.capabilities.text_input
    || !elements.input.value.trim();
  elements.modeSelect.disabled = state.running
    || Boolean(state.recorder)
    || state.connection !== "ready"
    || !state.capabilities.text_input;
  elements.microphoneButton.disabled = state.running
    || state.connection !== "ready"
    || !state.capabilities.voice_input;
  elements.newConversation.disabled = state.running || state.connection !== "ready";
}

function renderConversationHistory(response = null) {
  let currentSpeakButton = null;
  elements.conversation
    .querySelectorAll(":scope > :not(.date-rule):not([data-welcome])")
    .forEach((node) => node.remove());
  state.pipeline.conversation_history.forEach((turn) => {
    appendMessage("user", turn.user_transcript);
    const isCurrent = response
      && turn === state.pipeline.conversation_history.at(-1)
      && turn.assistant_response === response.spoken_response;
    const speakButton = appendMessage("assistant", turn.assistant_response, isCurrent ? {
      confirmation: confirmationKind(response),
      errors: response.errors,
      audio: response.audio,
    } : {});
    if (isCurrent) currentSpeakButton = speakButton;
  });
  const responseWasRecorded = response
    && state.pipeline.conversation_history.at(-1)?.assistant_response
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
    else if (state.pipeline.pending_memory_action) appendConfirmation("memory");
  }
  return currentSpeakButton;
}

function restoreConversationHistory() {
  renderConversationHistory();
}

function setConnectionStatus(status, health = null) {
  const previous = state.connection;
  state.connection = status;
  elements.runtimeDot.classList.toggle("is-offline", status === "offline");
  elements.runtimeDot.classList.toggle("is-connecting", status === "connecting");
  if (status === "ready") {
    elements.runtimeLabel.textContent = "Local pipeline";
    if (health?.runtime?.model) elements.runtimeModel.textContent = health.runtime.model;
  } else if (status === "connecting") {
    elements.runtimeLabel.textContent = "Reconnecting…";
  } else {
    elements.runtimeLabel.textContent = "Assistant disconnected";
    elements.runtimeModel.textContent = "retrying locally";
  }
  if (previous === "offline" && status === "ready") showToast("Local assistant reconnected");
  updateSendState();
}

async function connectPipeline({ silent = false } = {}) {
  if (!silent && state.connection !== "offline") setConnectionStatus("connecting");
  try {
    const health = await getJson("/api/health");
    state.capabilities = { ...state.capabilities, ...health.capabilities };
    setConnectionStatus("ready", health);
    elements.interactionLabel.textContent = state.capabilities.voice_input
      ? "Transcript or voice input"
      : "Transcript input · voice I/O disabled";
    if (!state.capabilities.voice_input) {
      elements.deviceStatus.textContent = (
        "Browser devices can be selected, but local STT/TTS is disabled. "
        + "Restart the server with --voice-io."
      );
    }
    elements.microphoneButton.title = state.capabilities.voice_input
      ? "Start voice input"
      : "Run the server with --voice-io to enable voice input";
    renderState();
  } catch {
    state.capabilities = {
      text_input: false,
      voice_input: false,
      voice_output: false,
      wake_word: false,
      reminders: false,
      guided_routines: false,
      privacy_centre: false,
    };
    setConnectionStatus("offline");
  }
}

async function startNewConversation() {
  if (state.running) return;
  elements.newConversation.disabled = true;
  try {
    const response = await requestJson("/api/session/reset", {});
    state.pipeline = response.state || structuredClone(defaultState);
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

async function openLocalData() {
  if (!elements.localDataDialog.open) elements.localDataDialog.showModal();
  await refreshLocalData();
}

async function refreshLocalData() {
  const privacyRequest = state.capabilities.privacy_centre
    ? getJson("/api/privacy")
    : Promise.resolve(null);
  const reminderRequest = state.capabilities.reminders
    ? getJson("/api/reminders")
    : Promise.resolve(null);
  const [privacy, reminders] = await Promise.allSettled([privacyRequest, reminderRequest]);

  if (privacy.status === "fulfilled" && privacy.value) {
    renderMemories(privacy.value);
    renderStorage(privacy.value.locations || []);
  } else {
    const message = state.capabilities.privacy_centre
      ? privacy.reason?.message || "Saved memories could not be loaded."
      : "Memory is disabled. Restart the server with --memory to save and review memories.";
    elements.memorySummary.textContent = message;
    elements.memoryList.innerHTML = `<p class="data-empty">${escapeHtml(message)}</p>`;
    elements.storageList.innerHTML = '<p class="data-empty">No persistent memory storage is active.</p>';
    elements.exportMemories.disabled = true;
    elements.forgetAllMemories.disabled = true;
  }

  if (reminders.status === "fulfilled" && reminders.value) {
    renderReminders(reminders.value.reminders || []);
  } else {
    const message = state.capabilities.reminders
      ? reminders.reason?.message || "Reminders could not be loaded."
      : "Reminders are disabled for this run.";
    elements.reminderSummary.textContent = message;
    elements.reminderList.innerHTML = `<p class="data-empty">${escapeHtml(message)}</p>`;
    elements.cancelAllReminders.disabled = true;
  }
}

function renderMemories(report) {
  const memories = Array.isArray(report.memories) ? report.memories : [];
  elements.memorySummary.textContent = memories.length === 1
    ? "1 memory is saved on this device."
    : `${memories.length} memories are saved on this device.`;
  elements.exportMemories.disabled = false;
  elements.forgetAllMemories.disabled = memories.length === 0;
  if (!memories.length) {
    elements.memoryList.innerHTML = '<p class="data-empty">No memories are saved.</p>';
    return;
  }
  elements.memoryList.innerHTML = memories.map((memory) => `
    <article class="data-item" data-memory-id="${memory.id}">
      <div class="data-item-main">
        <div>
          <p class="data-item-content">${escapeHtml(memory.content)}</p>
          <p class="data-item-meta">${escapeHtml(memory.layer_description || memory.layer)} · ${escapeHtml(memory.created || "Saved locally")}</p>
        </div>
        <div class="data-item-actions">
          <button type="button" data-memory-action="edit">Edit</button>
          <button class="delete-action" type="button" data-memory-action="delete">Delete</button>
        </div>
      </div>
    </article>`).join("");
}

function renderReminders(reminders) {
  elements.reminderSummary.textContent = reminders.length === 1
    ? "1 reminder is scheduled."
    : `${reminders.length} reminders are scheduled.`;
  elements.cancelAllReminders.disabled = reminders.length === 0;
  if (!reminders.length) {
    elements.reminderList.innerHTML = '<p class="data-empty">No reminders are scheduled.</p>';
    return;
  }
  elements.reminderList.innerHTML = reminders.map((reminder) => `
    <article class="data-item" data-reminder-id="${reminder.id}" data-reminder-text="${escapeHtml(reminder.text)}">
      <div class="data-item-main">
        <div>
          <p class="data-item-content">${escapeHtml(reminder.text)}</p>
          <p class="data-item-meta">${escapeHtml(reminder.due)}${reminder.recurrence !== "once" ? ` · Repeats ${escapeHtml(reminder.recurrence)}` : ""}</p>
        </div>
        <div class="data-item-actions">
          <button type="button" data-reminder-action="edit">Edit text</button>
          <button type="button" data-reminder-action="snooze">Snooze 10 min</button>
          <button class="delete-action" type="button" data-reminder-action="cancel">Cancel</button>
        </div>
      </div>
    </article>`).join("");
}

function renderStorage(locations) {
  if (!locations.length) {
    elements.storageList.innerHTML = '<p class="data-empty">No persistent memory storage is active.</p>';
    return;
  }
  elements.storageList.innerHTML = locations.map((location) => `
    <div class="storage-item">
      <strong>${escapeHtml(location.name)}</strong><span>${escapeHtml(location.size)}</span>
      <code>${escapeHtml(location.path)}</code>
    </div>`).join("");
}

function finishActionDialog(result) {
  const resolve = state.actionDialogResolve;
  if (!resolve) return;
  state.actionDialogResolve = null;
  if (elements.actionDialog.open) elements.actionDialog.close();
  resolve(result);
}

function requestAction({
  title,
  description,
  confirmLabel,
  inputLabel = "Updated value",
  inputValue = null,
  danger = false,
}) {
  if (state.actionDialogResolve) {
    return Promise.reject(new Error("Finish the open Local data action first."));
  }
  const hasInput = inputValue !== null;
  elements.actionTitle.textContent = title;
  elements.actionDescription.textContent = description;
  elements.actionInputField.hidden = !hasInput;
  elements.actionInputLabel.textContent = inputLabel;
  elements.actionInput.value = hasInput ? inputValue : "";
  elements.actionInput.required = hasInput;
  elements.actionInput.setCustomValidity("");
  elements.actionConfirm.textContent = confirmLabel;
  elements.actionConfirm.classList.toggle("is-danger", danger);

  return new Promise((resolve) => {
    state.actionDialogResolve = resolve;
    elements.actionDialog.showModal();
    window.requestAnimationFrame(() => {
      if (hasInput) {
        elements.actionInput.focus();
        elements.actionInput.select();
      } else {
        elements.actionConfirm.focus();
      }
    });
  });
}

async function handleMemoryAction(button) {
  const item = button.closest("[data-memory-id]");
  const identifier = Number(item.dataset.memoryId);
  const action = button.dataset.memoryAction;
  if (action === "edit") {
    const current = item.querySelector(".data-item-content").textContent.trim();
    const content = await requestAction({
      title: "Edit saved memory",
      description: "Correct this memory. The updated text will remain on this device.",
      confirmLabel: "Save change",
      inputLabel: "Memory",
      inputValue: current,
    });
    if (content === null || content === current) return;
    await requestJson("/api/privacy/memories/edit", { id: identifier, content });
    showToast("Memory updated");
  } else {
    const confirmed = await requestAction({
      title: "Delete saved memory?",
      description: "This memory will be permanently removed from this device. This cannot be undone.",
      confirmLabel: "Delete memory",
      danger: true,
    });
    if (!confirmed) return;
    await requestJson("/api/privacy/memories/delete", { id: identifier });
    showToast("Memory deleted");
  }
  await refreshLocalData();
}

async function handleReminderAction(button) {
  const item = button.closest("[data-reminder-id]");
  const identifier = Number(item.dataset.reminderId);
  const action = button.dataset.reminderAction;
  if (action === "edit") {
    const current = item.dataset.reminderText.trim();
    const text = await requestAction({
      title: "Edit reminder text",
      description: "Change what the assistant will say when this reminder is due.",
      confirmLabel: "Save change",
      inputLabel: "Reminder text",
      inputValue: current,
    });
    if (text === null || text === current) return;
    await requestJson("/api/reminders/edit", { id: identifier, text });
    showToast("Reminder updated");
  } else if (action === "snooze") {
    await requestJson("/api/reminders/snooze", { id: identifier, seconds: 600 });
    showToast("Reminder snoozed for 10 minutes");
  } else {
    const confirmed = await requestAction({
      title: "Cancel this reminder?",
      description: "The reminder will be removed and will not be announced.",
      confirmLabel: "Cancel reminder",
      danger: true,
    });
    if (!confirmed) return;
    await requestJson("/api/reminders/cancel", { id: identifier });
    showToast("Reminder cancelled");
  }
  await refreshLocalData();
}

async function exportMemories() {
  try {
    const data = await getJson("/api/privacy/export");
    const url = URL.createObjectURL(new Blob(
      [JSON.stringify(data, null, 2)],
      { type: "application/json" },
    ));
    const link = document.createElement("a");
    link.href = url;
    link.download = `granite-memories-${new Date().toISOString().slice(0, 10)}.json`;
    link.click();
    URL.revokeObjectURL(url);
    showToast("Memory export downloaded");
  } catch (error) {
    showToast(error.message);
  }
}

async function pollDueReminders() {
  if (state.connection !== "ready" || !state.capabilities.reminders) return;
  try {
    const result = await getJson("/api/reminders/due");
    for (const reminder of result.notifications || []) {
      appendMessage("assistant", reminder.announcement);
      speakText(reminder.announcement);
    }
    if ((result.notifications || []).length && elements.localDataDialog.open) {
      await refreshLocalData();
    }
  } catch {
    // Connection state and retry messaging are handled by requestJson.
  }
}

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
elements.previewVoice.addEventListener("click", () => {
  collectSettingsDraft();
  speakText("Hello. This is how Granite will sound.", state.settingsDraft);
});
elements.setupForm.addEventListener("input", () => {
  collectSettingsDraft();
  if (state.setupStep === setupSteps.length - 1) updateSetupReview();
});
elements.setupDialog.addEventListener("cancel", () => {
  state.settingsDraft = null;
});

document.documentElement.dataset.theme = window.localStorage.getItem("granite-theme") || "light";
window.localStorage.removeItem(LEGACY_PIPELINE_STORAGE_KEY);
applyPersonalSettings();
restoreConversationHistory();
connectPipeline();
window.setInterval(() => connectPipeline({ silent: true }), HEALTH_POLL_MILLISECONDS);
window.setInterval(pollDueReminders, DUE_POLL_MILLISECONDS);
if (!state.settings.setup_complete) {
  window.setTimeout(openSetup, 180);
}
