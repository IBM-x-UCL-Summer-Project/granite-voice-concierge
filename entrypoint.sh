#!/bin/bash
set -e

echo "🚀 Granite Voice Concierge - Starting..."

# Ensure persistent directories exist
mkdir -p .local/memory
mkdir -p .local/preferences
mkdir -p .local/reminders
mkdir -p .local/logs

echo "✓ Persistent directories ready"

# Wait for Ollama to be healthy if OLLAMA_API_URL is set
if [ ! -z "$OLLAMA_API_URL" ]; then
    echo "⏳ Waiting for Ollama to be ready at $OLLAMA_API_URL..."
    max_attempts=30
    attempt=1
    while [ $attempt -le $max_attempts ]; do
        if curl -s "$OLLAMA_API_URL/api/tags" > /dev/null 2>&1; then
            echo "✓ Ollama is ready!"
            break
        fi
        echo "  Attempt $attempt/$max_attempts..."
        sleep 2
        attempt=$((attempt + 1))
    done

    if [ $attempt -gt $max_attempts ]; then
        echo "⚠ Warning: Ollama not responding after $max_attempts attempts"
        echo "  Proceeding anyway - ensure Ollama is running separately"
    fi
fi

echo "📝 Starting application with: $@"
exec "$@"
