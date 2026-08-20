# Browser audio verification

The browser audio boundary has two layers of automated coverage:

- `pytest` exercises constraint filtering, actual-setting reporting, permission
  denial, interruption/resume cleanup, device replacement, band-limited
  resampling, binary framing, bounded queues, slow acknowledgements, session
  ownership, and WebSocket origin/session validation.
- Playwright runs the real `AudioContext`, `AudioWorklet`, and resampler against
  a generated microphone signal in Chromium, Firefox, and WebKit. WebKit is a
  useful engine-level regression target, but it is not a substitute for a
  release check in Safari itself.

## Automated cross-browser run

From `tests/browser`:

```bash
npm install
npm run install:browsers
npm test
```

The suite starts a loopback static server on port `4180`. It does not use a
physical microphone, persist audio, contact Ollama, or send data off-device.

## Release browser matrix

Before a release that changes browser audio, run the application with
`--voice-io --log-level DEBUG` and complete this matrix in the latest stable
Chrome, Firefox, and Safari on a supported host:

| Scenario | Expected result |
| --- | --- |
| Allow microphone | Push-to-talk records and sends; logs show requested constraints and actual track settings. |
| Deny microphone | The UI explains that permission was denied; no recording or continuous stream remains active. |
| Push-to-talk synthetic/known speech | One in-memory WAV is uploaded and Whisper receives intelligible 16 kHz mono input. |
| Wake phrase and command | Wake audio uses binary WebSocket frames; detection hands buffered command audio to capture without losing the first word. |
| Slow or paused backend | The client keeps at most one frame in flight and three queued frames, reports drops, and remains responsive. |
| Change selected microphone | The old track ends, the new device is opened with an exact `deviceId`, and wake/command listening resumes. |
| Unplug selected microphone | The selection falls back to the system default and continuous listening restarts cleanly. |
| Background then restore tab | Returning to the tab resumes a suspended audio context or shows a clear failure. |
| Interrupt track or revoke permission | Tracks and audio contexts close; the UI exits recording/listening state. |
| Two tabs start continuous listening | The newer stream owns the detector; the older tab receives a replacement error and cannot stop the new stream. |

Use a loopback or virtual audio device containing non-sensitive test speech when
repeatable microphone input is required. Record browser/version, OS, input
sample rate, selected settings, and any console/server diagnostics with the
release evidence. Do not commit recorded audio or DEBUG logs.
