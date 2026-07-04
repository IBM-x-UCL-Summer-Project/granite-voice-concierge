# granite-voice-concierge

Offline, voice-first IBM Granite assistant prototype for independent living.

## Development Setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

The requirements install the `voice_concierge` package in editable mode. Run
repository benchmark tools as modules from the repository root:

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
