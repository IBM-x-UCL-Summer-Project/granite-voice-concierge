const STORAGE_KEY = "granite-pipeline-state-v1";

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
  pending_memory_action: null,
  pending_memory_scope: null,
};

const state = {
  pipeline: loadState(),
  turn: 0,
  running: false,
};

const elements = {
  form: document.querySelector("#turn-form"),
  input: document.querySelector("#transcript-input"),
  send: document.querySelector("#send-button"),
  conversation: document.querySelector("#conversation"),
  modeLabel: document.querySelector("#mode-label"),
  pipelineList: document.querySelector("#pipeline-list"),
  turnCounter: document.querySelector("#turn-counter"),
  statusOrb: document.querySelector("#status-orb"),
  turnStatusLabel: document.querySelector("#turn-status-label"),
  turnStatusDetail: document.querySelector("#turn-status-detail"),
  turnLatency: document.querySelector("#turn-latency"),
  stateJson: document.querySelector("#state-json"),
  copyState: document.querySelector("#copy-state"),
  toast: document.querySelector("#toast"),
  themeButton: document.querySelector("#theme-button"),
};

const delay = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

function loadState() {
  try {
    const persisted = window.localStorage.getItem(STORAGE_KEY);
    return persisted ? { ...defaultState, ...JSON.parse(persisted) } : structuredClone(defaultState);
  } catch {
    return structuredClone(defaultState);
  }
}

function saveState() {
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(state.pipeline));
  renderState();
}

function syntaxHighlight(value) {
  return escapeHtml(JSON.stringify(value, null, 2))
    .replace(/(&quot;.*?&quot;)(?=\s*:)/g, '<span class="json-key">$1</span>')
    .replace(/:\s*(&quot;.*?&quot;)/g, ': <span class="json-string">$1</span>')
    .replace(/\bnull\b/g, '<span class="json-null">null</span>');
}

function renderState() {
  elements.stateJson.innerHTML = syntaxHighlight(state.pipeline);
  elements.modeLabel.textContent = capitalize(state.pipeline.context.mode);
  setText("#inspector-mode", state.pipeline.context.mode);
  setText("#inspector-pending-mode", valueOrNull(state.pipeline.context.pending_mode));
  setText("#inspector-memory-scope", state.pipeline.pending_memory_scope || "none");
  setText(
    "#inspector-memory-action",
    state.pipeline.pending_memory_action?.action || "null",
  );
}

function setText(selector, value) {
  const node = document.querySelector(selector);
  if (node) node.textContent = String(value);
}

function valueOrNull(value) {
  return value === null || value === undefined || value === "" ? "null" : value;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function capitalize(value) {
  return value.charAt(0).toUpperCase() + value.slice(1);
}

function setStage(stageName, status, label) {
  const stage = document.querySelector(`[data-stage="${stageName}"]`);
  stage.classList.remove("is-idle", "is-running", "is-complete", "is-error", "is-skipped");
  stage.classList.add(`is-${status}`);
  stage.querySelector(".stage-state").textContent = label || capitalize(status);
}

function resetStages() {
  document.querySelectorAll(".pipeline-stage").forEach((stage) => {
    stage.classList.remove("is-running", "is-complete", "is-error", "is-skipped");
    stage.classList.add("is-idle");
    stage.querySelector(".stage-state").textContent = "Idle";
  });
}

function openStage(stageName) {
  document.querySelectorAll(".pipeline-stage").forEach((stage) => {
    const button = stage.querySelector(":scope > button");
    const detail = stage.querySelector(":scope > .stage-detail");
    const expanded = stage.dataset.stage === stageName;
    button.setAttribute("aria-expanded", String(expanded));
    detail.hidden = !expanded;
  });
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

function buildResponse(transcript) {
  const normalized = transcript.trim().toLowerCase();
  const previousState = structuredClone(state.pipeline);
  const response = {
    state: structuredClone(state.pipeline),
    transcript: { text: transcript, language: "en", language_probability: 0.98 },
    spoken_response: "",
    context: {
      mode: state.pipeline.context.mode,
      mode_changed: false,
      needs_confirmation: false,
      command_action: detectCommand(normalized),
      confirmation_prompt: "",
    },
    reasoning: null,
    memory_operation: { attempted: false, succeeded: false, reason: "" },
    errors: [],
    audio: null,
  };

  if (state.pipeline.context.pending_mode) {
    if (isConfirmation(normalized)) {
      const target = state.pipeline.context.pending_mode;
      response.state.context.mode = target;
      response.state.context.pending_mode = null;
      response.context.mode = target;
      response.context.mode_changed = true;
      response.spoken_response = `${capitalize(target)} mode is now active.`;
      response.reasoning = reasoning("high");
      return response;
    }
    if (isCancellation(normalized)) {
      response.state.context.pending_mode = null;
      response.context.command_action = "cancel";
      response.spoken_response = "Okay, I’ll stay in home mode.";
      response.reasoning = reasoning("high");
      return response;
    }
  }

  if (state.pipeline.pending_memory_action) {
    if (isConfirmation(normalized)) {
      response.memory_operation = { attempted: true, succeeded: true, reason: "stored_successfully" };
      response.spoken_response = "Done. I’ll remember that preference.";
      response.state.pending_memory_action = null;
      response.state.pending_memory_scope = null;
      response.reasoning = reasoning("high");
      return response;
    }
    if (isCancellation(normalized)) {
      response.spoken_response = "Okay, I won’t save it.";
      response.state.pending_memory_action = null;
      response.state.pending_memory_scope = null;
      response.context.command_action = "cancel";
      response.reasoning = reasoning("high");
      return response;
    }
  }

  const requestedMode = detectMode(normalized);
  if (requestedMode === "driving" && state.pipeline.context.mode !== "driving") {
    const prompt = "Driving mode uses very short, safety-aware responses. Please confirm before I switch.";
    response.spoken_response = prompt;
    response.context.needs_confirmation = true;
    response.context.confirmation_prompt = prompt;
    response.state.context.pending_mode = "driving";
    response.state.last_spoken_response = prompt;
    return response;
  }
  if (requestedMode && requestedMode !== state.pipeline.context.mode) {
    response.state.context.mode = requestedMode;
    response.context.mode = requestedMode;
    response.context.mode_changed = true;
    response.spoken_response = `${capitalize(requestedMode)} mode is now active.`;
    response.reasoning = reasoning("high");
    return response;
  }

  if (/(remember|save|keep in mind)/.test(normalized)) {
    const content = normalized.includes("short")
      ? "User prefers short answers."
      : transcript.replace(/^(please\s+)?(remember|save)(\s+that)?\s*/i, "");
    const action = {
      action: "store",
      content,
      rationale: "User explicitly asked the assistant to remember this preference.",
      requires_confirmation: true,
    };
    response.spoken_response = "I can remember that. Please confirm before I save it.";
    response.reasoning = reasoning("high", action);
    response.state.pending_memory_action = action;
    response.state.pending_memory_scope = "personal_relevant";
    return response;
  }

  if (normalized.includes("simulate error")) {
    response.spoken_response = "I can’t reach local reasoning right now. Please try again.";
    response.reasoning = reasoning("low");
    response.errors = ["reasoning_failed"];
    return response;
  }

  if (normalized.includes("pasta")) {
    response.spoken_response = "For a simple pasta, you’ll need pasta, olive oil, garlic, tomatoes, salt, and parmesan. I can turn that into a shopping list.";
    response.state.context.last_topic = "pasta dinner";
    response.reasoning = reasoning("high");
    return response;
  }

  if (response.context.command_action === "repeat" && previousState.last_spoken_response) {
    response.spoken_response = previousState.last_spoken_response;
    response.reasoning = reasoning("high");
    return response;
  }

  response.spoken_response = "I’ve understood your request. The app pipeline will pass this transcript, context, and relevant memories to the local Granite model.";
  response.reasoning = reasoning("medium");
  return response;
}

function reasoning(confidence, proposedMemoryAction = null) {
  return {
    confidence,
    needs_confirmation: Boolean(proposedMemoryAction),
    proposed_memory_action: proposedMemoryAction,
    mode_suggestion: null,
  };
}

function detectMode(text) {
  const normalized = text.trim().toLowerCase();
  const firstWord = normalized.split(/\s+/, 1)[0]?.replace(/[.,!?]+$/g, "") || "";
  const questionPrefixes = new Set([
    "what", "why", "how", "when", "where", "who", "which",
    "is", "are", "do", "does", "did", "can", "could", "would", "should",
  ]);
  if (normalized.endsWith("?") || questionPrefixes.has(firstWord)) return null;

  const modes = {
    cooking: ["cooking", "kitchen"],
    shopping: ["shopping", "shop"],
    driving: ["driving", "drive"],
    home: ["home", "living"],
  };
  for (const [mode, aliases] of Object.entries(modes)) {
    const aliasPattern = aliases.join("|");
    const target = `(?:${aliasPattern})(?:\\s+mode)?`;
    const patterns = [
      `(?:switch|change|go)\\s+(?:me\\s+)?to\\s+(?:the\\s+)?${target}`,
      `(?:enter|enable|activate|start|use)\\s+(?:the\\s+)?${target}`,
      `(?:${aliasPattern})\\s+mode`,
    ];
    if (patterns.some((pattern) => matchesCommand(normalized, pattern))) return mode;
  }
  return null;
}

function detectCommand(text) {
  if (matchesCommand(text, "(?:repeat(?:\\s+(?:that|this|it))?|say\\s+that\\s+again)")) return "repeat";
  if (matchesCommand(text, "(?:next\\s+step|what(?:'s|\\s+is)\\s+the\\s+next\\s+step)")) return "next_step";
  if (matchesCommand(text, "stop(?:\\s+(?:speaking|talking|that|this|now|the\\s+response|playback))?")) return "stop";
  if (matchesCommand(text, "(?:cancel(?:\\s+(?:that|this))?|never\\s+mind|nevermind)")) return "cancel";
  return null;
}

function matchesCommand(text, commandPattern) {
  const pattern = new RegExp(`^(?:please\\s+)?${commandPattern}(?:\\s+please)?[.!]*$`);
  return pattern.test(text.trim().toLowerCase());
}

function isConfirmation(text) {
  return matchesCommand(text, "(?:yes(?:\\s*,?\\s*confirm)?|confirm|okay|ok|go\\s+ahead)");
}

function isCancellation(text) {
  return ["cancel", "stop"].includes(detectCommand(text));
}

function confirmationKind(response) {
  if (response.context.needs_confirmation) return "mode";
  if (response.reasoning?.proposed_memory_action?.requires_confirmation) return "memory";
  return null;
}

function updateInspector(response) {
  setText("#inspector-transcript", response.transcript?.text || "—");
  setText("#inspector-mode", response.context.mode);
  setText("#inspector-pending-mode", valueOrNull(response.state.context.pending_mode));
  setText("#inspector-command", valueOrNull(response.context.command_action));
  setText("#inspector-confirmation", response.context.needs_confirmation);
  setText("#inspector-memory-scope", response.state.pending_memory_scope || "none");
  setText("#inspector-memory-action", response.state.pending_memory_action?.action || "null");
  setText("#inspector-memory-attempted", response.memory_operation.attempted);
  setText("#inspector-memory-result", response.memory_operation.reason || "—");
  setText("#inspector-confidence", response.reasoning?.confidence || "not invoked");
  setText("#inspector-reasoning-confirmation", response.reasoning?.needs_confirmation ?? "—");
  setText("#inspector-mode-suggestion", valueOrNull(response.reasoning?.mode_suggestion));
  setText("#inspector-audio", response.audio ? "available" : "null");
}

async function runTurn(transcript) {
  if (!transcript.trim() || state.running) return;
  state.running = true;
  state.turn += 1;
  elements.turnCounter.textContent = `TURN ${String(state.turn).padStart(2, "0")}`;
  elements.input.value = "";
  autoSizeInput();
  updateSendState();
  appendMessage("user", transcript);
  resetStages();
  elements.statusOrb.className = "status-orb is-running";
  elements.turnStatusLabel.textContent = "Processing turn";
  elements.turnStatusDetail.textContent = "Transcript received";
  elements.turnLatency.textContent = "…";

  const timeline = [
    ["input", "Transcript accepted", 180],
    ["context", "Applying context policy", 260],
    ["memory", "Retrieving relevant memory", 300],
    ["reasoning", "Generating locally", 520],
    ["output", "Preparing spoken response", 240],
  ];
  let previous = null;
  for (const [stage, detail, duration] of timeline) {
    if (previous) setStage(previous, "complete", "Done");
    setStage(stage, "running", "Running");
    openStage(stage);
    elements.turnStatusDetail.textContent = detail;
    await delay(duration);
    previous = stage;
  }

  const response = buildResponse(transcript);
  const errorStage = response.errors.includes("reasoning_failed") ? "reasoning" : null;
  if (errorStage) {
    setStage(errorStage, "error", "Error");
    setStage("output", "complete", "Fallback");
  } else {
    setStage("output", "complete", response.audio ? "Audio" : "Text");
  }
  if (!response.reasoning) setStage("reasoning", "skipped", "Bypass");
  state.pipeline = response.state;
  state.pipeline.last_spoken_response = response.spoken_response;
  saveState();
  updateInspector(response);
  appendMessage("assistant", response.spoken_response, {
    confirmation: confirmationKind(response),
    errors: response.errors,
  });

  const elapsed = timeline.reduce((total, item) => total + item[2], 0);
  elements.statusOrb.className = response.errors.length ? "status-orb is-error" : "status-orb is-complete";
  elements.turnStatusLabel.textContent = response.errors.length ? "Completed with fallback" : "Turn complete";
  elements.turnStatusDetail.textContent = response.errors.length
    ? response.errors.join(", ")
    : response.context.needs_confirmation || response.reasoning?.needs_confirmation
      ? "Waiting for confirmation"
      : "State persisted for next turn";
  elements.turnLatency.textContent = `${elapsed} ms`;
  state.running = false;
  updateSendState();
}

function autoSizeInput() {
  elements.input.style.height = "auto";
  elements.input.style.height = `${Math.min(elements.input.scrollHeight, 140)}px`;
}

function updateSendState() {
  elements.send.disabled = state.running || !elements.input.value.trim();
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

elements.pipelineList.addEventListener("click", (event) => {
  const button = event.target.closest(".pipeline-stage > button");
  if (!button) return;
  const detail = button.nextElementSibling;
  const expanded = button.getAttribute("aria-expanded") === "true";
  button.setAttribute("aria-expanded", String(!expanded));
  detail.hidden = expanded;
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
  if (speak) showToast("Browser playback will use audio when the backend returns it.");
});

elements.copyState.addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(JSON.stringify(state.pipeline, null, 2));
    showToast("Pipeline state copied");
  } catch {
    showToast("Copy is unavailable in this browser");
  }
});

elements.themeButton.addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  document.documentElement.dataset.theme = next;
  window.localStorage.setItem("granite-theme", next);
});

document.documentElement.dataset.theme = window.localStorage.getItem("granite-theme") || "light";
renderState();
