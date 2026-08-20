// Same-origin backend transport and turn request helpers.

async function requestJson(
  path,
  payload = null,
  {
    method = "POST",
    updateConnection = true,
    timeoutMilliseconds = REQUEST_TIMEOUT_MILLISECONDS,
    diagnostic = true,
  } = {},
) {
  const logLifecycle = diagnostic && ![
    "/api/wake-word/frame",
    "/api/routine-command/frame",
    "/api/diagnostics/wake-timing",
  ].includes(path);
  const requestId = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  const startedAt = performance.now();
  if (logLifecycle) {
    diagnostics.debug("api_request_started", {
      request_id: requestId,
      method,
      path,
      timeout_ms: timeoutMilliseconds,
      payload,
    });
  }
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMilliseconds);
  let response;
  try {
    response = await fetch(path, {
      method,
      cache: "no-store",
      credentials: "same-origin",
      headers: {
        "X-Client-Request-ID": requestId,
        ...(payload === null ? {} : { "Content-Type": "application/json" }),
      },
      body: payload === null ? undefined : JSON.stringify(payload),
      signal: controller.signal,
    });
  } catch (error) {
    diagnostics.error("api_request_failed", {
      request_id: requestId,
      method,
      path,
      duration_ms: Math.round(performance.now() - startedAt),
      error_name: error.name,
      error_message: error.message,
    });
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
    diagnostics.error("api_response_unreadable", {
      request_id: requestId,
      server_request_id: response.headers.get("X-Request-ID"),
      method,
      path,
      status: response.status,
      duration_ms: Math.round(performance.now() - startedAt),
    });
    throw new Error("The local pipeline returned an unreadable response.");
  }
  if (!response.ok) {
    diagnostics.warning("api_response_rejected", {
      request_id: requestId,
      server_request_id: response.headers.get("X-Request-ID"),
      method,
      path,
      status: response.status,
      duration_ms: Math.round(performance.now() - startedAt),
      response: body,
    });
    throw new Error(body?.error?.message || `Local request failed (${response.status}).`);
  }
  if (logLifecycle) {
    diagnostics.debug("api_request_completed", {
      request_id: requestId,
      server_request_id: response.headers.get("X-Request-ID"),
      method,
      path,
      status: response.status,
      duration_ms: Math.round(performance.now() - startedAt),
      response: body,
    });
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

function requestVoicePreview() {
  return requestJson("/api/speech/preview", {});
}
