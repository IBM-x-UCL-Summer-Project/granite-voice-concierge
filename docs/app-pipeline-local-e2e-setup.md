# App Pipeline Local E2E Setup

This guide lists the local setup required before testing the app pipeline with
voice input, transcript processing, local reasoning, persistent memory,
text-to-speech, and speaker playback working together.

The target path is:

```text
microphone
  -> openWakeWord wake word
  -> Silero VAD utterance capture
  -> faster-whisper STT
  -> app turn pipeline
     -> context manager
     -> SQLite/sqlite-vec memory
     -> local Ollama embeddings
     -> local Ollama Granite reasoning
  -> Piper TTS
  -> sounddevice speaker playback
```

## Host System Setup

### Python

Use Python 3.12 or newer, matching `pyproject.toml`:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

### PortAudio

`pyaudio` needs PortAudio at the OS level.

macOS:

```bash
brew install portaudio
```

Debian/Ubuntu:

```bash
sudo apt-get install portaudio19-dev
```

## Local Services

### Ollama

Ollama must be installed and running locally. The default host is:

```text
http://localhost:11434
```

The app uses Ollama locally only. It should not require cloud credentials.

## Local Models and Artifacts

### Reasoning Model

The default reasoning model is `granite4.1:8b`. The lower-resource fallback used
in docs and model selection is `granite3.3:2b`.

Pull the default model:

```bash
ollama pull granite4.1:8b
```

Optionally select a different local model for the app-facing reasoning factory:

```bash
python -m benchmarks.reasoning.manage_models select granite4.1:8b
```

The selected model is stored in:

```text
.local/reasoning-model-selection.json
```

If that file is absent, the app falls back to `granite4.1:8b`.

### Embedding Model

Persistent memory uses Ollama embeddings with:

```text
granite-embedding:278m
```

Pull it before memory E2E:

```bash
ollama pull granite-embedding:278m
```

By default, local memory writes to ignored runtime files:

```text
.local/memory/memories.sqlite3
.local/memory/vectors.sqlite3
```

Use a clean `.local/memory/` directory when you want a clean memory test, and keep
an existing one when intentionally testing recall across restarts.

### Wake Word Model

The default wake-word model is:

```text
hey_jarvis_v0.1.onnx
```

The `WakeWordDetector` can download openWakeWord models on first construction,
but for offline E2E you should prefetch them while network access is available:

```bash
python -c "import openwakeword.utils; openwakeword.utils.download_models()"
```

### VAD Model

Silero VAD loads through `silero_vad.load_silero_vad()`. Depending on the local
cache state, the first load may need network access.

Prefetch it explicitly:

```bash
python -c "from silero_vad import load_silero_vad; load_silero_vad()"
```

### STT Model

The default STT model is faster-whisper `base.en` on CPU with int8 compute.

Prefetch/load it explicitly:

```bash
python -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')"
```

### TTS Model

The TTS backend uses the Piper CLI installed by `piper-tts` and the default voice:

```text
en_GB-alan-medium.onnx
en_GB-alan-medium.onnx.json
```

Download those files with:

```bash
python -m voice_concierge.voice_output.download_models
```

The files are written beside the Piper backend module under:

```text
src/voice_concierge/voice_output/
```

Do not commit generated model files.

## Hardware and Permissions

For live E2E, verify:

- a microphone input device is visible to PyAudio;
- a speaker/output device is visible to sounddevice;
- the terminal or Python process has microphone permission;
- output volume is audible;
- only one capture component owns the microphone at a time.

On macOS, microphone permission may be tied to the terminal application used to
run Python.

## Readiness Check

Run the local readiness checker before attempting live E2E:

```bash
python -m benchmarks.app.readiness
```

To skip hardware enumeration temporarily:

```bash
python -m benchmarks.app.readiness --skip-audio-devices
```

The checker is read-only. It does not install packages, pull Ollama models,
download wake/STT/VAD/TTS files, or modify `.local/`.

## Live App Runner

After readiness passes, run the full local voice loop:

```bash
python -m voice_concierge.app.live
```

This wires:

```text
openWakeWord -> Silero VAD -> faster-whisper STT -> app pipeline -> Piper TTS
-> sounddevice playback
```

Useful local variants:

```bash
# Skip wake-word detection and capture each command with VAD.
python -m voice_concierge.app.live --no-wake-word

# Use a specific PyAudio input device from the wake-word probe list.
python -m voice_concierge.app.live --device-index <index>

# Exercise one wake/capture attempt and exit.
python -m voice_concierge.app.live --one-shot

# Disable persistent memory for a clean run.
python -m voice_concierge.app.live --no-memory

# Synthesize response audio without speaker playback.
python -m voice_concierge.app.live --no-playback

# Disable TTS and playback entirely.
python -m voice_concierge.app.live --no-tts
```

## Current Test Surface

The app pipeline can already be tested in layers:

- fake app smoke: `python -m voice_concierge.app.smoke "hello"`;
- text + reasoning + memory through `build_voice_concierge_pipeline(...)`;
- captured audio through `VoiceConciergePipeline.process_audio(...)`;
- voice input components through `build_voice_input_pipeline()`;
- TTS through `build_text_to_speech()` and `SoundDevicePlayer`.
- full live loop through `python -m voice_concierge.app.live`.
