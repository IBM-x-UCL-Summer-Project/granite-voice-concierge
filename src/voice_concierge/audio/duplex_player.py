"""Full-duplex audio: play output and capture input in one stream.

Two separate audio streams (one output, one input) are refused by some macOS
devices with CoreAudio error -50. A single duplex stream, one audio unit doing
both directions, avoids that (the pattern video-call apps use).

The audio callback must never block, so it does only fast work: it fills the
output block and pushes the captured input block onto a queue. The play() call
drains that queue on its own thread and hands each input block to a caller
supplied callback, so recognition never runs on the real-time thread. A spotted
command can call stop()/pause()/resume() to act on the playback.

Satisfies the AudioPlayer protocol (play) and the PlaybackController protocol
(stop/pause/resume) structurally, so the audio package stays independent of
command control.
"""

# Standard library
import queue
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Third-party
import numpy as np

# Local
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.types import CapturedAudio

DEFAULT_BLOCKSIZE: int = 1024  # frames per duplex callback
_POLL_TIMEOUT: float = 0.05  # seconds to wait for an input block


@dataclass(frozen=True)
class DuplexBackend:
    """The duplex primitives this player needs from its audio library."""

    #: Opens a duplex stream; returns a context manager exposing abort().
    open_stream: Callable[..., Any]
    #: Exception the callback raises to end the stream normally.
    callback_stop: type[BaseException]


def _sounddevice_duplex_backend() -> DuplexBackend:
    """Return a DuplexBackend backed by sounddevice (imported lazily)."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioDeviceError("sounddevice is required for audio playback.") from exc
    return DuplexBackend(open_stream=sd.Stream, callback_stop=sd.CallbackStop)


class DuplexAudioPlayer:
    """Plays audio while capturing the microphone in a single duplex stream."""

    def __init__(
        self,
        *,
        blocksize: int = DEFAULT_BLOCKSIZE,
        backend: DuplexBackend | None = None,
    ) -> None:
        self._blocksize = blocksize
        self._backend = backend
        self._position = 0
        self._paused = threading.Event()
        self._finished = threading.Event()
        self._stream: Any | None = None
        self._input_queue: queue.Queue[bytes] = queue.Queue()

    def play(
        self,
        audio: CapturedAudio,
        *,
        on_input_frame: Callable[[bytes], None] | None = None,
    ) -> None:
        """Play the audio, optionally streaming mic blocks to on_input_frame.

        Blocks until the audio finishes or stop() is called.
        """
        backend = self._backend or _sounddevice_duplex_backend()
        samples = audio.samples.reshape(-1, audio.channels)

        self._position = 0
        self._paused.clear()
        self._finished.clear()
        self._drain_input()

        try:
            stream = backend.open_stream(
                samplerate=audio.sample_rate,
                channels=audio.channels,
                dtype="int16",
                blocksize=self._blocksize,
                callback=self._build_callback(
                    samples, backend.callback_stop, on_input_frame is not None
                ),
                finished_callback=self._finished.set,
            )
            self._stream = stream
            with stream:
                self._consume_input(on_input_frame)
        except Exception as exc:
            raise AudioDeviceError(f"Audio playback failed: {exc}") from exc
        finally:
            self._stream = None
            self._paused.clear()

    def stop(self) -> None:
        """Abort playback immediately and let a blocked play() return."""
        self._paused.clear()
        stream = self._stream
        if stream is not None:
            try:
                stream.abort()
            except Exception:  # already closing, nothing left to abort
                pass
        self._finished.set()

    def pause(self) -> None:
        """Hold playback at the current position, emitting silence."""
        self._paused.set()

    def resume(self) -> None:
        """Continue playback from the paused position."""
        self._paused.clear()

    @property
    def is_paused(self) -> bool:
        """True while playback is held at a position."""
        return self._paused.is_set()

    def _consume_input(self, on_input_frame: Callable[[bytes], None] | None) -> None:
        """Drain captured input blocks until playback finishes."""
        while not self._finished.is_set():
            self._consume_once(on_input_frame)

    def _consume_once(self, on_input_frame: Callable[[bytes], None] | None) -> None:
        """Deliver at most one captured input block to the callback."""
        if on_input_frame is None:
            self._finished.wait(timeout=_POLL_TIMEOUT)
            return
        try:
            frame = self._input_queue.get(timeout=_POLL_TIMEOUT)
        except queue.Empty:
            return
        on_input_frame(frame)

    def _drain_input(self) -> None:
        while not self._input_queue.empty():
            self._input_queue.get_nowait()

    def _build_callback(
        self,
        samples: np.ndarray,
        callback_stop: type[BaseException],
        capture: bool,
    ) -> Callable[..., None]:
        """Build the duplex callback that fills output and queues input."""

        def callback(
            indata: np.ndarray, outdata: np.ndarray, frames: int, *_: object
        ) -> None:
            if capture:
                self._input_queue.put_nowait(bytes(indata))
            if self._paused.is_set():
                outdata[:] = 0  # keep the stream alive while holding position
                return
            start = self._position
            chunk = samples[start : start + frames]
            outdata[: len(chunk)] = chunk
            self._position = start + len(chunk)
            if len(chunk) < frames:
                outdata[len(chunk) :] = 0
                raise callback_stop()

        return callback
