# Wake Word Detection Experiment

Spike to evaluate openWakeWord with a pre-trained model for wake word detection
in the IBM Granite On-Device Voice Concierge pipeline.

## Purpose

Test whether openWakeWord can reliably detect a pre-trained wake word from live
microphone input on macOS, and evaluate confidence threshold trade-offs between
detection rate and false positive rate.

## Related Issues

- [spike] Implement wake word detection with pre-trained model
- [spike] Benchmark wake word confidence threshold in realistic conditions

## Contents

```text
wake-word-detection/
├── wake_word_detection.py   # main detection script
├── play_audio.py            # plays back WAV test audio through speakers
├── requirements.txt         # dependencies for this experiment
├── test_audio/              # test audio files (not committed, see below)
└── README.md
```

## Setup

1. Create and activate a virtual environment from the project root:

```bash
   python3.9 -m venv .venv
   source .venv/bin/activate
```

2. Install dependencies:

```bash
   pip install -r experiments/wake-word-detection/requirements.txt
```

3. Grant microphone access to Terminal when prompted on first run.

## Usage

Run the wake word detector:

```bash
python experiments/wake-word-detection/wake_word_detection.py
```

Play back a test audio file in a separate terminal while the detector is running:

```bash
python experiments/wake-word-detection/play_audio.py
```

Say "hey Jarvis" to trigger the wake word. Detection results including confidence,
latency, RAM, and CPU are printed to the terminal on each detection.

## Configuration

The following constants can be adjusted at the top of `wake_word_detection.py`:

| Constant               | Default | Description                              |
|------------------------|---------|------------------------------------------|
| `CONFIDENCE_THRESHOLD` | `0.3`   | Minimum confidence score to trigger      |
| `CHUNK`                | `1280`  | Audio chunk size (~80ms at 16kHz)        |
| `RATE`                 | `16000` | Sample rate required by openWakeWord     |

## Test Audio

Test audio files are not committed to the repo. To generate them:

1. Go to elevenlabs.io and generate "hey Jarvis" samples using the following
   ElevenLabs voices to match the original test conditions:
   - Male 1: Spuds Oxley
   - Male 2: David
   - Female 1: Maria Moody
   - Female 2: Jane

2. Convert to 16kHz mono WAV using ffmpeg:

```bash
   ffmpeg -i input.mp3 -ar 16000 -ac 1 -sample_fmt s16 test_audio/filename.wav
```

3. Save files as:
   - `test_audio/hey_jarvis_older_male_1.wav`
   - `test_audio/hey_jarvis_older_male_2.wav`
   - `test_audio/hey_jarvis_older_female_1.wav`
   - `test_audio/hey_jarvis_older_female_2.wav`

## Benchmark Results

Results are recorded in:

```text
benchmarks/wake-word-detection/openwakeword-hey-jarvis.md
```
