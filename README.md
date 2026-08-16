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
```

### Guided routines

Asking to be walked through something ("guide me through making pasta", "how do
I ...", "steps to ...") starts a guided routine instead of a one-shot answer.
The assistant reads a step, keeps listening while it speaks, and moves on by
itself if you stay quiet, so it works with your hands busy.

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
**Hey Jarvis** wake-word mode; add `--memory` for persistent local memory. Use
`--demo` to review the UI without Ollama and audio models. If the virtual
environment has not been installed yet, run
`python -m pip install -e .` after activating it. See
[the web UI guide](web/README.md) for details.

For the complete local browser path with diagnostic logs:

```bash
python -m voice_concierge.app.web --voice-io --memory \
  --log-file .local/logs/web.log
```

The browser supports push-to-talk and wake-word capture, automatic Piper
response playback, startup and per-turn waiting states, and temporary chat JSON
export. Reminder and guided-routine requests are routed to their local services,
due reminders appear in the open browser, and **Local data** exposes memory
review/edit/delete/export plus reminder edit/snooze/cancel controls.
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

## Project Documentation

- [Repository Structure Guide](docs/repository-structure.md)
- [Development Workflow Guide](docs/development-workflow.md)
- [Python Style Guide](docs/python-style-guide.md)
- [App Pipeline Local E2E Setup](docs/app-pipeline-local-e2e-setup.md)

## Reasoning Documentation

- [Local Reasoning Guide](docs/reasoning/local-reasoning.md)
- [Recommended Default Model](docs/reasoning/recommended-default-model.md)
