"""Windowed barge-in listener: active only between VAD end and TTS end."""

# Standard library
import threading
from collections.abc import Callable

# Local
from voice_concierge.audio import AudioSource
from voice_concierge.command_control.interfaces import CommandSpotter
from voice_concierge.command_control.types import CommandEvent

DEFAULT_CHUNK: int = 512  # samples per frame fed to the spotter
DEFAULT_STOP_TIMEOUT: float = 2.0  # seconds to wait for the thread to exit


class CommandListener:
    """Runs a command spotter over an audio source on a background thread.

    Windowed: start() opens the capture window (call it when the VAD utterance
    ends) and stop() closes it (call it when TTS output ends), so the spotter
    only holds the microphone during the assistant's response.
    """

    def __init__(
        self,
        audio_source: AudioSource,
        spotter: CommandSpotter,
        on_command: Callable[[CommandEvent], None],
        *,
        chunk: int = DEFAULT_CHUNK,
    ) -> None:
        self._audio_source = audio_source
        self._spotter = spotter
        self._on_command = on_command
        self._chunk = chunk
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Open the audio source and begin spotting on a background thread."""
        if self._thread is not None:
            return
        self._stop_event.clear()
        self._audio_source.open()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self, timeout: float = DEFAULT_STOP_TIMEOUT) -> None:
        """Signal the thread to stop, join it, and close the audio source.

        The join is bounded: the worker spends most of its time blocked in a
        read() on the microphone, and a wedged read must not hang the caller.
        The source is closed either way, which releases a blocked read.
        """
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=timeout)
        self._thread = None
        self._audio_source.close()

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._pump()

    def _pump(self) -> None:
        frame = self._audio_source.read(self._chunk)
        event = self._spotter.process(frame)
        if event is not None:
            self._on_command(event)
