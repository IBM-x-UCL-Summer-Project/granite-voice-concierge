// Memory, reminder, privacy-centre, and export controls.

async function openLocalData() {
  diagnostics.info("local_data_opened", { capabilities: state.capabilities });
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
  diagnostics.debug("local_data_refreshed", {
    privacy_status: privacy.status,
    privacy: privacy.status === "fulfilled" ? privacy.value : null,
    privacy_error: privacy.status === "rejected" ? privacy.reason?.message : null,
    reminders_status: reminders.status,
    reminders: reminders.status === "fulfilled" ? reminders.value : null,
    reminders_error: reminders.status === "rejected" ? reminders.reason?.message : null,
  });

  if (privacy.status === "fulfilled" && privacy.value) {
    renderMemories(privacy.value);
    renderStorage(privacy.value.locations || []);
  } else {
    const message = state.capabilities.privacy_centre
      ? privacy.reason?.message || "Saved memories could not be loaded."
      : "Memory was disabled for this run. Restart without --no-memory to save and review memories.";
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
    downloadJson(
      data,
      `granite-memories-${new Date().toISOString().slice(0, 10)}.json`,
    );
    showToast("Memory export downloaded");
  } catch (error) {
    showToast(error.message);
  }
}

function exportChat() {
  const history = state.sessionHistory;
  if (!history.length) {
    showToast("There is no conversation to export yet");
    return;
  }
  const link = document.createElement("a");
  link.href = "/api/session/export";
  link.download = `granite-chat-${new Date().toISOString().slice(0, 10)}.json`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  showToast("Preparing chat export");
}

function downloadJson(data, filename) {
  const url = URL.createObjectURL(new Blob(
    [JSON.stringify(data, null, 2)],
    { type: "application/json" },
  ));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function pollDueReminders() {
  if (state.connection !== "ready" || !state.capabilities.reminders) return;
  try {
    const result = await getJson("/api/reminders/due");
    if ((result.notifications || []).length) {
      diagnostics.info("due_reminders_received", {
        notifications: result.notifications,
      });
    }
    for (const reminder of result.notifications || []) {
      const speakButton = appendMessage("assistant", reminder.announcement, {
        audio: reminder.audio,
      });
      if (speakButton) await playResponse(speakButton);
    }
    if ((result.notifications || []).length && elements.localDataDialog.open) {
      await refreshLocalData();
    }
  } catch (error) {
    diagnostics.warning("due_reminder_poll_failed", {
      error_message: error.message,
    });
    // Connection state and retry messaging are handled by requestJson.
  }
}

