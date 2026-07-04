# voice_input

The `voice_input` module implements the offline voice activation pipeline for
the IBM Granite On-Device Voice Concierge. It handles wake word detection and
utterance capture entirely on-device with no internet connectivity required.

## Components

```text
voice_input/
├── __init__.py                  # public module interface
├── wake_word_detector.py        # wake word detection using openWakeWord
├── voice_activity_detector.py   # utterance capture using Silero VAD
└── voice_input_pipeline.py      # pipeline orchestration
```

## Pipeline Position

This module implements the first stage of the full voice interaction pipeline:

```text
Wake Word (openWakeWord) → VAD (Silero) → STT → Granite → TTS
```

## Usage

```python
from voice_concierge.voice_input import VoiceInputPipeline
import numpy as np

def on_utterance_captured(audio: np.ndarray) -> None:
    # connect STT here
    pass

pipeline = VoiceInputPipeline()
pipeline.run(on_utterance_captured=on_utterance_captured)
```

## Classes

### WakeWordDetector

Listens continuously to the microphone and fires a callback when the wake
word is detected using openWakeWord.

```python
from voice_concierge.voice_input import WakeWordDetector

detector = WakeWordDetector(
    model_name="hey_jarvis_v0.1.onnx",  # pre-trained model
    confidence_threshold=0.3,            # from spike benchmarks
)
detector.listen(on_wake_word=my_callback)
```

Key parameters:

| Parameter              | Default               | Description                          |
|------------------------|-----------------------|--------------------------------------|
| `model_name`           | `hey_jarvis_v0.1.onnx`| openWakeWord ONNX model filename     |
| `confidence_threshold` | `0.3`                 | minimum confidence to trigger        |
| `chunk`                | `1280`                | audio chunk size (~80ms at 16kHz)    |
| `rate`                 | `16000`               | sample rate required by openWakeWord |

### VoiceActivityDetector

Captures a user utterance after the wake word fires, detecting speech
boundaries using Silero VAD.

```python
from voice_concierge.voice_input import VoiceActivityDetector

vad = VoiceActivityDetector(
    confidence_threshold=0.5,  # from spike benchmarks
    min_silence_ms=500,        # timeout after speech ends
    max_wait_s=5,              # timeout if no speech detected
    collect_metrics=False,     # set True for benchmarking
)
vad.capture_utterance(on_utterance_captured=my_callback)
```

Key parameters:

| Parameter              | Default | Description                                       |
|------------------------|---------|---------------------------------------------------|
| `confidence_threshold` | `0.5`   | minimum VAD confidence to detect speech           |
| `min_silence_ms`       | `500`   | ms of silence before utterance is complete        |
| `padding_ms`           | `100`   | ms of padding added to utterance boundaries       |
| `max_wait_s`           | `5`     | seconds before timeout if no speech detected      |
| `collect_metrics`      | `False` | collect and print latency, RAM, CPU on capture    |

Note: `min_silence_ms` should be configured per context mode — 500ms for
Home and Cooking modes, 300ms for Shopping and Driving modes.

### VoiceInputPipeline

Orchestrates the full wake word → VAD loop, resetting after each utterance
and returning to wake word listening.

```python
from voice_concierge.voice_input import VoiceInputPipeline
from voice_concierge.voice_input import WakeWordDetector
from voice_concierge.voice_input import VoiceActivityDetector

# Use defaults
pipeline = VoiceInputPipeline()

# Or inject custom instances
pipeline = VoiceInputPipeline(
    wake_word_detector=WakeWordDetector(confidence_threshold=0.3),
    voice_activity_detector=VoiceActivityDetector(min_silence_ms=300),
)

pipeline.run(on_utterance_captured=my_callback)
```

## Design Decisions

- **Dependency injection** — `WakeWordDetector` and `VoiceActivityDetector`
  are injected into `VoiceInputPipeline` rather than created internally,
  making the pipeline easy to configure and test.
- **Callback pattern** — all components communicate via callbacks, keeping
  the interface minimal and making STT integration straightforward.
- **CPU-only baseline** — all models run on CPU with no GPU requirement,
  suitable for edge deployment on laptops and tablets.
- **Privacy by design** — all audio processing is in-memory and discarded
  after inference. No audio is written to disk.

## Spike References

- Wake word threshold 0.3 — `benchmarks/wake-word-detection/openwakeword-hey-jarvis.md`
- VAD threshold 0.5, min_silence_ms 500 — `benchmarks/vad-integration/silero-vad.md`
