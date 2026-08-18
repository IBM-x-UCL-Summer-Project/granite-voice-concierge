// Conversation message and confirmation rendering.

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


