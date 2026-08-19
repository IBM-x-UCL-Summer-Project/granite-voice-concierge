# granite-voice-concierge

Offline, voice-first IBM Granite assistant prototype for independent living.

## Development Setup

The audio stack needs the PortAudio system library (for `pyaudio`): on macOS
`brew install portaudio`, on Debian/Ubuntu `sudo apt-get install portaudio19-dev`.

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Dependencies are declared in `pyproject.toml` — `[project.dependencies]` for the
runtime stack and `[project.optional-dependencies].dev` for tooling.
`requirements.txt` (`-e .`) and `requirements-dev.txt` (`-e .[dev]`) are thin shims
onto those, so the command above installs the `voice_concierge` package in editable
mode with the dev tools. Run repository benchmark tools as modules from the
repository root:

```bash
python -m benchmarks.reasoning.benchmark run --engine fake
```

Run the local live voice loop after completing the local E2E setup:

```bash
python -m voice_concierge.app.live
```

Useful manual variants:

```bash
python -m voice_concierge.app.live --no-wake-word
python -m voice_concierge.app.live --device-index <index>
python -m voice_concierge.app.live --no-memory --no-playback
python -m voice_concierge.app.live --no-guided-routines
python -m voice_concierge.app.live --policy-profile strict
```

### Guided routines

Explicitly asking to be walked through something (for example, "guide me through
making pasta") starts a guided routine instead of a one-shot answer. Ordinary
requests for a recipe or a list of steps remain normal answers. The assistant
reads a step, keeps listening while it speaks, and moves on by itself if you
stay quiet, so it works with your hands busy. Unrelated and urgent requests can
interrupt the routine without losing its place.

While a step is being read, or in the quiet window after it:

| Say | Effect |
| --- | --- |
| `next` / `back` / `repeat` | move through the routine |
| `pause` / `continue` | hold and resume; a paused routine will not auto-advance |
| `stop` | end the routine |
| `slower` / `faster` | change the speaking pace and re-read the step |

Barge-in during playback uses the macOS voice-processing unit for echo
cancellation, so the assistant does not hear its own speech as a command. It
needs the `macos-aec` extra; without it the app falls back to answering
normally. Use `--no-guided-routines` to switch the behaviour off.

### Browser UI

Run the pipeline-connected browser UI:

```bash
source .venv/bin/activate
python -m voice_concierge.app.web
```

Add `--voice-io` for browser recording/STT, response TTS, and hands-free
**Hey Jarvis** wake-word mode. Persistent local memory is enabled by default;
use `--no-memory` for a memory-free run. Use `--demo` to review the UI without
Ollama and audio models. If the virtual
environment has not been installed yet, run
`python -m pip install -e .` after activating it. See
[the web UI guide](web/README.md) for details.

The interactive web and live runners default to the `uat_relaxed` reasoning
profile during controlled testing. It favors useful ordinary answers when the
model's provenance metadata is imperfect, while retaining offline/live-data
honesty and all memory, deletion, privacy, confirmation, and exact-target
controls. Use `--policy-profile strict` to restore fail-closed provenance
enforcement. Programmatic reasoning construction remains strict by default.

For the complete local browser path with diagnostic logs:

```bash
python -m voice_concierge.app.web --voice-io \
  --log-level DEBUG \
  --log-file .local/logs/web.log
```

DEBUG mode correlates browser and server requests and records prompts,
responses, feature routing, local-data operations, playback/voice state, and
pipeline timings. Encoded audio bodies are represented by their size instead
of being copied into the log.

The browser supports push-to-talk and wake-word capture, an automatic follow-up
listening window, adjustable wake timing and sensitivity, automatic Piper
response playback, startup and per-turn waiting states, and temporary chat JSON
export. The header remains available while a long conversation scrolls, and an
extended temporary display transcript (up to 200 completed exchanges) is kept
separately from the shorter model context window. Reminder and guided-routine
requests are routed to their local services, due reminders appear in the open
browser, and **Local data** exposes
memory review/edit/delete/export plus reminder edit/snooze/cancel controls.
Guided routines automatically advance after each spoken step and accept the
same no-wake control words as the CLI, including pause, continue, next, back,
repeat, slower, faster, and stop.
**New conversation** clears only transient conversation context; approved
memories and scheduled reminders remain. Continuous wake-word listening remains
available through the live runner.

## Reminders and timers

Set one-off or repeating reminders by voice ("set a timer for ten minutes",
"remind me to take my pills every day at 8"), or from the command line:

```bash
python -m voice_concierge.scheduling                   # what is set
python -m voice_concierge.scheduling add "remind me to stretch in 10 minutes"
python -m voice_concierge.scheduling cancel 3
python -m voice_concierge.scheduling watch             # announce as they fall due
```

Reminders are stored at `.local/reminders/` and work offline. One missed while
the assistant was not running is announced on the next start rather than
skipped. Use `--no-reminders` to switch the feature off. See
[the scheduling package](src/voice_concierge/scheduling/README.md).

## Memory and privacy centre

Review, correct and remove what the assistant has stored about you:

```bash
python -m voice_concierge.privacy              # what is stored, and what is not
python -m voice_concierge.privacy list -v      # review stored memories
python -m voice_concierge.privacy export       # take a copy as JSON
python -m voice_concierge.privacy edit 3 "likes tea, not coffee"
python -m voice_concierge.privacy delete 3     # asks first
python -m voice_concierge.privacy forget-all   # asks you to type DELETE
```

Memories and their search index are kept under `.local/memory/`. Recorded audio,
conversation history and spoken preferences are never written to disk. See
[the privacy package](src/voice_concierge/privacy/README.md) for details.

## Docker setup

Docker runs the Web UI, application services, and required Python dependencies.
Ollama runs natively on macOS so it can use Apple Metal acceleration. Install
and start both Docker Desktop and Ollama before continuing. On macOS, live
microphone access is more reliable when the live voice runner is started on the
host; the containerized browser UI still supports browser recording.

### Quick start

Copy the environment template, then run the setup script:

```bash
cp .env.example .env
./scripts/quickstart.sh
```

The script checks native Ollama, downloads the configured reasoning and
embedding models, verifies that Docker can reach Ollama, and starts the
application container. The first run can take several minutes. When startup
completes, open:

```text
http://127.0.0.1:4173
```

### Manual start

Start native Ollama in the first terminal:

```bash
OLLAMA_HOST=0.0.0.0:11434 ollama serve
```

Leave it running, then use a second terminal for the models and application:

```bash
ollama pull granite4.1:8b
ollama pull granite-embedding:278m
docker compose up -d --build voice-concierge
docker compose logs -f voice-concierge
```

If the Ollama macOS application is already listening and Docker can reach it, a
second server is unnecessary. `0.0.0.0:11434` permits Docker Desktop to connect,
so do not publish that port through a router or expose it to an untrusted
network.

Use `Ctrl-C` to stop following the logs; the containers continue running in
the background. Check their status with:

```bash
docker compose ps
curl http://127.0.0.1:4173/api/health
```

### Model configuration

The default reasoning model is `granite4.1:8b`. Change it in `.env` without
editing application source code:

```env
OLLAMA_API_URL=http://host.docker.internal:11434
OLLAMA_MODEL=granite4.1:8b
```

Any Ollama model name can be used. A smaller model may start faster on machines
with limited memory. After changing the model, download it with native Ollama
and recreate the application container:

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

The default host port is `4173`. To expose the UI on port `5000`, change only
the host side of the mapping in `docker-compose.yml`:

```yaml
ports:
  - "127.0.0.1:5000:4173"
```

Then recreate the service and open `http://127.0.0.1:5000`:

```bash
docker compose up -d --force-recreate voice-concierge
```

### Persistent data

Application preferences, memory, reminders, and logs persist in
`./data/.local`. Downloaded application model caches persist in the
`model-cache` Docker volume. Native Ollama owns its models under the user's
Ollama data directory, outside Docker. A normal shutdown keeps all of this
data:

```bash
docker compose down
```

Do not add `-v` unless you intentionally want to delete the persisted Docker
volumes. To rebuild the application while retaining all persistent data, run:

```bash
docker compose down
docker compose up -d --build --force-recreate
```


## Project Documentation

- [Repository Structure Guide](docs/repository-structure.md)
- [Development Workflow Guide](docs/development-workflow.md)
- [Python Style Guide](docs/python-style-guide.md)
- [App Pipeline Local E2E Setup](docs/app-pipeline-local-e2e-setup.md)

## Reasoning Documentation

- [Local Reasoning Guide](docs/reasoning/local-reasoning.md)
- [Recommended Default Model](docs/reasoning/recommended-default-model.md)
