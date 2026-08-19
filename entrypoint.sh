#!/bin/bash
set -e

echo "Granite Voice Concierge - Starting..."

# Ensure persistent directories exist
mkdir -p .local/memory
mkdir -p .local/preferences
mkdir -p .local/reminders
mkdir -p .local/logs

echo "Persistent directories ready"

# The application stores its selected reasoning host in a local JSON file.
# Keep the user's model choices, but replace the host with the configured
# native Ollama address on every container start.
if [ -n "${OLLAMA_API_URL:-}" ]; then
    python3 - <<'PY'
import json
import os
from pathlib import Path

path = Path(".local/reasoning-model-selection.json")
selection = {}

if path.exists():
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(loaded, dict):
            selection = loaded
    except (OSError, json.JSONDecodeError):
        print(f"Ignoring invalid model selection file: {path}")

selection.setdefault("schema_version", 2)
selection.setdefault("backend", "ollama")
selection["model"] = os.environ.get("REASONING_MODEL", "granite4.1:8b")
selection.setdefault("fallback_model", "granite3.3:2b")
selection.setdefault("fallback_policy", "startup_missing_primary")
if selection["fallback_model"] == selection["model"]:
    selection["fallback_model"] = None
    selection["fallback_policy"] = "disabled"
selection["host"] = os.environ["OLLAMA_API_URL"]

temporary_path = path.with_suffix(".json.tmp")
temporary_path.write_text(
    json.dumps(selection, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
temporary_path.replace(path)
print(f"Configured reasoning host: {selection['host']}")
print(f"Configured reasoning model: {selection['model']}")
PY

    echo "Waiting for Ollama to be ready at $OLLAMA_API_URL..."
    max_attempts="${OLLAMA_WAIT_ATTEMPTS:-30}"
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        if curl -s "$OLLAMA_API_URL/api/tags" > /dev/null 2>&1; then
            echo "Ollama is ready!"
            break
        fi
        echo "  Attempt $attempt/$max_attempts..."
        sleep 2
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        echo "Warning: Ollama not responding after $max_attempts attempts"
        echo "  Proceeding anyway - ensure Ollama is running separately"
    fi
fi

echo "Starting application with: $@"
exec "$@"
