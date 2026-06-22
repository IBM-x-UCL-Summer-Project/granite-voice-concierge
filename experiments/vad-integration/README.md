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
├── silero-vad.py    # main VAD implementation
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
   python experiments/vad-integration/silero-vad.py
```

Speak a sentence after seeing `VAD listening — speak your command...`. The script
will print speech start, utterance capture confirmation, and performance metrics
once silence is detected. If no speech is detected within
`MAX_SPEECH_START_WAIT_S` seconds the script will exit cleanly.

## Configuration

The following constants can be adjusted at the top of `silero-vad.py`:

| Constant                              | Default | Description                                           |
|---------------------------------------|---------|-------------------------------------------------------|
| `SPEECH_CONFIDENCE_THRESHOLD`         | `0.5`   | Minimum VAD confidence score to detect speech         |
| `MIN_SILENCE_BEFORE_UTTERANCE_END_MS` | `300`   | Ms of silence before utterance is considered complete |
| `UTTERANCE_BOUNDARY_PADDING_MS`       | `100`   | Ms of padding added to start and end of utterance     |
| `MAX_SPEECH_START_WAIT_S`             | `5`     | Seconds before VAD times out if no speech detected    |
| `CHUNK`                               | `512`   | Audio chunk size (~32ms at 16kHz)                     |

`MIN_SILENCE_BEFORE_UTTERANCE_END_MS` was reduced from the Silero VAD default
of 500ms — 500ms felt slow in practice, 300ms provides more natural
conversational pacing. Note that 300ms may cause early cut-offs for users who
pause mid-utterance. See benchmark results for details.

## Pipeline Position

This component sits between wake word detection and STT in the pipeline:

```text
Wake Word (openWakeWord) → VAD (Silero) → STT → Granite → TTS
```

The `capture_utterance()` function is called from the wake word callback and
returns the captured audio as a numpy array ready for STT.

## Benchmark Results

Results are recorded in:

```text
benchmarks/vad-integration/silero-vad.md
```
