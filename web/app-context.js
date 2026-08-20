// Shared browser state, DOM references, and timing constants.

const LEGACY_PIPELINE_STORAGE_KEY = "granite-pipeline-state-v1";
const SETTINGS_STORAGE_KEY = "granite-personal-settings-v1";
const HEALTH_POLL_MILLISECONDS = 5000;
const DUE_POLL_MILLISECONDS = 5000;
const REQUEST_TIMEOUT_MILLISECONDS = 130000;
const WAKE_WORD_REQUEST_TIMEOUT_MILLISECONDS = 5000;
const WAKE_WORD_FRAME_SAMPLES = 3200;
const VOICE_COMMAND_FRAME_SAMPLES = 3200;
const WAKE_COMMAND_START_TIMEOUT_MILLISECONDS = 7000;
const WAKE_COMMAND_ARM_DELAY_MILLISECONDS = 350;
const PUSH_TO_TALK_MAXIMUM_MILLISECONDS = 60000;
const SILENT_WAV_URL = "data:audio/wav;base64,UklGRiYAAABXQVZFZm10IBAAAAABAAEAQB8AAIA+AAACABAAZGF0YQIAAAAAAA==";
const {
  isPlaybackBargeInCommand,
  shouldAutoPlayResponse: playbackPolicyAllows,
  shouldListenForVoiceCommands,
} = window.GranitePlaybackPolicy;
const {
  prepareWakeCapture,
  speechCanStart,
} = window.GraniteWakeCapturePolicy;

const defaultSettings = {
  version: 2,
  setup_complete: false,
  microphone_id: "default",
  speaker_id: "default",
  speech_rate: 1,
  volume: 80,
  response_length: "normal",
  wake_word_sensitivity: 60,
  wake_end_pause_seconds: 1.8,
  wake_follow_up_seconds: 7,
  wake_max_request_seconds: 20,
  wake_auto_follow_up: true,
  wake_show_conversation: false,
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
  pending_bulk_memory_delete: false,
};

const state = {
  pipeline: structuredClone(defaultState),
  sessionHistory: [],
  sessionLoaded: false,
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
    routine_barge_in: false,
    playback_barge_in: false,
    diagnostics: false,
    privacy_centre: false,
  },
  connection: "connecting",
  recorder: null,
  recorderStarting: false,
  wakeWord: {
    active: false,
    generation: 0,
    audio: null,
    phase: "inactive",
    frameChunks: [],
    frameSampleCount: 0,
    sendingFrame: false,
    commandChunks: [],
    commandStartedAt: 0,
    speechArmedAt: 0,
    lastVoiceAt: 0,
    voiceDetected: false,
    followUp: false,
    noiseFloor: 0.004,
    timing: null,
  },
  routine: {
    active: false,
    status: null,
    awaiting_choice: false,
    awaiting_confirmation: false,
    auto_advance_seconds: 6,
    autoTimer: null,
    confirmationTimer: null,
    confirmationReady: false,
    autoGeneration: 0,
  },
  voiceCommands: {
    serverActive: false,
    sendingFrame: false,
    frameChunks: [],
    frameSampleCount: 0,
    audio: null,
    generation: 0,
    starting: false,
  },
  playback: null,
  responseAudioElement: null,
  actionDialogResolve: null,
  setupPrompted: false,
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
  wakeWordButton: document.querySelector("#wake-word-button"),
  wakeWordScreen: document.querySelector("#wake-word-screen"),
  wakeWordCloseForm: document.querySelector("#wake-word-close-form"),
  wakeWordTitle: document.querySelector("#wake-word-title"),
  wakeWordStatus: document.querySelector("#wake-word-status"),
  wakeWordDetail: document.querySelector("#wake-word-detail"),
  wakeConversationToggle: document.querySelector("#wake-conversation-toggle"),
  wakeConversationPanel: document.querySelector("#wake-conversation-panel"),
  wakeConversationList: document.querySelector("#wake-conversation-list"),
  wakePushButton: document.querySelector("#wake-push-button"),
  wakePushLabel: document.querySelector("#wake-push-label"),
  wakeCancelButton: document.querySelector("#wake-cancel-button"),
  wakeQuickSensitivity: document.querySelector("#wake-quick-sensitivity"),
  wakeQuickSensitivityOutput: document.querySelector("#wake-quick-sensitivity-output"),
  wakeQuickPause: document.querySelector("#wake-quick-pause"),
  wakeQuickPauseOutput: document.querySelector("#wake-quick-pause-output"),
  wakeQuickFollowUp: document.querySelector("#wake-quick-follow-up"),
  wakeQuickFollowUpOutput: document.querySelector("#wake-quick-follow-up-output"),
  wakeQuickAutoFollowUp: document.querySelector("#wake-quick-auto-follow-up"),
  wakeQuickMaximum: document.querySelector("#wake-quick-maximum"),
  wakeQuickMaximumOutput: document.querySelector("#wake-quick-maximum-output"),
  startupScreen: document.querySelector("#startup-screen"),
  startupTitle: document.querySelector("#startup-title"),
  startupMessage: document.querySelector("#startup-message"),
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
  wakeEndPause: document.querySelector("#wake-end-pause"),
  wakeEndPauseOutput: document.querySelector("#wake-end-pause-output"),
  wakeFollowUp: document.querySelector("#wake-follow-up"),
  wakeFollowUpOutput: document.querySelector("#wake-follow-up-output"),
  wakeAutoFollowUp: document.querySelector("#wake-auto-follow-up"),
  wakeMaximumRequest: document.querySelector("#wake-maximum-request"),
  wakeMaximumRequestOutput: document.querySelector("#wake-maximum-request-output"),
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
  exportChat: document.querySelector("#export-chat-button"),
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
