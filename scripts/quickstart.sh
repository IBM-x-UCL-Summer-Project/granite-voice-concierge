#!/bin/bash
set -e

echo "Granite Voice Concierge - Quick Start"
echo ""

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
    echo "Ollama not found. Install the macOS Ollama application first:"
    echo "  brew install --cask ollama-app"
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

# Models are owned by native Ollama and remain outside the Docker image.
export OLLAMA_MODEL="${OLLAMA_MODEL:-granite4.1:8b}"
if ! ollama list | grep -Fq "$OLLAMA_MODEL"; then
    echo "Downloading $OLLAMA_MODEL (first run only)..."
    ollama pull "$OLLAMA_MODEL"
fi

OLLAMA_EMBEDDING_MODEL="${OLLAMA_EMBEDDING_MODEL:-granite-embedding:278m}"
if ! ollama list | grep -Fq "$OLLAMA_EMBEDDING_MODEL"; then
    echo "Downloading $OLLAMA_EMBEDDING_MODEL (first run only)..."
    ollama pull "$OLLAMA_EMBEDDING_MODEL"
fi

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
echo "4. For continuous live voice on macOS, run it on the host:"
echo "   make live"
echo "   (Docker Desktop cannot expose the Mac microphone as /dev/snd.)"
echo ""
