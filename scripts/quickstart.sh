#!/bin/bash
set -e

echo "Granite Voice Concierge - Quick Start"
echo ""

# Docker Compose reads .env automatically, but native Ollama commands do not.
# Import the same file while preserving explicit shell overrides, which have
# higher precedence in Compose as well.
shell_ollama_model_set="${OLLAMA_MODEL+x}"
shell_ollama_model="${OLLAMA_MODEL:-}"
shell_embedding_model_set="${OLLAMA_EMBEDDING_MODEL+x}"
shell_embedding_model="${OLLAMA_EMBEDDING_MODEL:-}"
if [ -f .env ]; then
    set -a
    # The checked-in template is shell-compatible as well as Compose-compatible.
    . ./.env
    set +a
fi
if [ -n "$shell_ollama_model_set" ]; then
    export OLLAMA_MODEL="$shell_ollama_model"
fi
if [ -n "$shell_embedding_model_set" ]; then
    export OLLAMA_EMBEDDING_MODEL="$shell_embedding_model"
fi

# Check required host applications.
if ! command -v docker &> /dev/null; then
    echo "Docker not found. Please install Docker Desktop"
    exit 1
fi

if ! docker compose version > /dev/null 2>&1; then
    echo "Docker Compose plugin not found. Please install Docker Desktop"
    exit 1
fi

echo "Docker found"
echo ""

if ! command -v ollama &> /dev/null; then
    # The install command differs per platform, and telling a Linux user to run
    # brew is worse than saying nothing.
    echo "Ollama not found. Install it first:"
    if [ "$(uname -s)" = "Darwin" ]; then
        echo "  brew install --cask ollama-app"
    else
        echo "  curl -fsSL https://ollama.com/install.sh | sh"
    fi
    echo "  or download it from https://ollama.com/download"
    exit 1
fi

if ! curl --fail --silent http://127.0.0.1:11434/api/tags > /dev/null; then
    echo "Native Ollama is not responding on http://127.0.0.1:11434"
    echo "Start the Ollama application, or run:"
    echo "  OLLAMA_HOST=0.0.0.0:11434 ollama serve"
    exit 1
fi

echo "Native Ollama is ready"
echo ""

# OLLAMA_HOST is read by the server as the address to bind and by the CLI as the
# address to reach. Someone who set it to 0.0.0.0 so the container could connect
# has also pointed their CLI at 0.0.0.0, where "ollama show" can report a model
# missing that is really present. Pin the CLI to loopback for the calls below.
caller_ollama_host="${OLLAMA_HOST:-}"
export OLLAMA_HOST="http://127.0.0.1:11434"

# Make sure one model is present locally, pulling it if it is not. A failed pull
# stops the script: continuing would build and start everything only for the
# first turn to fail with a missing model.
ensure_model() {
    model_name="$1"
    if ollama show "$model_name" > /dev/null 2>&1; then
        return 0
    fi

    echo "Downloading $model_name (first run only)..."
    if ! ollama pull "$model_name"; then
        echo ""
        echo "Could not download $model_name."
        echo ""
        echo "Check the name exists and that there is disk space for it:"
        echo "  ollama pull $model_name"
        echo "  ollama list"
        echo ""
        echo "To use a smaller model instead, set it and run this script again:"
        echo "  OLLAMA_MODEL=granite4.1:3b ./scripts/quickstart.sh"
        exit 1
    fi
}

# Models are owned by native Ollama and remain outside the Docker image.
export OLLAMA_MODEL="${OLLAMA_MODEL:-granite4.1:8b}"
ensure_model "$OLLAMA_MODEL"

export OLLAMA_EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-granite-embedding:278m}"
ensure_model "$OLLAMA_EMBEDDING_MODEL"

# The container needs the host address, not the loopback one used above.
if [ -n "$caller_ollama_host" ]; then
    export OLLAMA_HOST="$caller_ollama_host"
else
    unset OLLAMA_HOST
fi

# Creating the bind-mount source on the host avoids Docker creating a root-owned
# directory on native Linux. Existing application state is left untouched.
mkdir -p data/.local/memory data/.local/preferences \
    data/.local/reminders data/.local/logs

echo "Building Docker image..."
docker compose build

# Verify the host service is reachable through Docker Desktop before starting
# the long-running application container.
echo "Checking Ollama access from Docker..."
if ! docker compose run --rm --no-deps --entrypoint sh voice-concierge \
    -c 'curl --fail --silent "$OLLAMA_API_URL/api/tags" > /dev/null'; then
    echo "Docker cannot reach native Ollama. Restart Ollama with:"
    echo "  OLLAMA_HOST=0.0.0.0:11434 ollama serve"
    exit 1
fi

echo "Starting Granite Voice Concierge..."
docker compose up -d

echo ""
echo "Service Status:"
docker compose ps
echo ""

echo "Next Steps:"
echo ""
echo "1. Native Ollama model is ready: $OLLAMA_MODEL"
echo "   The embedding model is ready: $OLLAMA_EMBEDDING_MODEL"
echo ""
echo "2. Access Web UI:"
echo "   open http://127.0.0.1:4173"
echo ""
echo "3. View logs:"
echo "   docker compose logs -f voice-concierge"
echo ""
echo "4. For continuous live voice, run it on the host rather than in Docker:"
echo "   make live"
echo "   (Docker Desktop cannot expose the host microphone as /dev/snd.)"
echo ""
