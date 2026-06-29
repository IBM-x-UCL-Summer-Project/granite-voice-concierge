# Repository Structure Guide

This document explains how the project repository should be organised and where different types of work should be placed.

## Top-Level Structure

```text
granite-voice-concierge/
├── README.md
├── docs/
├── experiments/
├── src/
├── tests/
├── benchmarks/
└── .github/
```

## Dependency Files

`pyproject.toml` is the canonical source for package metadata and runtime
dependencies. It configures setuptools to discover `voice_concierge` under the
`src/` layout.

`requirements.txt` installs the project in editable mode, including the runtime
dependencies declared in `pyproject.toml`. Editable installation lets repository
tools import `voice_concierge` without modifying `sys.path` while keeping source
changes immediately available.

## `docs/`

The `docs/` folder is for project documentation that supports planning, design, reporting and any other additional information.

Do not put experimental code in `docs/`.

## `experiments/`

The `experiments/` folder is for technical spikes, proof of concept work or testing component code if required.

Suggested structure:

```text
experiments/
├── granite-inference/
├── stt-vad-wakeword/
├── tts/
├── memory-rag/
└── context-manager/
```

Use this folder when testing whether a tool or approach works before integrating it into the main system (if necessary).

Each experiment folder should ideally contain:

```text
README.md
requirements.txt or setup notes
source code
test inputs if needed
results or benchmark notes
```

## `src/`

The `src/` folder is for the main application code.

Suggested structure:

```text
src/
└── voice_concierge/
    ├── voice_input/
    ├── reasoning/
    ├── memory/
    ├── context/
    ├── voice_output/
    └── app/
```

Possible component responsibilities:

- `voice_input/`: wake word detection, VAD, STT, audio capture;
- `reasoning/`: Granite model interface and prompt handling;
- `memory/`: local memory storage, retrieval, embeddings, sqlite-vec;
- `context/`: context modes, behaviour profiles, state management;
- `voice_output/`: TTS and spoken response handling;
- `app/`: main pipeline or application entry point.

Experimental or throwaway code should stay in `experiments/` until it is stable enough to integrate.

## `tests/`

The `tests/` folder is for tests of the main application code in `src/`.

Use this folder for:

- unit tests;
- integration tests;

Suggested structure:

```text
tests/
├── unit/
├── integration/
└── fixtures/
```

Use `tests/` for stable project tests. Quick one off testing scripts for technical spikes can stay inside the relevant `experiments/` folder until the code is moved into `src/`.

## `benchmarks/`

The `benchmarks/` folder is for performance and evaluation results.

Use this folder for:

- latency measurements;
- memory/RAM usage results;
- STT accuracy tests;
- Granite response timing;
- TTS timing;
- end-to-end pipeline measurements;
- benchmark scripts and templates.

Benchmark results should ideally include:

- date tested;
- device used;
- tool/model tested;
- test input;
- latency;
- RAM/CPU usage where possible;
- issues observed;
- recommendation.

## `.github/`

The `.github/` folder is for GitHub-specific project files.

```text
.github/
├── ISSUE_TEMPLATE/
└── pull_request_template.md
```

## General Rules

1. Use `experiments/` for early technical testing.
2. Use `src/` only for code intended for the final product.
3. Use `docs/` for planning, research, architecture, and decisions.
4. Use `benchmarks/` for evidence and measurement results.
5. Every major folder should eventually have its own `README.md`.
6. Large files, model weights, datasets, and generated outputs should not be committed.
7. Every important technical choice should be linked to an issue, benchmark, or decision note.
8. Work should be done on feature branches and merged through pull requests, not pushed directly to `main`.
