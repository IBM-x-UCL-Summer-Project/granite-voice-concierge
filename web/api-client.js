// Same-origin backend transport and turn request helpers.

async function requestJson(
  path,
  payload = null,
  {
    method = "POST",
    updateConnection = true,
    timeoutMilliseconds = REQUEST_TIMEOUT_MILLISECONDS,
  } = {},
) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMilliseconds);
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
    if (updateConnection) setConnectionStatus("offline");
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
  if (updateConnection) setConnectionStatus("ready");
  return body;
}

function getJson(path, options = {}) {
  return requestJson(path, null, { method: "GET", ...options });
}

function turnOptions() {
  return {
    synthesize: Boolean(state.capabilities.voice_output),
    play: false,
    response_length: state.settings.response_length,
  };
}

function requestTextTurn(transcript, { automaticRoutine = false } = {}) {
  return requestJson("/api/turn", {
    transcript,
    options: turnOptions(),
    automatic_routine: automaticRoutine,
  });
}

function requestAudioTurn(wavBase64) {
  return requestJson("/api/audio", {
    wav_base64: wavBase64,
    options: turnOptions(),
  });
}


