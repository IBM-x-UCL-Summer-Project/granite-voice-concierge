.PHONY: help build up down logs shell live live-no-wakeword \
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
	@echo "  test            Build the test image and run tests in a fresh container"
	@echo "  dev-up          Start with source and tests mounted from the host"
	@echo "  pull-model      Pull a model into Ollama"
	@echo "  list-models     List available Ollama models"
	@echo "  clean           Remove containers & data"
	@echo "  rebuild         Clean build and start fresh"

build:
	docker compose build

up:
	docker compose up -d
	@echo "Services started"
	@echo "  Web UI: http://127.0.0.1:4173"
	@echo "  Native Ollama: http://localhost:11434"

down:
	docker compose down
	@echo "Services stopped"

logs:
	docker compose logs -f voice-concierge

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
	@echo "Building the isolated Docker test target..."
	docker compose -f docker-compose.yml -f docker-compose.dev.yml build voice-concierge
	@echo "Running tests without starting Ollama or the long-running web service..."
	docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm \
		--no-deps --entrypoint python voice-concierge -m pytest -v

pull-model:
	@read -p "Enter model name: " model; \
	ollama pull $$model

list-models:
	ollama list

clean:
	docker compose down
	rm -rf data/.local/*
	@echo "Cleaned"

rebuild: clean build up

ps:
	docker compose ps

# Development: mount source, tests, and web assets from the host. The current
# server has no auto-reloader, so restart the service after Python changes.
dev-up:
	@echo "Starting in source-mounted development mode..."
	docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
	@echo "Development services started"

.DEFAULT_GOAL := help
