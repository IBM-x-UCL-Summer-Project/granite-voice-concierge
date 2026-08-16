# Pipeline-connected web UI

This dependency-free web client provides the conversation experience for the
current Granite Voice Concierge pipeline and follows the shapes in
`docs/app-pipeline-ui-contract.md`. Pipeline state remains internal to the
application flow and is not exposed as an inspector in the user interface.

Run it from the repository root with the local application pipeline:

```bash
source .venv/bin/activate
python -m voice_concierge.app.web
```

Then open `http://localhost:4173`.

The real pipeline requires the project dependencies, including the Ollama
Python client. If they have not been installed in this virtual environment,
run `python -m pip install -e .`. The `--demo` mode does not import or require
the Ollama client.

Enable browser microphone transcription and pipeline-generated response audio:

```bash
python -m voice_concierge.app.web --voice-io
```

Without `--voice-io`, the microphone control is disabled and the response play
button deliberately falls back to the browser's installed system voice. Device
selection alone does not load Whisper or Piper. With `--voice-io`, click the
microphone once to start recording and again to transcribe and send it. The
**Voice first** setting automatically plays every Piper response; **Push to
talk** automatically plays only responses to microphone turns; **Text first**
keeps playback manual. The browser unlocks one reusable response-audio element
during the initiating click or key action so delayed local Piper responses can
still play under browser autoplay rules.

The web transport does not continuously stream microphone audio, so wake-word
detection remains a live-runner capability rather than a browser capability.

Persistent local memory remains opt-in:

```bash
python -m voice_concierge.app.web --voice-io --memory
```

Reminders and guided routines are enabled by default for the real pipeline.
Use `--no-reminders` or `--no-guided-routines` to disable either service. The
same chat composer accepts reminder and routine requests. Due reminders are
acknowledged only when an open browser polls and receives them, so closing the
browser does not silently consume a due reminder.

The **Local data** panel lists scheduled reminders and, when `--memory` is
enabled, saved memories and their local storage locations. Memories can be
edited, deleted, exported, or forgotten together; reminders can be edited,
snoozed, or cancelled. Destructive actions use an explicit in-app confirmation
dialog, and bulk actions also require a separate API confirmation token.

For privacy-conscious diagnostic logs in both the terminal and an ignored local
file:

```bash
python -m voice_concierge.app.web --voice-io --memory \
  --log-level INFO --log-file .local/logs/web.log
```

Turn logs include the endpoint, duration, recoverable error codes, and typed
memory-operation status/detail. They do not include transcript or memory text.

For UI review without Ollama or audio models, use the deterministic pipeline
adapters while keeping the same HTTP, serialization, state, and component flow:

```bash
python -m voice_concierge.app.web --demo
```

## Integration boundary

The server exposes same-origin `POST /api/turn` and `POST /api/audio` endpoints.
Both paths run through `VoiceConciergePipeline`, return the same serialized turn
result, and use complete pipeline state held by the server for the browser's
HTTP-only session. The browser keeps response state in memory only for rendering
and never writes conversation history to browser storage or supplies
authoritative context, confirmation, or memory actions. It does not apply
response-shaping or error fallback rules itself.

Text turns send:

```js
{
  transcript,
  options: {
    synthesize: voiceOutputEnabled,
    play: false,
    response_length: "short" | "normal" | "detailed"
  }
}
```

Response length is applied to the server-owned accessibility profile and the
reasoning word limit. Detailed responses never relax Driving mode's shorter
safety limit.

The server ignores any posted `state` field for backwards compatibility. This
prevents browser storage or a manually crafted request from manufacturing a
pending memory mutation and then confirming it. Session state is intentionally
in-process and is cleared when the local server restarts. **New conversation**
calls `POST /api/session/reset` to clear it immediately without deleting saved
memories or reminders.

Additional same-origin endpoints support the connected local features:

- `GET /api/health`, `/api/privacy`, `/api/privacy/export`, `/api/reminders`,
  and `/api/reminders/due`;
- memory edit/delete/forget-all under `POST /api/privacy/memories/...`;
- reminder create/edit/snooze/cancel/cancel-all under
  `POST /api/reminders/...`.

Unknown `/api/` routes return JSON errors for both GET and POST requests. The
browser checks health every five seconds, disables turn controls while
disconnected, shows a reconnecting state, and restores them when the local
server returns.

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
header reopens the setup at any time. These device preferences and the theme are
the only application values stored in browser local storage; transcripts and
conversation state are not persisted there.
