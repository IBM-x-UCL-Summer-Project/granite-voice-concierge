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

## Project Documentation

- [Repository Structure Guide](docs/repository-structure.md)
- [Development Workflow Guide](docs/development-workflow.md)
- [Python Style Guide](docs/python-style-guide.md)

## Reasoning Documentation

- [Local Reasoning Guide](docs/reasoning/local-reasoning.md)
- [Recommended Default Model](docs/reasoning/recommended-default-model.md)
