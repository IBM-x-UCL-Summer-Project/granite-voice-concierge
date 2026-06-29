# Local Reasoning Guide

This document describes the current local reasoning workstream.

## Contract

The main input type is `ReasoningRequest`.

It contains:

- `transcript`: the text from STT;
- `mode`: current behavior mode, such as `home`, `cooking`, `shopping`, or `driving`;
- `memories`: local memories supplied by the memory component;
- `conversation_summary`: optional recent context;
- `constraints`: runtime limits such as max spoken words and whether memory writes are allowed.

The main output type is `ReasoningResponse`.

It contains:

- `spoken_response`: the response intended for TTS;
- `needs_confirmation`: whether the user must confirm before an action is taken;
- `proposed_memory_action`: optional proposed store/update/delete operation;
- `mode_suggestion`: optional future mode switch hint;
- `confidence`: coarse confidence label;
- `metadata`: backend-specific details.

The reasoning layer should propose memory actions. It should not directly write to memory.

## Install

Create a local virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install development tools:

```bash
python -m pip install -r requirements-dev.txt
```

Runtime dependencies are declared in `pyproject.toml`. The root requirements file
installs `voice_concierge` in editable mode so repository tools can import the
`src/` package without changing `sys.path`.

## Run the Deterministic Fake

The default benchmark uses a fixed deterministic fake. It verifies request,
response, suite, and reporting plumbing without requiring a model runner. It does
not detect intent, apply policy, enforce word limits, or provide evidence about
response quality.

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark run --engine fake
```

Write a report to a file:

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark \
  run \
  --engine fake \
  --output benchmarks/reasoning/results/fake-report.json
```

## Run With Ollama

Running an Ollama model is optional. The adapter uses Ollama's official Python
client, and connects to the local runner at `http://localhost:11434` by
default, requires no cloud account or credentials. Ollama itself must be
installed, running locally, and have a local model available.

For Ollama runs, the benchmark loads the active model and host from
`.local/reasoning-model-selection.json`. If the file is absent, the selection
defaults to `granite4.1:8b` at `http://localhost:11434`. The model-management
helpers can list, inspect, pull, and select local Ollama models, but the benchmark
runner will not silently download a missing model.

Example:

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark \
  run \
  --engine ollama
```

Explicit model and host arguments override the persisted selection:

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark \
  run \
  --engine ollama \
  --model <local-model-name> \
  --host http://localhost:11434
```

Ollama runs use the bundled `v1` runtime prompt by default. Select another
bundled version explicitly when testing a prompt revision:

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark \
  run \
  --engine ollama \
  --prompt-version v2
```

The selected prompt ID and version are recorded in each Ollama response's
benchmark metadata.

The benchmark report includes per-prompt latency, response word count,
confirmation flags, proposed memory action type, confidence, and backend
metadata. Ollama reports can also retain raw and guarded evaluations from the
same model generation:

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark \
  run \
  --engine ollama \
  --evaluation-mode both
```

Evaluation modes are:

- `raw`: parsed model output before deterministic policy guards and word-limit
  shaping;
- `guarded`: the engine's final product facing output; the Ollama adapter applies
  policy and word limit shaping before returning it;
- `both`: both evaluations from one inference, with guarded output retained in
  the legacy top level result fields.

Raw and `both` modes require a trace-capable engine. The deterministic fake only
supports `guarded` mode.

The Ollama backend requests schema constrained JSON from the local model. A
single Pydantic boundary model generates the JSON schema sent to Ollama and
validates the returned content. The validated result is mapped into `ReasoningResponse`,
including `needs_confirmation`, `proposed_memory_action`, `mode_suggestion`, and
`confidence`. If the model returns invalid JSON or misses required fields, the
backend returns a low confidence fallback and records the parse problem in
response metadata.

The Ollama backend also applies deterministic policy guards after parsing model output. These guards do not store, retrieve, edit, or delete memory. They only correct the reasoning response when a simple local policy should not depend on model compliance, such as confirming accessibility preference changes or refusing to invent a shopping list when no list memory was supplied.

## Manage Local Models

Use the model management helper to inspect local Ollama state before running a
comparison.

List installed models:

```bash
.venv/bin/python -m benchmarks.reasoning.manage_models list
```

Show metadata for the default candidate:

```bash
.venv/bin/python -m benchmarks.reasoning.manage_models show granite4.1:8b
```

Persist the active benchmark model selection locally:

```bash
.venv/bin/python -m benchmarks.reasoning.manage_models select granite4.1:8b \
  --fallback-model granite3.3:2b
```

his writes `.local/reasoning-model-selection.json`. A subsequent
`python -m benchmarks.reasoning.benchmark run --engine ollama` uses its primary
model and host unless
`--model` or `--host` overrides them. The fallback is recorded for later runtime
use but is not silently benchmarked or activated.

If a model is missing, pull it through Ollama:

```bash
.venv/bin/python -m benchmarks.reasoning.manage_models pull granite4.1:8b --stream
```

The current `--stream` implementation parses streamed Ollama updates but prints
them together after the pull finishes. It does not provide live terminal progress.

## Compare Candidate Models

Use the benchmark runner's `compare` subcommand when evaluating local Ollama
models against the same prompt suite.

The comparison runner defaults to `--evaluation-mode both`. Its summary preserves
the model order supplied on the command line and displays raw pass rate, guarded
pass rate, guard intervention count, latency, issue counts, and failed case IDs.
It does not rank candidates or generate a `best_model` field. These automated
checks are diagnostics and basic acceptance evidence; Final decisions to be made based on human review at this stage as automated reviewing is too shallow/not worth to implement.

Comparison mode requires at least two explicit model names:

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark compare \
  --models granite3.3:2b granite4.1:8b
```

Comparison candidates remain explicit so a saved preference cannot silently
change a comparison set. The persisted host is used unless `--host` overrides it.

For active local reasoning work, prefer a small explicit shortlist instead of testing every installed model. I used:

- `granite4.1:8b`: current default IBM Granite candidate if the machine can run it comfortably.
- `granite3.3:2b`: fast local baseline and lower resource fallback.
- `granite4.1:3b`: smaller Granite 4.1 candidate if later benchmarking justifies it.

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark compare \
  --models granite3.3:2b granite4.1:3b granite4.1:8b gemma4:e2b
```

This creates a timestamped directory under `benchmarks/reasoning/results/`
containing:

- one detailed JSON benchmark report per model;
- `comparison-summary.json`;
- `comparison-summary.md`.

You can choose a specific output directory:

```bash
.venv/bin/python -m benchmarks.reasoning.benchmark compare \
  --models granite3.3:2b granite4.1:3b granite4.1:8b gemma4:e2b \
  --output-dir benchmarks/reasoning/results/model-comparison-local
```

## Prompt Policy

Runtime model instructions are bundled under
`src/voice_concierge/reasoning/prompts/<version>/`. Each version contains:

- `manifest.toml`: schema version, prompt identity, template filenames, default
  mode, and mode-specific policies;
- `system.txt`: product rules and structured-output examples;
- `user.txt`: placeholders for mode, supplied context, memories, and transcript.

`prompting.py` validates the manifest, required placeholders, and resource names,
then renders the selected templates with `string.Template`. Once a prompt
version has produced benchmark evidence, leave it unchanged and create a new
version directory so old results remain reproducible.

The prompt builder instructs the model to follow these local reasoning rules:

- operate as if no internet or cloud service is available;
- use only the transcript, supplied local memories, and supplied summary;
- keep responses short and suitable for speech;
- do not invent remembered facts;
- ask for confirmation before saving, changing, or deleting personal data;
- avoid medical diagnosis, medication dosing, and safety-critical decisions;
- adapt response style using the supplied mode.

## Recommended Model

`granite4.1:8b` is the recommended quality oriented default, with
`granite3.3:2b` retained as the lower resource fallback. See the
[Recommended Default Model](recommended-default-model.md) for the evidence and
limits of that decision. Benchmarking now consumes the configurable selection;
the future application entry point should do the same rather than hard-coding a
model.
