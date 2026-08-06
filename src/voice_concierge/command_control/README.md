# command_control

Event-driven **barge-in** control for the IBM Granite On-Device Voice Concierge:
a low-latency path that lets the user interrupt the assistant *while it is
speaking* (e.g. say "stop"), bypassing the normal request pipeline.

## Why this exists

The turn pipeline is synchronous — while text-to-speech is playing it blocks in
`speak()` and nothing is listening, so a "stop" spoken during playback is never
heard until after the audio already finished. This module runs a lightweight
command spotter on a **background thread** during the response window, so a
command can act on playback immediately, without going through STT → context →
reasoning.

## Components

```text
command_control/
├── types.py                  # CommandEvent, PlaybackCommand (stop/pause/resume)
├── interfaces.py             # CommandSpotter, PlaybackController, PhraseRecognizer
├── spotter.py                # PhraseCommandSpotter (phrase -> command mapping)
├── vosk_recognizer.py        # VoskPhraseRecognizer (the only Vosk-specific code)
├── sounddevice_controller.py # SoundDevicePlaybackController (stop via sd.stop())
├── dispatcher.py             # CommandDispatcher (event -> controller fast-lane)
├── listener.py               # CommandListener (windowed background thread)
├── factory.py                # build_* assembly helpers
├── fakes.py, errors.py
```

## Flow

```text
VAD ends ─▶ CommandListener.start()          (open the barge-in window)
  [background thread]
   AudioSource frame ─▶ PhraseRecognizer (Vosk) ─▶ PhraseCommandSpotter
     ─▶ CommandEvent ─▶ CommandDispatcher ─▶ PlaybackController.stop()
TTS ends ─▶ CommandListener.stop()           (close the window)
```

## Design

- **Windowed, not always-on** — the listener is active only between the VAD
  utterance end and the TTS output end, so it never competes with the VAD for
  the microphone and only spends CPU during the assistant's response.
- **Recognizer decoupled from the KWS mapping** — `PhraseRecognizer`
  (audio → recognized phrase) is separate from `PhraseCommandSpotter`
  (phrase → command). Swapping Vosk for another engine means writing one
  `PhraseRecognizer`; the mapping and everything downstream is unchanged.
- **Fast-lane** — `CommandDispatcher` routes a `CommandEvent` straight to the
  `PlaybackController`, deliberately bypassing context and reasoning (an
  emergency "stop" must not wait on the LLM).
- **Protocols + fakes** — every stage has a protocol and a deterministic fake,
  so the whole loop is unit-testable without a microphone, models, or threads.

## Usage

```python
from voice_concierge.command_control import build_stop_command_control

# Recognizes "stop" and aborts playback via sounddevice.
listener = build_stop_command_control()

# Driven by the pipeline around the assistant's response:
listener.start()   # when the VAD utterance ends
# ... STT -> reasoning -> TTS plays (on another thread) ...
listener.stop()    # when TTS output ends
```

For the full `stop`/`pause`/`resume` vocabulary, pass a controller that can hold
a playback position — `StreamingAudioPlayer` satisfies both `AudioPlayer` (so it
is the pipeline's speaker) and `PlaybackController` (so barge-in drives it):

```python
from voice_concierge.audio import StreamingAudioPlayer
from voice_concierge.command_control import build_playback_command_control

player = StreamingAudioPlayer()          # also used as the pipeline's audio player
listener = build_playback_command_control(player)
```

The Vosk model (~40 MB, e.g. `vosk-model-small-en-us-0.15`) is downloaded and
cached automatically on first use; there is no manual download step. Override
the name via the `model_name=` argument if needed.

## Scope

- **Implemented:** stop/pause/resume barge-in — Vosk recognition, phrase→command
  mapping, windowed listener, and two playback controllers: a stop-only
  `SoundDevicePlaybackController` (`sounddevice.stop()`) and the resumable
  `audio.StreamingAudioPlayer`, which holds a playback position so `pause` and
  `resume` work.
- **Deferred:** wiring `listener.start()`/`stop()` into the `app/` pipeline
  (requires non-blocking TTS playback); acoustic echo / self-trigger handling
  (the recognizer emits from partial results, so the assistant's own voice can
  in principle self-trigger during playback).
```
