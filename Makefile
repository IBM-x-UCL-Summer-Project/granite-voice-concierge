.PHONY: help build up down logs logs-ollama shell live live-no-wakeword \
	live-no-memory test pull-model list-models clean rebuild ps dev-up

help:
	@echo "Granite Voice Concierge - Docker Commands"
	@echo ""
	@echo "Usage: make [target]"
	@echo ""
	@echo "Targets:"
	@echo "  build           Build Docker image"
	@echo "  up              Start all services"
	@echo "  down            Stop all services"
	@echo "  logs            Show service logs"
	@echo "  shell           Open shell in voice-concierge container"
	@echo "  live            Run live voice mode on the host (uses the Mac microphone)"
	@echo "  test            Run tests in container"
	@echo "  pull-model      Pull a model into Ollama"
	@echo "  list-models     List available Ollama models"
	@echo "  clean           Remove containers & data"
	@echo "  rebuild         Clean build and start fresh"

build:
	docker compose build

up:
	docker compose up -d
	@echo "✓ Services started"
	@echo "  Web UI: http://127.0.0.1:4173"
	@echo "  Ollama: http://localhost:11434"

down:
	docker compose down
	@echo "✓ Services stopped"

logs:
	docker compose logs -f voice-concierge

logs-ollama:
	docker compose logs -f ollama

shell:
	docker compose exec voice-concierge /bin/bash

live:
	@echo "Running live voice mode on the host so macOS audio devices are available..."
	@test -x .venv/bin/python || (echo "Missing .venv; create it and install the project first." && exit 1)
	.venv/bin/python -m voice_concierge.app.live

live-no-wakeword:
	@test -x .venv/bin/python || (echo "Missing .venv; create it and install the project first." && exit 1)
	.venv/bin/python -m voice_concierge.app.live --no-wake-word

live-no-memory:
	@test -x .venv/bin/python || (echo "Missing .venv; create it and install the project first." && exit 1)
	.venv/bin/python -m voice_concierge.app.live --no-memory --no-playback

test:
	docker compose exec voice-concierge pytest -v

pull-model:
	@read -p "Enter model name (e.g., granite3.3:2b): " model; \
	docker compose exec ollama ollama pull $$model

list-models:
	docker compose exec ollama ollama list

clean:
	docker compose down
	rm -rf data/.local/*
	@echo "✓ Cleaned"

rebuild: clean build up

ps:
	docker compose ps

# Development: mount source code for live reloading
dev-up:
	@echo "Starting in development mode (source code mounted)..."
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
	@echo "✓ Development services started"

.DEFAULT_GOAL := help
