#!/bin/bash
set -e

echo "🚀 Granite Voice Concierge - Quick Start"
echo ""

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Please install Docker Desktop"
    exit 1
fi

if ! docker compose version > /dev/null 2>&1; then
    echo "❌ Docker Compose plugin not found. Please install Docker Desktop"
    exit 1
fi

echo "✓ Docker found"
echo ""

# Build
echo "📦 Building Docker image..."
docker compose build

echo ""
echo "✓ Build complete!"
echo ""

# Start Ollama first so a model can be present before the application starts.
echo "🚀 Starting Ollama..."
docker compose up -d ollama

echo ""
echo "✓ Services started!"
echo ""

# Wait for Ollama
echo "⏳ Waiting for Ollama to be ready..."
for i in {1..30}; do
    if docker compose exec -T ollama ollama list > /dev/null 2>&1; then
        echo "✓ Ollama is ready!"
        break
    fi
    echo "  Attempt $i/30..."
    sleep 2
done

# The application defaults to this lightweight fallback when the primary model
# is not installed. The named Ollama volume keeps it across restarts.
OLLAMA_MODEL="${OLLAMA_MODEL:-granite3.3:2b}"
if ! docker compose exec -T ollama ollama list | grep -Fq "$OLLAMA_MODEL"; then
    echo "📥 Downloading $OLLAMA_MODEL (first run only)..."
    docker compose exec -T ollama ollama pull "$OLLAMA_MODEL"
fi

echo "🚀 Starting Granite Voice Concierge..."
docker compose up -d voice-concierge

echo ""
echo "📊 Service Status:"
docker compose ps
echo ""

echo "🎯 Next Steps:"
echo ""
echo "1. The default model is ready: $OLLAMA_MODEL"
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
