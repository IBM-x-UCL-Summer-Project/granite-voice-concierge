"""Manual live test: start and navigate a routine by voice.

Interaction model:

* Say "hey jarvis", then a request like "start making tea" to begin a routine,
  or a navigation word ("next", "go back", "repeat", "pause", "continue",
  "stop") to move through the active routine. The parser shares one vocabulary
  with the KWS spotter.
* The assistant speaks each step. Between turns the wake-word listener resumes.

Barge-in is optional, controlled by --barge-in (default off):

* Off (default): playback is uninterruptible. One audio stream at a time, so it
  runs cleanly everywhere.
* On (--barge-in): the barge-in KWS listener is live while a step plays, so
  "stop"/"pause"/"continue" act on the speech. This needs the microphone open
  during playback. Some macOS devices refuse a concurrent input and output
  stream and raise CoreAudio "PaMacCore err -50", which truncates the speech.
  The flag lets us keep developing and testing workarounds without blocking the
  default run.

Uses the macOS `say` TTS backend (piper is broken on macOS).

Run from the repo root in the venv:
    .venv/bin/python scripts/demo_live_routines.py            # uninterruptible
    .venv/bin/python scripts/demo_live_routines.py --barge-in # interruptible

First run downloads models (openWakeWord, Whisper, Vosk). Requires Ollama running
with the configured reasoning model. Ctrl+C to quit.
"""

# Standard library
import argparse
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
from voice_concierge.command_control import (  # noqa: E402
    CommandDispatcher,
    CommandListener,
    TranscriptCommandParser,
    build_vosk_command_spotter,
)
from voice_concierge.command_control.listener import DEFAULT_CHUNK  # noqa: E402
from voice_concierge.memory import build_memory_manager  # noqa: E402
from voice_concierge.reasoning.factory import build_reasoning_engine  # noqa: E402
from voice_concierge.routines import RoutineError, build_routine_adapter  # noqa: E402
from voice_concierge.voice_input.stt.factory import build_speech_to_text  # noqa: E402
from voice_concierge.voice_output import (  # noqa: E402
    SayTextToSpeech,
    TextToSpeechError,
)

MIC_RATE = 16000  # Vosk expects 16 kHz mono int16


class SoundDeviceMic:
    """AudioSource over sounddevice, so barge-in input shares the playback backend.

    Opening the microphone through the same audio library as playback keeps both
    streams under one PortAudio instance. On devices that support a concurrent
    input+output stream this avoids the macOS CoreAudio (-50) collision a
    separate PyAudio input stream caused; devices that refuse concurrency at all
    still raise -50, which is why barge-in is opt-in here.
    """

    def __init__(self, *, samplerate: int = MIC_RATE, channels: int = 1) -> None:
        self._samplerate = samplerate
        self._channels = channels
        self._stream = None

    def open(self) -> None:
        import sounddevice as sd

        self._stream = sd.RawInputStream(
            samplerate=self._samplerate, channels=self._channels, dtype="int16"
        )
        self._stream.start()

    def read(self, num_samples: int) -> bytes:
        if self._stream is None:
            raise AudioDeviceError("Microphone read before open().")
        data, _overflowed = self._stream.read(num_samples)
        return bytes(data)

    def close(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None


def main(*, barge_in_enabled: bool = False) -> None:
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

    # Barge-in listener is built only when enabled. When on, "stop"/"pause"/
    # "continue" act on playback while a step is spoken.
    barge_in = None
    if barge_in_enabled:
        dispatcher = CommandDispatcher(player)
        barge_in = CommandListener(
            SoundDeviceMic(),
            build_vosk_command_spotter(),
            dispatcher.dispatch,
            chunk=DEFAULT_CHUNK,
        )

    def speak(text: str) -> None:
        """Speak a response; interruptible only when barge-in is enabled."""
        audio = tts.synthesize(text)
        if barge_in is None:
            player.play(audio)
            return
        barge_in.start()
        try:
            player.play(audio)  # blocks until finished or "stop" cuts it off
        finally:
            barge_in.stop()

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
                print("(thinking...)")
                response = adapter.start_routine(transcript)
                active = True
            print(f"Assistant: {response}")
            speak(response)
        except RoutineError as exc:
            print(f"Assistant: Sorry, I couldn't load that routine right now. [{exc}]")
        except (AudioDeviceError, TextToSpeechError) as exc:
            print(f"Assistant: (I built the response but couldn't speak it: {exc})")

    mode = "barge-in ON" if barge_in_enabled else "uninterruptible"
    print(f"Say 'hey jarvis', then e.g. 'start making tea'. [{mode}] Ctrl+C to quit.\n")
    try:
        while True:
            wake.listen(on_wake_word=on_wake)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    arg_parser = argparse.ArgumentParser(description="Live guided-routines demo.")
    arg_parser.add_argument(
        "--barge-in",
        action="store_true",
        help="Enable interrupting speech with 'stop'/'pause' during playback "
        "(may raise CoreAudio -50 on some macOS devices).",
    )
    args = arg_parser.parse_args()
    main(barge_in_enabled=args.barge_in)
