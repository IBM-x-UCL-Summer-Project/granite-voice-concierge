"""Manual live test: start and navigate a routine by voice.

Interaction model (single microphone consumer at any moment):

* Between turns, only the wake-word listener is live. Say "hey jarvis", then a
  request like "start making tea" to begin, or a navigation word ("next", "go
  back", "repeat", "pause", "continue", "stop") to move through an active
  routine. This is the wake-word command path.
* While the assistant is speaking a step, the barge-in KWS listener is live
  (windowed: only from the end of your utterance to the end of playback) and
  lets you cut the speech short with "stop", or hold it with "pause" /
  "continue". The wake-word listener is not running during this window, so the
  two never contend for the microphone.

Uses the macOS `say` TTS backend (piper is broken on macOS).

Run from the repo root in the venv:
    .venv/bin/python scripts/demo_live_routines.py

First run downloads models (openWakeWord, Whisper, Vosk). Requires Ollama running
with the configured reasoning model. Ctrl+C to quit.
"""

# Standard library
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Local
from voice_concierge.app.live import (  # noqa: E402
    LiveAppConfig,
    build_utterance_capturer,
    build_wake_word_listener,
)
from voice_concierge.audio import CapturedAudio, StreamingAudioPlayer  # noqa: E402
from voice_concierge.audio.source import PyAudioSource  # noqa: E402
from voice_concierge.command_control import (  # noqa: E402
    CommandDispatcher,
    CommandListener,
    TranscriptCommandParser,
    build_vosk_command_spotter,
)
from voice_concierge.command_control.listener import DEFAULT_CHUNK  # noqa: E402
from voice_concierge.memory import build_memory_manager  # noqa: E402
from voice_concierge.reasoning.factory import build_reasoning_engine  # noqa: E402
from voice_concierge.routines import build_routine_adapter  # noqa: E402
from voice_concierge.voice_input.stt.factory import build_speech_to_text  # noqa: E402
from voice_concierge.voice_output import SayTextToSpeech  # noqa: E402


def main() -> None:
    print("Loading models (first run downloads them)...")
    config = LiveAppConfig(download_wake_models=True)
    stt = build_speech_to_text()
    tts = SayTextToSpeech()
    adapter = build_routine_adapter(
        memory_manager=build_memory_manager(),
        reasoning_engine=build_reasoning_engine(),
    )
    wake = build_wake_word_listener(config)
    capturer = build_utterance_capturer(config)
    parser = TranscriptCommandParser()

    # One pausable player is both the speaker and the barge-in controller.
    player = StreamingAudioPlayer()
    dispatcher = CommandDispatcher(player)  # stop/pause/resume act on playback
    barge_in = CommandListener(
        PyAudioSource(frames_per_buffer=DEFAULT_CHUNK),
        build_vosk_command_spotter(),
        dispatcher.dispatch,
        chunk=DEFAULT_CHUNK,
    )

    def speak(text: str) -> None:
        """Speak a response; the barge-in KWS listener is live only while it plays."""
        audio = tts.synthesize(text)
        barge_in.start()  # window opens (STT done) ...
        try:
            player.play(audio)  # blocks until finished or "stop" cuts it off
        finally:
            barge_in.stop()  # ... window closes (TTS done)

    active = False

    def on_wake() -> None:
        nonlocal active
        captured: list[CapturedAudio] = []
        capturer.capture_utterance(on_utterance_captured=captured.append)
        if not captured:
            return
        transcript = stt.transcribe(captured[0]).text
        print(f"You: {transcript}")
        command = parser.parse(transcript)
        if active and command is not None:
            response = adapter.handle_command(command)  # navigate the active routine
        else:
            response = adapter.start_routine(transcript)  # start a new routine
            active = True
        print(f"Assistant: {response}")
        speak(response)

    print("Say 'hey jarvis', then e.g. 'start making tea'. Ctrl+C to quit.\n")
    try:
        while True:
            wake.listen(on_wake_word=on_wake)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
