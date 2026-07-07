# voice_input

The `voice_input` module implements the offline voice activation pipeline for
the IBM Granite On-Device Voice Concierge. It handles wake word detection,
utterance capture, and speech-to-text entirely on-device with no internet
connectivity required.

## Components

```text
voice_input/
├── __init__.py                  # public module interface
├── interfaces.py                # WakeWordListener, UtteranceCapturer protocols
├── wake_word_detector.py        # wake word detection using openWakeWord
├── voice_activity_detector.py   # utterance capture using Silero VAD
├── voice_input_pipeline.py      # pipeline orchestration
├── factory.py                   # build_voice_input_pipeline()
└── stt/                         # speech-to-text (SpeechToText + faster-whisper)
```

## Pipeline Position

```text
Wake Word (openWakeWord) → VAD (Silero) → STT (faster-whisper) → Granite → TTS
```

Audio flows between stages as a `CapturedAudio` value (shared `audio` package):
the VAD emits it, and the STT consumes it as an in-memory WAV — no audio is
written to disk.

## Design

- **Stage protocols** — `WakeWordListener` and `UtteranceCapturer`
  (`interfaces.py`) define the pipeline contract. `VoiceInputPipeline` depends on
  these protocols, so any implementation can be swapped in without changing the
  orchestrator.
- **Injected audio I/O** — microphone capture is abstracted behind
  `AudioSource` (`voice_concierge.audio`). Detectors receive an `AudioSource`
  (defaulting to `PyAudioSource`), so PyAudio can be swapped and tests inject a
  `FakeAudioSource` instead of mocking the driver.
- **CapturedAudio hand-off** — the VAD emits `CapturedAudio` (int16 PCM + rate),
  which serializes to an in-memory WAV for STT. Privacy by design: audio stays
  in memory and is discarded after inference.
- **Factory** — `build_voice_input_pipeline()` wires the default stack, mirroring
  `build_reasoning_engine` in the reasoning package.
- **Swappable STT** — `stt/` exposes a `SpeechToText` protocol with a
  faster-whisper backend and a deterministic fake, built via
  `build_speech_to_text()`.

## Usage

```python
from voice_concierge.voice_input import build_voice_input_pipeline
from voice_concierge.voice_input.stt import build_speech_to_text
from voice_concierge.audio import CapturedAudio

stt = build_speech_to_text()
pipeline = build_voice_input_pipeline()

def on_utterance_captured(audio: CapturedAudio) -> None:
    transcript = stt.transcribe(audio)
    print(transcript.text)

pipeline.run(on_utterance_captured=on_utterance_captured)
```

## Configuration

`WakeWordDetector`, `VoiceActivityDetector`, and the STT backend all accept
constructor overrides (thresholds, chunk sizes, model selection). Inject an
`AudioSource` to redirect capture, or a custom `SpeechToText`/`WakeWordListener`/
`UtteranceCapturer` to replace a stage entirely.

Note: `min_silence_ms` should be configured per context mode — 500ms for Home
and Cooking modes, 300ms for Shopping and Driving modes.

## Spike References

- Wake word threshold 0.3 — `benchmarks/wake-word-detection/openwakeword-hey-jarvis.md`
- VAD threshold 0.5, min_silence_ms 500 — `benchmarks/vad-integration/silero-vad.md`
