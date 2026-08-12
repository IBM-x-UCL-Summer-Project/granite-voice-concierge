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
```

Run the pipeline-connected browser UI:

```bash
source .venv/bin/activate
python -m voice_concierge.app.web
```

Add `--voice-io` for browser recording/STT and response TTS, `--memory` for
persistent local memory, or `--demo` to review the UI without Ollama and audio
models. If the virtual environment has not been installed yet, run
`python -m pip install -e .` after activating it. See
[the web UI guide](web/README.md) for details.

## Project Documentation

- [Repository Structure Guide](docs/repository-structure.md)
- [Development Workflow Guide](docs/development-workflow.md)
- [Python Style Guide](docs/python-style-guide.md)
- [App Pipeline Local E2E Setup](docs/app-pipeline-local-e2e-setup.md)

## Reasoning Documentation

- [Local Reasoning Guide](docs/reasoning/local-reasoning.md)
- [Recommended Default Model](docs/reasoning/recommended-default-model.md)
