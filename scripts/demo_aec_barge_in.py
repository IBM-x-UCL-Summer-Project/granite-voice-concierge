"""Live barge-in with macOS acoustic echo cancellation.

Speaks a phrase through VoiceProcessingAudioPlayer, which plays and captures the
microphone in one echo-cancelled audio graph. Because the OS removes the
assistant's own voice from the mic, it does not hear itself, so it plays the
whole phrase when you are silent and cuts off only when YOU say "stop".

macOS only: needs pyobjc-framework-AVFoundation (see the macos-aec extra).

Run from the repo root:
    .venv/bin/python scripts/demo_aec_barge_in.py

First run downloads the Vosk model. Press Enter to play, then say "stop" / "pause"
/ "continue". Ctrl+C to quit.
"""

# Standard library
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Local
from voice_concierge.audio import VoiceProcessingAudioPlayer  # noqa: E402
from voice_concierge.command_control import (  # noqa: E402
    CommandDispatcher,
    CommandEvent,
    build_vosk_command_spotter,
)
from voice_concierge.voice_output import SayTextToSpeech  # noqa: E402

PHRASE = (
    "Step one. Bring a large pot of water to a rolling boil. "
    "Step two. Add a generous pinch of salt. "
    "Step three. Add the pasta and stir occasionally for about ten minutes. "
    "Step four. Drain the pasta and serve it immediately."
)


def main() -> None:
    print("Loading the Vosk command model and synthesizing the phrase...")
    audio = SayTextToSpeech().synthesize(PHRASE)  # any rate; the player resamples
    player = VoiceProcessingAudioPlayer()
    # The player delivers echo-cancelled 16 kHz mono frames, so no debounce is
    # needed: the recognizer can act on the first hit.
    spotter = build_vosk_command_spotter()
    dispatcher = CommandDispatcher(player)

    def on_frame(frame: bytes) -> None:
        event: CommandEvent | None = spotter.process(frame)
        if event is not None:
            print(f"    [barge-in] heard {event.phrase!r} -> {event.command}")
            dispatcher.dispatch(event)

    print("Say 'stop' while it speaks to interrupt. Ctrl+C to quit.\n")
    try:
        while True:
            input("Press Enter to play... ")
            print(">>> speaking - say 'stop'")
            player.play(audio, on_input_frame=on_frame)
            print("<<< playback ended\n")
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")


if __name__ == "__main__":
    main()
