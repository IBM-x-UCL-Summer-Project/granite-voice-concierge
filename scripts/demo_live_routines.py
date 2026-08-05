"""Manual live test: start and navigate a routine by voice.

Interaction model (one microphone consumer at a time, uninterruptible playback):

* Say "hey jarvis", then a request like "start making tea" to begin a routine,
  or a navigation word ("next", "go back", "repeat", "pause", "continue",
  "stop") to move through the active routine. This is the wake-word command
  path (the parser shares one vocabulary with the KWS spotter).
* The assistant speaks each step to completion; the wake-word listener resumes
  between turns.

Barge-in (interrupting speech with "stop") is a separate feature of the
`command_control` package with its own harness, `demo_live_barge_in.py`. It is
intentionally left out here: running a second (input) audio stream concurrently
with playback trips macOS CoreAudio (PaMacCore err -50) and truncates speech, so
this routines harness keeps playback uninterruptible for a clean run.

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
from voice_concierge.audio import (  # noqa: E402
    AudioDeviceError,
    CapturedAudio,
    StreamingAudioPlayer,
)
from voice_concierge.command_control import TranscriptCommandParser  # noqa: E402
from voice_concierge.memory import build_memory_manager  # noqa: E402
from voice_concierge.reasoning.factory import build_reasoning_engine  # noqa: E402
from voice_concierge.routines import RoutineError, build_routine_adapter  # noqa: E402
from voice_concierge.voice_input.stt.factory import build_speech_to_text  # noqa: E402
from voice_concierge.voice_output import (  # noqa: E402
    SayTextToSpeech,
    TextToSpeechError,
)


def main() -> None:
    print("Loading models (first run downloads them)...")
    config = LiveAppConfig(download_wake_models=True)
    stt = build_speech_to_text()
    tts = SayTextToSpeech()
    player = StreamingAudioPlayer()
    adapter = build_routine_adapter(
        memory_manager=build_memory_manager(),
        reasoning_engine=build_reasoning_engine(),
    )
    wake = build_wake_word_listener(config)
    capturer = build_utterance_capturer(config)
    parser = TranscriptCommandParser()

    def speak(text: str) -> None:
        """Synthesize and play a response to completion (uninterruptible)."""
        player.play(tts.synthesize(text))

    active = False

    def on_wake() -> None:
        nonlocal active
        captured: list[CapturedAudio] = []
        capturer.capture_utterance(on_utterance_captured=captured.append)
        if not captured:
            return
        transcript = stt.transcribe(captured[0]).text
        print(f"You: {transcript}")
        # Fail gracefully: announce what went wrong rather than dropping the turn.
        try:
            command = parser.parse(transcript)
            if active and command is not None:
                response = adapter.handle_command(command)
            else:
                response = adapter.start_routine(transcript)
                active = True
            print(f"Assistant: {response}")
            speak(response)
        except RoutineError as exc:
            print(f"Assistant: Sorry, I couldn't load that routine right now. [{exc}]")
        except (AudioDeviceError, TextToSpeechError) as exc:
            print(f"Assistant: (I built the response but couldn't speak it: {exc})")

    print("Say 'hey jarvis', then e.g. 'start making tea'. Ctrl+C to quit.\n")
    try:
        while True:
            wake.listen(on_wake_word=on_wake)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
