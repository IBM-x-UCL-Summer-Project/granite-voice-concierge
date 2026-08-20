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

The web runner defaults to the explicit `uat_relaxed` reasoning profile for
controlled testing. The UI shows **relaxed UAT** beside the local model so the
active behavior is visible. This profile prevents imperfect provenance metadata
from replacing otherwise useful non-current answers with generic verification
errors. It still blocks unavailable current/live information and retains all
memory-write, edit, deletion, privacy, confirmation, and exact-target rules.
Run the stricter fail-closed profile explicitly when needed:

```bash
python -m voice_concierge.app.web --policy-profile strict
```

The real pipeline requires the project dependencies, including the Ollama
Python client. If they have not been installed in this virtual environment,
run `python -m pip install -e .`. The `--demo` mode does not import or require
the Ollama client.

Enable browser microphone transcription, wake-word mode, and pipeline-generated
response audio:

```bash
python -m voice_concierge.app.web --voice-io
```

The UI stays on port `4173`; continuous wake-word and voice-command PCM uses a
bounded binary WebSocket on loopback port `4174`. The WebSocket requires the
active HTTP session cookie, validates the page origin and protocol, accepts one
acknowledged frame at a time, and bounds queued audio so a slow model cannot
grow browser memory without limit. Push-to-talk remains a single in-memory WAV
upload. The Docker deployment publishes both ports to `127.0.0.1` and does not
map a host audio device into the container.

Without `--voice-io`, the microphone control is disabled and the response play
button deliberately falls back to the browser's installed system voice. Device
selection alone does not load Whisper or Piper. With `--voice-io`, click the
microphone once to start recording and again to transcribe and send it. The
**Wake mode** button opens a dedicated hands-free screen. Microphone samples are
resampled in the browser and sent only to the same-origin local server, where
the existing openWakeWord model listens for **Hey Jarvis**. After detection,
the browser records until a local silence threshold is reached, sends the
utterance through Whisper and the normal application pipeline, plays the spoken
response, then opens a short follow-up listening window before resuming
wake-word listening. The dedicated wake screen also provides push-to-talk and
cancel controls. Wake sensitivity, allowed mid-request pauses, the follow-up
window, and maximum request length can be changed in that screen or Personalise.
The pinned header remains interactive while wake mode is open, so Local data,
Personalise, theme, and wake-mode controls stay available without ending the
hands-free session. The conversation workspace remains covered by the wake view.
Only one browser tab owns the stateful detector at a time. Use `--no-wake-word`
to keep push-to-talk voice I/O while disabling continuous wake-word mode.

Spoken responses use Piper first. When the server runs directly on macOS and
Piper fails, it retries with the native `say` command. If neither server-side
voice produces audio, the UI can use the browser's speech-synthesis voice as a
last fallback. A Docker container cannot call the host's `say` command, so its
chain is Piper then browser speech. To preserve local data control, the browser
fallback only selects a voice the Web Speech API marks as a local service.
Installed voices vary by device and browser; the response always remains
readable as text when no local voice is available.

The **Voice first** setting automatically plays every spoken response; **Push
to talk** automatically plays only responses to microphone turns; **Text
first** keeps playback manual; **Wake word** opens the dedicated hands-free
view after setup. The browser unlocks one reusable response-audio element
during the initiating click or key action so delayed local responses can still
play under browser autoplay rules.

Persistent local memory is enabled by default. To run without it:

```bash
python -m voice_concierge.app.web --voice-io --no-memory
```

Reminders and guided routines are enabled by default for the real pipeline.
Use `--no-reminders` or `--no-guided-routines` to disable either service. The
same chat composer accepts reminder and routine requests. Due reminders are
queued by the running local application, delivered to the browser exactly once,
and use configured Piper audio when voice I/O is enabled. If the bounded queue
is full, a reminder stays due and is retried instead of being discarded.

Guided routines automatically move on after a six-second quiet window. With
`--voice-io`, local Vosk spotting keeps the same CLI control vocabulary active
during playback and between steps: `pause`, `continue`, `next`, `back`,
`repeat`, `slower`, `faster`, and `stop`. Going back still requires a spoken or
typed confirmation.

The **Local data** panel lists scheduled reminders and saved memories with their
local storage locations. Memories can be
edited, deleted, exported, or forgotten together; reminders can be edited,
snoozed, or cancelled. Destructive actions use an explicit in-app confirmation
dialog, and bulk actions also require a separate API confirmation token.

**Export chat** downloads the current server-owned temporary conversation over
the same-origin local connection. It includes text messages, mode, export time,
and explicit privacy metadata; it never includes recorded audio or saved
memories. Exporting does not turn on conversation persistence.

The server keeps an extended temporary display/export history of up to 200
completed exchanges separately from the six-turn reasoning context window.
Long conversations therefore remain visible and survive a page reload while
that local server session is alive, without sending every old turn back through
the model. The header stays pinned while the transcript scrolls.

For detailed UAT diagnostic logs in both the terminal and an ignored local
file:

```bash
python -m voice_concierge.app.web --voice-io \
  --log-level DEBUG --log-file .local/logs/web.log
```

DEBUG mode includes prompts, responses, selected feature/reasoning routes,
memory and reminder operations, startup/STT/request timings, wake and barge-in
detections, browser connection state, voice capture, and response playback.
The example therefore persists conversation text and should be used only for
deliberate local troubleshooting, not as the normal service configuration.
Each browser API request sends a client request ID which the backend returns as
`X-Request-ID`, making the browser event and server-side pipeline entries easy
to correlate. Raw WAV/PCM base64 bodies are represented by their character
count instead of being copied into the log. INFO mode keeps the shorter turn
completion summaries.

For UI review without Ollama or audio models, use the deterministic pipeline
adapters while keeping the same HTTP, serialization, state, and component flow:

```bash
python -m voice_concierge.app.web --demo
```

## Browser code structure

The dependency-free client is split by responsibility: shared state and DOM
references (`app-context.js`), diagnostics, settings, conversation rendering,
API transport, playback, push-to-talk input, voice commands, wake-word mode,
session orchestration, and local-data controls. `app.js` contains only startup
and event wiring. `index.html` loads these classic scripts in dependency order
so the application does not require a browser build step.

Microphone modes share `audio-capture.js`, which filters a common constraint
set through `getSupportedConstraints()`, logs the browser-selected
`MediaStreamTrack.getSettings()`, and owns track/context cleanup. An
`AudioWorklet` converts the browser rate to 16 kHz mono with a stateful
windowed-sinc low-pass resampler. Continuous modes use `audio-stream.js`; raw
audio stays binary and its queue applies application-level backpressure.

Unit, protocol, and real-engine browser coverage is described in
[`docs/browser-audio-testing.md`](../docs/browser-audio-testing.md).

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

Chance utilities such as coin flips, dice rolls, and bounded random-number
selection execute in local application code rather than relying on model text.
Clear gas, fire, smoke, and urgent medical phrases also take a deterministic
emergency path so model source metadata cannot replace urgent guidance with an
offline-information error. Explicit facts stated in the recent conversation can
be recalled directly when the follow-up names the same personal fact.

Additional same-origin endpoints support the connected local features:

- `GET /api/health`, `/api/privacy`, `/api/privacy/export`, `/api/reminders`,
  and `/api/reminders/due`;
- memory edit/delete/forget-all under `POST /api/privacy/memories/...`;
- reminder create/edit/snooze/cancel/cancel-all under
  `POST /api/reminders/...`;
- fixed-text local speech-chain testing under `POST /api/speech/preview`;
- compatibility wake-word and guided-command controls under the existing HTTP
  endpoints (the bundled browser uses the authenticated binary WebSocket for
  continuous PCM);
- privacy-safe browser wake timing under `POST /api/diagnostics/wake-timing`;
- DEBUG browser-event forwarding under `POST /api/diagnostics/client-event`;
- temporary state/display-history restoration under `GET /api/session`.

Unknown `/api/` routes return JSON errors for both GET and POST requests. The
browser checks health every five seconds, disables turn controls while
disconnected, shows a reconnecting state, and restores them when the local
server returns.

For the real pipeline, the HTTP server starts an Ollama warm-up turn in the
background before accepting user turns. `GET /api/health` reports `starting`,
`ready`, or `error`, and the browser shows a blocking local-engine startup view
until readiness is confirmed. Each submitted prompt also renders a visible
transcribing/thinking message and keeps waiting for the configured local
reasoning timeout rather than failing after a short browser-only timeout.

Audio turns send a browser-recorded mono PCM WAV as `wav_base64`; the backend
decodes it and calls `pipeline.process_audio(...)`. Playback stays browser-
controlled so the selected output device, pace, volume, replay, and stop controls
remain responsive without asking the server to use its own speakers. The
pipeline's persisted `context.accessibility.speech_pace` is applied as the base
playback pace, with the personal device setting acting as a local multiplier.

### Wake-word timing diagnostics

The dedicated wake-timing endpoint reports timing values only—never audio or
transcript text—when a wake phrase starts request capture. Other DEBUG browser
events deliberately include transcripts and responses for controlled UAT
diagnosis. Run the server with debug logging to measure the browser/server
handoff:

```bash
.venv/bin/python -m voice_concierge.app.web --voice-io \
  --log-level DEBUG --log-file .local/logs/web-debug.log
```

Then look for `web_wake_detection` and `web_wake_timing`. The useful values are
`server_processing_ms` (local wake model time), `wake_round_trip_ms` (complete
browser-to-server round trip), `detection_to_capture_ms` (UI transition time),
and `buffered_audio_ms` (audio received and retained as request pre-roll while
detection was in flight). The browser console shows the same client timing
events as `[Granite] wake_timing`. Retained pre-roll does not trigger a request
on its own. Request detection arms after a short wake-tail window, so a prompt
that continues after “Hey Jarvis” is kept while the wake phrase alone cannot
become a spurious turn. The same guard prevents response playback tails from
submitting empty follow-up turns.

## Guided personal setup

On the first visit, the UI opens a four-step setup for:

- microphone and speaker selection;
- speech rate and volume, with a Piper-first local voice-chain test and explicit
  offline browser fallback;
- wake-word sensitivity, pause/follow-up/request timing, and wake-word,
  voice-first, push-to-talk, or text-first control;
- response length and spoken confirmation preferences.

The browser asks for microphone permission only when **Find devices** is
selected. Preferences are saved under `granite-personal-settings-v1` in browser
local storage and restored on later visits. The **Personalise** control in the
header reopens the setup at any time. These device preferences and the theme are
the only application values stored in browser local storage; transcripts and
conversation state are not persisted there.
