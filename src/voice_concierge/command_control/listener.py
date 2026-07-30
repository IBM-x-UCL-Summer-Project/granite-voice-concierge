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
        """Signal the thread to stop, release the source, and join the thread.

        The source is closed *before* the join: the worker spends most of its
        time blocked in read(), and closing the source is what unblocks a wedged
        read, so a blocked worker exits at once instead of after the timeout.
        The join keeps its bound purely as a safety net.
        """
        if self._thread is None:
            return
        self._stop_event.set()
        self._audio_source.close()
        self._thread.join(timeout=timeout)
        self._thread = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            self._pump()

    def _pump(self) -> None:
        try:
            frame = self._audio_source.read(self._chunk)
        except Exception:
            # stop() closes the source under a live read; that failure is the
            # expected way the read unblocks during shutdown, so swallow it.
            if self._stop_event.is_set():
                return
            raise
        event = self._spotter.process(frame)
        if event is not None:
            self._on_command(event)
