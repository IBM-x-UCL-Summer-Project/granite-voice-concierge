// Browser diagnostics mirrored into the local backend when DEBUG logging is active.

const diagnostics = (() => {
  const endpoint = "/api/diagnostics/client-event";
  const browserId = typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  let enabled = false;
  const pending = [];

  function summarize(value, key = "") {
    if (value === null || value === undefined) return value;
    if (typeof value === "string" && key.endsWith("base64")) {
      return `<base64 characters=${value.length}>`;
    }
    if (Array.isArray(value)) {
      return value.map((item) => summarize(item));
    }
    if (typeof value === "object") {
      return Object.fromEntries(
        Object.entries(value).map(([name, item]) => [name, summarize(item, name)]),
      );
    }
    return value;
  }

  function deliver(payload) {
    fetch(endpoint, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      keepalive: true,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }).catch((error) => {
      console.warn("[Granite] diagnostic_delivery_failed", error);
    });
  }

  function write(level, event, details = {}) {
    const payload = {
      timestamp: new Date().toISOString(),
      browser_id: browserId,
      level,
      event,
      details: summarize(details),
    };
    const consoleMethod = level === "warning" ? "warn" : level;
    const writer = console[consoleMethod] || console.log;
    writer.call(console, `[Granite] ${event}`, payload.details);
    if (!enabled) {
      pending.push(payload);
      if (pending.length > 50) pending.shift();
      return;
    }
    deliver(payload);
  }

  return Object.freeze({
    setEnabled(value) {
      const next = Boolean(value);
      if (next === enabled) return;
      enabled = next;
      write("info", "diagnostics_state_changed", { enabled });
      if (enabled) pending.splice(0).forEach(deliver);
    },
    summarize,
    debug(event, details) {
      write("debug", event, details);
    },
    info(event, details) {
      write("info", event, details);
    },
    warning(event, details) {
      write("warning", event, details);
    },
    error(event, details) {
      write("error", event, details);
    },
  });
})();
