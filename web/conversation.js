// Conversation message and confirmation rendering.

// Turn errors the assistant already explains out loud. When it has just said
// "I didn't catch that", repeating "empty_transcript" in a red card tells the
// user nothing and makes a handled situation look like a crash.
const SELF_EXPLAINED_ERRORS = new Set(["empty_transcript"]);

// Plain-English replacements for the rest. These are conditions a user can act
// on, so they say what happened and what still works.
const ERROR_NOTICES = {
  stt_failed: "I couldn't make out any speech. Try again, or type instead.",
  tts_failed: "Speech isn't available, so this reply is text only.",
  playback_failed: "The reply couldn't be played aloud, but the text is above.",
  reasoning_failed: "I had trouble working out a reply. Please try again.",
  memory_retrieval_failed: "I couldn't check what I've remembered for this reply.",
  memory_action_failed: "I couldn't save that to memory.",
  runtime_context_failed: "I couldn't check the time or device details.",
};

function describeTurnErrors(errors) {
  const notices = [];
  for (const code of errors || []) {
    if (SELF_EXPLAINED_ERRORS.has(code)) continue;
    notices.push(ERROR_NOTICES[code] || `Something went wrong (${code}).`);
  }
  return notices;
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
      <div class="message-meta"><strong>${isAssistant ? "Granite" : "You"}</strong>${messageTimeMarkup(options.timestamp)}</div>
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
  const notices = describeTurnErrors(options.errors);
  if (notices.length) {
    const error = document.createElement("div");
    error.className = "error-card";
    error.textContent = notices.join(" ");
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

function appendPendingMessage(label) {
  removePendingMessage();
  const article = document.createElement("article");
  article.className = "message message-assistant message-pending";
  article.dataset.pending = "true";
  article.innerHTML = `
    <div class="avatar" aria-hidden="true">G</div>
    <div class="message-body">
      <div class="message-meta"><strong>Granite</strong><span>Working locally</span></div>
      <div class="bubble">
        <span>${escapeHtml(label)}</span>
        <span class="thinking-dots" aria-hidden="true"><span></span><span></span><span></span></span>
      </div>
    </div>`;
  elements.conversation.appendChild(article);
  article.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function messageTime(timestamp) {
  if (!timestamp) return "Now";
  const moment = new Date(timestamp);
  if (Number.isNaN(moment.getTime())) return "Now";
  return new Intl.DateTimeFormat([], {
    hour: "2-digit",
    minute: "2-digit",
  }).format(moment);
}

function messageTimeMarkup(timestamp) {
  if (!timestamp) return "<span>Now</span>";
  const moment = new Date(timestamp);
  if (Number.isNaN(moment.getTime())) return "<span>Now</span>";
  const iso = moment.toISOString();
  return `<time datetime="${escapeHtml(iso)}" title="${escapeHtml(moment.toLocaleString())}">${escapeHtml(messageTime(iso))}</time>`;
}

function removePendingMessage() {
  elements.conversation.querySelector('[data-pending="true"]')?.remove();
}

function appendConfirmation(kind) {
  const card = document.createElement("div");
  card.className = "confirmation-card";
  const isMode = kind === "mode";
  const isBulkDelete = kind === "bulk-memory-delete";
  const isRoutine = kind === "routine";
  card.innerHTML = `
    <div>
      <strong>${isMode ? "Mode change requires confirmation" : isBulkDelete ? "Delete every saved memory?" : isRoutine ? "Go back one routine step?" : "Memory change requires confirmation"}</strong>
      <span>${isMode ? "Driving mode changes response policy." : isBulkDelete ? "This cannot be undone." : isRoutine ? "The routine stays on this step until you approve." : "No memory is changed until you approve."}</span>
    </div>
    <div class="confirmation-actions">
      <button type="button" data-confirm="cancel">Cancel</button>
      <button class="confirm" type="button" data-confirm="yes">Confirm</button>
    </div>`;
  elements.conversation.appendChild(card);
}


