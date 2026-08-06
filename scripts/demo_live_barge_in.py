"""Manual live test: full pipeline (wake word -> VAD -> STT -> reasoning -> TTS)
with barge-in.

Say the wake word ("hey jarvis"), speak a request, then control the reply while
it plays: "stop" cuts it off, "pause"/"wait" holds it, "continue"/"resume"
picks up where it left off.

Run from the repo root in the venv:
    .venv/bin/python scripts/demo_live_barge_in.py

Uses the macOS `say` TTS backend (piper is broken on macOS — espeak-ng data).
First run downloads models (openWakeWord, Whisper, Vosk). Requires Ollama
running with the configured reasoning model. Ctrl+C to quit.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import time  # noqa: E402

from voice_concierge.app.factory import build_voice_concierge_pipeline  # noqa: E402
from voice_concierge.app.live import (  # noqa: E402
    LiveAppConfig,
    build_utterance_capturer,
    build_wake_word_listener,
)
from voice_concierge.app.types import AppPipelineState  # noqa: E402
from voice_concierge.audio import CapturedAudio, StreamingAudioPlayer  # noqa: E402
from voice_concierge.audio.source import PyAudioSource  # noqa: E402
from voice_concierge.command_control import (  # noqa: E402
    CommandDispatcher,
    CommandEvent,
    CommandListener,
    PlaybackController,
    build_vosk_command_spotter,
)
from voice_concierge.command_control.listener import DEFAULT_CHUNK  # noqa: E402
from voice_concierge.voice_input.stt.factory import build_speech_to_text  # noqa: E402
from voice_concierge.voice_output import SayTextToSpeech  # noqa: E402


def build_logged_barge_in(controller: PlaybackController) -> CommandListener:
    """Build the stop/pause/resume barge-in stack, logging each spotted command.

    The assembly factories wire the dispatcher in silently, so a run cannot tell
    "never spotted" apart from "spotted but playback ignored it". Composing the
    callback by hand keeps that distinction visible.
    """
    spotter = build_vosk_command_spotter()  # full default vocabulary
    dispatcher = CommandDispatcher(controller)

    def on_command(event: CommandEvent) -> None:
        print(f"    [barge-in] spotted {event.phrase!r} -> {event.command}")
        dispatcher.dispatch(event)

    source = PyAudioSource(frames_per_buffer=DEFAULT_CHUNK)
    return CommandListener(source, spotter, on_command, chunk=DEFAULT_CHUNK)


def main() -> None:
    print("Loading models (first run downloads them)...")
    config = LiveAppConfig(download_wake_models=True)

    # One pausable player serves as both the pipeline's speaker output and the
    # barge-in controller, so pause/resume act on the audio actually playing.
    player = StreamingAudioPlayer()

    pipeline = build_voice_concierge_pipeline(
        speech_to_text=build_speech_to_text(),
        text_to_speech=SayTextToSpeech(),  # macOS TTS instead of piper
        audio_player=player,
        load_memory=True,
    )
    wake = build_wake_word_listener(config)
    capturer = build_utterance_capturer(config)
    barge_in = build_logged_barge_in(player)  # Vosk model downloads on first use

    state = AppPipelineState()

    def handle_audio(audio: CapturedAudio) -> None:
        nonlocal state
        print(">>> thinking / speaking — say 'stop', 'pause', or 'continue'")
        barge_in.start()
        started = time.monotonic()
        try:
            result = pipeline.process_audio(audio, state, synthesize=True, play=True)
        finally:
            barge_in.stop()
        # A turn cut short by barge-in shows a playback time well under the
        # audio's own duration.
        elapsed = time.monotonic() - started
        spoken = result.response_audio
        if spoken is not None:
            print(
                f"    [timing] played {elapsed:.2f}s "
                f"of {spoken.duration_seconds:.2f}s of speech"
            )
        state = result.state
        said = result.transcript.text if result.transcript is not None else "<none>"
        print(f"You: {said}")
        print(f"Assistant: {result.spoken_response}\n")

    def on_wake() -> None:
        # Let the VAD finish and close its mic stream before barge-in opens one.
        captured: list[CapturedAudio] = []
        capturer.capture_utterance(on_utterance_captured=captured.append)
        if captured:
            handle_audio(captured[0])

    print("Say 'hey jarvis', speak a request, then 'stop' to barge in.")
    print("Ctrl+C to quit.\n")
    try:
        while True:
            wake.listen(on_wake_word=on_wake)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        pipeline.close()


if __name__ == "__main__":
    main()
