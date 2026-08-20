# Development and Operations Guide

This guide covers the Docker and host-development commands that are intentionally
kept out of the main [README](../README.md). Docker is the recommended way to run
the browser application. Ollama remains on the host so it can use native hardware
acceleration.

The supported Docker Desktop hosts are Apple Silicon macOS and x86-64 Windows
with WSL 2 and Linux containers. The web service is bound to
`127.0.0.1:4173`; it is not designed for unauthenticated network exposure.

## Docker workflow

### First start

Install and start Docker Desktop and Ollama, then run from the repository root.

macOS:

```bash
cp .env.example .env
./scripts/quickstart.sh
```

Windows:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\quickstart.ps1
```

The launchers download missing Ollama models, build the image, verify that the
container can reach Ollama, start the service, and wait for the application
health endpoint. Larger speech models can make the first start take several
minutes. Open `http://127.0.0.1:4173` only after the launcher reports readiness.

Windows networking and troubleshooting are covered separately in the
[Windows Docker guide](windows-docker.md).

### Routine commands

| Task | macOS/Linux | Direct Compose equivalent |
| --- | --- | --- |
| Start existing deployment | `make up` | `docker compose up -d` |
| Stop and retain data | `make down` | `docker compose down` |
| Build the runtime image | `make build` | `docker compose build` |
| Follow logs | `make logs` | `docker compose logs -f voice-concierge` |
| Show service status | `make ps` | `docker compose ps` |
| Open a container shell | `make shell` | `docker compose exec voice-concierge bash` |
| List Ollama models | `make list-models` | `ollama list` |

After pulling repository changes, rerun the platform quick-start script. For a
normal source or Piper-voice change, this is equivalent to:

```bash
docker compose up -d --build
```

Changing only the faster-whisper selection does not require an image rebuild,
but the service must be recreated:

```bash
docker compose up -d --force-recreate voice-concierge
```

### Health and startup diagnostics

```bash
docker compose ps
curl --fail http://127.0.0.1:4173/api/health
docker compose logs --tail 100 voice-concierge
ollama ps
```

The Bash launcher waits for readiness for 600 seconds by default. Override this
only when a particularly large model needs longer:

```bash
GVC_HEALTH_TIMEOUT_SECONDS=1200 ./scripts/quickstart.sh
```

If the health endpoint says `ready` but the browser still shows its startup
screen, reload the page and inspect the browser console. A healthy backend and a
stuck overlay normally indicate a client-side script error rather than model
initialisation.

## Configuration

Copy `.env.example` to the ignored `.env` file and edit local selections there.
The launchers and Compose read the same values.

| Setting | Default | Purpose |
| --- | --- | --- |
| `OLLAMA_API_URL` | `http://host.docker.internal:11434` | Ollama address seen by the container |
| `OLLAMA_MODEL` | `granite4.1:8b` | Reasoning model |
| `OLLAMA_EMBEDDING_MODEL` | `granite-embedding:278m` | Memory embedding model |
| `GVC_STT_MODEL` | `base.en` | faster-whisper model name, model ID, or local path |
| `GVC_STT_DEVICE` | `cpu` | CTranslate2 inference device |
| `GVC_STT_COMPUTE_TYPE` | `int8` | CTranslate2 compute type |
| `GVC_TTS_VOICE` | `en_GB-alan-medium` | Piper voice embedded during the Docker build |
| `GVC_LOG_LEVEL` | `INFO` | Application log detail |

Inspect the resolved Compose configuration before troubleshooting unexpected
values:

```bash
docker compose config
```

### Speech models and voices

`GVC_STT_MODEL` is passed directly to faster-whisper. Examples include
`small.en`, `medium.en`, `large-v3`, `turbo`, and `distil-large-v3`. Downloaded
models persist in the `voice-model-cache` Docker volume. CPU with `int8` is the
portable Docker default; unsupported device and compute combinations fail
explicitly instead of silently changing models.

Changing `GVC_TTS_VOICE` requires an image rebuild because the selected Piper
voice is stored in the image. For host-native development, list and download
voices with:

```bash
python -m voice_concierge.voice_output.download_models --list
python -m voice_concierge.voice_output.download_models en_US-lessac-medium
```

Review a voice's upstream `MODEL_CARD` licence before distributing it.

### Logging

Use `make logs` for normal diagnostics. Set `GVC_LOG_LEVEL=DEBUG` temporarily
when detailed request, routing, and timing information is required. Debug output
can contain conversation text and may be retained by Docker's logging driver.

## Persistent data

| Data | Location |
| --- | --- |
| Preferences, memories, reminders, optional logs | `./data/.local` |
| Whisper and Hugging Face caches | Docker volume `voice-model-cache` |
| Ollama models | Native Ollama storage |
| Piper voice | Runtime Docker image |

`make down`, image rebuilds, and ordinary container recreation retain this data.

> **Data-loss warning:** `make clean` deletes everything below
> `./data/.local`. `make rebuild` invokes `make clean`. Use either only for an
> intentional factory reset.

`docker compose down -v` removes the named speech-model cache volume but does
not delete `./data/.local`.

## Development workflows

### Docker development

Run the isolated Docker test target with:

```bash
make test
```

For development with repository files mounted into the test image:

```bash
make dev-up
```

The server does not auto-reload Python changes. Restart it after server-side
edits:

```bash
docker compose restart voice-concierge
```

### Host development

Host development requires Python 3.12 or later and PortAudio.

```bash
# macOS
brew install portaudio

# Debian or Ubuntu
sudo apt-get install portaudio19-dev
```

Create the environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Run the browser application or direct microphone loop:

```bash
python -m voice_concierge.app.web --voice-io
python -m voice_concierge.app.live
```

Both entry points accept the speech selections documented above:

```bash
python -m voice_concierge.app.web --voice-io \
  --stt-model small.en \
  --stt-device cpu \
  --stt-compute-type int8 \
  --tts-voice en_US-lessac-medium
```

For microphone permissions, native audio dependencies, model prefetching, and
live-mode checks, use the [local end-to-end setup guide](app-pipeline-local-e2e-setup.md).

### Quality checks

Run the standard host checks before handing over substantive changes:

```bash
python -m black .
python -m ruff check .
python -m pytest
```

Browser startup and audio tests live under `tests/browser`:

```bash
cd tests/browser
npm test
```

## Further reference

- [Web UI architecture and API](../web/README.md)
- [Browser audio testing](browser-audio-testing.md)
- [Windows Docker guide](windows-docker.md)
- [Local reasoning](reasoning/local-reasoning.md)
- [Development workflow](development-workflow.md)
- [Python style guide](python-style-guide.md)
- [Repository structure](repository-structure.md)
