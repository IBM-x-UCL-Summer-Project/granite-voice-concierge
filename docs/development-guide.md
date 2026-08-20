# Development and Operations Guide

This guide contains the detailed setup, runtime, testing, and maintenance
instructions for Granite Voice Concierge. For the project overview and primary
quick start, see the [root README](../README.md).

## Contents

- [Reference deployment](#reference-deployment)
- [Docker setup](#docker-setup)
- [Configuration](#configuration)
- [Persistent data](#persistent-data)
- [Make command reference](#make-command-reference)
- [Docker development and tests](#docker-development-and-tests)
- [Host development setup](#host-development-setup)
- [Runtime entry points](#runtime-entry-points)
- [Feature-specific tools](#feature-specific-tools)
- [Quality checks](#quality-checks)

## Reference deployment

Docker is the recommended way to run the browser UI and application services.
The application image contains Python 3.12, native audio libraries, the
machine-learning stack, and the Piper voice model. Ollama runs on the host so
it can use the host's available hardware acceleration.

The current reference environment is Apple Silicon macOS with Docker Desktop
and native Ollama. The container itself is Linux and currently uses
`python:3.12-slim` as its base image. Other Docker hosts may work, but should be
validated before they are treated as supported deployment targets.

The Compose service binds the web application to `127.0.0.1:4173`. This is a
local-only development deployment. Do not expose it to a network without an
appropriate authentication, TLS, and reverse-proxy design.

## Docker setup

### Prerequisites

Install and start:

- [Docker with the Compose plugin](https://docs.docker.com/get-started/get-docker/)
- [Ollama](https://ollama.com/download)

### Quick start

Copy the environment template and run the setup script from the repository
root:

```bash
cp .env.example .env
./scripts/quickstart.sh
```

The script:

1. checks Docker, Compose, and native Ollama;
2. downloads the configured reasoning and embedding models;
3. builds the application image;
4. verifies that the container can reach Ollama; and
5. starts the application service.

A cold image build can take several minutes because it installs the
machine-learning and audio stack and downloads the Piper voice model. Cached
rebuilds should be substantially faster.

When startup completes, open `http://127.0.0.1:4173`.

### Manual start

If Ollama is not already accepting container connections, start it in the
first terminal:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Leave it running, then use a second terminal for the models and application:

```bash
ollama pull granite4.1:8b
ollama pull granite-embedding:278m
make build
make up
make logs
```

If the Ollama desktop application is already listening and Docker can reach
it, a second Ollama server is unnecessary. Binding Ollama to
`0.0.0.0:11434` permits Docker to connect, but also broadens the listening
interface. Do not publish that port through a router or expose it to an
untrusted network.

Use `Ctrl-C` to stop following the logs; the application container continues
running in the background.

Check the service and application health with:

```bash
make ps
curl http://127.0.0.1:4173/api/health
```

Stop the application while retaining persistent data with:

```bash
make down
```

## Configuration

The checked-in `.env.example` documents the supported environment variables.
Copy it to the ignored `.env` file before changing local values.

### Reasoning model

The default reasoning model is `granite4.1:8b` and the default embedding model
used by the quick-start workflow is `granite-embedding:278m`.

```env
OLLAMA_API_URL=http://host.docker.internal:11434
OLLAMA_MODEL=granite4.1:8b
```

After changing the reasoning model, download it with native Ollama and recreate
the application container:

```bash
ollama pull granite4.1:8b
docker compose up -d --build --force-recreate voice-concierge
```

Confirm the effective configuration and available models with:

```bash
docker compose config
ollama list
docker compose exec voice-concierge printenv REASONING_MODEL
docker compose exec voice-concierge printenv OLLAMA_API_URL
```

### Port configuration

The default host port is `4173`. To expose the UI on a different local port,
change only the host side of the mapping in `docker-compose.yml`:

```yaml
ports:
  - '127.0.0.1:5000:4173'
```

Then recreate the service and open `http://127.0.0.1:5000`:

```bash
docker compose up -d --force-recreate voice-concierge
```

Changing the binding from `127.0.0.1` to `0.0.0.0` is not merely a port
change: it exposes the service to the network. Do that only as part of a
deliberate deployment design with appropriate security controls.

## Persistent data

Application preferences, memories, reminders, and logs persist in
`./data/.local`, which is bind-mounted at `/app/.local`. Downloaded Whisper and
other application model caches persist in the `model-cache` Docker volume.
Native Ollama owns its models outside Docker.

A normal shutdown or rebuild retains application data:

```bash
make down
make build
make up
```

> **Data-loss warning:** `make clean` deletes everything below
> `./data/.local`, including memories, reminders, preferences, and logs.
> `make rebuild` invokes `make clean` and deletes the same data. Use these
> targets only when a factory reset is intentional.

`docker compose down -v` removes named Docker volumes, including the
application model cache. It does not delete the bind-mounted
`./data/.local` directory, but should still be used only when volume removal
is intentional.

## Make command reference

Run `make help` to display the primary targets.

| Command                 | Purpose                                                              |
| ----------------------- | -------------------------------------------------------------------- |
| `make build`            | Build the runtime image.                                             |
| `make up`               | Start the application container in the background.                   |
| `make down`             | Stop and remove containers while retaining persistent data.          |
| `make logs`             | Follow the application container logs.                               |
| `make shell`            | Open Bash inside the running application container.                  |
| `make ps`               | Show the current Compose service status.                             |
| `make test`             | Build the isolated test target and run the full suite.               |
| `make dev-up`           | Start the test target with repository files mounted.                 |
| `make pull-model`       | Prompt for and download a model through native Ollama.               |
| `make list-models`      | List models available to native Ollama.                              |
| `make live`             | Run live voice mode on macOS using `.venv` and the host microphone.  |
| `make live-no-wakeword` | Run host live mode without wake-word detection.                      |
| `make live-no-memory`   | Run host live mode without persistent memory or playback.            |
| `make clean`            | Delete application state below `data/.local` after stopping Compose. |
| `make rebuild`          | Delete application state, rebuild the image, and start Compose.      |

## Docker development and tests

Build the dedicated test target and run the full suite in a fresh container:

```bash
make test
```

The test target contains development tools, tests, benchmark modules, and
checked-in documentation fixtures. These are not added to the normal runtime
image.

Start the web service with source, tests, benchmarks, documentation, and web
assets mounted from the host with:

```bash
make dev-up
```

The server does not auto-reload Python changes. Restart it after server-side
edits:

```bash
docker compose restart voice-concierge
```

### Container entrypoint

`entrypoint.sh` is an internal container startup wrapper. Docker runs it
automatically to:

1. create local-state directories;
2. update the configured Ollama host and model selection;
3. wait briefly for Ollama; and
4. execute the Compose command.

Running `./entrypoint.sh` directly without a command does not start the
application. It also creates `.local` relative to the current host directory
rather than using Docker's `data/.local` mount.

## Host development setup

Host development requires Python 3.12 or later and the PortAudio development
library used by `pyaudio`.

On macOS:

```bash
brew install portaudio
```

On Debian or Ubuntu:

```bash
sudo apt-get install portaudio19-dev
```

Create the development environment:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Dependencies are declared in `pyproject.toml`. `requirements.txt` and
`requirements-dev.txt` are thin editable-install shims for the runtime and
development dependency groups.

The complete model and audio setup is documented in the
[local end-to-end setup guide](app-pipeline-local-e2e-setup.md).

Run repository benchmark tools as modules from the repository root:

```bash
python -m benchmarks.reasoning.benchmark run --engine fake
```

## Runtime entry points

### Browser application

Run the pipeline-connected web application on the host with:

```bash
source .venv/bin/activate
python -m voice_concierge.app.web --voice-io
```

Useful variants:

```bash
python -m voice_concierge.app.web --demo
python -m voice_concierge.app.web --voice-io --no-memory
python -m voice_concierge.app.web --voice-io --no-wake-word
python -m voice_concierge.app.web --voice-io --policy-profile strict
```

The interactive web and live runners default to the `uat_relaxed` reasoning
profile for controlled testing. It retains memory, deletion, privacy,
confirmation, exact-target, and current-information controls while avoiding
unhelpful failures caused only by imperfect provenance metadata. Use
`--policy-profile strict` for fail-closed provenance enforcement.

For detailed local diagnostics:

```bash
python -m voice_concierge.app.web --voice-io \
  --log-level DEBUG \
  --log-file .local/logs/web.log
```

DEBUG logs include prompts, responses, feature routing, local-data operations,
playback state, voice state, and pipeline timings. Encoded audio bodies are
represented by their size rather than copied into logs.

See the [web UI guide](../web/README.md) for the browser architecture, API
contract, wake mode, playback behavior, and diagnostic details.

### Live voice application

Run the host microphone loop after completing the local end-to-end setup:

```bash
python -m voice_concierge.app.live
```

Useful variants:

```bash
python -m voice_concierge.app.live --no-wake-word
python -m voice_concierge.app.live --device-index <index>
python -m voice_concierge.app.live --no-memory --no-playback
python -m voice_concierge.app.live --no-guided-routines
python -m voice_concierge.app.live --policy-profile strict
```

### Voice output fallback

Spoken responses use Piper first. When the server runs directly on macOS and
Piper fails, it retries with the native `say` command. If server-side synthesis
still fails, the browser can use a locally installed speech-synthesis voice.

Docker containers cannot call the host's `say` command, so containerized runs
fall back directly from Piper to local browser speech. If no local browser
voice is available, the response remains readable as text.

## Feature-specific tools

### Guided routines

Explicitly asking to be guided through a task starts a step-by-step routine.
The assistant reads each step, keeps listening while it speaks, and advances
after a quiet interval.

| Spoken command              | Effect                                        |
| --------------------------- | --------------------------------------------- |
| `next`, `back`, or `repeat` | Move through the routine.                     |
| `pause` or `continue`       | Hold or resume the routine.                   |
| `stop`                      | End the routine.                              |
| `slower` or `faster`        | Change the speaking pace and repeat the step. |

Barge-in during host playback uses the optional macOS voice-processing unit
for acoustic echo cancellation. Install the `macos-aec` extra when developing
that path. Without it, the application falls back to normal response handling.

### Reminders and timers

Manage reminders through the application or command line:

```bash
python -m voice_concierge.scheduling
python -m voice_concierge.scheduling add "remind me to stretch in 10 minutes"
python -m voice_concierge.scheduling cancel 3
python -m voice_concierge.scheduling watch
```

Reminders are stored under `.local/reminders/` and work offline. A reminder
missed while the application was stopped is announced after the next start.
See the [scheduling package guide](../src/voice_concierge/scheduling/README.md).

### Memory and privacy tools

Review, correct, export, and remove stored memories:

```bash
python -m voice_concierge.privacy
python -m voice_concierge.privacy list -v
python -m voice_concierge.privacy export
python -m voice_concierge.privacy edit 3 "likes tea, not coffee"
python -m voice_concierge.privacy delete 3
python -m voice_concierge.privacy forget-all
```

Memories and their search index are stored under `.local/memory/`. Recorded
audio and conversation history are not persisted. See the
[privacy package guide](../src/voice_concierge/privacy/README.md).

## Quality checks

Run the standard host checks before handing over a substantive change:

```bash
python -m black .
python -m ruff check .
python -m pytest
```

The Docker equivalent builds the isolated test image and runs the full suite:

```bash
make test
```

Repository conventions and pull-request expectations are documented in:

- [Development workflow](development-workflow.md)
- [Python style guide](python-style-guide.md)
- [Repository structure](repository-structure.md)
