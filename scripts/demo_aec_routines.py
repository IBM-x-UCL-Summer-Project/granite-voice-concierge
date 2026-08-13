"""Manual test for guided routines with echo-cancelled barge-in.

Runs the same components the live app uses (see voice_concierge.app.routines),
just without the wake word, so a routine can be exercised by typing the request
instead of saying "hey jarvis" each time. The behaviour under test is the voice
part: the routine reads a step, listens while it speaks, and moves on by itself.

While a step is read aloud, or in the quiet window after it:

* "pause" / "continue" hold and resume the reading; a paused routine waits
  rather than auto-advancing.
* "next" / "back" / "repeat" move through the routine.
* "stop" ends it.

Stay quiet and it advances on its own.

macOS only: needs pyobjc-framework-AVFoundation (see the macos-aec extra), and
Ollama running with the configured reasoning model. First run downloads the Vosk
command model. Ctrl+C to quit.

Run from the repo root:
    .venv/bin/python scripts/demo_aec_routines.py
"""

# Standard library
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

# Local
from voice_concierge.app.routines import (  # noqa: E402
    EchoCancelledStepSpeaker,
    MicCommandWaiter,
    RoutineTurnHandler,
)
from voice_concierge.audio import PyAudioSource  # noqa: E402
from voice_concierge.audio.voice_processing_player import (  # noqa: E402
    VoiceProcessingAudioPlayer,
)
from voice_concierge.command_control import (  # noqa: E402
    CommandEvent,
    StableCommandSpotter,
    build_vosk_command_spotter,
)
from voice_concierge.memory import build_memory_manager  # noqa: E402
from voice_concierge.reasoning.factory import build_reasoning_engine  # noqa: E402
from voice_concierge.routines import RoutineRunner, build_routine_adapter  # noqa: E402
from voice_concierge.voice_output import SayTextToSpeech  # noqa: E402


def _log(event: CommandEvent) -> None:
    """Show what the recognizer heard, so a mishear is easy to spot."""
    print(f"    [heard] {event.phrase!r} -> {event.command}")


def main() -> None:
    print("Loading models (first run downloads them)...")
    adapter = build_routine_adapter(
        memory_manager=build_memory_manager(),
        reasoning_engine=build_reasoning_engine(),
    )
    # One shared vocabulary spots playback and routine words; the stabilizer
    # keeps a partial-result recognizer from firing twice or on noise.
    spotter = StableCommandSpotter(build_vosk_command_spotter())
    speaker = EchoCancelledStepSpeaker(
        SayTextToSpeech(), VoiceProcessingAudioPlayer(), spotter, on_event=_log
    )
    waiter = MicCommandWaiter(PyAudioSource(), spotter, on_event=_log)
    handler = RoutineTurnHandler(adapter, RoutineRunner(adapter, speaker, waiter))

    print("Type a request, e.g. 'guide me through making pasta'. Ctrl+C to quit.\n")
    try:
        while True:
            request = input("You: ").strip()
            if not request:
                continue
            if not handler.handles(request):
                print("(not a guided-routine request; try 'guide me through ...')\n")
                continue
            print(handler.run(request), end="\n\n")
    except (KeyboardInterrupt, EOFError):
        print("\nStopped.")


if __name__ == "__main__":
    main()
