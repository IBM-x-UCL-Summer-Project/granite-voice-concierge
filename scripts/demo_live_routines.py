"""Manual live test: start and navigate a routine by voice, with barge-in.

Interaction model:

* Say "hey jarvis", then a request like "start making tea" to begin a routine,
  or a navigation word ("next", "go back", "repeat", "pause", "continue",
  "stop") to move through the active routine. This is the wake-word command
  path (the parser shares one vocabulary with the KWS spotter).
* While the assistant is speaking a step, the barge-in KWS listener is live
  (windowed to playback) so you can cut the speech short with "stop" or hold it
  with "pause" / "continue".

macOS CoreAudio note: the barge-in microphone is opened through sounddevice, the
same backend as playback, so the input and output streams share one PortAudio
instance instead of colliding (which previously threw PaMacCore err -50 and
truncated speech). Uses the macOS `say` TTS backend (piper is broken on macOS).

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
    streams under one PortAudio instance, avoiding the macOS CoreAudio (-50)
    collision that a separate PyAudio input stream caused during playback.
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

    # Barge-in: "stop"/"pause"/"continue" act on playback while a step is spoken.
    # The mic uses sounddevice so it shares the playback backend (no -50 collision).
    dispatcher = CommandDispatcher(player)
    barge_in = CommandListener(
        SoundDeviceMic(),
        build_vosk_command_spotter(),
        dispatcher.dispatch,
        chunk=DEFAULT_CHUNK,
    )

    def speak(text: str) -> None:
        """Speak a response; barge-in is live only while it plays (windowed)."""
        audio = tts.synthesize(text)
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
