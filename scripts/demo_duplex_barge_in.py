"""Live barge-in through a single full-duplex stream (macOS -50 fix).

Plays a spoken phrase through DuplexAudioPlayer while listening for "stop" /
"pause" / "continue" on the microphone in the SAME audio stream. Because input
and output share one CoreAudio unit (the pattern video-call apps use), this
avoids the PaMacCore -50 that two separate streams caused on some macOS devices.

Run from the repo root:
    .venv/bin/python scripts/demo_duplex_barge_in.py

First run downloads the Vosk model. Press Enter to play, then say "stop" while it
speaks to cut it off. Ctrl+C to quit.

Note: a single duplex stream uses one sample rate for both directions, so the
Vosk recognizer is built at the playback (TTS) rate, not the usual 16 kHz.
"""

# Standard library
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Local
from voice_concierge.audio import DuplexAudioPlayer  # noqa: E402
from voice_concierge.command_control import (  # noqa: E402
    CommandDispatcher,
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
    print("Loading the Vosk command model (first run downloads it)...")
    tts = SayTextToSpeech()
    player = DuplexAudioPlayer()
    audio = tts.synthesize(PHRASE)

    # One duplex stream = one sample rate; match Vosk to the playback rate.
    spotter = build_vosk_command_spotter(sample_rate=audio.sample_rate)
    dispatcher = CommandDispatcher(player)

    def on_frame(frame: bytes) -> None:
        event = spotter.process(frame)
        if event is not None:
            print(f"    [barge-in] heard {event.phrase!r} -> {event.command}")
            dispatcher.dispatch(event)

    duration = len(audio.samples) / audio.sample_rate
    print(f"\nSynthesized {duration:.1f}s of speech at {audio.sample_rate} Hz.\n")
    try:
        while True:
            input("Press Enter to play, then say 'stop' to interrupt... ")
            print(">>> speaking - say 'stop'")
            player.play(audio, on_input_frame=on_frame)
            print("<<< playback ended\n")
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")


if __name__ == "__main__":
    main()
