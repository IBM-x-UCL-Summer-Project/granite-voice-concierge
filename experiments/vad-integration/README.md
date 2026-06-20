# VAD Integration Experiment

Spike to evaluate Silero VAD for utterance boundary detection in the IBM Granite
On-Device Voice Concierge pipeline. This component connects after the wake word
callback fires in the Option B pipeline.

## Purpose

Test whether Silero VAD can reliably capture the boundaries of a user utterance
on macOS, and confirm it is lightweight enough to run without meaningful impact
on CPU or RAM.

## Related Issues

- [spike] Implement and evaluate Silero VAD for utterance boundary detection

## Contents

```text
vad-integration/
├── vad.py           # main VAD implementation
├── requirements.txt # dependencies for this experiment
└── README.md
```

## Setup

1. Activate the project virtual environment from the project root:

```bash
   source .venv/bin/activate
```

2. Install dependencies:

```bash
   pip install -r experiments/vad-integration/requirements.txt
```

## Usage

Run the VAD standalone to test utterance capture:

```bash
python experiments/vad-integration/vad.py
```

Speak a sentence after seeing `VAD listening — speak your command...`. The script
will print speech start, utterance capture confirmation, and performance metrics
once silence is detected.

## Configuration

The following constants can be adjusted at the top of `vad.py`:

| Constant                  | Default | Description                                        |
|---------------------------|---------|----------------------------------------------------|
| `THRESHOLD`               | `0.5`   | Minimum VAD confidence score to detect speech      |
| `MIN_SILENCE_DURATION_MS` | `300`   | Ms of silence before utterance is considered done  |
| `SPEECH_PAD_MS`           | `100`   | Ms of padding added to start and end of utterance  |
| `CHUNK`                   | `512`   | Audio chunk size (~32ms at 16kHz)                  |

`MIN_SILENCE_DURATION_MS` was reduced from the Silero VAD default of 500ms —
500ms felt slow in practice, 300ms provides more natural conversational pacing.

## Pipeline Position

This component sits between wake word detection and STT in the pipeline:

Wake Word (openWakeWord) → VAD (Silero) → STT → Granite → TTS

The `capture_utterance()` function is called from the wake word callback and
returns the captured audio as a numpy array ready for STT.

## Benchmark Results

Results are recorded in:

```text
benchmarks/vad-integration/silero-vad.md
```
