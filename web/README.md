# Pipeline-connected web UI

This dependency-free web prototype visualises the current Granite Voice
Concierge pipeline and follows the shapes in
`docs/app-pipeline-ui-contract.md`.

Run it from the repository root with the local application pipeline:

```bash
python -m voice_concierge.app.web
```

Then open `http://localhost:4173`.

Enable browser microphone transcription and pipeline-generated response audio:

```bash
python -m voice_concierge.app.web --voice-io
```

Persistent local memory remains opt-in:

```bash
python -m voice_concierge.app.web --voice-io --memory
```

For UI review without Ollama or audio models, use the deterministic pipeline
adapters while keeping the same HTTP, serialization, state, and component flow:

```bash
python -m voice_concierge.app.web --demo
```

## Integration boundary

The server exposes same-origin `POST /api/turn` and `POST /api/audio` endpoints.
Both paths run through `VoiceConciergePipeline`, return the same serialized turn
result, and round-trip the complete pipeline state. The browser never applies
context, memory, confirmation, response-shaping, or error fallback rules itself.

Text turns send:

```js
{
  transcript,
  state: state.pipeline,
  options: { synthesize: voiceOutputEnabled, play: false }
}
```

Audio turns send a browser-recorded mono PCM WAV as `wav_base64`; the backend
decodes it and calls `pipeline.process_audio(...)`. Playback stays browser-
controlled so the selected output device, pace, volume, replay, and stop controls
remain responsive without asking the server to use its own speakers. The
pipeline's persisted `context.accessibility.speech_pace` is applied as the base
playback pace, with the personal device setting acting as a local multiplier.

## Guided personal setup

On the first visit, the UI opens a four-step setup for:

- microphone and speaker selection;
- speech rate and volume, with local voice preview;
- wake-word sensitivity and voice-first, push-to-talk, or text-first control;
- response length and spoken confirmation preferences.

The browser asks for microphone permission only when **Find devices** is
selected. Preferences are saved under `granite-personal-settings-v1` in browser
local storage and restored on later visits. The **Personalise** control in the
header reopens the setup at any time.
