"""Manual live test: start and navigate a routine by voice.

Say the wake word ("hey jarvis"), then a request like "start making tea". While
the routine is active, say "next", "go back", "repeat", "pause", "continue", or
"stop". Uses the macOS `say` TTS backend (piper is broken on macOS).

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
from voice_concierge.audio import CapturedAudio  # noqa: E402
from voice_concierge.audio.source import PyAudioSource  # noqa: E402
from voice_concierge.command_control import (  # noqa: E402
    CommandEvent,
    CommandListener,
    TranscriptCommandParser,
    build_vosk_command_spotter,
)
from voice_concierge.command_control.listener import DEFAULT_CHUNK  # noqa: E402
from voice_concierge.memory import build_memory_manager  # noqa: E402
from voice_concierge.reasoning.factory import build_reasoning_engine  # noqa: E402
from voice_concierge.routines import build_routine_adapter  # noqa: E402
from voice_concierge.voice_input.stt.factory import build_speech_to_text  # noqa: E402


def main() -> None:
    print("Loading models (first run downloads them)...")
    config = LiveAppConfig(download_wake_models=True)
    stt = build_speech_to_text()
    adapter = build_routine_adapter(
        memory_manager=build_memory_manager(),
        reasoning_engine=build_reasoning_engine(),
    )
    wake = build_wake_word_listener(config)
    capturer = build_utterance_capturer(config)

    # Path 1 — always-on KWS: navigation words spotted during a routine drive
    # the adapter directly.
    spotter = build_vosk_command_spotter()

    def on_command(event: CommandEvent) -> None:
        print(adapter.handle_command(event))

    nav = CommandListener(
        PyAudioSource(frames_per_buffer=DEFAULT_CHUNK),
        spotter,
        on_command,
        chunk=DEFAULT_CHUNK,
    )

    # Path 2 — wake-word: a command word inside a transcribed utterance drives
    # the adapter too, using the same shared vocabulary as the KWS path.
    parser = TranscriptCommandParser()
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
            print(adapter.handle_command(command))  # wake-word navigation
            return
        print(f"Assistant: {adapter.start_routine(transcript)}")
        active = True
        nav.start()  # KWS listens for next/back/repeat/pause/stop during the routine

    print("Say 'hey jarvis', then e.g. 'start making tea'. Ctrl+C to quit.\n")
    try:
        while True:
            wake.listen(on_wake_word=on_wake)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        nav.stop()


if __name__ == "__main__":
    main()
