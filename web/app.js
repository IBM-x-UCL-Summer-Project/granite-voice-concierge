const STORAGE_KEY = "granite-pipeline-state-v1";
const SETTINGS_STORAGE_KEY = "granite-personal-settings-v1";

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
  pipeline: loadState(),
  settings: loadSettings(),
  settingsDraft: null,
  setupStep: 0,
  running: false,
  capabilities: { text_input: false, voice_input: false, voice_output: false },
  recorder: null,
  playback: null,
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
};

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function loadState() {
  try {
    const persisted = window.localStorage.getItem(STORAGE_KEY);
    if (!persisted) return structuredClone(defaultState);
    const parsed = JSON.parse(persisted);
    return {
      ...structuredClone(defaultState),
      ...parsed,
      context: {
        ...structuredClone(defaultState.context),
        ...parsed.context,
        accessibility: {
          ...defaultState.context.accessibility,
          ...parsed.context?.accessibility,
        },
      },
      conversation_history: Array.isArray(parsed.conversation_history)
        ? parsed.conversation_history
        : [],
    };
  } catch {
    return structuredClone(defaultState);
  }
}

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
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.pipeline));
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
    description: "Tune wake-word sensitivity and decide how each conversation starts.",
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
    voice_first: "Wake word + transcript",
    push_to_talk: "Push to talk",
    text_first: "Transcript input",
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
    : sensitivity > 70
      ? "Sensitive"
      : "Balanced";
  elements.sensitivityOutput.textContent = `${sensitivityLabel} · ${sensitivity}%`;
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
    elements.deviceStatus.textContent = `Found ${microphones} microphone${microphones === 1 ? "" : "s"} and ${speakers} speaker${speakers === 1 ? "" : "s"}.`;
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
          Play response
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
      <strong>${isMode ? "Mode change requires confirmation" : "Memory write requires confirmation"}</strong>
      <span>${isMode ? "Driving mode changes response policy." : "No memory is written until you approve."}</span>
    </div>
    <div class="confirmation-actions">
      <button type="button" data-confirm="cancel">Cancel</button>
      <button class="confirm" type="button" data-confirm="yes">Confirm</button>
    </div>`;
  elements.conversation.appendChild(card);
}

async function requestJson(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  let body = null;
  try {
    body = await response.json();
  } catch {
    throw new Error("The local pipeline returned an unreadable response.");
  }
  if (!response.ok) {
    throw new Error(body?.error?.message || `Pipeline request failed (${response.status}).`);
  }
  return body;
}

function turnOptions() {
  return {
    synthesize: Boolean(state.capabilities.voice_output),
    play: false,
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
  if (response.context.needs_confirmation) return "mode";
  if (response.reasoning?.proposed_memory_action?.requires_confirmation) return "memory";
  return null;
}

function stopPlayback() {
  window.speechSynthesis?.cancel();
  if (!state.playback) return;
  state.playback.audio.pause();
  state.playback.audio.currentTime = 0;
  state.playback.button?.classList.remove("is-playing");
  if (state.playback.button) state.playback.button.lastChild.textContent = " Play response";
  URL.revokeObjectURL(state.playback.url);
  state.playback = null;
}

async function playResponse(button) {
  if (state.playback?.button === button) {
    stopPlayback();
    return;
  }
  stopPlayback();
  const audioPayload = button.responseAudio;
  if (!audioPayload?.wav_base64) {
    speakText(button.fallbackText || "");
    return;
  }

  const binary = window.atob(audioPayload.wav_base64);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], { type: "audio/wav" }));
  const audio = new Audio(url);
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
  audio.addEventListener("ended", stopPlayback, { once: true });
  try {
    await audio.play();
  } catch {
    stopPlayback();
    speakText(button.fallbackText || "");
  }
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

    renderConversationHistory(response);
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
    || !state.capabilities.text_input
    || !elements.input.value.trim();
  elements.modeSelect.disabled = state.running
    || Boolean(state.recorder)
    || !state.capabilities.text_input;
  elements.microphoneButton.disabled = state.running || !state.capabilities.voice_input;
}

function renderConversationHistory(response = null) {
  elements.conversation
    .querySelectorAll(":scope > :not(.date-rule):not([data-welcome])")
    .forEach((node) => node.remove());
  state.pipeline.conversation_history.forEach((turn) => {
    appendMessage("user", turn.user_transcript);
    const isCurrent = response
      && turn === state.pipeline.conversation_history.at(-1)
      && turn.assistant_response === response.spoken_response;
    appendMessage("assistant", turn.assistant_response, isCurrent ? {
      confirmation: confirmationKind(response),
      errors: response.errors,
      audio: response.audio,
    } : {});
  });
  const responseWasRecorded = response
    && state.pipeline.conversation_history.at(-1)?.assistant_response
      === response.spoken_response;
  if (response?.spoken_response && !responseWasRecorded) {
    appendMessage("assistant", response.spoken_response, {
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
}

function restoreConversationHistory() {
  renderConversationHistory();
}

async function connectPipeline() {
  try {
    const response = await fetch("/api/health", { cache: "no-store" });
    if (!response.ok) throw new Error("not ready");
    const health = await response.json();
    state.capabilities = { ...state.capabilities, ...health.capabilities };
    elements.runtimeLabel.textContent = "Local pipeline";
    elements.runtimeModel.textContent = health.runtime?.model || "configured model";
    elements.runtimeDot.classList.remove("is-offline");
    elements.interactionLabel.textContent = state.capabilities.voice_input
      ? "Transcript or voice input"
      : "Transcript input · voice I/O disabled";
    elements.microphoneButton.title = state.capabilities.voice_input
      ? "Start voice input"
      : "Run the server with --voice-io to enable voice input";
  } catch {
    state.capabilities = { text_input: false, voice_input: false, voice_output: false };
    elements.runtimeLabel.textContent = "Pipeline offline";
    elements.runtimeModel.textContent = "unavailable";
    elements.runtimeDot.classList.add("is-offline");
  }
  updateSendState();
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
applyPersonalSettings();
restoreConversationHistory();
connectPipeline();
if (!state.settings.setup_complete) {
  window.setTimeout(openSetup, 180);
}
