"""Pausable audio playback built on a callback-driven output stream.

SoundDevicePlayer plays a whole buffer with sd.play()/sd.wait(), which exposes
no playback position and therefore cannot pause. This player pulls audio block
by block from a callback, so it can hold position and resume from it.

It satisfies both the AudioPlayer protocol (play) and command_control's
PlaybackController protocol (stop/pause/resume) without importing the latter:
those protocols are structural, so the audio package stays independent of
command control.
"""

# Standard library
import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

# Third-party
import numpy as np

# Local
from voice_concierge.audio.errors import AudioDeviceError
from voice_concierge.audio.types import CapturedAudio

DEFAULT_BLOCKSIZE: int = 1024  # frames per playback callback


@dataclass(frozen=True)
class PlaybackBackend:
    """The playback primitives this player needs from its audio library."""

    #: Opens an output stream; returns a context manager exposing abort().
    open_stream: Callable[..., Any]
    #: Exception the callback raises to end the stream normally.
    callback_stop: type[BaseException]


def _sounddevice_backend() -> PlaybackBackend:
    """Return a PlaybackBackend backed by sounddevice (imported lazily)."""
    try:
        import sounddevice as sd
    except ImportError as exc:
        raise AudioDeviceError("sounddevice is required for audio playback.") from exc
    return PlaybackBackend(open_stream=sd.OutputStream, callback_stop=sd.CallbackStop)


class StreamingAudioPlayer:
    """AudioPlayer that supports stop, pause, and resume during playback.

    play() blocks until the audio finishes or is stopped, so it can be driven
    from the pipeline exactly like SoundDevicePlayer. stop()/pause()/resume()
    are called from another thread (the command listener) while play() blocks.
    """

    def __init__(
        self,
        *,
        blocksize: int = DEFAULT_BLOCKSIZE,
        backend: PlaybackBackend | None = None,
    ) -> None:
        self._blocksize = blocksize
        self._backend = backend
        self._position = 0
        self._paused = threading.Event()
        self._finished = threading.Event()
        self._stream: Any | None = None

    def play(self, audio: CapturedAudio) -> None:
        """Play the audio, blocking until it finishes or is stopped."""
        backend = self._backend or _sounddevice_backend()
        samples = audio.samples.reshape(-1, audio.channels)

        self._position = 0
        self._paused.clear()
        self._finished.clear()

        try:
            stream = backend.open_stream(
                samplerate=audio.sample_rate,
                channels=audio.channels,
                dtype="int16",
                blocksize=self._blocksize,
                callback=self._build_callback(samples, backend.callback_stop),
                finished_callback=self._finished.set,
            )
            self._stream = stream
            with stream:
                self._finished.wait()
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
            except Exception:  # already closing — nothing left to abort
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

    def _build_callback(
        self, samples: np.ndarray, callback_stop: type[BaseException]
    ) -> Callable[..., None]:
        """Build the output callback that feeds blocks from `samples`."""

        def callback(outdata: np.ndarray, frames: int, *_: object) -> None:
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
